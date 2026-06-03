#!/usr/bin/env python3
"""Characterisation tests for the execution paths of dmenu-extended.

These tests pin down the CURRENT behaviour of execute(), command_to_list(),
open_terminal(), open_url(), open_in_terminal_editor() and the special modifier
characters handled by handle_command() (the '@', ';' and ';;' suffixes plus the
path/url/binary dispatch). Boundaries (subprocess.call, the shell-command file
on disk, os.chmod and scan_binaries) are mocked - no real terminal, browser or
menu is ever launched.

Note: several of these behaviours are quirky (e.g. fork appends a literal '&'
argument to the argv list rather than detaching the process, and open_url
percent-encodes spaces in the path portion too). Characterisation tests assert
what the code does today, not what it arguably ought to do.
"""

import contextlib
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import mock  # noqa: E402
import pytest  # noqa: E402

from dmenu_extended import main  # noqa: E402


def make_menu(**pref_overrides):
    """Return a dmenu instance with prefs pre-populated.

    Pre-setting ``prefs`` to a dict makes load_preferences() a no-op, so none of
    the code under test reads the user's real config from disk.
    """
    menu = main.dmenu()
    prefs = dict(main.default_prefs)
    prefs.update(pref_overrides)
    menu.prefs = prefs
    menu.preCommand = False
    return menu


# ---------------------------------------------------------------------------
# execute()
# ---------------------------------------------------------------------------


def test_execute_basic_splits_into_argv():
    menu = make_menu(interactive_shell=False)
    with mock.patch("subprocess.call") as call:
        call.return_value = 0
        rc = menu.execute("firefox --new-window")
    call.assert_called_once_with(["firefox", "--new-window"])
    assert rc == 0


def test_execute_fork_appends_literal_ampersand_argument():
    # fork=True does NOT detach the process; it appends a literal "&" arg.
    menu = make_menu(interactive_shell=False)
    with mock.patch("subprocess.call") as call:
        menu.execute("firefox", fork=True)
    call.assert_called_once_with(["firefox", "&"])


def test_execute_default_fork_none_does_not_append_ampersand():
    menu = make_menu(interactive_shell=False)
    with mock.patch("subprocess.call") as call:
        menu.execute("firefox")
    call.assert_called_once_with(["firefox"])


def test_execute_precommand_is_prepended():
    menu = make_menu(interactive_shell=False)
    menu.preCommand = "sudo"
    with mock.patch("subprocess.call") as call:
        menu.execute("reboot")
    call.assert_called_once_with(["sudo", "reboot"])


def test_execute_precommand_and_fork_combined_order():
    # preCommand goes first, then the command, then the trailing "&".
    menu = make_menu(interactive_shell=False)
    menu.preCommand = "sudo"
    with mock.patch("subprocess.call") as call:
        menu.execute("reboot", fork=True)
    call.assert_called_once_with(["sudo", "reboot", "&"])


def test_execute_interactive_shell_joins_into_single_string():
    menu = make_menu(interactive_shell=True)
    with (
        mock.patch("subprocess.call") as call,
        mock.patch.dict(os.environ, {"SHELL": "/bin/zsh"}),
    ):
        menu.execute("firefox --new-window")
    call.assert_called_once_with(["/bin/zsh", "-i", "-c", "firefox --new-window"])


def test_execute_interactive_shell_falls_back_to_bin_sh():
    menu = make_menu(interactive_shell=True)
    env = dict(os.environ)
    env.pop("SHELL", None)
    with (
        mock.patch("subprocess.call") as call,
        mock.patch.dict(os.environ, env, clear=True),
    ):
        menu.execute("ls")
    call.assert_called_once_with(["/bin/sh", "-i", "-c", "ls"])


def test_execute_interactive_shell_fork_ampersand_is_inside_joined_string():
    # With fork=True the "&" is appended as a list element, then joined into the
    # single shell string - so it becomes a trailing " &" in the -c argument.
    menu = make_menu(interactive_shell=True)
    with (
        mock.patch("subprocess.call") as call,
        mock.patch.dict(os.environ, {"SHELL": "/bin/bash"}),
    ):
        menu.execute("firefox", fork=True)
    call.assert_called_once_with(["/bin/bash", "-i", "-c", "firefox &"])


# ---------------------------------------------------------------------------
# command_to_list() - coverage gaps not already in tests/test_main.py
# (single-quote handling and odd-quote-count behaviour)
# ---------------------------------------------------------------------------


def test_command_to_list_single_quotes_rejoined_and_stripped():
    menu = make_menu()
    assert menu.command_to_list("vim '/home/user/my file.txt'") == [
        "vim",
        "/home/user/my file.txt",
    ]


def test_command_to_list_odd_double_quote_count_left_untouched():
    # An odd number of double quotes skips the rejoin/strip logic entirely, so
    # the stray quote survives in the output.
    menu = make_menu()
    assert menu.command_to_list('echo "hello') == ["echo", '"hello']


def test_command_to_list_non_string_non_list_returns_empty():
    menu = make_menu()
    assert menu.command_to_list(None) == []
    assert menu.command_to_list(123) == []


# ---------------------------------------------------------------------------
# open_terminal() - writes the shell-command file, chmods it, then runs it
# ---------------------------------------------------------------------------


def test_open_terminal_direct_runs_sh_e(tmp_path):
    sh_file = tmp_path / "shellCommand.sh"
    menu = make_menu(path_shellCommand=str(sh_file), terminal="xterm")
    with mock.patch("subprocess.call") as call:
        menu.open_terminal("htop", direct=True)

    # The generated script is written to disk with a bash shebang + the command.
    contents = sh_file.read_text()
    assert contents == "#! /bin/bash\nhtop\n"
    # direct=True invokes the script straight through sh -e, not the terminal.
    call.assert_called_once_with(["sh", "-e", str(sh_file)])


def test_open_terminal_non_direct_uses_terminal_with_dash_e(tmp_path):
    sh_file = tmp_path / "shellCommand.sh"
    menu = make_menu(path_shellCommand=str(sh_file), terminal="xterm")
    with mock.patch("subprocess.call") as call:
        menu.open_terminal("htop")
    call.assert_called_once_with(["xterm", "-e", str(sh_file)])


def test_open_terminal_terminal_pref_is_shlex_split(tmp_path):
    # A multi-word terminal preference is shlex-split, not passed as one arg.
    sh_file = tmp_path / "shellCommand.sh"
    menu = make_menu(path_shellCommand=str(sh_file), terminal="gnome-terminal --tab")
    with mock.patch("subprocess.call") as call:
        menu.open_terminal("htop")
    call.assert_called_once_with(["gnome-terminal", "--tab", "-e", str(sh_file)])


def test_open_terminal_hold_appends_pause_lines(tmp_path):
    sh_file = tmp_path / "shellCommand.sh"
    menu = make_menu(path_shellCommand=str(sh_file), terminal="xterm")
    with mock.patch("subprocess.call"):
        menu.open_terminal("htop", hold=True)
    contents = sh_file.read_text()
    assert contents == ('#! /bin/bash\nhtop\necho "\n\nPress enter to exit";read var;')


def test_open_terminal_chmods_file_0744(tmp_path):
    sh_file = tmp_path / "shellCommand.sh"
    menu = make_menu(path_shellCommand=str(sh_file), terminal="xterm")
    with mock.patch("subprocess.call"), mock.patch("os.chmod") as chmod:
        menu.open_terminal("htop")
    chmod.assert_called_once_with(str(sh_file), 0o744)


# ---------------------------------------------------------------------------
# open_url()
# ---------------------------------------------------------------------------


def test_open_url_executes_webbrowser_with_url():
    menu = make_menu(webbrowser="firefox", interactive_shell=False)
    with mock.patch("subprocess.call") as call:
        menu.open_url("http://example.com")
    call.assert_called_once_with(["firefox", "http://example.com"])


def test_open_url_percent_encodes_spaces():
    # Spaces anywhere in the url (including the path) are turned into %20 before
    # the command string is split, so they don't get split into extra argv items.
    menu = make_menu(webbrowser="firefox", interactive_shell=False)
    with mock.patch("subprocess.call") as call:
        menu.open_url("http://example.com/a b")
    call.assert_called_once_with(["firefox", "http://example.com/a%20b"])


# ---------------------------------------------------------------------------
# open_in_terminal_editor() - note: it uses the module-global `d`, not `self`.
# ---------------------------------------------------------------------------


def test_open_in_terminal_editor_missing_path_returns_none(tmp_path):
    menu = make_menu()
    missing = str(tmp_path / "does-not-exist.txt")
    with mock.patch("subprocess.call") as call:
        result = menu.open_in_terminal_editor(missing)
    assert result is None
    call.assert_not_called()


def test_open_in_terminal_editor_builds_command_via_global_d(tmp_path):
    real_file = tmp_path / "notes.txt"
    real_file.write_text("hi")
    editor_menu = make_menu(terminal="xterm", terminal_editor="vim")

    # The method references the module global `d`, so patch that for both the
    # prefs lookup and the execute() call it delegates to.
    with (
        mock.patch.object(main, "d", editor_menu),
        mock.patch.object(editor_menu, "execute") as execute,
    ):
        execute.return_value = 0
        rc = main.dmenu.open_in_terminal_editor(editor_menu, str(real_file))

    # Command string: terminal -e 'editor path' with spaces in path escaped.
    expected_cmd = "xterm -e 'vim %s'" % str(real_file)
    execute.assert_called_once_with(expected_cmd, False)
    assert rc == 0


def test_open_in_terminal_editor_escapes_spaces_in_path(tmp_path):
    spaced = tmp_path / "my notes.txt"
    spaced.write_text("hi")
    editor_menu = make_menu(terminal="xterm", terminal_editor="nano")
    with (
        mock.patch.object(main, "d", editor_menu),
        mock.patch.object(editor_menu, "execute") as execute,
    ):
        main.dmenu.open_in_terminal_editor(editor_menu, str(spaced))
    sent_cmd = execute.call_args[0][0]
    # Spaces in the path are backslash-escaped inside the single-quoted command.
    assert "my\\ notes.txt" in sent_cmd
    assert sent_cmd.startswith("xterm -e 'nano ")


# ---------------------------------------------------------------------------
# handle_command() - the special modifier characters and dispatch logic.
# ---------------------------------------------------------------------------


def test_handle_command_at_suffix_opens_terminal_editor(tmp_path):
    target = tmp_path / "file.txt"
    target.write_text("x")
    menu = make_menu()
    with mock.patch.object(menu, "open_in_terminal_editor") as editor:
        main.handle_command(menu, str(target) + "@")
    # The trailing '@' is stripped before being passed to the editor.
    editor.assert_called_once_with(str(target))


def test_handle_command_single_semicolon_runs_in_terminal_no_hold():
    menu = make_menu()
    with (
        mock.patch.object(menu, "open_terminal") as term,
        mock.patch("os.path.isdir", return_value=False),
    ):
        main.handle_command(menu, "htop;")
    term.assert_called_once_with("htop", hold=False)


def test_handle_command_double_semicolon_runs_in_terminal_with_hold():
    menu = make_menu()
    with (
        mock.patch.object(menu, "open_terminal") as term,
        mock.patch("os.path.isdir", return_value=False),
    ):
        main.handle_command(menu, "htop;;")
    term.assert_called_once_with("htop", hold=True)


def test_handle_command_semicolon_on_directory_opens_terminal_directly():
    menu = make_menu(terminal="xterm")
    with (
        mock.patch.object(menu, "open_terminal") as term,
        mock.patch("os.path.isdir", return_value=True),
    ):
        main.handle_command(menu, "/some/dir;")
    # A directory + ';' opens a terminal cd'd into it, with direct=True.
    term.assert_called_once_with("cd /some/dir && xterm &", direct=True)


def test_handle_command_http_url_dispatches_to_open_url():
    menu = make_menu()
    with mock.patch.object(menu, "open_url") as open_url:
        main.handle_command(menu, "http://example.com")
    open_url.assert_called_once_with("http://example.com")


def test_handle_command_https_url_dispatches_to_open_url():
    menu = make_menu()
    with mock.patch.object(menu, "open_url") as open_url:
        main.handle_command(menu, "https://example.com/path")
    open_url.assert_called_once_with("https://example.com/path")


def test_handle_command_executable_binary_path_is_executed():
    menu = make_menu()
    with (
        mock.patch.object(menu, "execute") as execute,
        mock.patch("dmenu_extended.main.is_binary", return_value=True),
    ):
        main.handle_command(menu, "/usr/bin/firefox")
    execute.assert_called_once_with("/usr/bin/firefox")


def test_handle_command_path_with_spaces_known_binary_is_executed():
    menu = make_menu()
    with (
        mock.patch.object(menu, "execute") as execute,
        mock.patch("dmenu_extended.main.is_binary", return_value=False),
        mock.patch.object(menu, "scan_binaries", return_value=["xdg-open"]),
    ):
        main.handle_command(menu, "xdg-open /home/user/a/b")
    execute.assert_called_once_with("xdg-open /home/user/a/b")


def test_handle_command_path_with_spaces_unknown_binary_opens_directory():
    menu = make_menu()
    with contextlib.ExitStack() as stack:
        stack.enter_context(
            mock.patch("dmenu_extended.main.is_binary", return_value=False)
        )
        stack.enter_context(mock.patch.object(menu, "scan_binaries", return_value=[]))
        stack.enter_context(mock.patch("os.path.isdir", return_value=True))
        open_dir = stack.enter_context(mock.patch.object(menu, "open_directory"))
        main.handle_command(menu, "/home/user/some dir")
    open_dir.assert_called_once_with("/home/user/some dir")


def test_handle_command_path_no_space_file_opens_file():
    menu = make_menu()
    with (
        mock.patch("dmenu_extended.main.is_binary", return_value=False),
        mock.patch("os.path.isdir", return_value=False),
        mock.patch.object(menu, "open_file") as open_file,
    ):
        main.handle_command(menu, "/home/user/notes.txt")
    open_file.assert_called_once_with("/home/user/notes.txt")


def test_handle_command_path_no_space_directory_opens_directory():
    menu = make_menu()
    with (
        mock.patch("dmenu_extended.main.is_binary", return_value=False),
        mock.patch("os.path.isdir", return_value=True),
        mock.patch.object(menu, "open_directory") as open_dir,
    ):
        main.handle_command(menu, "/home/user/Documents")
    open_dir.assert_called_once_with("/home/user/Documents")


def test_handle_command_plain_command_no_slash_is_executed():
    menu = make_menu()
    with mock.patch.object(menu, "execute") as execute:
        main.handle_command(menu, "firefox")
    execute.assert_called_once_with("firefox")


def test_handle_command_tilde_is_expanded_before_dispatch():
    menu = make_menu()
    home = os.path.expanduser("~")
    with (
        mock.patch("dmenu_extended.main.is_binary", return_value=False),
        mock.patch("os.path.isdir", return_value=False),
        mock.patch.object(menu, "open_file") as open_file,
    ):
        main.handle_command(menu, "~/notes.txt")
    open_file.assert_called_once_with(home + "/notes.txt")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
