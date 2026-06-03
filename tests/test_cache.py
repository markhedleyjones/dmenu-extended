#!/usr/bin/env python3

"""Characterisation tests for the cache machinery in dmenu_extended.main.

These pin down the CURRENT behaviour of build_cache, cache_load, cache_save,
cache_open, cache_regenerate, scan_binaries, scan_applications, system_path and
the include/exclude/ignore/alias preferences that shape the cache. The
filesystem is redirected into a temporary directory via the
DMENU_EXTENDED_CACHE_DIR environment variable, and every boundary that would
touch the real system (binary scan, application scan, plugins, subprocess) is
mocked.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from dmenu_extended import main
import mock


class CacheTestBase(unittest.TestCase):
    """Redirect cache files into a temp dir and give a fresh dmenu instance.

    The module reads DMENU_EXTENDED_CACHE_DIR at import time to choose
    path_cache, so we set it, reload the module, then re-point the module-level
    file_cache_* globals (mirroring tests/test_frequently_used_cleanup.py).
    """

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self._orig_cache_dir = os.environ.get("DMENU_EXTENDED_CACHE_DIR")
        os.environ["DMENU_EXTENDED_CACHE_DIR"] = self.test_dir

        import importlib

        importlib.reload(main)

        self._repoint_cache_globals()

        self.dmenu = main.dmenu()
        # Avoid sharing class-level prefs between instances/tests.
        self.dmenu.prefs = dict(main.default_prefs)

    def tearDown(self):
        if self._orig_cache_dir is not None:
            os.environ["DMENU_EXTENDED_CACHE_DIR"] = self._orig_cache_dir
        else:
            os.environ.pop("DMENU_EXTENDED_CACHE_DIR", None)

        import importlib

        importlib.reload(main)
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _repoint_cache_globals(self):
        c = main.path_cache
        main.file_cache = c + "/dmenuExtended_all.txt"
        main.file_cache_binaries = c + "/dmenuExtended_binaries.txt"
        main.file_cache_files = c + "/dmenuExtended_files.txt"
        main.file_cache_folders = c + "/dmenuExtended_folders.txt"
        main.file_cache_aliases = c + "/dmenuExtended_aliases.txt"
        main.file_cache_aliasesLookup = c + "/dmenuExtended_aliases_lookup.json"
        main.file_cache_plugins = c + "/dmenuExtended_plugins.txt"
        main.file_cache_frequentlyUsed_frequency = (
            c + "/dmenuExtended_frequentlyUsed_frequency.json"
        )
        main.file_cache_frequentlyUsed_ordered = (
            c + "/dmenuExtended_frequentlyUsed_ordered.json"
        )


# ---------------------------------------------------------------------------
# cache_save / cache_open round-trips
# ---------------------------------------------------------------------------


class TestCacheSaveOpen(CacheTestBase):
    def test_save_list_writes_newline_terminated_lines(self):
        path = os.path.join(self.test_dir, "list.txt")
        result = self.dmenu.cache_save(["alpha", "beta", "gamma"], path)
        # Returns 1 on the normal path.
        self.assertEqual(result, 1)
        with open(path) as f:
            self.assertEqual(f.read(), "alpha\nbeta\ngamma\n")

    def test_save_string_written_verbatim(self):
        path = os.path.join(self.test_dir, "str.txt")
        # A plain string is written as-is, with no added trailing newline.
        result = self.dmenu.cache_save("just a string", path)
        self.assertEqual(result, 1)
        with open(path) as f:
            self.assertEqual(f.read(), "just a string")

    def test_open_returns_full_file_contents_as_string(self):
        path = os.path.join(self.test_dir, "round.txt")
        self.dmenu.cache_save(["one", "two"], path)
        # cache_open returns the raw text including trailing newline, not a list.
        self.assertEqual(self.dmenu.cache_open(path), "one\ntwo\n")

    def test_open_missing_file_returns_false(self):
        missing = os.path.join(self.test_dir, "does_not_exist.txt")
        self.assertIs(self.dmenu.cache_open(missing), False)

    def test_save_non_printable_excludes_offending_items_returns_2(self):
        # A surrogate cannot be encoded to the default locale on write, which
        # trips the UnicodeEncodeError branch; offending lines are dropped and
        # the remainder written unicode-escaped. Return code is 2.
        path = os.path.join(self.test_dir, "bad.txt")
        items = ["clean", "ba\udcffd"]
        result = self.dmenu.cache_save(items, path)
        self.assertEqual(result, 2)
        with open(path, "rb") as f:
            data = f.read()
        # Only the clean item is written; the offending one is dropped entirely.
        self.assertEqual(data, b"clean\n")


# ---------------------------------------------------------------------------
# system_path
# ---------------------------------------------------------------------------


class TestSystemPath(CacheTestBase):
    def test_dedupes_and_drops_empty_entries(self):
        with mock.patch.dict(os.environ, {"PATH": "/bin:/usr/bin:/bin::"}):
            result = self.dmenu.system_path()
        self.assertIsInstance(result, list)
        self.assertNotIn("", result)
        # Deduplicated: /bin appears once despite being listed twice.
        self.assertEqual(sorted(result), ["/bin", "/usr/bin"])


# ---------------------------------------------------------------------------
# scan_binaries
# ---------------------------------------------------------------------------


class TestScanBinaries(CacheTestBase):
    def test_lists_directory_contents_and_skips_gpk_prefixed(self):
        bindir = os.path.join(self.test_dir, "bin")
        os.makedirs(bindir)
        for name in ["firefox", "htop", "gpk-application", "gpkother"]:
            open(os.path.join(bindir, name), "w").close()

        with mock.patch.object(self.dmenu, "system_path", lambda: [bindir]):
            result = self.dmenu.scan_binaries()

        self.assertIn("firefox", result)
        self.assertIn("htop", result)
        # Anything whose first three characters are "gpk" is filtered out.
        self.assertNotIn("gpk-application", result)
        self.assertNotIn("gpkother", result)

    def test_path_entry_that_is_a_file_is_appended_directly(self):
        # When a PATH entry is itself a file (not a directory), the full path is
        # appended verbatim rather than its contents listed.
        filepath = os.path.join(self.test_dir, "a_file")
        open(filepath, "w").close()
        with mock.patch.object(self.dmenu, "system_path", lambda: [filepath]):
            result = self.dmenu.scan_binaries()
        self.assertEqual(result, [filepath])


# ---------------------------------------------------------------------------
# scan_applications (parsing .desktop files)
# ---------------------------------------------------------------------------


class TestScanApplications(CacheTestBase):
    def _write_desktop(self, dirpath, filename, contents):
        os.makedirs(dirpath, exist_ok=True)
        with open(os.path.join(dirpath, filename), "w") as f:
            f.write(contents)

    def test_parses_name_command_terminal_and_descriptor(self):
        appdir = os.path.join(self.test_dir, "applications")
        self._write_desktop(
            appdir,
            "firefox.desktop",
            "[Desktop Entry]\nName=Firefox\nGenericName=Web Browser\n"
            "Exec=firefox %u\nTerminal=false\n",
        )
        with (
            mock.patch.object(self.dmenu, "application_paths", lambda: [appdir]),
            mock.patch.object(self.dmenu, "system_path", lambda: []),
        ):
            apps = self.dmenu.scan_applications()

        self.assertEqual(len(apps), 1)
        app = apps[0]
        self.assertEqual(app["name"], "Firefox")
        self.assertEqual(app["name_generic"], "Web Browser")
        # The "%u" field code and everything after it is stripped from Exec.
        self.assertEqual(app["command"], "firefox")
        self.assertIs(app["terminal"], False)
        # descriptor is the filename minus the .desktop suffix.
        self.assertEqual(app["descriptor"], "firefox")

    def test_terminal_true_recorded_and_generic_defaults_to_name(self):
        appdir = os.path.join(self.test_dir, "applications")
        self._write_desktop(
            appdir,
            "htop.desktop",
            "[Desktop Entry]\nName=Htop\nExec=htop\nTerminal=True\n",
        )
        with (
            mock.patch.object(self.dmenu, "application_paths", lambda: [appdir]),
            mock.patch.object(self.dmenu, "system_path", lambda: []),
        ):
            apps = self.dmenu.scan_applications()

        self.assertEqual(len(apps), 1)
        self.assertIs(apps[0]["terminal"], True)
        # With no GenericName line, name_generic falls back to name.
        self.assertEqual(apps[0]["name_generic"], "Htop")

    def test_entry_missing_exec_or_name_is_skipped(self):
        appdir = os.path.join(self.test_dir, "applications")
        self._write_desktop(appdir, "noexec.desktop", "[Desktop Entry]\nName=NoExec\n")
        self._write_desktop(appdir, "noname.desktop", "[Desktop Entry]\nExec=mystery\n")
        with (
            mock.patch.object(self.dmenu, "application_paths", lambda: [appdir]),
            mock.patch.object(self.dmenu, "system_path", lambda: []),
        ):
            apps = self.dmenu.scan_applications()
        # Both entries lack one of the required Name/Exec pair, so neither is kept.
        self.assertEqual(apps, [])

    def test_command_with_absolute_path_in_system_path_is_shortened(self):
        appdir = os.path.join(self.test_dir, "applications")
        self._write_desktop(
            appdir,
            "tool.desktop",
            "[Desktop Entry]\nName=Tool\nExec=/usr/bin/tool\nTerminal=false\n",
        )
        with (
            mock.patch.object(self.dmenu, "application_paths", lambda: [appdir]),
            mock.patch.object(self.dmenu, "system_path", lambda: ["/usr/bin"]),
        ):
            apps = self.dmenu.scan_applications()
        # The leading "/usr/bin/" is stripped because the bare name has no slash.
        self.assertEqual(apps[0]["command"], "tool")


# ---------------------------------------------------------------------------
# alias file parsing (path_aliasFile)
# ---------------------------------------------------------------------------


class TestParseAliasFile(CacheTestBase):
    def test_parses_alias_lines_and_strips_matching_outer_quotes(self):
        alias_path = os.path.join(self.test_dir, ".bash_aliases")
        with open(alias_path, "w") as f:
            f.write(
                'alias ll="ls -la"\n'
                "alias gs='git status'\n"
                "# a comment line\n"
                "export FOO=bar\n"
                "alias gp=git push\n"
            )
        result = self.dmenu.parse_alias_file(alias_path)
        # Only "alias " lines are parsed; comments and exports are ignored.
        self.assertEqual(
            result,
            [
                ["ll", "ls -la"],
                ["gs", "git status"],
                ["gp", "git push"],
            ],
        )

    def test_preserves_interior_equals_in_command(self):
        alias_path = os.path.join(self.test_dir, ".bash_aliases")
        with open(alias_path, "w") as f:
            f.write('alias setx="export X=1"\n')
        result = self.dmenu.parse_alias_file(alias_path)
        # The value is re-joined on "=" so interior equals signs survive.
        self.assertEqual(result, [["setx", "export X=1"]])


# ---------------------------------------------------------------------------
# build_cache: how include/exclude/ignore/alias prefs shape the output
# ---------------------------------------------------------------------------


class TestBuildCache(CacheTestBase):
    def _run_build(self, prefs_overrides=None):
        """Run build_cache with all expensive boundaries stubbed out.

        Returns the cache_load() text after the build. Plugins are forced to an
        empty list, the filesystem walk is suppressed by pointing watch_folders
        at an empty temp directory, and binary/application scans are controlled
        per-test via the supplied prefs.
        """
        self.dmenu.prefs.update(prefs_overrides or {})
        # An empty watch folder so os.walk yields nothing (no real home scan).
        empty = os.path.join(self.test_dir, "watch_empty")
        os.makedirs(empty, exist_ok=True)
        self.dmenu.prefs["watch_folders"] = [empty]

        # message_open/message_close spawn the real menu (dmenu) for progress
        # UI; stub them so neither the build nor a cache_load-triggered
        # regenerate shells out. plugins_available is stubbed only around
        # build_cache - cache_load needs the real one so it writes the plugins
        # cache file (otherwise cache_load hits its exitOnFail sys.exit).
        with (
            mock.patch.object(self.dmenu, "message_open"),
            mock.patch.object(self.dmenu, "message_close"),
        ):
            with mock.patch.object(self.dmenu, "plugins_available", lambda: []):
                self.dmenu.build_cache()
            return self.dmenu.cache_load()

    def test_binaries_excluded_by_default(self):
        # include_binaries defaults to False, so scan_binaries is never invoked
        # and no binary appears in the cache.
        with (
            mock.patch.object(
                self.dmenu, "scan_binaries", lambda: ["should_not_appear"]
            ),
            mock.patch.object(self.dmenu, "scan_applications", lambda: []),
        ):
            text = self._run_build({"include_applications": False})
        self.assertNotIn("should_not_appear", text)

    def test_include_binaries_true_adds_binaries(self):
        with (
            mock.patch.object(self.dmenu, "scan_binaries", lambda: ["firefox", "htop"]),
            mock.patch.object(self.dmenu, "scan_applications", lambda: []),
        ):
            text = self._run_build(
                {"include_binaries": True, "include_applications": False}
            )
        self.assertIn("firefox", text)
        self.assertIn("htop", text)

    def test_include_items_appended_to_cache(self):
        with mock.patch.object(self.dmenu, "scan_applications", lambda: []):
            text = self._run_build(
                {
                    "include_applications": False,
                    "include_items": ["my custom entry"],
                }
            )
        self.assertIn("my custom entry", text)

    def test_exclude_items_removed_from_cache(self):
        with (
            mock.patch.object(
                self.dmenu, "scan_binaries", lambda: ["keepme", "dropme"]
            ),
            mock.patch.object(self.dmenu, "scan_applications", lambda: []),
        ):
            text = self._run_build(
                {
                    "include_binaries": True,
                    "include_applications": False,
                    "exclude_items": ["dropme"],
                }
            )
        self.assertIn("keepme", text)
        self.assertNotIn("dropme", text)

    def test_rebuild_cache_sentinel_always_present(self):
        with mock.patch.object(self.dmenu, "scan_applications", lambda: []):
            text = self._run_build({"include_applications": False})
        # build_cache always appends a literal "rebuild cache" entry.
        self.assertIn("rebuild cache", text)

    def test_aliased_application_writes_lookup_and_aliases_files(self):
        apps = [
            {
                "name": "Htop",
                "name_generic": "Process Viewer",
                "command": "htop",
                "terminal": True,
                "descriptor": "htop",
            }
        ]
        with (
            mock.patch.object(self.dmenu, "scan_applications", lambda: apps),
            mock.patch.object(self.dmenu, "scan_binaries", lambda: []),
        ):
            text = self._run_build(
                {
                    "include_applications": True,
                    "alias_applications": True,
                    "include_binaries": False,
                }
            )
        # Default alias_display_format is "{name}" and indicator_alias is empty,
        # so the displayed item is just the application name.
        self.assertIn("Htop", text)

        # The lookup file maps the displayed title to the real command, and a
        # terminal app gets a trailing ";" appended to its command.
        with open(main.file_cache_aliasesLookup) as f:
            lookup = json.load(f)
        self.assertEqual(lookup, [["Htop", "htop;"]])

    def test_include_items_alias_pair_added_as_alias(self):
        # A two-element list in include_items is treated as an [name, command]
        # alias, not a plain string entry.
        with (
            mock.patch.object(self.dmenu, "scan_applications", lambda: []),
            mock.patch.object(self.dmenu, "scan_binaries", lambda: []),
        ):
            text = self._run_build(
                {
                    "include_applications": False,
                    "include_items": [["My Editor", "vim"]],
                }
            )
        self.assertIn("My Editor", text)
        with open(main.file_cache_aliasesLookup) as f:
            lookup = json.load(f)
        self.assertIn(["My Editor", "vim"], lookup)

    def test_path_alias_file_entries_folded_into_cache(self):
        alias_path = os.path.join(self.test_dir, "myaliases")
        with open(alias_path, "w") as f:
            f.write('alias ll="ls -la"\n')
        with (
            mock.patch.object(self.dmenu, "scan_applications", lambda: []),
            mock.patch.object(self.dmenu, "scan_binaries", lambda: []),
        ):
            text = self._run_build(
                {
                    "include_applications": False,
                    "path_aliasFile": alias_path,
                }
            )
        # The alias name (formatted via "{name}") is present in the cache.
        self.assertIn("ll", text)
        with open(main.file_cache_aliasesLookup) as f:
            lookup = json.load(f)
        self.assertIn(["ll", "ls -la"], lookup)

    def test_include_item_with_trailing_semicolon_drops_plain_binary(self):
        # If a binary "htop" exists and an include_item "htop;" is supplied, the
        # non-semicolon binary form is removed in favour of the terminal form.
        with (
            mock.patch.object(self.dmenu, "scan_binaries", lambda: ["htop"]),
            mock.patch.object(self.dmenu, "scan_applications", lambda: []),
        ):
            text = self._run_build(
                {
                    "include_binaries": True,
                    "include_applications": False,
                    "include_items": ["htop;"],
                }
            )
        lines = text.split("\n")
        self.assertIn("htop;", lines)
        self.assertNotIn("htop", lines)


# ---------------------------------------------------------------------------
# cache_load / cache_regenerate behaviour
# ---------------------------------------------------------------------------


class TestCacheLoad(CacheTestBase):
    def test_regenerates_when_scanned_cache_missing(self):
        # With no cache files present, cache_load triggers cache_regenerate,
        # which we intercept to write a minimal cache, then it re-reads.
        self.dmenu.prefs = dict(main.default_prefs)

        def fake_regenerate(message=True):
            self.dmenu.cache_save(["plugin item"], main.file_cache_plugins)
            self.dmenu.cache_save(["scanned item"], main.file_cache)
            return True

        with mock.patch.object(self.dmenu, "cache_regenerate", fake_regenerate):
            text = self.dmenu.cache_load()

        self.assertIn("scanned item", text)
        # Settings entry is injected using the indicator_submenu prefix.
        self.assertIn("Settings", text)

    def test_show_scanned_false_omits_scanned_entries(self):
        self.dmenu.prefs = dict(main.default_prefs)
        self.dmenu.cache_save(["plugin item"], main.file_cache_plugins)
        self.dmenu.cache_save(["scanned item"], main.file_cache)
        self.dmenu.show_scanned = False
        text = self.dmenu.cache_load()
        self.assertNotIn("scanned item", text)

    def test_show_settings_false_puts_settings_last(self):
        self.dmenu.prefs = dict(main.default_prefs)
        self.dmenu.cache_save([], main.file_cache_plugins)
        self.dmenu.cache_save(["scanned item"], main.file_cache)
        self.dmenu.show_settings = False
        text = self.dmenu.cache_load()
        # When show_settings is False the Settings entry is appended at the end.
        self.assertTrue(text.rstrip("\n").endswith("Settings"))

    def test_cache_regenerate_without_message_calls_build_cache(self):
        with mock.patch.object(self.dmenu, "build_cache", lambda: ["built"]) as _:
            result = self.dmenu.cache_regenerate(message=False)
        self.assertEqual(result, ["built"])


if __name__ == "__main__":
    unittest.main()
