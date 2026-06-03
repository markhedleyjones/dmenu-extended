#!/usr/bin/env python3

"""Characterisation tests for the dmenu-extended plugin system.

These tests pin down the CURRENT actual behaviour of the plugin machinery:
the Version comparison class, the requirements/dependency logic, plugin
loading, and the download/update flows. Where the code behaves oddly (for
example raising on a plugin index entry that lacks a requirements key), the
test asserts the odd behaviour rather than the ideal one.

All boundaries are mocked: no real dmenu/rofi is launched, no network request
is made (fetch_resource / urllib are stubbed), and any filesystem writes go to
tmp_path or a tempfile directory.
"""

import contextlib
import hashlib
import os
import sys
import tempfile
import types
from os import path

import mock

# Add src directory to path to import dmenu_extended
sys.path.insert(0, path.join(path.dirname(__file__), "..", "src"))
import dmenu_extended as d
from dmenu_extended import main


def make_extension():
    """Build an extension instance without running __init__.

    extension.__init__ calls load_preferences which would read the real user
    config from disk. Bypassing __init__ via __new__ gives a usable instance
    whose download_plugins_json / download_plugins / update_plugins methods can
    be exercised in isolation.
    """
    return main.extension.__new__(main.extension)


# ---------------------------------------------------------------------------
# Version class
# ---------------------------------------------------------------------------


def test_version_parses_first_three_components():
    # A version string is split on "." and only the first three parts are kept.
    v = main.Version("1.2.3.4")
    assert v.parsed == [1, 2, 3]
    # The original string is retained verbatim, including the dropped 4th part.
    assert v.string == "1.2.3.4"


def test_version_equality_and_ordering():
    assert main.Version("1.2.3") == main.Version("1.2.3")
    assert main.Version("1.2.3") != main.Version("1.2.4")
    assert main.Version("1.2.3") < main.Version("1.2.4")
    assert main.Version("1.3.0") > main.Version("1.2.9")
    assert main.Version("2.0.0") >= main.Version("2.0.0")
    assert main.Version("1.0.0") <= main.Version("1.0.1")


def test_version_ordering_is_major_then_minor_then_patch():
    # A larger major beats a smaller minor/patch.
    assert main.Version("2.0.0") > main.Version("1.9.9")
    # Equal major, larger minor wins.
    assert main.Version("1.5.0") > main.Version("1.4.9")


def test_version_two_component_string_breaks_equality():
    # A two-component version produces a parsed list of length 2. __eq__ always
    # indexes parsed[2], so comparing two such versions raises IndexError. This
    # is a current quirk: Version assumes three components for equality.
    v = main.Version("1.2")
    assert v.parsed == [1, 2]
    import pytest

    with pytest.raises(IndexError):
        _ = v == main.Version("1.2")


def test_version_two_component_less_than_can_short_circuit():
    # __lt__ only reaches parsed[2] when major and minor are equal. When the
    # minor differs it short-circuits and never touches the missing index.
    assert (main.Version("1.2") < main.Version("1.3")) is True


# ---------------------------------------------------------------------------
# provided_package_versions
# ---------------------------------------------------------------------------


def test_provided_package_versions_keys():
    # The module advertises exactly two satisfiable packages.
    assert set(main.provided_package_versions.keys()) == {"dmenu-extended", "python"}
    assert isinstance(main.provided_package_versions["python"], main.Version)


# ---------------------------------------------------------------------------
# get_plugin_requirements
# ---------------------------------------------------------------------------


def test_get_plugin_requirements_new_format():
    # The current index format uses a "requirements" dict of package -> version
    # string. Each value is wrapped in a Version object.
    reqs = main.get_plugin_requirements(
        {"requirements": {"dmenu-extended": "0.2.0", "python": "3.6.0"}}
    )
    assert set(reqs.keys()) == {"dmenu-extended", "python"}
    assert all(isinstance(v, main.Version) for v in reqs.values())
    assert reqs["dmenu-extended"].string == "0.2.0"


def test_get_plugin_requirements_legacy_min_version_nonzero():
    # Legacy plugins used an integer "min_version". Any non-zero value maps to a
    # dmenu-extended requirement of exactly 0.2.0 (the semantic-versioning
    # cut-over point).
    reqs = main.get_plugin_requirements({"min_version": 5})
    assert {k: v.string for k, v in reqs.items()} == {"dmenu-extended": "0.2.0"}


def test_get_plugin_requirements_legacy_min_version_zero():
    # A zero min_version means no requirement.
    assert main.get_plugin_requirements({"min_version": 0}) == {}


def test_get_plugin_requirements_min_version_comment_is_printed(capsys):
    # When a "_min_version_comment" is present alongside min_version, it is
    # printed to stdout.
    main.get_plugin_requirements(
        {"min_version": 1, "_min_version_comment": "please upgrade"}
    )
    assert "please upgrade" in capsys.readouterr().out


def test_get_plugin_requirements_returns_none_when_no_keys():
    # A plugin entry with neither "requirements" nor "min_version" falls through
    # every branch and returns None (not an empty dict). This is the root cause
    # of the crash pinned in the next test.
    assert main.get_plugin_requirements({"desc": "no requirements"}) is None


# ---------------------------------------------------------------------------
# unsatisfied_plugin_requirements
# ---------------------------------------------------------------------------


def test_unsatisfied_requirements_all_met_returns_empty():
    # A requirement the running system satisfies yields no unsatisfied entries.
    assert (
        main.unsatisfied_plugin_requirements({"requirements": {"python": "0.0.1"}})
        == {}
    )


def test_unsatisfied_requirements_version_too_high():
    # A python requirement higher than the running interpreter is reported as
    # unsatisfied, keyed by package with the required version string.
    result = main.unsatisfied_plugin_requirements(
        {"requirements": {"python": "99.0.0"}}
    )
    assert result == {"python": "99.0.0"}


def test_unsatisfied_requirements_unknown_package_always_unsatisfied():
    # A package that is not in provided_package_versions is always treated as
    # unsatisfied, regardless of the requested version.
    result = main.unsatisfied_plugin_requirements(
        {"requirements": {"some-unknown-pkg": "1.0.0"}}
    )
    assert result == {"some-unknown-pkg": "1.0.0"}


def test_unsatisfied_requirements_none_requirements_raises():
    # When get_plugin_requirements returns None (no requirements key), this
    # function calls .items() on None and raises AttributeError. Current quirk.
    import pytest

    with pytest.raises(AttributeError):
        main.unsatisfied_plugin_requirements({"desc": "no requirements"})


# ---------------------------------------------------------------------------
# load_plugins
# ---------------------------------------------------------------------------


def test_load_plugins_seeds_settings_plugin_first():
    # load_plugins always seeds the settings plugin (plugin_settings.py) as the
    # first entry, then propagates the global d.launch_args onto it.
    fake_plugins_mod = types.SimpleNamespace(__all__=[])
    with (
        mock.patch.object(main, "plugins", fake_plugins_mod),
        mock.patch.object(main, "extension", return_value=mock.Mock()),
        mock.patch.object(main, "d", main.dmenu()),
    ):
        main.d.launch_args = ["preselected"]
        loaded = main.load_plugins()

    assert len(loaded) == 1
    assert loaded[0]["filename"] == "plugin_settings.py"
    assert loaded[0]["plugin"].launch_args == ["preselected"]


def test_load_plugins_survives_broken_plugin(capsys):
    # A plugin name in plugins.__all__ that cannot be imported is caught: an
    # error is printed and the loop continues. The settings plugin still loads.
    fake_plugins_mod = types.SimpleNamespace(__all__=["does_not_exist_plugin_xyz"])
    with (
        mock.patch.object(main, "plugins", fake_plugins_mod),
        mock.patch.object(main, "extension", return_value=mock.Mock()),
        mock.patch.object(main, "d", main.dmenu()),
    ):
        main.d.launch_args = []
        loaded = main.load_plugins()

    assert len(loaded) == 1
    assert loaded[0]["filename"] == "plugin_settings.py"
    assert "Error loading plugin does_not_exist_plugin_xyz" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# get_plugins (caching behaviour)
# ---------------------------------------------------------------------------


def test_get_plugins_loads_once_when_not_loaded():
    inst = main.dmenu()
    inst.plugins_loaded = False
    with mock.patch.object(main, "load_plugins", return_value=["loaded"]) as lp:
        out = inst.get_plugins()
    assert lp.called
    assert out == ["loaded"]


def test_get_plugins_returns_cache_without_reloading():
    # If plugins_loaded already holds a (truthy) value, get_plugins returns it
    # and does NOT call load_plugins again.
    inst = main.dmenu()
    inst.plugins_loaded = [{"filename": "plugin_settings.py", "plugin": object()}]
    with mock.patch.object(main, "load_plugins") as lp:
        out = inst.get_plugins()
    assert lp.called is False
    assert out is inst.plugins_loaded


def test_get_plugins_force_reloads():
    # force=True reloads the plugins package and rebuilds the loaded list.
    inst = main.dmenu()
    inst.plugins_loaded = ["stale"]
    with (
        mock.patch.object(main, "load_plugins", return_value=["fresh"]) as lp,
        mock.patch("importlib.reload") as reload_mock,
    ):
        out = inst.get_plugins(force=True)
    assert lp.called
    assert reload_mock.called
    assert out == ["fresh"]


# ---------------------------------------------------------------------------
# plugins_available
# ---------------------------------------------------------------------------


def test_plugins_available_marks_submenus_and_sorts_by_length():
    inst = main.dmenu()
    cache_file = os.path.join(tempfile.mkdtemp(), "plugins.txt")

    class FakeSubmenu:
        is_submenu = True
        title = "Settings"

    class FakeNormal:
        title = "Calculator"

    fake_plugins = [
        {"filename": "plugin_settings.py", "plugin": FakeSubmenu()},
        {"filename": "plugin_calc.py", "plugin": FakeNormal()},
    ]

    with (
        mock.patch.object(inst, "load_preferences"),
        mock.patch.object(inst, "get_plugins", return_value=fake_plugins),
        mock.patch.object(main, "file_cache_plugins", cache_file),
    ):
        inst.prefs = {"indicator_submenu": "->"}
        out = inst.plugins_available()

    # Submenu plugins get the indicator prefix; normal plugins keep their title.
    # The list is sorted shortest-first, so "Calculator" (10 chars) precedes
    # "-> Settings" (11 chars).
    assert out == ["Calculator", "-> Settings"]
    with open(cache_file) as f:
        assert f.read() == "Calculator\n-> Settings\n"


def test_plugins_available_forces_plugin_reload():
    # plugins_available calls get_plugins(True) - it always forces a reload.
    inst = main.dmenu()
    cache_file = os.path.join(tempfile.mkdtemp(), "plugins.txt")

    class FakeNormal:
        title = "X"

    with (
        mock.patch.object(inst, "load_preferences"),
        mock.patch.object(
            inst,
            "get_plugins",
            return_value=[{"filename": "p.py", "plugin": FakeNormal()}],
        ) as gp,
        mock.patch.object(main, "file_cache_plugins", cache_file),
    ):
        inst.prefs = {"indicator_submenu": "->"}
        inst.plugins_available()

    gp.assert_called_once_with(True)


# ---------------------------------------------------------------------------
# download_plugins_json
# ---------------------------------------------------------------------------


def test_download_plugins_json_fetches_index_from_each_base():
    # The index is fetched from "<base>/plugins_index.json" for every configured
    # repository base, then merged into a single dict.
    inst = make_extension()
    inst.prefs = {"plugin_repositories": ["https://repo-a", "https://repo-b"]}
    with mock.patch.object(inst, "fetch_resource") as fetch:
        fetch.side_effect = [
            b'{"plugin_a": {"url": "ua", "sha256": "sa"}}',
            b'{"plugin_b": {"url": "ub", "sha256": "sb"}}',
        ]
        merged = inst.download_plugins_json()

    # One fetch per base, addressed at the index file under each base.
    assert [c[0][0] for c in fetch.call_args_list] == [
        "https://repo-a/plugins_index.json",
        "https://repo-b/plugins_index.json",
    ]
    assert merged == {
        "plugin_a": {"url": "ua", "sha256": "sa", "repository": "https://repo-a"},
        "plugin_b": {"url": "ub", "sha256": "sb", "repository": "https://repo-b"},
    }


def test_download_plugins_json_tags_entries_with_repository():
    # Every merged entry is tagged with the base it came from so the install and
    # update flows know where to fetch the plugin source.
    inst = make_extension()
    inst.prefs = {"plugin_repositories": ["https://repo-a"]}
    with mock.patch.object(
        inst,
        "fetch_resource",
        return_value=b'{"plugin_a": {"url": "ua", "sha256": "sa"}}',
    ):
        merged = inst.download_plugins_json()

    assert merged["plugin_a"]["repository"] == "https://repo-a"


def test_download_plugins_json_last_repository_wins_on_collision():
    # When two repositories define the same plugin name, the later base in the
    # list overwrites the earlier one (and so does its repository tag).
    inst = make_extension()
    inst.prefs = {"plugin_repositories": ["https://repo-a", "https://repo-b"]}
    with mock.patch.object(inst, "fetch_resource") as fetch:
        fetch.side_effect = [
            b'{"plugin_x": {"url": "from-a", "sha256": "sa"}}',
            b'{"plugin_x": {"url": "from-b", "sha256": "sb"}}',
        ]
        merged = inst.download_plugins_json()

    assert merged["plugin_x"]["url"] == "from-b"
    assert merged["plugin_x"]["repository"] == "https://repo-b"


def test_download_plugins_json_error_exits():
    # A failure reading any index closes the wait message, shows an error menu
    # naming the offending base, and exits the process via sys.exit().
    import pytest

    inst = make_extension()
    inst.prefs = {"plugin_repositories": ["https://repo-a"]}
    with (
        mock.patch.object(inst, "fetch_resource", side_effect=Exception("boom")),
        mock.patch.object(inst, "message_close") as mc,
        mock.patch.object(inst, "menu") as menu,
    ):
        with pytest.raises(SystemExit):
            inst.download_plugins_json()

    assert mc.called
    assert menu.call_args[0][0] == [
        "Error: Could not read plugin repository https://repo-a",
        "Please check your connection or configuration and try again.",
    ]


# ---------------------------------------------------------------------------
# download_plugins
# ---------------------------------------------------------------------------


def test_download_plugins_installs_selected_plugin(tmp_path):
    # The happy path: an index entry carrying a sha256 + desc + (empty)
    # requirements is offered, selected, fetched from "<repository>/<name>.py",
    # verified, and written to path_plugins as <plugin_name>.py.
    inst = make_extension()
    source = b"# plugin source"
    plugins_json = {
        "plugin_foo": {
            "sha256": hashlib.sha256(source).hexdigest(),
            "desc": "Foo plugin",
            "requirements": {},
            "repository": "https://repo-a",
        }
    }

    with contextlib.ExitStack() as stack:
        stack.enter_context(
            mock.patch.object(inst, "download_plugins_json", return_value=plugins_json)
        )
        stack.enter_context(
            mock.patch.object(
                inst, "get_plugins", return_value=[{"filename": "plugin_settings.py"}]
            )
        )
        select = stack.enter_context(
            mock.patch.object(inst, "select", return_value="foo - Foo plugin")
        )
        stack.enter_context(mock.patch.object(inst, "message_open"))
        stack.enter_context(mock.patch.object(inst, "message_close"))
        fetch = stack.enter_context(
            mock.patch.object(inst, "fetch_resource", return_value=source)
        )
        stack.enter_context(mock.patch.object(inst, "plugins_available"))
        menu = stack.enter_context(mock.patch.object(inst, "menu"))
        stack.enter_context(mock.patch.object(main, "path_plugins", str(tmp_path)))
        inst.download_plugins()

    # The selectable item has the "plugin_" prefix stripped for display.
    assert select.call_args[0][0] == ["foo - Foo plugin"]
    # The source is fetched from "<repository>/<plugin_name>.py".
    fetch.assert_called_once_with("https://repo-a/plugin_foo.py")
    # The file is written back WITH the plugin_ prefix.
    written = tmp_path / "plugin_foo.py"
    assert written.exists()
    assert written.read_bytes() == source
    assert menu.call_args[0][0] == ["Plugin downloaded and installed successfully"]


def test_download_plugins_refuses_to_write_on_failed_verification(tmp_path):
    # When the fetched source fails verify_plugin (sha256 mismatch), the install
    # is aborted: the failure menu is shown and NO file is written to disk.
    inst = make_extension()
    plugins_json = {
        "plugin_foo": {
            "sha256": "0" * 64,  # does not match the fetched bytes
            "desc": "Foo plugin",
            "requirements": {},
            "repository": "https://repo-a",
        }
    }

    with contextlib.ExitStack() as stack:
        stack.enter_context(
            mock.patch.object(inst, "download_plugins_json", return_value=plugins_json)
        )
        stack.enter_context(
            mock.patch.object(
                inst, "get_plugins", return_value=[{"filename": "plugin_settings.py"}]
            )
        )
        stack.enter_context(
            mock.patch.object(inst, "select", return_value="foo - Foo plugin")
        )
        stack.enter_context(mock.patch.object(inst, "message_open"))
        stack.enter_context(mock.patch.object(inst, "message_close"))
        stack.enter_context(
            mock.patch.object(inst, "fetch_resource", return_value=b"tampered source")
        )
        plugins_available = stack.enter_context(
            mock.patch.object(inst, "plugins_available")
        )
        menu = stack.enter_context(mock.patch.object(inst, "menu"))
        stack.enter_context(mock.patch.object(main, "path_plugins", str(tmp_path)))
        inst.download_plugins()

    assert menu.call_args[0][0] == [
        "Plugin failed its integrity check and was not installed"
    ]
    # Nothing was written, and the success path (cache rebuild) was not reached.
    assert list(tmp_path.iterdir()) == []
    assert plugins_available.called is False


def test_download_plugins_no_new_plugins(tmp_path):
    # When every index plugin is already installed, the menu reports that there
    # are no new plugins and nothing is downloaded.
    inst = make_extension()
    plugins_json = {
        "plugin_foo": {
            "url": "u",
            "sha1sum": "s",
            "desc": "d",
            "requirements": {},
        }
    }
    with contextlib.ExitStack() as stack:
        stack.enter_context(
            mock.patch.object(inst, "download_plugins_json", return_value=plugins_json)
        )
        stack.enter_context(
            mock.patch.object(
                inst, "get_plugins", return_value=[{"filename": "plugin_foo.py"}]
            )
        )
        menu = stack.enter_context(mock.patch.object(inst, "menu"))
        dt = stack.enter_context(mock.patch.object(inst, "download_text"))
        inst.download_plugins()

    assert menu.call_args[0][0] == ["There are no new plugins to install"]
    assert dt.called is False


def test_download_plugins_unmet_requirements_blocks_install():
    # A plugin whose requirements are not met is listed with a "Requires:"
    # description and accept=False. Selecting it shows the unmet-dependencies
    # message instead of downloading.
    inst = make_extension()
    plugins_json = {
        "plugin_bar": {
            "url": "u",
            "sha1sum": "s",
            "desc": "d",
            "requirements": {"python": "99.0.0"},
        }
    }
    with contextlib.ExitStack() as stack:
        stack.enter_context(
            mock.patch.object(inst, "download_plugins_json", return_value=plugins_json)
        )
        stack.enter_context(
            mock.patch.object(
                inst, "get_plugins", return_value=[{"filename": "plugin_settings.py"}]
            )
        )
        select = stack.enter_context(
            mock.patch.object(
                inst, "select", return_value="bar - Requires: python => 99.0.0"
            )
        )
        menu = stack.enter_context(mock.patch.object(inst, "menu"))
        dt = stack.enter_context(mock.patch.object(inst, "download_text"))
        inst.download_plugins()

    # The displayed item carries the generated "Requires:" description.
    assert select.call_args[0][0] == ["bar - Requires: python => 99.0.0"]
    assert menu.call_args[0][0] == [
        "The requested plugin has unmet dependencies, please update your system and try again"
    ]
    assert dt.called is False


def test_download_plugins_entry_without_requirements_key_raises():
    # An index entry that omits both "requirements" and "min_version" makes
    # unsatisfied_plugin_requirements raise AttributeError, which propagates out
    # of download_plugins. This pins the current fragility of the index format:
    # a requirements (or min_version) key is effectively mandatory.
    import pytest

    inst = make_extension()
    plugins_json = {
        "plugin_baz": {"url": "u", "sha1sum": "s", "desc": "d"}  # no requirements
    }
    with (
        mock.patch.object(inst, "download_plugins_json", return_value=plugins_json),
        mock.patch.object(
            inst, "get_plugins", return_value=[{"filename": "plugin_settings.py"}]
        ),
    ):
        with pytest.raises(AttributeError):
            inst.download_plugins()


def test_download_plugins_missing_python_dependency_aborts(tmp_path):
    # A plugin declaring a python dependency that cannot be imported fails the
    # dependency check: the missing-dependency message is shown and the plugin
    # is NOT written to disk.
    inst = make_extension()
    plugins_json = {
        "plugin_dep": {
            "url": "http://example/dep.py",
            "sha1sum": "s",
            "desc": "Needs a lib",
            "requirements": {},
            "dependencies": {"python": ["a_module_that_does_not_exist_xyz"]},
        }
    }
    with contextlib.ExitStack() as stack:
        stack.enter_context(
            mock.patch.object(inst, "download_plugins_json", return_value=plugins_json)
        )
        stack.enter_context(
            mock.patch.object(
                inst, "get_plugins", return_value=[{"filename": "plugin_settings.py"}]
            )
        )
        stack.enter_context(mock.patch.object(inst, "message_open"))
        stack.enter_context(mock.patch.object(inst, "message_close"))
        stack.enter_context(
            mock.patch.object(inst, "select", side_effect=["dep - Needs a lib", 0])
        )
        stack.enter_context(mock.patch.object(main, "d", inst))
        stack.enter_context(mock.patch.object(inst, "open_url"))
        menu = stack.enter_context(mock.patch.object(inst, "menu"))
        dt = stack.enter_context(mock.patch.object(inst, "download_text"))
        stack.enter_context(mock.patch.object(main, "path_plugins", str(tmp_path)))
        inst.download_plugins()

    assert menu.call_args[0][0] == [
        "Plugin has missing dependencies and therefore was not installed"
    ]
    assert dt.called is False
    assert list(tmp_path.iterdir()) == []


def test_download_plugins_missing_external_dependency_aborts(tmp_path):
    # A plugin declaring an external (binary) dependency that is absent from the
    # scanned binaries fails the dependency check the same way.
    inst = make_extension()
    plugins_json = {
        "plugin_ext": {
            "url": "http://example/ext.py",
            "sha1sum": "s",
            "desc": "Needs a binary",
            "requirements": {},
            "dependencies": {
                "external": [{"name": "some_missing_binary", "url": "http://help"}]
            },
        }
    }
    with contextlib.ExitStack() as stack:
        stack.enter_context(
            mock.patch.object(inst, "download_plugins_json", return_value=plugins_json)
        )
        stack.enter_context(
            mock.patch.object(
                inst, "get_plugins", return_value=[{"filename": "plugin_settings.py"}]
            )
        )
        stack.enter_context(mock.patch.object(inst, "message_open"))
        stack.enter_context(mock.patch.object(inst, "message_close"))
        stack.enter_context(
            mock.patch.object(inst, "select", side_effect=["ext - Needs a binary", 0])
        )
        stack.enter_context(mock.patch.object(main, "d", inst))
        stack.enter_context(
            mock.patch.object(inst, "scan_binaries", return_value=["ls", "cat"])
        )
        open_url = stack.enter_context(mock.patch.object(inst, "open_url"))
        menu = stack.enter_context(mock.patch.object(inst, "menu"))
        dt = stack.enter_context(mock.patch.object(inst, "download_text"))
        stack.enter_context(mock.patch.object(main, "path_plugins", str(tmp_path)))
        inst.download_plugins()

    # The missing-external message references the dependency's help url.
    assert menu.call_args[0][0] == [
        "Plugin has missing dependencies and therefore was not installed"
    ]
    # The help url is offered for opening.
    assert open_url.call_args[0][0] == "http://help"
    assert dt.called is False
    assert list(tmp_path.iterdir()) == []


# ---------------------------------------------------------------------------
# update_plugins
# ---------------------------------------------------------------------------


def test_update_plugins_downloads_when_hash_differs(tmp_path):
    # When the local file does not verify against the index hash, the new source
    # is fetched from "<repository>/<name>.py"; once it verifies, the local file
    # is overwritten in place (no /tmp, no wget, no subprocess).
    inst = make_extension()
    new_source = b"# updated plugin source"
    plugins_there = {
        "foo": {
            "sha256": hashlib.sha256(new_source).hexdigest(),
            "repository": "https://repo-a",
        }
    }
    local_file = tmp_path / "foo.py"
    local_file.write_bytes(b"# stale local source")

    with contextlib.ExitStack() as stack:
        stack.enter_context(mock.patch.object(inst, "message_open"))
        stack.enter_context(mock.patch.object(inst, "message_close"))
        stack.enter_context(
            mock.patch.object(
                inst,
                "get_plugins",
                return_value=[
                    {"filename": "plugin_settings.py"},
                    {"filename": "foo.py"},
                ],
            )
        )
        stack.enter_context(
            mock.patch.object(inst, "download_plugins_json", return_value=plugins_there)
        )
        fetch = stack.enter_context(
            mock.patch.object(inst, "fetch_resource", return_value=new_source)
        )
        menu = stack.enter_context(mock.patch.object(inst, "menu"))
        stack.enter_context(mock.patch.object(main, "path_plugins", str(tmp_path)))
        inst.update_plugins()

    # The new source is fetched from "<repository>/<name>.py".
    fetch.assert_called_once_with("https://repo-a/foo.py")
    # The verified download is written over the stale local copy.
    assert local_file.read_bytes() == new_source
    assert menu.call_args[0][0] == ["foo was updated to the latest version"]


def test_update_plugins_skips_when_hash_matches(tmp_path):
    # When the local file already verifies against the index hash, nothing is
    # fetched and the "no new updates" message is shown.
    inst = make_extension()
    source = b"# current plugin source"
    plugins_there = {
        "foo": {
            "sha256": hashlib.sha256(source).hexdigest(),
            "repository": "https://repo-a",
        }
    }
    local_file = tmp_path / "foo.py"
    local_file.write_bytes(source)

    with contextlib.ExitStack() as stack:
        stack.enter_context(mock.patch.object(inst, "message_open"))
        stack.enter_context(mock.patch.object(inst, "message_close"))
        stack.enter_context(
            mock.patch.object(
                inst,
                "get_plugins",
                return_value=[
                    {"filename": "plugin_settings.py"},
                    {"filename": "foo.py"},
                ],
            )
        )
        stack.enter_context(
            mock.patch.object(inst, "download_plugins_json", return_value=plugins_there)
        )
        fetch = stack.enter_context(mock.patch.object(inst, "fetch_resource"))
        menu = stack.enter_context(mock.patch.object(inst, "menu"))
        stack.enter_context(mock.patch.object(main, "path_plugins", str(tmp_path)))
        inst.update_plugins()

    assert fetch.called is False
    assert local_file.read_bytes() == source
    assert menu.call_args[0][0] == ["There are no new updates for installed plugins"]


def test_update_plugins_does_not_write_on_failed_verification(tmp_path):
    # If the freshly fetched source fails verification, the local file is left
    # untouched and the update is not counted.
    inst = make_extension()
    plugins_there = {
        "foo": {
            "sha256": "0" * 64,  # matches neither local nor fetched bytes
            "repository": "https://repo-a",
        }
    }
    local_file = tmp_path / "foo.py"
    local_file.write_bytes(b"# stale local source")

    with contextlib.ExitStack() as stack:
        stack.enter_context(mock.patch.object(inst, "message_open"))
        stack.enter_context(mock.patch.object(inst, "message_close"))
        stack.enter_context(
            mock.patch.object(
                inst,
                "get_plugins",
                return_value=[
                    {"filename": "plugin_settings.py"},
                    {"filename": "foo.py"},
                ],
            )
        )
        stack.enter_context(
            mock.patch.object(inst, "download_plugins_json", return_value=plugins_there)
        )
        stack.enter_context(
            mock.patch.object(inst, "fetch_resource", return_value=b"tampered source")
        )
        menu = stack.enter_context(mock.patch.object(inst, "menu"))
        stack.enter_context(mock.patch.object(main, "path_plugins", str(tmp_path)))
        inst.update_plugins()

    assert local_file.read_bytes() == b"# stale local source"
    assert menu.call_args[0][0] == ["There are no new updates for installed plugins"]


def test_update_plugins_requires_settings_plugin_present():
    # update_plugins unconditionally calls plugins_here.remove("plugin_settings").
    # If the settings plugin is somehow absent from the loaded list, this raises
    # ValueError. Current quirk: the settings plugin is assumed always loaded.
    import pytest

    inst = make_extension()
    with contextlib.ExitStack() as stack:
        stack.enter_context(mock.patch.object(inst, "message_open"))
        stack.enter_context(mock.patch.object(inst, "message_close"))
        stack.enter_context(
            mock.patch.object(
                inst, "get_plugins", return_value=[{"filename": "foo.py"}]
            )
        )
        stack.enter_context(
            mock.patch.object(inst, "download_plugins_json", return_value={})
        )
        stack.enter_context(mock.patch.object(inst, "menu"))
        with pytest.raises(ValueError):
            inst.update_plugins()


# ---------------------------------------------------------------------------
# Plugin index format sanity (documents the expected entry shape)
# ---------------------------------------------------------------------------


def test_default_prefs_plugin_repositories_points_at_official_main_branch():
    # The shipped default repository is the official plugins repo on its main
    # branch, served over https.
    repos = main.default_prefs["plugin_repositories"]
    assert repos == [
        "https://raw.githubusercontent.com/markhedleyjones/dmenu-extended-plugins/main"
    ]


# ---------------------------------------------------------------------------
# repository_bases
# ---------------------------------------------------------------------------


def test_repository_bases_derived_from_prefs():
    # repository_bases reads the plugin_repositories preference verbatim.
    inst = make_extension()
    inst.prefs = {"plugin_repositories": ["https://repo-a", "https://repo-b"]}
    assert inst.repository_bases() == ["https://repo-a", "https://repo-b"]


def test_repository_bases_strips_trailing_slash():
    # A trailing slash on a configured base is stripped so "<base>/file" joins
    # cleanly without a doubled slash.
    inst = make_extension()
    inst.prefs = {"plugin_repositories": ["https://repo-a/", "/local/path/"]}
    assert inst.repository_bases() == ["https://repo-a", "/local/path"]


def test_repository_bases_empty_when_pref_absent():
    # With no plugin_repositories key the list is empty (the get() default).
    inst = make_extension()
    inst.prefs = {}
    assert inst.repository_bases() == []


# ---------------------------------------------------------------------------
# verify_plugin
# ---------------------------------------------------------------------------


def test_verify_plugin_sha256_match():
    data = b"plugin bytes"
    meta = {"sha256": hashlib.sha256(data).hexdigest()}
    assert main.extension.verify_plugin(meta, data) is True


def test_verify_plugin_sha256_mismatch():
    meta = {"sha256": "0" * 64}
    assert main.extension.verify_plugin(meta, b"plugin bytes") is False


def test_verify_plugin_sha256_takes_precedence_over_sha1(capsys):
    # When a sha256 is present it is used and the sha1 branch (which prints a
    # warning) is never reached.
    data = b"plugin bytes"
    meta = {
        "sha256": hashlib.sha256(data).hexdigest(),
        "sha1sum": "deadbeef",  # wrong, but should be ignored
    }
    assert main.extension.verify_plugin(meta, data) is True
    assert "sha1" not in capsys.readouterr().out


def test_verify_plugin_sha1_only_match(capsys):
    # With no sha256, a matching sha1sum verifies, but a warning is printed.
    data = b"plugin bytes"
    meta = {"sha1sum": hashlib.sha1(data).hexdigest()}
    assert main.extension.verify_plugin(meta, data) is True
    assert "sha1" in capsys.readouterr().out


def test_verify_plugin_sha1_only_mismatch():
    meta = {"sha1sum": "0" * 40}
    assert main.extension.verify_plugin(meta, b"plugin bytes") is False


def test_verify_plugin_no_hash_returns_false(capsys):
    # An entry with no integrity hash cannot be verified and is refused, with a
    # warning printed.
    assert main.extension.verify_plugin({}, b"plugin bytes") is False
    assert "no integrity hash" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# fetch_resource
# ---------------------------------------------------------------------------


def test_fetch_resource_refuses_plain_http():
    import pytest

    inst = make_extension()
    with pytest.raises(ValueError):
        inst.fetch_resource("http://example/plugin.py")


def test_fetch_resource_reads_local_path(tmp_path):
    inst = make_extension()
    target = tmp_path / "plugin.py"
    target.write_bytes(b"# local plugin source")
    assert inst.fetch_resource(str(target)) == b"# local plugin source"


def test_fetch_resource_https_uses_urllib():
    # An https URL is fetched via urllib.request.urlopen and the bytes returned.
    inst = make_extension()
    response = mock.Mock()
    response.read.return_value = b"# remote plugin source"
    with mock.patch("urllib.request.urlopen", return_value=response) as urlopen:
        out = inst.fetch_resource("https://example/plugin.py")

    assert out == b"# remote plugin source"
    assert urlopen.call_args[0][0] == "https://example/plugin.py"


def test_module_path_cache_suffix():
    # Sanity check that the imported package exposes the expected cache path,
    # mirroring the existing test_main.py expectation.
    assert d.path_cache[-len("dmenu-extended") :] == "dmenu-extended"
