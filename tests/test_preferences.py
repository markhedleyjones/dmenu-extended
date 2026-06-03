#!/usr/bin/env python3

"""Characterisation tests for the preferences subsystem of dmenu-extended.

These tests pin down the CURRENT behaviour of preference path resolution,
load_json / save_json, and load_preferences / save_preferences (including the
missing-key merge and the aliased_applications_format migration). They assert
what the code does today, including its quirks, not what it ideally should do.

Boundaries are mocked: the filesystem uses tmp paths, subprocess never spawns a
real dmenu/rofi (the menu method and open_file are patched), and sys.exit is
patched so the missing-config branch can be exercised without killing pytest.
"""

import copy
import importlib
import json
import os
import sys
import tempfile

import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from dmenu_extended import main


# ---------------------------------------------------------------------------
# Path / default_prefs resolution at module level
# ---------------------------------------------------------------------------


def test_path_base_is_under_config_dmenu_extended():
    # path_base is hard-wired to ~/.config/dmenu-extended and does NOT honour
    # XDG_CONFIG_HOME (only the cache path honours an env override).
    assert main.path_base.endswith("/.config/dmenu-extended")


def test_prefs_paths_derive_from_path_base():
    assert main.path_prefs == main.path_base + "/config"
    assert main.path_plugins == main.path_base + "/plugins"


def test_file_prefs_is_a_txt_file_holding_json():
    # The preferences file carries a .txt extension despite holding JSON.
    assert main.file_prefs == main.path_prefs + "/dmenuExtended_preferences.txt"
    assert main.file_prefs.endswith(".txt")


def test_default_prefs_core_values():
    # Pin a representative slice of the shipped defaults.
    assert main.default_prefs["menu"] == "dmenu"
    assert main.default_prefs["fileopener"] == "xdg-open"
    assert main.default_prefs["filebrowser"] == "xdg-open"
    assert main.default_prefs["webbrowser"] == "xdg-open"
    assert main.default_prefs["alias_display_format"] == "{name}"
    assert main.default_prefs["frequently_used"] == 0
    assert main.default_prefs["include_applications"] is True
    assert main.default_prefs["interactive_shell"] is False
    # menu_arguments is the full dmenu styling argv list.
    assert main.default_prefs["menu_arguments"][0] == "-b"
    assert "-i" in main.default_prefs["menu_arguments"]


def test_cache_path_honours_env_override_on_reload():
    # Unlike path_base, path_cache honours DMENU_EXTENDED_CACHE_DIR. Guard the
    # reload's setup_user_files side effect so the real ~/.config is untouched.
    original = os.environ.get("DMENU_EXTENDED_CACHE_DIR")
    os.environ["DMENU_EXTENDED_CACHE_DIR"] = "/tmp/dmenu-ext-test-cache-probe"
    try:
        with mock.patch.object(main, "setup_user_files"):
            importlib.reload(main)
        assert main.path_cache == "/tmp/dmenu-ext-test-cache-probe"
    finally:
        if original is None:
            del os.environ["DMENU_EXTENDED_CACHE_DIR"]
        else:
            os.environ["DMENU_EXTENDED_CACHE_DIR"] = original
        with mock.patch.object(main, "setup_user_files"):
            importlib.reload(main)


# ---------------------------------------------------------------------------
# load_json
# ---------------------------------------------------------------------------


def test_load_json_returns_parsed_dict_for_valid_file():
    menu = main.dmenu()
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tf:
        json.dump({"x": [1, 2, 3], "y": "z"}, tf)
        name = tf.name
    try:
        assert menu.load_json(name) == {"x": [1, 2, 3], "y": "z"}
    finally:
        os.unlink(name)


def test_load_json_returns_false_for_missing_file():
    menu = main.dmenu()
    assert menu.load_json("/nonexistent/definitely/missing.json") is False


def test_load_json_invalid_json_returns_none_and_sets_default_prefs():
    # On a JSONDecodeError load_json does NOT return False: it returns None
    # (falls off the end of the function), assigns self.prefs to the SHARED
    # default_prefs object, and prompts the user via self.menu().
    menu = main.dmenu()
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as tf:
        tf.write("{ this is not valid json")
        name = tf.name
    try:
        with mock.patch.object(menu, "menu", return_value="ignored") as mock_menu:
            result = menu.load_json(name)
        assert result is None
        assert mock_menu.called
        # self.prefs is the actual default_prefs object, not a copy.
        assert menu.prefs is main.default_prefs
    finally:
        os.unlink(name)


def test_load_json_invalid_json_offers_to_open_file_when_chosen():
    # If the user's menu response equals the offered "Edit file manually"
    # option, open_file(path) is invoked on the bad file.
    menu = main.dmenu()
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as tf:
        tf.write("not json")
        name = tf.name
    try:
        with mock.patch.object(menu, "menu", return_value="Edit file manually"):
            with mock.patch.object(menu, "open_file") as mock_open:
                menu.load_json(name)
        mock_open.assert_called_once_with(name)
    finally:
        os.unlink(name)


# ---------------------------------------------------------------------------
# save_json / save_preferences
# ---------------------------------------------------------------------------


def test_save_json_writes_sorted_indented_json():
    menu = main.dmenu()
    target = os.path.join(tempfile.mkdtemp(), "out.json")
    menu.save_json(target, {"b": 2, "a": 1})
    with open(target) as f:
        content = f.read()
    # sort_keys=True, indent=4 (4 leading spaces, keys alphabetical).
    assert content == '{\n    "a": 1,\n    "b": 2\n}'


def test_save_preferences_writes_prefs_to_file_prefs():
    menu = main.dmenu()
    menu.prefs = {"menu": "dmenu", "frequently_used": 0}
    target = os.path.join(tempfile.mkdtemp(), "prefs.txt")
    with mock.patch.object(main, "file_prefs", target):
        menu.save_preferences()
    assert os.path.exists(target)
    with open(target) as f:
        assert json.load(f) == {"menu": "dmenu", "frequently_used": 0}


def test_save_json_load_json_round_trip():
    menu = main.dmenu()
    target = os.path.join(tempfile.mkdtemp(), "rt.json")
    data = {"watch_folders": ["~/"], "menu": "rofi", "nested": {"k": [1, 2]}}
    menu.save_json(target, data)
    assert menu.load_json(target) == data


# ---------------------------------------------------------------------------
# load_preferences: missing file
# ---------------------------------------------------------------------------


def test_load_preferences_missing_file_opens_file_and_exits():
    # When the prefs file is absent, load_json returns False, so
    # load_preferences opens the file for editing then calls sys.exit().
    # open_file is patched to break the recursion it would otherwise cause
    # (open_file itself calls load_preferences again).
    menu = main.dmenu()
    menu.prefs = False
    with mock.patch.object(main, "file_prefs", "/nonexistent/missing-prefs.txt"):
        with mock.patch.object(menu, "open_file") as mock_open:
            with mock.patch.object(main.sys, "exit") as mock_exit:
                menu.load_preferences()
    mock_open.assert_called_once_with("/nonexistent/missing-prefs.txt")
    assert mock_exit.called
    # prefs is left as False after the missing-file branch.
    assert menu.prefs is False


# ---------------------------------------------------------------------------
# load_preferences: idempotency
# ---------------------------------------------------------------------------


def test_load_preferences_is_noop_when_prefs_already_loaded():
    # load_preferences only does work while self.prefs is False; once it is a
    # dict, the method short-circuits and never re-reads the file.
    menu = main.dmenu()
    menu.prefs = {"already": "set"}
    with mock.patch.object(menu, "load_json") as mock_load:
        menu.load_preferences()
    assert not mock_load.called
    assert menu.prefs == {"already": "set"}


# ---------------------------------------------------------------------------
# load_preferences: complete config (no resave)
# ---------------------------------------------------------------------------


def test_load_preferences_complete_config_does_not_resave():
    menu = main.dmenu()
    menu.prefs = False
    complete = copy.deepcopy(main.default_prefs)
    complete["menu"] = "rofi"
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as tf:
        json.dump(complete, tf)
        name = tf.name
    try:
        with mock.patch.object(main, "file_prefs", name):
            with mock.patch.object(menu, "save_preferences") as mock_save:
                menu.load_preferences()
        assert not mock_save.called
        assert menu.prefs["menu"] == "rofi"
    finally:
        os.unlink(name)


# ---------------------------------------------------------------------------
# load_preferences: partial config (missing-key merge)
# ---------------------------------------------------------------------------


def test_load_preferences_partial_config_fills_missing_keys_and_resaves():
    # A config missing default keys gets them backfilled from default_prefs and
    # is resaved. User-set values survive.
    menu = main.dmenu()
    menu.prefs = False
    partial = {"menu": "rofi"}
    saved_to = os.path.join(tempfile.mkdtemp(), "prefs.txt")
    with open(saved_to, "w") as f:
        json.dump(partial, f)
    with mock.patch.object(main, "file_prefs", saved_to):
        menu.load_preferences()
    # User value preserved.
    assert menu.prefs["menu"] == "rofi"
    # A default-only key is now present.
    assert menu.prefs["terminal"] == main.default_prefs["terminal"]
    # All default keys are now present.
    for key in main.default_prefs:
        assert key in menu.prefs
    # The resave actually hit disk with the merged content.
    with open(saved_to) as f:
        on_disk = json.load(f)
    assert on_disk["menu"] == "rofi"
    assert "terminal" in on_disk


# ---------------------------------------------------------------------------
# load_preferences: aliased_applications_format migration
# ---------------------------------------------------------------------------


def test_load_preferences_migrates_aliased_applications_format():
    # The legacy key aliased_applications_format is migrated: its value is moved
    # to alias_display_format and the old key is removed.
    menu = main.dmenu()
    menu.prefs = False
    legacy = {"aliased_applications_format": "{name} LEGACY"}
    target = os.path.join(tempfile.mkdtemp(), "prefs.txt")
    with open(target, "w") as f:
        json.dump(legacy, f)
    with mock.patch.object(main, "file_prefs", target):
        menu.load_preferences()
    assert menu.prefs["alias_display_format"] == "{name} LEGACY"
    assert "aliased_applications_format" not in menu.prefs
    # Persisted to disk too.
    with open(target) as f:
        on_disk = json.load(f)
    assert on_disk["alias_display_format"] == "{name} LEGACY"
    assert "aliased_applications_format" not in on_disk


def test_load_preferences_without_legacy_key_uses_default_alias_format():
    # When neither alias_display_format nor the legacy key is present, the
    # default alias_display_format is filled in (no migration path taken).
    menu = main.dmenu()
    menu.prefs = False
    partial = {"menu": "dmenu"}
    target = os.path.join(tempfile.mkdtemp(), "prefs.txt")
    with open(target, "w") as f:
        json.dump(partial, f)
    with mock.patch.object(main, "file_prefs", target):
        menu.load_preferences()
    assert menu.prefs["alias_display_format"] == "{name}"
    assert "aliased_applications_format" not in menu.prefs


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-q"])
