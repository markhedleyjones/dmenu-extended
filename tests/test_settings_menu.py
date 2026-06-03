#!/usr/bin/env python3

"""Characterisation tests for the Settings submenu (extension class).

These pin down the CURRENT actual behaviour of three pieces of the settings
plugin in dmenu_extended.main:

  * extension.run() - how it assembles the action list (which items appear
    depending on installed plugins, frequently_used and the systemd status)
    and how it dispatches options.index(item) -> actions[index]().
  * extension.get_automatic_rebuild_cache_status() - its 0/1/2 return values
    over the which/systemctl/list-unit-files/is-enabled subprocess boundaries.
  * extension.rebuild_cache() - the cache-size-delta wording it feeds to menu().

Every boundary that would touch the real system is mocked: subprocess.call /
subprocess.check_output, and the UI methods select() / menu(). The real
dispatch and branching bodies are allowed to run.
"""

import sys
from os import path

import mock
import pytest

# Add src directory to path to import dmenu_extended
sys.path.insert(0, path.join(path.dirname(__file__), "..", "src"))
from dmenu_extended import main


def make_extension(prefs=None):
    """Build an extension instance without running __init__.

    extension.__init__ calls load_preferences which would read the real user
    config from disk, so we bypass it via __new__ and inject prefs directly.
    """
    inst = main.extension.__new__(main.extension)
    if prefs is None:
        prefs = {"indicator_submenu": "->", "frequently_used": 0}
    inst.prefs = prefs
    return inst


# ---------------------------------------------------------------------------
# extension.run() - action-list assembly
# ---------------------------------------------------------------------------


def _run_and_capture_items(inst, plugins, status, selected=-1):
    """Drive run() with the boundaries stubbed and return the items offered.

    installed_plugins(), get_automatic_rebuild_cache_status() and select() are
    all patched. select() returns -1 by default so dispatch is skipped (run()
    only dispatches when the result is not -1). Returns the list passed to
    select().
    """
    with (
        mock.patch.object(inst, "installed_plugins", return_value=plugins),
        mock.patch.object(
            inst, "get_automatic_rebuild_cache_status", return_value=status
        ),
        mock.patch.object(inst, "select", return_value=selected) as select,
    ):
        inst.run("")
    return select.call_args[0][0]


def test_run_base_items_when_no_plugins_no_recent_no_systemd():
    # No installed plugins, frequently_used == 0, systemd status 0: only the two
    # always-present items plus "Edit menu preferences" are offered.
    inst = make_extension({"indicator_submenu": "->", "frequently_used": 0})
    items = _run_and_capture_items(inst, plugins=[], status=0)
    assert items == [
        "Rebuild cache",
        "-> Download new plugins",
        "Edit menu preferences",
    ]


def test_run_plugin_items_appear_only_when_plugins_installed():
    # With at least one installed plugin, the remove + update plugin items appear
    # immediately after the download item.
    inst = make_extension({"indicator_submenu": "->", "frequently_used": 0})
    items = _run_and_capture_items(inst, plugins=["foo (plugin_foo.py)"], status=0)
    assert items == [
        "Rebuild cache",
        "-> Download new plugins",
        "-> Remove existing plugins",
        "Update installed plugins",
        "Edit menu preferences",
    ]


def test_run_clear_recent_item_appears_only_when_frequently_used_positive():
    # frequently_used > 0 adds the "Clear recent entries" item after the edit
    # preferences item.
    inst = make_extension({"indicator_submenu": "->", "frequently_used": 5})
    items = _run_and_capture_items(inst, plugins=[], status=0)
    assert items == [
        "Rebuild cache",
        "-> Download new plugins",
        "Edit menu preferences",
        "Clear recent entries",
    ]


def test_run_systemd_status_one_offers_disable_item():
    # Status 1 (timer installed and enabled) offers the "Disable" item only.
    inst = make_extension({"indicator_submenu": "->", "frequently_used": 0})
    items = _run_and_capture_items(inst, plugins=[], status=1)
    assert items[-1] == "Disable automatic cache rebuilding"
    assert "Enable automatic cache rebuilding" not in items


def test_run_systemd_status_two_offers_enable_item():
    # Status 2 (timer installed but disabled) offers the "Enable" item only.
    inst = make_extension({"indicator_submenu": "->", "frequently_used": 0})
    items = _run_and_capture_items(inst, plugins=[], status=2)
    assert items[-1] == "Enable automatic cache rebuilding"
    assert "Disable automatic cache rebuilding" not in items


def test_run_systemd_status_zero_omits_both_systemd_items():
    inst = make_extension({"indicator_submenu": "->", "frequently_used": 0})
    items = _run_and_capture_items(inst, plugins=[], status=0)
    assert "Disable automatic cache rebuilding" not in items
    assert "Enable automatic cache rebuilding" not in items


def test_run_all_items_present_with_plugins_recent_and_enabled_timer():
    # Every conditional branch active at once: plugins installed, recent enabled,
    # systemd timer enabled (status 1 -> Disable item).
    inst = make_extension({"indicator_submenu": "->", "frequently_used": 3})
    items = _run_and_capture_items(inst, plugins=["foo (plugin_foo.py)"], status=1)
    assert items == [
        "Rebuild cache",
        "-> Download new plugins",
        "-> Remove existing plugins",
        "Update installed plugins",
        "Edit menu preferences",
        "Clear recent entries",
        "Disable automatic cache rebuilding",
    ]


# ---------------------------------------------------------------------------
# extension.run() - dispatch via options.index(item) -> actions[index]()
# ---------------------------------------------------------------------------


def _dispatch(inst, selected, plugins=None, status=0, frequently_used=0):
    """Run dispatch for ``selected`` and return the patched action mocks.

    Returns a dict mapping action-method name -> mock so the test can assert
    exactly one of them fired. The eight action methods are patched out so the
    dispatch table can be exercised without running the real bodies.
    """
    inst.prefs = {"indicator_submenu": "->", "frequently_used": frequently_used}
    action_names = [
        "rebuild_cache",
        "download_plugins",
        "remove_plugin",
        "update_plugins",
        "edit_preferences",
        "clear_recent",
        "disable_automatic_rebuild_cache",
        "enable_automatic_rebuild_cache",
    ]
    patchers = {name: mock.patch.object(inst, name) for name in action_names}
    mocks = {name: p.start() for name, p in patchers.items()}
    try:
        with (
            mock.patch.object(inst, "installed_plugins", return_value=plugins or []),
            mock.patch.object(
                inst, "get_automatic_rebuild_cache_status", return_value=status
            ),
            mock.patch.object(inst, "select", return_value=selected),
        ):
            inst.run("")
    finally:
        for p in patchers.values():
            p.stop()
    return mocks


def test_dispatch_rebuild_cache():
    inst = make_extension()
    mocks = _dispatch(inst, selected="Rebuild cache")
    mocks["rebuild_cache"].assert_called_once_with()
    # No other action fired.
    assert sum(m.called for m in mocks.values()) == 1


def test_dispatch_download_plugins():
    inst = make_extension()
    mocks = _dispatch(inst, selected="-> Download new plugins")
    mocks["download_plugins"].assert_called_once_with()
    assert sum(m.called for m in mocks.values()) == 1


def test_dispatch_remove_plugin():
    inst = make_extension()
    mocks = _dispatch(
        inst, selected="-> Remove existing plugins", plugins=["foo (plugin_foo.py)"]
    )
    mocks["remove_plugin"].assert_called_once_with()
    assert sum(m.called for m in mocks.values()) == 1


def test_dispatch_update_plugins():
    inst = make_extension()
    mocks = _dispatch(
        inst, selected="Update installed plugins", plugins=["foo (plugin_foo.py)"]
    )
    mocks["update_plugins"].assert_called_once_with()
    assert sum(m.called for m in mocks.values()) == 1


def test_dispatch_edit_preferences():
    inst = make_extension()
    mocks = _dispatch(inst, selected="Edit menu preferences")
    mocks["edit_preferences"].assert_called_once_with()
    assert sum(m.called for m in mocks.values()) == 1


def test_dispatch_clear_recent():
    inst = make_extension()
    mocks = _dispatch(inst, selected="Clear recent entries", frequently_used=4)
    mocks["clear_recent"].assert_called_once_with()
    assert sum(m.called for m in mocks.values()) == 1


def test_dispatch_disable_automatic_rebuild():
    inst = make_extension()
    mocks = _dispatch(inst, selected="Disable automatic cache rebuilding", status=1)
    mocks["disable_automatic_rebuild_cache"].assert_called_once_with()
    assert sum(m.called for m in mocks.values()) == 1


def test_dispatch_enable_automatic_rebuild():
    inst = make_extension()
    mocks = _dispatch(inst, selected="Enable automatic cache rebuilding", status=2)
    mocks["enable_automatic_rebuild_cache"].assert_called_once_with()
    assert sum(m.called for m in mocks.values()) == 1


def test_dispatch_does_nothing_when_select_returns_minus_one():
    # select() returns -1 when nothing matched; run() then skips dispatch and no
    # action method is invoked.
    inst = make_extension()
    mocks = _dispatch(inst, selected=-1)
    assert all(not m.called for m in mocks.values())


# ---------------------------------------------------------------------------
# get_automatic_rebuild_cache_status() - 0/1/2 over the subprocess boundaries
# ---------------------------------------------------------------------------


def test_status_zero_when_systemctl_absent():
    # `which systemctl` returning non-zero means no systemd: status 0, and no
    # further systemctl calls are attempted.
    inst = make_extension()
    with (
        mock.patch("subprocess.call", return_value=1) as call,
        mock.patch("subprocess.check_output") as check,
    ):
        assert inst.get_automatic_rebuild_cache_status() == 0
    # Only the `which systemctl` probe ran; daemon-reload / is-enabled never did.
    call.assert_called_once_with(["which", "systemctl"])
    assert check.called is False


def test_status_zero_when_list_unit_files_raises():
    # If list-unit-files raises CalledProcessError, status is 0.
    inst = make_extension()
    with (
        mock.patch("subprocess.call", return_value=0),
        mock.patch(
            "subprocess.check_output",
            side_effect=main.subprocess.CalledProcessError(1, "systemctl"),
        ),
    ):
        assert inst.get_automatic_rebuild_cache_status() == 0


def test_status_zero_when_timer_not_listed():
    # `which` and daemon-reload succeed but the timer unit is not in the
    # list-unit-files output, so status is 0.
    inst = make_extension()
    with (
        mock.patch("subprocess.call", return_value=0),
        mock.patch("subprocess.check_output", return_value=b"some-other.timer\n"),
    ):
        assert inst.get_automatic_rebuild_cache_status() == 0


def test_status_one_when_timer_enabled():
    # Timer present and `is-enabled` returns 0 -> status 1 (running/enabled).
    inst = make_extension()
    call_values = iter([0, 0, 0])  # which, daemon-reload, is-enabled

    def fake_call(cmd):
        return next(call_values)

    with (
        mock.patch("subprocess.call", side_effect=fake_call),
        mock.patch(
            "subprocess.check_output",
            return_value=b"dmenu-extended-update-db.timer enabled\n",
        ),
    ):
        assert inst.get_automatic_rebuild_cache_status() == 1


def test_status_two_when_timer_disabled():
    # Timer present but `is-enabled` returns non-zero -> status 2 (not running).
    inst = make_extension()
    call_values = iter([0, 0, 1])  # which, daemon-reload, is-enabled

    def fake_call(cmd):
        return next(call_values)

    with (
        mock.patch("subprocess.call", side_effect=fake_call),
        mock.patch(
            "subprocess.check_output",
            return_value=b"dmenu-extended-update-db.timer disabled\n",
        ),
    ):
        assert inst.get_automatic_rebuild_cache_status() == 2


def test_status_issues_is_enabled_probe_for_the_timer_unit():
    # Confirm the is-enabled probe targets the correct timer unit name.
    inst = make_extension()
    calls = []

    def fake_call(cmd):
        calls.append(cmd)
        return 0

    with (
        mock.patch("subprocess.call", side_effect=fake_call),
        mock.patch(
            "subprocess.check_output",
            return_value=b"dmenu-extended-update-db.timer enabled\n",
        ),
    ):
        inst.get_automatic_rebuild_cache_status()
    assert calls[-1] == [
        "systemctl",
        "--user",
        "is-enabled",
        "dmenu-extended-update-db.timer",
    ]


# ---------------------------------------------------------------------------
# rebuild_cache() - cache-size-delta messaging
# ---------------------------------------------------------------------------


def _rebuild_with_sizes(inst, before_lines, after_lines, regenerate_result=True):
    """Run rebuild_cache() with cache_load returning two distinct sizes.

    cache_load() is called twice (before and after regenerate); we feed it a
    string with the requested number of newline-joined lines each time. The menu
    response list is captured and returned.
    """
    before = "\n".join(["x"] * before_lines)
    after = "\n".join(["x"] * after_lines)
    with (
        mock.patch.object(inst, "cache_load", side_effect=[before, after]),
        mock.patch.object(inst, "cache_regenerate", return_value=regenerate_result),
        mock.patch.object(inst, "menu") as menu,
    ):
        inst.rebuild_cache()
    return menu.call_args[0][0]


def test_rebuild_cache_singular_added():
    # A net change of +1 item uses the singular "one new item was added." wording.
    inst = make_extension()
    response = _rebuild_with_sizes(inst, before_lines=2, after_lines=3)
    assert response[0] == "Cache updated successfully; one new item was added."


def test_rebuild_cache_plural_added():
    # A net change of +3 uses the plural "<n> items were added." wording.
    inst = make_extension()
    response = _rebuild_with_sizes(inst, before_lines=2, after_lines=5)
    assert response[0] == "Cache updated successfully; 3 items were added."


def test_rebuild_cache_singular_removed():
    # A net change of -1 uses the singular "one item was removed." wording.
    inst = make_extension()
    response = _rebuild_with_sizes(inst, before_lines=5, after_lines=4)
    assert response[0] == "Cache updated successfully; one item was removed."


def test_rebuild_cache_plural_removed():
    # A net change of -3 uses "<abs(n)> items were removed.".
    inst = make_extension()
    response = _rebuild_with_sizes(inst, before_lines=6, after_lines=3)
    assert response[0] == "Cache updated successfully; 3 items were removed."


def test_rebuild_cache_size_did_not_change():
    # Equal before/after sizes produce the single "size did not change" line.
    inst = make_extension()
    response = _rebuild_with_sizes(inst, before_lines=4, after_lines=4)
    assert response[0] == "Cache rebuilt; its size did not change."
    # No performance notice is appended on the unchanged path.
    assert len(response) == 2


def test_rebuild_cache_performance_notice_when_result_is_two():
    # When cache_regenerate returns 2 (performance issues) AND the size changed,
    # a NOTICE line is inserted between the status line and the summary line.
    inst = make_extension()
    response = _rebuild_with_sizes(
        inst, before_lines=2, after_lines=4, regenerate_result=2
    )
    assert response[0] == "Cache updated successfully; 2 items were added."
    assert response[1] == (
        "NOTICE: Performance issues were encountered while caching data"
    )


def test_rebuild_cache_no_performance_notice_when_size_unchanged():
    # The performance NOTICE only fires on the "size changed" branch; an
    # unchanged size with result==2 still omits it.
    inst = make_extension()
    response = _rebuild_with_sizes(
        inst, before_lines=4, after_lines=4, regenerate_result=2
    )
    assert all("NOTICE" not in line for line in response)


def test_rebuild_cache_summary_reports_original_size():
    # The final summary line reports the ORIGINAL (pre-rebuild) cache size, not
    # the new one - a quirk worth pinning.
    inst = make_extension()
    response = _rebuild_with_sizes(inst, before_lines=7, after_lines=10)
    assert response[-1].startswith("The cache contains 7 items and took ")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
