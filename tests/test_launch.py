#!/usr/bin/env python3

"""Characterisation tests for the launch entry points.

Pins the current behaviour of ``init_menu(launch_args)`` and ``run()`` in
``dmenu_extended.main``: argument parsing, the ``show_*`` toggles, the
executable check via ``shutil.which``, and the automation/bypass path where
launch arguments drive menu selections through to the command handler.

These assert the ACTUAL behaviour today, including quirks (e.g. ``init_menu``
returns ``1`` on ``--help`` and ``None`` otherwise, and mutates module-level
state). Boundaries (subprocess, preferences, plugins, the command handler) are
mocked so no real menu launches and nothing touches the real config.

The project targets Python 3.8, so contextlib.ExitStack is used instead of
parenthesised ``with`` blocks (which are 3.9+ syntax).
"""

import contextlib
import os
import sys

import mock
import pytest

# Add src directory to path to import dmenu_extended
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from dmenu_extended import main


def patches(*context_managers):
    """Enter several mock patchers under one ExitStack and yield their mocks."""

    stack = contextlib.ExitStack()
    mocks = [stack.enter_context(cm) for cm in context_managers]
    return stack, mocks


@pytest.fixture(autouse=True)
def restore_module_state():
    """Save and restore the global state that init_menu/run mutate.

    ``init_menu`` flips ``main.debug`` and the ``main.d.show_*`` toggles and
    overwrites ``main.d.launch_args``/``main.d.prefs``. Without restoring these
    between tests the suite would leak state across cases.
    """

    saved_debug = main.debug
    saved_prefs = main.d.prefs
    saved_launch_args = main.d.launch_args
    saved_show = (
        main.d.show_scanned,
        main.d.show_recent,
        main.d.show_settings,
        main.d.show_plugins,
    )

    yield

    main.debug = saved_debug
    main.d.prefs = saved_prefs
    main.d.launch_args = saved_launch_args
    (
        main.d.show_scanned,
        main.d.show_recent,
        main.d.show_settings,
        main.d.show_plugins,
    ) = saved_show


@pytest.fixture
def prefs():
    """A fresh copy of the default preferences installed on the shared instance.

    ``load_preferences`` is patched out in the tests that use this so the copy
    here is exactly what the code under test sees.
    """

    main.d.prefs = dict(main.default_prefs)
    return main.d.prefs


# ---------------------------------------------------------------------------
# init_menu: --help
# ---------------------------------------------------------------------------


def test_init_menu_help_returns_1_and_prints(capsys):
    # --help short-circuits everything: returns 1 (truthy), prints the Help
    # text, and never reaches load_preferences or the executable check.
    stack, (load_prefs, which) = patches(
        mock.patch.object(main.d, "load_preferences"),
        mock.patch("shutil.which"),
    )
    with stack:
        result = main.init_menu(["--help"])

    assert result == 1
    assert "Dmenu Extended command line options" in capsys.readouterr().out
    load_prefs.assert_not_called()
    which.assert_not_called()


# ---------------------------------------------------------------------------
# init_menu: executable check
# ---------------------------------------------------------------------------


def test_init_menu_missing_executable_returns_1(prefs, capsys):
    # When shutil.which reports the configured menu binary is absent, init_menu
    # prints an abort message and returns 1.
    stack, (_load_prefs, which) = patches(
        mock.patch.object(main.d, "load_preferences"),
        mock.patch("shutil.which", return_value=None),
    )
    with stack:
        result = main.init_menu([])

    assert result == 1
    which.assert_called_once_with(prefs["menu"])
    assert "executable not found, aborting" in capsys.readouterr().out


def test_init_menu_present_executable_returns_none(prefs):
    # The happy path returns None (falsy), having loaded preferences and checked
    # the configured menu against shutil.which.
    stack, (load_prefs, which) = patches(
        mock.patch.object(main.d, "load_preferences"),
        mock.patch("shutil.which", return_value="/usr/bin/dmenu"),
    )
    with stack:
        result = main.init_menu([])

    assert result is None
    load_prefs.assert_called_once()
    which.assert_called_once_with(prefs["menu"])


# ---------------------------------------------------------------------------
# init_menu: flag parsing and state mutation
# ---------------------------------------------------------------------------


def test_init_menu_no_recent_flag(prefs):
    # --no-recent clears show_recent, leaves the other toggles untrue, and is
    # consumed from the argument list (removed in place).
    main.d.show_recent = True
    args = ["--no-recent"]
    stack, _ = patches(
        mock.patch.object(main.d, "load_preferences"),
        mock.patch("shutil.which", return_value="/usr/bin/dmenu"),
    )
    with stack:
        main.init_menu(args)

    assert main.d.show_recent is False
    assert args == []
    assert main.d.launch_args == []


def test_init_menu_all_visibility_flags_removed_and_args_become_launch_args(prefs):
    # All four visibility flags flip their respective toggles to False, are
    # stripped from the list, and whatever non-flag tokens remain become the
    # menu's launch_args (the automation queue).
    main.d.show_scanned = True
    main.d.show_recent = True
    main.d.show_settings = True
    main.d.show_plugins = True

    args = [
        "--no-scanned",
        "--no-recent",
        "--no-settings",
        "--no-plugins",
        "selection one",
        "selection two",
    ]
    stack, _ = patches(
        mock.patch.object(main.d, "load_preferences"),
        mock.patch("shutil.which", return_value="/usr/bin/dmenu"),
    )
    with stack:
        main.init_menu(args)

    assert main.d.show_scanned is False
    assert main.d.show_recent is False
    assert main.d.show_settings is False
    assert main.d.show_plugins is False
    # Flags consumed, only the menu selections remain.
    assert args == ["selection one", "selection two"]
    assert main.d.launch_args == ["selection one", "selection two"]


def test_init_menu_debug_flag_sets_global_and_is_removed(prefs, capsys):
    # --debug sets the module-level debug flag, prints two debug lines, and is
    # removed from the argument list (the remaining tokens still flow through).
    main.debug = False
    args = ["--debug", "thing"]
    stack, _ = patches(
        mock.patch.object(main.d, "load_preferences"),
        mock.patch("shutil.which", return_value="/usr/bin/dmenu"),
    )
    with stack:
        main.init_menu(args)

    assert main.debug is True
    assert args == ["thing"]
    assert main.d.launch_args == ["thing"]
    out = capsys.readouterr().out
    assert "Debugging enabled" in out
    assert "Launch arguments: ['thing']" in out


def test_init_menu_unknown_arg_passed_through_as_launch_arg(prefs):
    # A token that is not a recognised flag is treated as a menu selection and
    # ends up in launch_args verbatim (no error, no removal).
    args = ["--no-such-flag"]
    stack, _ = patches(
        mock.patch.object(main.d, "load_preferences"),
        mock.patch("shutil.which", return_value="/usr/bin/dmenu"),
    )
    with stack:
        main.init_menu(args)

    assert main.d.launch_args == ["--no-such-flag"]


# ---------------------------------------------------------------------------
# dmenu.menu / dmenu.select: launch-argument bypass
# ---------------------------------------------------------------------------


def test_select_bypassed_returns_matching_item(prefs):
    # select() with a queued launch arg matches it against the items list and
    # returns the matching item (the queued value is consumed).
    main.d.launch_args = ["htop"]
    result = main.d.select(["firefox", "htop", "code"])

    assert result == "htop"
    assert main.d.launch_args == []


def test_select_bypassed_numeric_returns_index(prefs):
    # numeric=True makes select() return the index of the matched item rather
    # than the item itself.
    main.d.launch_args = ["htop"]
    result = main.d.select(["firefox", "htop", "code"], numeric=True)

    assert result == 1


def test_select_no_match_returns_minus_one(prefs):
    # When the queued launch arg matches none of the items, select() returns -1.
    main.d.launch_args = ["nonexistent"]
    result = main.d.select(["firefox", "htop"])

    assert result == -1


# ---------------------------------------------------------------------------
# run(): control flow
# ---------------------------------------------------------------------------


def test_run_returns_early_when_init_menu_truthy():
    # run() bails out (returning None) without loading the cache whenever
    # init_menu returns a truthy value (e.g. --help or a missing executable).
    stack, (_init, cache_load) = patches(
        mock.patch.object(main, "init_menu", return_value=1),
        mock.patch.object(main.d, "cache_load"),
    )
    with stack:
        result = main.run()

    assert result is None
    cache_load.assert_not_called()


def test_run_empty_selection_does_nothing(prefs):
    # If the first menu returns an empty/whitespace-only string, run() takes no
    # further action: no plugins are loaded and no command is handled.
    main.d.launch_args = []
    stack, (_init, _cache, _menu, load_plugins, handle_command) = patches(
        mock.patch.object(main, "init_menu", return_value=None),
        mock.patch.object(main.d, "cache_load", return_value="a\nb"),
        mock.patch.object(main.d, "menu", return_value="   "),
        mock.patch.object(main, "load_plugins"),
        mock.patch.object(main, "handle_command"),
    )
    with stack:
        main.run()

    load_plugins.assert_not_called()
    handle_command.assert_not_called()


def test_run_automation_routes_launch_arg_to_handle_command(prefs):
    # End-to-end automation: a queued launch arg drives the first menu, and a
    # plain command (no slash, colon, URL prefix, or special keyword) is routed
    # to handle_command with the selected text. The launch queue is drained.
    prefs["frequently_used"] = 0
    main.d.launch_args = ["htop"]
    stack, (_init, _cache, _plugins, _alias, handle_command) = patches(
        mock.patch.object(main, "init_menu", return_value=None),
        mock.patch.object(main.d, "cache_load", return_value="firefox\nhtop"),
        mock.patch.object(main, "load_plugins", return_value=[]),
        mock.patch.object(main.d, "retrieve_aliased_command", return_value=None),
        mock.patch.object(main, "handle_command"),
    )
    with stack:
        main.run()

    handle_command.assert_called_once_with(main.d, "htop")
    assert main.d.launch_args == []


def test_run_stores_frequent_command_before_handling(prefs):
    # When frequently_used > 0 and the selection is a non-aliased command, run()
    # records the selection via frequent_commands_store before handling it.
    prefs["frequently_used"] = 5
    main.d.launch_args = []
    stack, (_init, _cache, _menu, _plugins, _alias, store, handle_command) = patches(
        mock.patch.object(main, "init_menu", return_value=None),
        mock.patch.object(main.d, "cache_load", return_value="x"),
        mock.patch.object(main.d, "menu", return_value="firefox"),
        mock.patch.object(main, "load_plugins", return_value=[]),
        mock.patch.object(main.d, "retrieve_aliased_command", return_value=None),
        mock.patch.object(main, "frequent_commands_store"),
        mock.patch.object(main, "handle_command"),
    )
    with stack:
        main.run()

    store.assert_called_once_with("firefox")
    handle_command.assert_called_once_with(main.d, "firefox")


def test_run_aliased_command_stored_as_display_text_and_dealiased(prefs):
    # For an aliased selection: the displayed alias text is what gets recorded
    # in the frequent store, but the resolved (de-aliased) command is what is
    # passed to handle_command.
    prefs["frequently_used"] = 1
    main.d.launch_args = []
    stack, (_init, _cache, _menu, _plugins, _alias, store, handle_command) = patches(
        mock.patch.object(main, "init_menu", return_value=None),
        mock.patch.object(main.d, "cache_load", return_value="x"),
        mock.patch.object(main.d, "menu", return_value="My Alias"),
        mock.patch.object(main, "load_plugins", return_value=[]),
        mock.patch.object(
            main.d, "retrieve_aliased_command", return_value="firefox --private"
        ),
        mock.patch.object(main, "frequent_commands_store"),
        mock.patch.object(main, "handle_command"),
    )
    with stack:
        main.run()

    store.assert_called_once_with("My Alias")
    handle_command.assert_called_once_with(main.d, "firefox --private")


def test_run_rebuild_cache_keyword_regenerates(prefs):
    # The literal selection "rebuild cache" triggers cache_regenerate rather
    # than handle_command, and (on success, result truthy) shows a follow-up
    # menu message.
    prefs["frequently_used"] = 0
    main.d.launch_args = []
    stack, (_init, _cache, menu, _plugins, _alias, regenerate, handle_command) = (
        patches(
            mock.patch.object(main, "init_menu", return_value=None),
            mock.patch.object(main.d, "cache_load", return_value="x"),
            mock.patch.object(main.d, "menu", return_value="rebuild cache"),
            mock.patch.object(main, "load_plugins", return_value=[]),
            mock.patch.object(main.d, "retrieve_aliased_command", return_value=None),
            mock.patch.object(main.d, "cache_regenerate", return_value=1),
            mock.patch.object(main, "handle_command"),
        )
    )
    with stack:
        main.run()

    regenerate.assert_called_once()
    handle_command.assert_not_called()
    # First menu call selects, second reports the result.
    assert menu.call_count == 2


def test_run_plugin_hook_invoked_when_title_matches(prefs):
    # When the selection begins with a plugin's title, run() loads that plugin's
    # preferences and calls its run() with the remainder of the selection
    # (stripped of the title), bypassing handle_command entirely.
    prefs["frequently_used"] = 0
    main.d.launch_args = []

    class FakePlugin:
        is_submenu = False
        title = "MyPlugin"

        def __init__(self):
            self.loaded = False
            self.ran_with = None

        def load_preferences(self):
            self.loaded = True

        def run(self, argument):
            self.ran_with = argument

    plugin = FakePlugin()
    stack, (_init, _cache, _menu, _plugins, handle_command) = patches(
        mock.patch.object(main, "init_menu", return_value=None),
        mock.patch.object(main.d, "cache_load", return_value="x"),
        mock.patch.object(main.d, "menu", return_value="MyPlugin hello"),
        mock.patch.object(main, "load_plugins", return_value=[{"plugin": plugin}]),
        mock.patch.object(main, "handle_command"),
    )
    with stack:
        main.run()

    assert plugin.loaded is True
    assert plugin.ran_with == "hello"
    handle_command.assert_not_called()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
