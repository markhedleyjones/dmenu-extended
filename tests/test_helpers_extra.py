#!/usr/bin/env python3

"""Characterisation tests for the remaining helper gaps in dmenu_extended.main.

These pin down the CURRENT behaviour (including quirks) of:

* cache_load() visibility/assembly branches not already covered by
  tests/test_cache.py: show_plugins=False forcing cache_plugins to '',
  show_recent=False forcing cache_frequent to '', the '-> Settings\\n' line
  being stripped out of the plugins cache, and the prepend ordering of the
  frequently-used items relative to the scanned items.
* retrieve_aliased_command(): a real lookup returning item[1], None on a miss,
  and the unconditional print(alias) side effect.
* open_directory(): the filebrowser command string it hands to execute().
* open_file()'s exit-code 256/4 fallback-offer path.
* get_password(): the in-place prefs['password_helper'] {prompt} substitution
  quirk, then the command_output delegation.

The cache files are redirected into a temp dir via DMENU_EXTENDED_CACHE_DIR and
the module is reloaded, mirroring tests/test_cache.py. Every boundary that would
touch the real system (subprocess, the menu/select/message UI, the cache regen)
is mocked so nothing real is launched and the real config is never touched.
"""

import contextlib
import importlib
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from dmenu_extended import main
import mock


class HelpersTestBase(unittest.TestCase):
    """Redirect cache files into a temp dir and give a fresh dmenu instance.

    The module reads DMENU_EXTENDED_CACHE_DIR at import time to choose
    path_cache, so we set it, reload the module, then re-point the module-level
    file_cache_* globals (mirroring tests/test_cache.py).
    """

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self._orig_cache_dir = os.environ.get("DMENU_EXTENDED_CACHE_DIR")
        os.environ["DMENU_EXTENDED_CACHE_DIR"] = self.test_dir

        importlib.reload(main)
        self._repoint_cache_globals()

        self.dmenu = main.dmenu()
        # Avoid sharing class-level prefs between instances/tests, and a fresh
        # copy so the get_password in-place mutation cannot leak across tests.
        self.dmenu.prefs = dict(main.default_prefs)
        # load_preferences() becomes a no-op once prefs is truthy, but stub it
        # so nothing reads the user's real config from disk.
        self.dmenu.load_preferences = lambda: None

    def tearDown(self):
        if self._orig_cache_dir is not None:
            os.environ["DMENU_EXTENDED_CACHE_DIR"] = self._orig_cache_dir
        else:
            os.environ.pop("DMENU_EXTENDED_CACHE_DIR", None)

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

    def _write_frequent(self, lines):
        """Write the ordered frequently-used cache that cache_load reads via
        frequent_commands_retrieve()."""
        with open(main.file_cache_frequentlyUsed_ordered, "w") as f:
            f.write("".join(line + "\n" for line in lines))


# ---------------------------------------------------------------------------
# cache_load(): visibility and assembly branches (main.py:920-952)
# ---------------------------------------------------------------------------


class TestCacheLoadVisibility(HelpersTestBase):
    def test_show_plugins_false_forces_plugins_empty(self):
        # show_plugins False drops the plugins cache entirely (but Settings stay).
        self.dmenu.cache_save(["a plugin entry"], main.file_cache_plugins)
        self.dmenu.cache_save(["scanned item"], main.file_cache)
        self.dmenu.show_plugins = False
        text = self.dmenu.cache_load()
        self.assertNotIn("a plugin entry", text)
        self.assertIn("scanned item", text)
        # The Settings entry is still injected even with plugins hidden.
        self.assertIn("Settings", text)

    def test_show_recent_false_forces_frequent_empty(self):
        # show_recent False drops the frequently-used items even when the cache
        # exists and frequently_used is non-zero.
        self.dmenu.prefs["frequently_used"] = 5
        self._write_frequent(["recent one", "recent two"])
        self.dmenu.cache_save([], main.file_cache_plugins)
        self.dmenu.cache_save(["scanned item"], main.file_cache)
        self.dmenu.show_recent = False
        text = self.dmenu.cache_load()
        self.assertNotIn("recent one", text)
        self.assertNotIn("recent two", text)
        self.assertIn("scanned item", text)

    def test_show_recent_true_includes_frequent_items(self):
        # With show_recent left at its default True and a populated cache, the
        # frequently-used items appear.
        self.dmenu.prefs["frequently_used"] = 5
        self._write_frequent(["recent one"])
        self.dmenu.cache_save([], main.file_cache_plugins)
        self.dmenu.cache_save(["scanned item"], main.file_cache)
        text = self.dmenu.cache_load()
        self.assertIn("recent one", text)

    def test_settings_line_stripped_out_of_plugins_cache(self):
        # The plugins cache may contain its own "-> Settings" line; cache_load
        # removes that copy so it is not duplicated with the injected one.
        settings_line = self.dmenu.prefs["indicator_submenu"] + " Settings"
        self.dmenu.cache_save(
            ["plugin one", settings_line, "plugin two"], main.file_cache_plugins
        )
        self.dmenu.cache_save(["scanned item"], main.file_cache)
        text = self.dmenu.cache_load()
        # The injected Settings entry appears exactly once, not twice.
        self.assertEqual(text.count(settings_line), 1)
        self.assertIn("plugin one", text)
        self.assertIn("plugin two", text)

    def test_assembly_ordering_plugins_settings_frequent_scanned(self):
        # show_settings default True -> plugins, then Settings, then frequent,
        # then scanned. Frequent items are prepended ahead of the scanned ones.
        self.dmenu.prefs["frequently_used"] = 5
        self._write_frequent(["FREQ_ITEM"])
        self.dmenu.cache_save(["PLUGIN_ITEM"], main.file_cache_plugins)
        self.dmenu.cache_save(["SCANNED_ITEM"], main.file_cache)
        text = self.dmenu.cache_load()
        settings_line = self.dmenu.prefs["indicator_submenu"] + " Settings"
        # Positions must increase in this exact order.
        self.assertLess(text.index("PLUGIN_ITEM"), text.index(settings_line))
        self.assertLess(text.index(settings_line), text.index("FREQ_ITEM"))
        self.assertLess(text.index("FREQ_ITEM"), text.index("SCANNED_ITEM"))

    def test_show_settings_false_orders_plugins_frequent_scanned_settings(self):
        # show_settings False -> plugins, frequent, scanned, then Settings last.
        self.dmenu.prefs["frequently_used"] = 5
        self._write_frequent(["FREQ_ITEM"])
        self.dmenu.cache_save(["PLUGIN_ITEM"], main.file_cache_plugins)
        self.dmenu.cache_save(["SCANNED_ITEM"], main.file_cache)
        self.dmenu.show_settings = False
        text = self.dmenu.cache_load()
        settings_line = self.dmenu.prefs["indicator_submenu"] + " Settings"
        self.assertLess(text.index("PLUGIN_ITEM"), text.index("FREQ_ITEM"))
        self.assertLess(text.index("FREQ_ITEM"), text.index("SCANNED_ITEM"))
        self.assertLess(text.index("SCANNED_ITEM"), text.index(settings_line))


# ---------------------------------------------------------------------------
# retrieve_aliased_command() (main.py:1051-1066)
# ---------------------------------------------------------------------------


class TestRetrieveAliasedCommand(HelpersTestBase):
    def _write_lookup(self, pairs):
        with open(main.file_cache_aliasesLookup, "w") as f:
            json.dump(pairs, f)

    def test_returns_command_for_matching_alias(self):
        self._write_lookup([["Firefox", "firefox"], ["Htop", "htop;"]])
        self.assertEqual(self.dmenu.retrieve_aliased_command("Htop"), "htop;")

    def test_returns_none_on_miss(self):
        # No matching first element -> the loop falls through and the method
        # returns None implicitly.
        self._write_lookup([["Firefox", "firefox"]])
        self.assertIsNone(self.dmenu.retrieve_aliased_command("Nope"))

    def test_prints_the_alias_unconditionally(self):
        # The method prints the alias on every call regardless of hit/miss.
        self._write_lookup([["Firefox", "firefox"]])
        with mock.patch("builtins.print") as printed:
            self.dmenu.retrieve_aliased_command("Firefox")
        printed.assert_any_call("Firefox")


# ---------------------------------------------------------------------------
# open_directory() (main.py:661-666)
# ---------------------------------------------------------------------------


class TestOpenDirectory(HelpersTestBase):
    def test_passes_quoted_path_to_filebrowser_via_execute(self):
        self.dmenu.prefs["filebrowser"] = "thunar"
        with mock.patch.object(self.dmenu, "execute") as execute:
            self.dmenu.open_directory("/home/user/Documents")
        # The path is double-quoted and appended after the filebrowser command.
        execute.assert_called_once_with('thunar "/home/user/Documents"')


# ---------------------------------------------------------------------------
# open_file(): exit-code 256/4 fallback-offer path (main.py:722-748)
# ---------------------------------------------------------------------------


class TestOpenFileFallback(HelpersTestBase):
    def test_zero_exit_code_takes_no_fallback(self):
        # A successful open returns 0; none of the fallback logic runs.
        self.dmenu.prefs["fileopener"] = "xdg-open"
        with (
            mock.patch.object(self.dmenu, "execute", return_value=0) as execute,
            mock.patch.object(self.dmenu, "menu") as menu,
        ):
            self.dmenu.open_file("/tmp/notes.txt")
        execute.assert_called_once_with('xdg-open "/tmp/notes.txt"', fork=False)
        menu.assert_not_called()

    def test_gnome_open_256_offers_xdg_open_and_retries_on_accept(self):
        # gnome-open returning 256 offers xdg-open; accepting the offer switches
        # the fileopener pref and recurses to retry the open.
        self.dmenu.prefs["fileopener"] = "gnome-open"
        offer = "Try opening with xdg-open?"
        # First execute (gnome-open) fails with 256, the retried execute (now
        # xdg-open) succeeds with 0.
        with contextlib.ExitStack() as stack:
            execute = stack.enter_context(
                mock.patch.object(self.dmenu, "execute", side_effect=[256, 0])
            )
            stack.enter_context(
                mock.patch.object(
                    self.dmenu, "command_output", return_value=["text/plain"]
                )
            )
            stack.enter_context(
                mock.patch.object(self.dmenu, "menu", return_value=offer)
            )
            self.dmenu.open_file("/tmp/file.txt")
        # The offer was accepted, so fileopener was switched to xdg-open and the
        # second (recursive) execute used it.
        self.assertEqual(self.dmenu.prefs["fileopener"], "xdg-open")
        self.assertEqual(execute.call_count, 2)
        execute.assert_any_call('xdg-open "/tmp/file.txt"', fork=False)

    def test_gnome_open_256_offer_declined_does_not_switch_or_retry(self):
        # Declining the menu offer leaves the fileopener untouched and does not
        # retry the open.
        self.dmenu.prefs["fileopener"] = "gnome-open"
        with contextlib.ExitStack() as stack:
            execute = stack.enter_context(
                mock.patch.object(self.dmenu, "execute", return_value=256)
            )
            stack.enter_context(
                mock.patch.object(
                    self.dmenu, "command_output", return_value=["text/plain"]
                )
            )
            stack.enter_context(
                mock.patch.object(self.dmenu, "menu", return_value="something else")
            )
            self.dmenu.open_file("/tmp/file.txt")
        self.assertEqual(self.dmenu.prefs["fileopener"], "gnome-open")
        execute.assert_called_once()

    def test_xdg_open_4_shows_message_with_no_offer_option(self):
        # xdg-open returning 4 marks an open_failure but leaves offer None, so
        # the message list never gains an offer option; a NameError can surface
        # if a previous loop left `option` bound, but with a single failure the
        # menu is still called with the constructed message.
        self.dmenu.prefs["fileopener"] = "xdg-open"
        with contextlib.ExitStack() as stack:
            stack.enter_context(
                mock.patch.object(self.dmenu, "execute", return_value=4)
            )
            stack.enter_context(
                mock.patch.object(
                    self.dmenu, "command_output", return_value=["application/pdf"]
                )
            )
            menu = stack.enter_context(mock.patch.object(self.dmenu, "menu"))
            # offer is None so `option` is never assigned; message.append(option)
            # raises NameError on a fresh interpreter state.
            with self.assertRaises(NameError):
                self.dmenu.open_file("/tmp/file.pdf")
        menu.assert_not_called()


# ---------------------------------------------------------------------------
# get_password() (main.py:537-546)
# ---------------------------------------------------------------------------


class TestGetPassword(HelpersTestBase):
    def test_substitutes_prompt_in_place_and_delegates_to_command_output(self):
        # password_helper items containing {prompt} are formatted in place, then
        # the whole command list is handed to command_output.
        self.dmenu.prefs["password_helper"] = [
            "zenity",
            "--password",
            "--title={prompt}",
        ]
        with mock.patch.object(
            self.dmenu, "command_output", return_value="hunter2"
        ) as command_output:
            result = self.dmenu.get_password()
        self.assertEqual(result, "hunter2")
        # Default prompt with no helper text is "Password: ".
        command_output.assert_called_once_with(
            ["zenity", "--password", "--title=Password: "]
        )

    def test_helper_text_is_embedded_in_the_prompt(self):
        self.dmenu.prefs["password_helper"] = ["pinentry", "--prompt={prompt}"]
        with mock.patch.object(
            self.dmenu, "command_output", return_value=""
        ) as command_output:
            self.dmenu.get_password(helper_text="sudo")
        # helper_text is wrapped in parentheses inside the prompt string.
        command_output.assert_called_once_with(
            ["pinentry", "--prompt=Password (sudo): "]
        )

    def test_substitution_mutates_the_prefs_list_in_place(self):
        # The method takes a reference to prefs['password_helper'] (not a copy)
        # and rewrites the {prompt} element in place, so the stored pref is
        # mutated as a side effect.
        helper = ["zenity", "--title={prompt}"]
        self.dmenu.prefs["password_helper"] = helper
        with mock.patch.object(self.dmenu, "command_output", return_value=""):
            self.dmenu.get_password()
        self.assertEqual(
            self.dmenu.prefs["password_helper"],
            ["zenity", "--title=Password: "],
        )
        # Same list object, confirming the in-place mutation quirk.
        self.assertIs(self.dmenu.prefs["password_helper"], helper)

    def test_items_without_prompt_token_are_left_unchanged(self):
        self.dmenu.prefs["password_helper"] = ["zenity", "--password"]
        with mock.patch.object(
            self.dmenu, "command_output", return_value="pw"
        ) as command_output:
            self.dmenu.get_password()
        # No {prompt} token anywhere, so the command list is passed through as-is.
        command_output.assert_called_once_with(["zenity", "--password"])


if __name__ == "__main__":
    unittest.main()
