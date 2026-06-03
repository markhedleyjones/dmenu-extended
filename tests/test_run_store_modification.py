#!/usr/bin/env python3

"""Characterisation tests for the store-modification block inside run().

Pins the CURRENT behaviour of the ``out[0] in "+-"`` branch of
``dmenu_extended.main.run()`` (main.py:1956-2238). A selection that begins with
``+`` or ``-`` is treated as a request to add/remove an item (plain or aliased)
from ``prefs['include_items']``, the on-disk scanned cache, and the
aliases-lookup JSON. This block:

  - splits the input on ``#`` into a command and an optional alias,
  - scans ``include_items`` to decide whether the item is already in the store
    (the ``found_in_store`` loop),
  - flips ``+`` -> ``-`` (or ``-`` -> ``+``) via a confirmation menu when the
    item's presence contradicts the requested action,
  - rewrites the scanned cache (prepend + ``sort(key=len)`` for additions, or
    ``list.remove`` for removals),
  - updates the aliases-lookup JSON for aliased additions,
  - calls ``save_preferences()`` and ``cache_save()``, then shows a feedback
    menu and ``sys.exit()``.

These assert the actual behaviour today, INCLUDING quirks (e.g. the dead
``cache_scanned is False`` branch that actually raises ``TypeError`` because of
the ``[:-1]`` slice on a missing cache file). Boundaries are mocked: the menu
UI (``menu``/``message_open``/``message_close``), the cache loader, plugin
loading and ``init_menu``; the real dispatch body runs and touches only the
tmp_path files we redirect the module globals to.

The project targets Python 3.8, so contextlib.ExitStack is used instead of
parenthesised ``with`` blocks (which are 3.9+ syntax).
"""

import contextlib
import json
import os
import sys

import mock
import pytest

# Add src directory to path to import dmenu_extended
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from dmenu_extended import main


def patches(*context_managers):
    """Enter several mock patchers under one ExitStack and return their mocks."""

    stack = contextlib.ExitStack()
    mocks = [stack.enter_context(cm) for cm in context_managers]
    return stack, mocks


@pytest.fixture(autouse=True)
def restore_module_state():
    """Save and restore the shared instance state the block mutates.

    ``run()`` operates on the module-level ``main.d`` singleton and mutates its
    ``prefs`` (notably ``include_items``) and ``launch_args``. Restore them so
    cases do not bleed into one another.
    """

    saved_prefs = main.d.prefs
    saved_launch_args = main.d.launch_args
    saved_debug = main.debug

    yield

    main.d.prefs = saved_prefs
    main.d.launch_args = saved_launch_args
    main.debug = saved_debug


@pytest.fixture
def store(tmp_path):
    """Redirect the cache, aliases-lookup and prefs files into tmp_path.

    Returns an object exposing the three paths plus helpers to read them back.
    The module reads ``main.file_cache`` / ``main.file_cache_aliasesLookup`` /
    ``main.file_prefs`` as globals at call time, so monkeypatching the module
    attributes is enough to keep every write inside tmp_path.
    """

    cache_path = str(tmp_path / "all.txt")
    aliases_path = str(tmp_path / "aliases_lookup.json")
    prefs_path = str(tmp_path / "preferences.txt")

    main.file_cache = cache_path
    main.file_cache_aliasesLookup = aliases_path
    main.file_prefs = prefs_path

    # dict() is a shallow copy: default_prefs["include_items"] is a shared list
    # that the block mutates in place. Give each test its own list so appends do
    # not leak into default_prefs (and thus into later tests).
    main.d.prefs = dict(main.default_prefs)
    main.d.prefs["include_items"] = []
    main.d.launch_args = []
    main.debug = False

    class Store:
        cache = cache_path
        aliases = aliases_path
        prefs = prefs_path

        def write_cache(self, lines):
            with open(cache_path, "w") as f:
                for line in lines:
                    f.write(line + "\n")

        def write_aliases(self, items):
            with open(aliases_path, "w") as f:
                json.dump(items, f)

        def read_cache_lines(self):
            with open(cache_path) as f:
                # The block stores the cache as a list and cache_save writes one
                # item per line with a trailing newline.
                return f.read().split("\n")

        def read_aliases(self):
            with open(aliases_path) as f:
                return json.load(f)

        def read_prefs(self):
            with open(prefs_path) as f:
                return json.load(f)

    return Store()


def drive_run(selection, menu_side_effect=None):
    """Run main.run() with everything up to the store block mocked out.

    ``selection`` becomes the first menu() result (so ``out`` inside run()).
    ``menu_side_effect``, if given, is used as the menu mock's side_effect so a
    test can script the later confirmation/feedback menu answers; otherwise the
    first call returns ``selection`` and subsequent calls return "".

    Returns the menu mock so callers can inspect the prompts that were shown.
    """

    if menu_side_effect is None:
        menu_side_effect = [selection, ""]

    menu_mock = mock.Mock(side_effect=menu_side_effect)

    stack, _ = patches(
        mock.patch.object(main, "init_menu", return_value=None),
        mock.patch.object(main.d, "cache_load", return_value="ignored"),
        mock.patch.object(main.d, "menu", menu_mock),
        mock.patch.object(main, "load_plugins", return_value=[]),
        mock.patch.object(main.d, "retrieve_aliased_command", return_value=None),
        mock.patch.object(main.d, "message_open"),
        mock.patch.object(main.d, "message_close"),
        mock.patch.object(main, "frequent_commands_store"),
    )
    with stack:
        with pytest.raises(SystemExit):
            main.run()
    return menu_mock


# ---------------------------------------------------------------------------
# Adding plain items
# ---------------------------------------------------------------------------


def test_add_plain_item_appends_to_include_items(store):
    # "+firefox" with firefox absent from the store: the bare command is
    # appended to include_items.
    store.write_cache(["aaaa", "bb"])
    store.write_aliases([])

    drive_run("+firefox")

    assert "firefox" in main.d.prefs["include_items"]


def test_add_plain_item_prepends_to_cache_then_sorts_by_length(store):
    # On addition the new command is prepended to the scanned cache list, then
    # the whole list is sorted by length (shortest first). cache_save writes one
    # item per line plus a trailing newline (yielding a trailing empty element).
    store.write_cache(["aaaa", "bb", "cccccc"])
    store.write_aliases([])

    drive_run("+ff")

    lines = store.read_cache_lines()
    # Sorted ascending by len: "ff" (2), "bb" (2), "aaaa" (4), "cccccc" (6).
    # "ff" and "bb" are both length 2; the prepend puts "ff" first and a stable
    # sort keeps it ahead of "bb".
    assert lines == ["ff", "bb", "aaaa", "cccccc", ""]


def test_add_plain_item_saves_preferences_to_disk(store):
    # save_preferences() is called at the end, writing the mutated include_items
    # out to the (tmp) prefs file as json.
    store.write_cache(["xxxx"])
    store.write_aliases([])

    drive_run("+newcmd")

    saved = store.read_prefs()
    assert "newcmd" in saved["include_items"]


def test_add_plain_item_feedback_message_and_exit(store):
    # The final feedback menu reports the addition, then run() exits.
    store.write_cache(["xxxx"])
    store.write_aliases([])

    menu_mock = drive_run("+newcmd")

    last_prompt = menu_mock.call_args_list[-1][0][0]
    assert last_prompt == "New item (newcmd) added to cache."


# ---------------------------------------------------------------------------
# Adding aliased items ([alias, command] pairs)
# ---------------------------------------------------------------------------


def test_add_aliased_item_appends_pair_to_include_items(store):
    # "+vim#My Editor" splits on "#": command="vim", alias="My Editor". The
    # [alias, command] pair is appended to include_items.
    store.write_cache(["aaaa"])
    store.write_aliases([])

    drive_run("+vim#My Editor")

    assert ["My Editor", "vim"] in main.d.prefs["include_items"]


def test_add_aliased_item_writes_alias_into_lookup_json(store):
    # The [alias, command] pair is also appended to the aliases-lookup json.
    store.write_cache(["aaaa"])
    store.write_aliases([])

    drive_run("+vim#My Editor")

    assert ["My Editor", "vim"] in store.read_aliases()


def test_add_aliased_item_prepends_formatted_alias_to_cache(store):
    # The cache receives the *formatted* alias (format_alias with default
    # alias_display_format "{name}" and empty indicator yields just the name),
    # prepended then length-sorted.
    store.write_cache(["aaaaaaaa"])
    store.write_aliases([])

    drive_run("+vim#Ed")

    lines = store.read_cache_lines()
    # "Ed" (2) sorts before "aaaaaaaa" (8); trailing "" from cache_save.
    assert lines == ["Ed", "aaaaaaaa", ""]


def test_add_aliased_item_not_duplicated_in_lookup(store):
    # If the [alias, command] pair already exists in the lookup json it is not
    # appended a second time (the "not in aliases" guard).
    store.write_cache(["aaaa"])
    store.write_aliases([["My Editor", "vim"]])

    drive_run("+vim#My Editor")

    aliases = store.read_aliases()
    assert aliases.count(["My Editor", "vim"]) == 1


def test_add_aliased_item_feedback_mentions_alias(store):
    store.write_cache(["aaaa"])
    store.write_aliases([])

    menu_mock = drive_run("+vim#My Editor")

    last_prompt = menu_mock.call_args_list[-1][0][0]
    assert last_prompt == "New item (vim aliased as 'My Editor') added to cache."


# ---------------------------------------------------------------------------
# Removing plain items
#
# QUIRK: the found_in_store matching loop only inspects list (aliased) items.
# A plain *string* entry in include_items is never matched, so "-firefox" with
# a plain string "firefox" present is reported as "not found in store" and the
# action flips to "+", duplicating the entry instead of removing it. The
# plain-removal codepath (include_items.remove(command) with alias is None) is
# therefore unreachable through this UI. These tests pin that behaviour.
# ---------------------------------------------------------------------------


def test_remove_plain_string_item_is_reported_not_found(store):
    # "-firefox" with a plain string "firefox" in the store: the loop never
    # matches it, so found_in_store stays False and a "not found in store"
    # confirmation is shown offering to ADD it.
    store.write_cache(["firefox", "other"])
    store.write_aliases([])
    main.d.prefs["include_items"] = ["firefox", "keepme"]

    menu_mock = drive_run("-firefox", menu_side_effect=["-firefox", "declined"])

    confirm_prompt = menu_mock.call_args_list[1][0][0]
    assert "Command 'firefox' was not found in store" in confirm_prompt
    # Declined, so nothing was removed; the string entry is still present.
    assert main.d.prefs["include_items"] == ["firefox", "keepme"]


def test_remove_plain_string_item_accepting_flip_duplicates_it(store):
    # Accepting the "Add to store" offer flips action to "+" and appends the
    # command, so the plain string ends up listed twice rather than removed.
    store.write_cache(["firefox", "other"])
    store.write_aliases([])
    main.d.prefs["include_items"] = ["firefox"]

    add_option = main.d.prefs["indicator_submenu"] + " Add to store"
    menu_mock = drive_run("-firefox", menu_side_effect=["-firefox", add_option, ""])

    assert main.d.prefs["include_items"].count("firefox") == 2
    # The feedback reports an addition, confirming the flip.
    assert menu_mock.call_args_list[-1][0][0] == "New item (firefox) added to cache."


# ---------------------------------------------------------------------------
# Removing aliased items
# ---------------------------------------------------------------------------


def test_remove_aliased_item_by_displayed_alias_removes_pair(store):
    # "-My Editor": command="My Editor". The loop's "-" path matches on
    # `command == d.format_alias(item[0], item[1])`; with the default format
    # ("{name}", no indicator) format_alias yields "My Editor", so the pair
    # ["My Editor", "vim"] is matched, found_in_store becomes True, and the pair
    # is removed from include_items.
    store.write_cache(["My Editor", "other"])
    store.write_aliases([["My Editor", "vim"]])
    main.d.prefs["include_items"] = [["My Editor", "vim"]]

    drive_run("-My Editor")

    assert ["My Editor", "vim"] not in main.d.prefs["include_items"]


def test_remove_aliased_item_removes_formatted_alias_from_cache(store):
    store.write_cache(["My Editor", "other"])
    store.write_aliases([["My Editor", "vim"]])
    main.d.prefs["include_items"] = [["My Editor", "vim"]]

    drive_run("-My Editor")

    lines = store.read_cache_lines()
    assert "My Editor" not in lines
    assert "other" in lines


def test_remove_aliased_item_feedback_mentions_alias(store):
    store.write_cache(["My Editor"])
    store.write_aliases([["My Editor", "vim"]])
    main.d.prefs["include_items"] = [["My Editor", "vim"]]

    menu_mock = drive_run("-My Editor")

    last_prompt = menu_mock.call_args_list[-1][0][0]
    assert last_prompt == "Existing alias (My Editor) removed from cache."


# ---------------------------------------------------------------------------
# The + -> - flip ("already in store") prompt
# ---------------------------------------------------------------------------


def test_add_existing_aliased_item_prompts_to_remove_then_flips_to_removal(store):
    # "+vim#My Editor" while the [alias, command] pair is already in
    # include_items: found_in_store is True (the "+" branch matches alias ==
    # item[0]), so a confirmation menu offers "-> Remove from store". Answering
    # with that option flips action to "-" and the pair is removed.
    store.write_cache(["My Editor", "other"])
    store.write_aliases([["My Editor", "vim"]])
    main.d.prefs["include_items"] = [["My Editor", "vim"]]

    remove_option = main.d.prefs["indicator_submenu"] + " Remove from store"
    # First menu() = the original selection; second = the confirmation; the
    # answer must equal the offered option to proceed, then a feedback menu.
    menu_mock = drive_run(
        "+vim#My Editor", menu_side_effect=["+vim#My Editor", remove_option, ""]
    )

    assert ["My Editor", "vim"] not in main.d.prefs["include_items"]
    # The confirmation prompt announces the alias is already in the store.
    confirm_prompt = menu_mock.call_args_list[1][0][0]
    assert "already in store" in confirm_prompt
    # And the final feedback reports a removal (action flipped to "-").
    assert menu_mock.call_args_list[-1][0][0].startswith("Existing alias")


def test_add_existing_aliased_item_declined_exits_without_change(store):
    # If the confirmation answer is NOT the offered option, the block sys.exit()s
    # immediately and include_items is left untouched.
    store.write_cache(["My Editor"])
    store.write_aliases([["My Editor", "vim"]])
    main.d.prefs["include_items"] = [["My Editor", "vim"]]

    drive_run("+vim#My Editor", menu_side_effect=["+vim#My Editor", "no thanks"])

    # No flip, no removal: the pair is still present.
    assert main.d.prefs["include_items"] == [["My Editor", "vim"]]


def test_add_existing_plain_string_appends_without_any_prompt(store):
    # QUIRK companion: "+firefox" while a plain string "firefox" is in the store
    # does NOT find it (the loop ignores non-list items), so no confirmation is
    # shown and the command is appended a second time. Only the original
    # selection menu and the final feedback menu are shown (no confirmation in
    # between).
    store.write_cache(["firefox"])
    store.write_aliases([])
    main.d.prefs["include_items"] = ["firefox"]

    menu_mock = drive_run("+firefox")

    assert main.d.prefs["include_items"].count("firefox") == 2
    # Exactly two menu calls: selection + feedback, no confirmation prompt.
    assert menu_mock.call_count == 2
    assert menu_mock.call_args_list[-1][0][0] == "New item (firefox) added to cache."


def test_add_existing_aliased_item_prompt_mentions_alias(store):
    # For an aliased addition that already exists, the confirmation prompt is
    # phrased in terms of the alias rather than the command.
    store.write_cache(["My Editor"])
    store.write_aliases([["My Editor", "vim"]])
    main.d.prefs["include_items"] = [["My Editor", "vim"]]

    remove_option = main.d.prefs["indicator_submenu"] + " Remove from store"
    menu_mock = drive_run(
        "+vim#My Editor",
        menu_side_effect=["+vim#My Editor", remove_option, ""],
    )

    confirm_prompt = menu_mock.call_args_list[1][0][0]
    assert "Alias 'My Editor' already in store" in confirm_prompt


# ---------------------------------------------------------------------------
# The - -> + flip ("not found in store") prompt
# ---------------------------------------------------------------------------


def test_remove_absent_plain_item_prompts_to_add_then_flips_to_addition(store):
    # "-firefox" while firefox is NOT in include_items: found_in_store is False,
    # so a confirmation offers "-> Add to store". Accepting flips action to "+"
    # and the item is added.
    store.write_cache(["other"])
    store.write_aliases([])
    main.d.prefs["include_items"] = []

    add_option = main.d.prefs["indicator_submenu"] + " Add to store"
    menu_mock = drive_run("-firefox", menu_side_effect=["-firefox", add_option, ""])

    assert "firefox" in main.d.prefs["include_items"]
    confirm_prompt = menu_mock.call_args_list[1][0][0]
    assert "was not found in store" in confirm_prompt
    assert menu_mock.call_args_list[-1][0][0].startswith("New item")


def test_remove_absent_plain_item_declined_exits_without_change(store):
    # Declining the "Add to store" offer exits immediately, adding nothing.
    store.write_cache(["other"])
    store.write_aliases([])
    main.d.prefs["include_items"] = []

    drive_run("-firefox", menu_side_effect=["-firefox", "nope"])

    assert main.d.prefs["include_items"] == []


# ---------------------------------------------------------------------------
# found_in_store matching loop specifics
# ---------------------------------------------------------------------------


def test_found_in_store_plain_string_item_match(store):
    # A plain string include_item that equals the command is detected by the
    # final `isinstance(item, list)` ... wait: the last branch checks
    # `command == item` only when `isinstance(item, list)`. A plain string item
    # therefore does NOT satisfy that branch, so "+firefox" with a *string*
    # include_item "firefox" is treated as NOT found and is appended again
    # (duplicated). This pins that quirk.
    store.write_cache(["firefox"])
    store.write_aliases([])
    main.d.prefs["include_items"] = ["firefox"]

    drive_run("+firefox")

    # firefox ends up listed twice because the string item was not matched.
    assert main.d.prefs["include_items"].count("firefox") == 2


def test_found_in_store_alias_pair_matched_on_add_by_alias(store):
    # For an add ("+"), the loop matches an existing [alias, command] pair when
    # alias == item[0]. So "+vim#My Editor" with the pair already present is
    # found_in_store True and triggers the remove confirmation rather than a
    # second append.
    store.write_cache(["My Editor"])
    store.write_aliases([["My Editor", "vim"]])
    main.d.prefs["include_items"] = [["My Editor", "vim"]]

    # Decline the resulting "Remove from store" confirmation so nothing changes.
    drive_run("+vim#My Editor", menu_side_effect=["+vim#My Editor", "declined"])

    # The pair was detected as present; declining left it untouched (not added
    # again).
    assert main.d.prefs["include_items"].count(["My Editor", "vim"]) == 1


# ---------------------------------------------------------------------------
# Quirk: missing cache file raises TypeError (dead False-branch)
# ---------------------------------------------------------------------------


def test_missing_cache_file_raises_typeerror(store):
    # cache_open() returns False for a missing file; the block immediately
    # slices it with `[:-1]`, and `False[:-1]` raises TypeError. The intended
    # `cache_scanned is False` recovery branch is therefore unreachable.
    store.write_aliases([])
    main.d.prefs["include_items"] = []
    # Deliberately do NOT create the cache file.
    assert not os.path.exists(store.cache)

    menu_mock = mock.Mock(side_effect=["+firefox", ""])
    stack, _ = patches(
        mock.patch.object(main, "init_menu", return_value=None),
        mock.patch.object(main.d, "cache_load", return_value="ignored"),
        mock.patch.object(main.d, "menu", menu_mock),
        mock.patch.object(main, "load_plugins", return_value=[]),
        mock.patch.object(main.d, "retrieve_aliased_command", return_value=None),
        mock.patch.object(main.d, "message_open"),
        mock.patch.object(main.d, "message_close"),
        mock.patch.object(main, "frequent_commands_store"),
    )
    with stack:
        with pytest.raises(TypeError):
            main.run()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
