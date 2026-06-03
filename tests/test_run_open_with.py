#!/usr/bin/env python3

"""Characterisation tests for run()'s colon-dispatch ("open X with Y") block.

Pins the CURRENT behaviour of the branch in ``dmenu_extended.main.run()`` that
fires when the menu selection contains a colon (``main.py`` ~lines 2248-2340).
This is the "open X with Y" path: ``program:filter`` filters cached paths and
runs/opens the chosen file, ``:filter`` prompts a sub-menu, a trailing ``;`` or
``;;`` on the program switches to a terminal (held open with ``;;``), and the
various path-with-colon forms either open the whole path, use the given program,
or prompt for a binary from ``scan_binaries()``.

The block calls ``sys.exit()`` on EVERY path, so each test wraps ``run()`` in
``pytest.raises(SystemExit)``. Boundaries are mocked so nothing real launches and
nothing touches the real config: ``init_menu``/``cache_load`` (setup),
``load_plugins``/``retrieve_aliased_command`` (so the selection reaches the colon
block unmolested), ``d.menu`` (the UI - first call yields the colon selection,
later calls yield sub-menu picks), and ``d.execute`` / ``d.open_terminal`` /
``d.scan_binaries`` / ``handle_command`` (the action sinks). The real
dispatch/branching body runs untouched.

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


# ---------------------------------------------------------------------------
# Shared scaffolding
# ---------------------------------------------------------------------------


def patches(*context_managers):
    """Enter several mock patchers under one ExitStack and yield their mocks."""

    stack = contextlib.ExitStack()
    mocks = [stack.enter_context(cm) for cm in context_managers]
    return stack, mocks


@pytest.fixture(autouse=True)
def restore_module_state():
    """Save and restore the global state that run() mutates.

    ``run()`` (via ``init_menu`` in the real flow, and directly here) overwrites
    ``main.d.prefs``/``main.d.launch_args`` and may flip ``main.debug``. Restore
    them so cases do not bleed into one another.
    """

    saved_debug = main.debug
    saved_prefs = main.d.prefs
    saved_launch_args = main.d.launch_args

    yield

    main.debug = saved_debug
    main.d.prefs = saved_prefs
    main.d.launch_args = saved_launch_args


@pytest.fixture
def prefs():
    """A fresh copy of the default preferences on the shared instance.

    ``frequently_used`` is forced to 0 so the pre-colon ``else`` branch records
    nothing and the selection flows straight into the colon block.
    """

    main.d.prefs = dict(main.default_prefs)
    main.d.prefs["frequently_used"] = 0
    main.d.launch_args = []
    return main.d.prefs


def drive_run(selection, cache, menu_side_effect, binaries=None):
    """Drive ``run()`` so ``selection`` reaches the colon-dispatch block.

    ``selection`` is what the first ``d.menu`` (cache picker) returns. Any later
    ``d.menu`` calls inside the colon block consume the rest of
    ``menu_side_effect``. ``binaries`` is what ``scan_binaries`` reports.

    Returns the ExitStack (already entered) plus the four action-sink mocks:
    (execute, open_terminal, scan_binaries, handle_command). The caller runs
    inside the stack and asserts on the sinks.
    """

    if binaries is None:
        binaries = []

    (
        stack,
        (
            _init,
            _cache,
            _plugins,
            _alias,
            menu,
            execute,
            open_terminal,
            scan_binaries,
            handle_command,
        ),
    ) = patches(
        mock.patch.object(main, "init_menu", return_value=None),
        mock.patch.object(main.d, "cache_load", return_value=cache),
        mock.patch.object(main, "load_plugins", return_value=[]),
        mock.patch.object(main.d, "retrieve_aliased_command", return_value=None),
        mock.patch.object(main.d, "menu", side_effect=menu_side_effect),
        mock.patch.object(main.d, "execute"),
        mock.patch.object(main.d, "open_terminal"),
        mock.patch.object(main.d, "scan_binaries", return_value=binaries),
        mock.patch.object(main, "handle_command"),
    )
    return stack, (execute, open_terminal, scan_binaries, handle_command)


# ---------------------------------------------------------------------------
# ':filter' - empty program, sub-menu prompt (cmds[0] == "")
# ---------------------------------------------------------------------------


def test_empty_program_filters_cache_and_handles_chosen_item(prefs):
    # ":pdf" has an empty program, so the cache is filtered to lines containing
    # "pdf" and offered as a sub-menu; the chosen line goes to handle_command.
    cache = "report.pdf\nnotes.txt\nmanual.pdf"
    stack, (execute, open_terminal, _scan, handle_command) = drive_run(
        ":pdf", cache, [":pdf", "report.pdf"]
    )
    with stack:
        with pytest.raises(SystemExit):
            main.run()

    handle_command.assert_called_once_with(main.d, "report.pdf")
    execute.assert_not_called()
    open_terminal.assert_not_called()


def test_empty_program_filter_offers_only_matching_cache_lines(prefs):
    # The sub-menu is built from cache lines matching the filter substring only.
    cache = "report.pdf\nnotes.txt\nmanual.pdf"
    stack, (_execute, _open, _scan, _handle) = drive_run(
        ":pdf", cache, [":pdf", "report.pdf"]
    )
    with stack:
        with pytest.raises(SystemExit):
            main.run()
        # The second menu call (the sub-menu) received the filtered list.
        offered = main.d.menu.call_args_list[1][0][0]

    assert offered == ["report.pdf", "manual.pdf"]


# ---------------------------------------------------------------------------
# 'program:filter' - cmds[0] in scan_binaries()
# ---------------------------------------------------------------------------


def test_program_in_binaries_filters_paths_and_executes(prefs):
    # "vlc:mp4" - vlc is a known binary, so cache PATHS (lines with "/") are
    # filtered to those containing "mp4", the pick is appended, and execute runs
    # "<program> <filename>" (no terminal, run_withshell is False).
    cache = "/home/u/a.mp4\n/home/u/b.txt\n/home/u/c.mp4\nplainword"
    stack, (execute, open_terminal, _scan, handle_command) = drive_run(
        "vlc:mp4", cache, ["vlc:mp4", "/home/u/a.mp4"], binaries=["vlc"]
    )
    with stack:
        with pytest.raises(SystemExit):
            main.run()

    execute.assert_called_once_with("vlc /home/u/a.mp4")
    open_terminal.assert_not_called()
    handle_command.assert_not_called()


def test_program_in_binaries_path_submenu_excludes_non_path_lines(prefs):
    # The path sub-menu only ever contains cache lines that have a "/" in them;
    # the "mp4" filter then narrows that further.
    cache = "/home/u/a.mp4\n/home/u/b.txt\n/home/u/c.mp4\nplainword"
    stack, (_execute, _open, _scan, _handle) = drive_run(
        "vlc:mp4", cache, ["vlc:mp4", "/home/u/a.mp4"], binaries=["vlc"]
    )
    with stack:
        with pytest.raises(SystemExit):
            main.run()
        offered = main.d.menu.call_args_list[1][0][0]

    assert offered == ["/home/u/a.mp4", "/home/u/c.mp4"]


def test_program_in_binaries_empty_filter_offers_all_path_lines(prefs):
    # "vlc:" has an empty filter (cmds[1] == ""), so no extra narrowing happens
    # and every path line in the cache is offered.
    cache = "/home/u/a.mp4\n/home/u/b.txt\nplainword"
    stack, (execute, _open, _scan, _handle) = drive_run(
        "vlc:", cache, ["vlc:", "/home/u/b.txt"], binaries=["vlc"]
    )
    with stack:
        with pytest.raises(SystemExit):
            main.run()
        offered = main.d.menu.call_args_list[1][0][0]

    assert offered == ["/home/u/a.mp4", "/home/u/b.txt"]
    execute.assert_called_once_with("vlc /home/u/b.txt")


def test_program_in_binaries_quotes_filename_with_spaces(prefs):
    # A chosen filename containing a space is wrapped in double quotes before
    # being appended to the program.
    cache = "/home/u/my file.mp4"
    stack, (execute, _open, _scan, _handle) = drive_run(
        "vlc:mp4", cache, ["vlc:mp4", "/home/u/my file.mp4"], binaries=["vlc"]
    )
    with stack:
        with pytest.raises(SystemExit):
            main.run()

    execute.assert_called_once_with('vlc "/home/u/my file.mp4"')


def test_program_in_binaries_expands_user_in_chosen_filename(prefs):
    # The chosen filename is passed through os.path.expanduser, so a leading "~"
    # becomes the home directory.
    cache = "~/notes.mp4"
    stack, (execute, _open, _scan, _handle) = drive_run(
        "vlc:mp4", cache, ["vlc:mp4", "~/notes.mp4"], binaries=["vlc"]
    )
    expected_path = os.path.expanduser("~/notes.mp4")
    with stack:
        with pytest.raises(SystemExit):
            main.run()

    execute.assert_called_once_with("vlc " + expected_path)


# ---------------------------------------------------------------------------
# 'command;:' and 'command;;:' - run_withshell / shell_hold parsing
# ---------------------------------------------------------------------------


def test_single_semicolon_opens_terminal_without_hold(prefs):
    # "vlc;:mp4" - the single trailing ";" on the program turns on run_withshell
    # but NOT shell_hold, so the command is sent to open_terminal with hold=False.
    cache = "/home/u/a.mp4"
    stack, (execute, open_terminal, _scan, _handle) = drive_run(
        "vlc;:mp4", cache, ["vlc;:mp4", "/home/u/a.mp4"], binaries=["vlc"]
    )
    with stack:
        with pytest.raises(SystemExit):
            main.run()

    open_terminal.assert_called_once_with("vlc /home/u/a.mp4", False)
    execute.assert_not_called()


def test_double_semicolon_opens_terminal_with_hold(prefs):
    # "vlc;;:mp4" - the double trailing ";;" turns on both run_withshell and
    # shell_hold, so open_terminal is called with hold=True.
    cache = "/home/u/a.mp4"
    stack, (execute, open_terminal, _scan, _handle) = drive_run(
        "vlc;;:mp4", cache, ["vlc;;:mp4", "/home/u/a.mp4"], binaries=["vlc"]
    )
    with stack:
        with pytest.raises(SystemExit):
            main.run()

    open_terminal.assert_called_once_with("vlc /home/u/a.mp4", True)
    execute.assert_not_called()


def test_semicolons_stripped_from_program_before_binary_lookup(prefs):
    # The ";" characters are removed from cmds[0] before the scan_binaries
    # membership test, so the bare "vlc" (not "vlc;") must be a known binary for
    # the terminal path to fire.
    cache = "/home/u/a.mp4"
    stack, (_execute, open_terminal, _scan, _handle) = drive_run(
        "vlc;:mp4", cache, ["vlc;:mp4", "/home/u/a.mp4"], binaries=["vlc"]
    )
    with stack:
        with pytest.raises(SystemExit):
            main.run()

    # Command begins with the de-semicoloned program name.
    assert open_terminal.call_args[0][0].startswith("vlc ")


# ---------------------------------------------------------------------------
# os.path.exists(out) - the whole selection is an existing path with a colon
# ---------------------------------------------------------------------------


def test_whole_path_with_colon_that_exists_goes_to_handle_command(prefs, tmp_path):
    # A real on-disk file whose name contains a colon is not a program-with-arg;
    # the entire selection is handed to handle_command verbatim.
    colon_file = tmp_path / "file:name.txt"
    colon_file.write_text("x")
    out = str(colon_file)
    stack, (execute, open_terminal, _scan, handle_command) = drive_run(out, out, [out])
    with stack:
        with pytest.raises(SystemExit):
            main.run()

    handle_command.assert_called_once_with(main.d, out)
    execute.assert_not_called()
    open_terminal.assert_not_called()


# ---------------------------------------------------------------------------
# cmds[0].find('/') != -1 - first item is a path
# ---------------------------------------------------------------------------


def test_path_with_trailing_colon_prompts_for_binary(prefs):
    # "/home/u/notes.txt:" - the path does not exist and ends in ":", so the user
    # is prompted with scan_binaries() and the picked binary is wired up to open
    # the path (colon stripped, single-quoted) via execute.
    out = "/home/u/notes.txt:"
    stack, (execute, open_terminal, scan_binaries, handle_command) = drive_run(
        out, out, [out, "vim"], binaries=["vim", "nano"]
    )
    with stack:
        with pytest.raises(SystemExit):
            main.run()

    scan_binaries.assert_called()
    execute.assert_called_once_with("vim '/home/u/notes.txt'")
    open_terminal.assert_not_called()
    handle_command.assert_not_called()


def test_path_with_trailing_colon_expands_user(prefs):
    # The trailing-colon prompt path expands "~" in the (colon-stripped) path.
    out = "~/notes.txt:"
    stack, (execute, _open, _scan, _handle) = drive_run(
        out, out, [out, "vim"], binaries=["vim"]
    )
    expected = os.path.expanduser("~/notes.txt")
    with stack:
        with pytest.raises(SystemExit):
            main.run()

    execute.assert_called_once_with("vim '" + expected + "'")


def test_path_with_second_item_uses_it_as_opener(prefs):
    # "/home/u/notes.txt:vim" - path does not exist, does not end in ":", and a
    # second item is supplied, so cmds[1] is used directly as the opener: the
    # command is "<opener> '<expanded path>'". No binary prompt is shown - the
    # only d.menu call is the cache picker (scan_binaries IS still hit, once, by
    # the earlier "cmds[0] in d.scan_binaries()" membership check on the path).
    out = "/home/u/notes.txt:vim"
    stack, (execute, open_terminal, _scan, handle_command) = drive_run(
        out, out, [out], binaries=["vim"]
    )
    with stack:
        with pytest.raises(SystemExit):
            main.run()
        # No sub-menu prompt: d.menu was called exactly once (the cache picker).
        menu_call_count = main.d.menu.call_count

    execute.assert_called_once_with("vim '/home/u/notes.txt'")
    assert menu_call_count == 1
    open_terminal.assert_not_called()
    handle_command.assert_not_called()


def test_path_with_empty_second_item_prompts_for_binary(prefs):
    # The "path, no usable second item, not a trailing colon" branch. The raw
    # selection ends in whitespace (so out[-1] != ":") but cmds[1] strips to "",
    # which sends control to the prompt: scan_binaries() is offered and the pick
    # opens the path.
    out = "/home/u/notes.txt:  "
    stack, (execute, open_terminal, scan_binaries, _handle) = drive_run(
        out, out, [out, "nano"], binaries=["nano"]
    )
    with stack:
        with pytest.raises(SystemExit):
            main.run()

    # cmds[1] strips to "", out[-1] is a space (not ":"), so the user is prompted
    # with scan_binaries() and the result opens the path.
    scan_binaries.assert_called()
    execute.assert_called_once_with("nano '/home/u/notes.txt'")
    open_terminal.assert_not_called()


# ---------------------------------------------------------------------------
# 'Cant find X' fallback
# ---------------------------------------------------------------------------


def test_unknown_program_shows_cant_find_message(prefs):
    # "nosuchprog:arg" - cmds[0] is non-empty, not a known binary, the whole
    # thing is not an existing path, and cmds[0] has no "/", so the final else
    # shows the "Cant find ..., is it installed?" message and exits.
    out = "nosuchprog:arg"
    stack, (execute, open_terminal, _scan, handle_command) = drive_run(
        out, "somecache", [out, "ignored"], binaries=["vlc", "vim"]
    )
    with stack:
        with pytest.raises(SystemExit):
            main.run()
        # The (single) colon-block menu call carried the fallback message.
        message = main.d.menu.call_args_list[1][0][0]

    assert message == ["Cant find nosuchprog, is it installed?"]
    execute.assert_not_called()
    open_terminal.assert_not_called()
    handle_command.assert_not_called()


# ---------------------------------------------------------------------------
# Exit guarantee - every colon path ends in sys.exit()
# ---------------------------------------------------------------------------


def test_colon_block_always_exits(prefs):
    # The whole colon block falls through to a shared sys.exit(); even the
    # do-nothing-useful "Cant find" branch terminates the process.
    out = "unknown:thing"
    stack, _sinks = drive_run(out, "cache", [out, "x"], binaries=[])
    with stack:
        with pytest.raises(SystemExit):
            main.run()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
