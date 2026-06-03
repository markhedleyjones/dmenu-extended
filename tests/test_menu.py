#! /usr/bin/env python3

"""Characterisation tests for menu I/O.

Pins down the CURRENT behaviour of dmenu.menu(), select(), message_open(),
message_close() and the interactive_shell branch of execute(). These methods
shell out to the configured menu (dmenu/rofi) via subprocess. Popen is mocked
so nothing real is launched and we can assert on the argv that was built.
"""

import sys
from os import path

import mock
import pytest

# Add src directory to path to import dmenu_extended
sys.path.insert(0, path.join(path.dirname(__file__), "..", "src"))
import dmenu_extended as d


def make_menu(prefs=None):
    """Return a dmenu instance with prefs pre-loaded so load_preferences()
    becomes a no-op, and an empty per-instance launch_args list.
    """
    menu = d.dmenu()
    if prefs is None:
        prefs = {
            "menu": "dmenu",
            "menu_arguments": ["-b", "-i"],
        }
    menu.prefs = prefs
    # load_preferences() is a no-op once prefs is truthy, but stub it anyway so
    # the tests never depend on a real config file on disk.
    menu.load_preferences = lambda: None
    # launch_args defaults to a shared class-level list - give each instance
    # its own so tests do not bleed into one another.
    menu.launch_args = []
    return menu


def fake_popen(stdout="result\n", returncode=0):
    """Build a mock standing in for subprocess.Popen.

    communicate() returns (stdout, None) and the instance exposes returncode.
    """
    proc = mock.Mock()
    proc.communicate.return_value = (stdout, None)
    proc.returncode = returncode
    proc.stdin = mock.Mock()
    proc.pid = 4242
    factory = mock.Mock(return_value=proc)
    return factory, proc


# ---------------------------------------------------------------------------
# menu()
# ---------------------------------------------------------------------------


def test_menu_builds_argv_with_menu_name_args_and_prompt():
    menu = make_menu({"menu": "dmenu", "menu_arguments": ["-b", "-i"]})
    factory, proc = fake_popen(stdout="firefox\n")
    with mock.patch("subprocess.Popen", factory):
        out = menu.menu(["firefox", "chrome"], prompt="Open:")
    assert out == "firefox"
    argv = factory.call_args[0][0]
    # menu name first, then the (expanded) arguments, then -p and the prompt.
    assert argv == ["dmenu", "-b", "-i", "-p", "Open:"]


def test_menu_empty_prompt_still_appends_dash_p_and_empty_string():
    menu = make_menu({"menu": "dmenu", "menu_arguments": []})
    factory, proc = fake_popen(stdout="x\n")
    with mock.patch("subprocess.Popen", factory):
        menu.menu(["x"])
    argv = factory.call_args[0][0]
    # The default prompt is "" but -p is always appended with the empty value.
    assert argv == ["dmenu", "-p", ""]


def test_menu_joins_list_items_with_newlines_into_communicate():
    menu = make_menu()
    factory, proc = fake_popen(stdout="a\n")
    with mock.patch("subprocess.Popen", factory):
        menu.menu(["a", "b", "c"], prompt="p")
    # The list is joined with newlines and handed to communicate() as stdin.
    proc.communicate.assert_called_once_with("a\nb\nc")


def test_menu_passes_string_items_through_unchanged():
    menu = make_menu()
    factory, proc = fake_popen(stdout="a\n")
    with mock.patch("subprocess.Popen", factory):
        menu.menu("already a string", prompt="p")
    proc.communicate.assert_called_once_with("already a string")


def test_menu_strips_newlines_and_surrounding_whitespace_from_output():
    menu = make_menu()
    factory, proc = fake_popen(stdout="  spaced result  \n")
    with mock.patch("subprocess.Popen", factory):
        out = menu.menu(["spaced result"], prompt="p")
    # Output is stripped of trailing newline then of surrounding whitespace.
    assert out == "spaced result"


def test_menu_empty_output_exits():
    menu = make_menu()
    factory, proc = fake_popen(stdout="\n")
    with mock.patch("subprocess.Popen", factory):
        with pytest.raises(SystemExit):
            menu.menu(["a"], prompt="p")


def test_menu_whitespace_only_output_exits():
    menu = make_menu()
    factory, proc = fake_popen(stdout="   \n")
    with mock.patch("subprocess.Popen", factory):
        with pytest.raises(SystemExit):
            menu.menu(["a"], prompt="p")


def test_menu_expands_environment_variables_in_arguments(monkeypatch):
    monkeypatch.setenv("DMENU_TEST_COLOUR", "#abcdef")
    menu = make_menu(
        {"menu": "dmenu", "menu_arguments": ["-nf", "$DMENU_TEST_COLOUR", "-i"]}
    )
    factory, proc = fake_popen(stdout="x\n")
    with mock.patch("subprocess.Popen", factory):
        menu.menu(["x"], prompt="p")
    argv = factory.call_args[0][0]
    # $DMENU_TEST_COLOUR is expanded by os.path.expandvars before launch.
    assert argv == ["dmenu", "-nf", "#abcdef", "-i", "-p", "p"]


def test_menu_unset_variable_is_left_verbatim(monkeypatch):
    monkeypatch.delenv("DMENU_DEFINITELY_UNSET", raising=False)
    menu = make_menu({"menu": "dmenu", "menu_arguments": ["$DMENU_DEFINITELY_UNSET"]})
    factory, proc = fake_popen(stdout="x\n")
    with mock.patch("subprocess.Popen", factory):
        menu.menu(["x"], prompt="p")
    argv = factory.call_args[0][0]
    # expandvars leaves an undefined variable untouched, so it is passed as-is.
    assert argv == ["dmenu", "$DMENU_DEFINITELY_UNSET", "-p", "p"]


def test_menu_uses_configured_menu_executable():
    menu = make_menu({"menu": "rofi", "menu_arguments": ["-dmenu"]})
    factory, proc = fake_popen(stdout="x\n")
    with mock.patch("subprocess.Popen", factory):
        menu.menu(["x"], prompt="p")
    argv = factory.call_args[0][0]
    assert argv[0] == "rofi"


def test_menu_rofi_with_empty_items_substitutes_single_space():
    menu = make_menu({"menu": "rofi", "menu_arguments": []})
    factory, proc = fake_popen(stdout="x\n")
    with mock.patch("subprocess.Popen", factory):
        menu.menu([], prompt="p")
    # rofi closes immediately on empty input, so a single space is sent instead.
    proc.communicate.assert_called_once_with(" ")


def test_menu_dmenu_with_empty_items_sends_empty_string():
    menu = make_menu({"menu": "dmenu", "menu_arguments": []})
    factory, proc = fake_popen(stdout="x\n")
    with mock.patch("subprocess.Popen", factory):
        menu.menu([], prompt="p")
    # The space substitution is rofi-only; dmenu receives an empty string.
    proc.communicate.assert_called_once_with("")


def test_menu_returncode_10_with_output_copies_to_clipboard_and_exits():
    menu = make_menu()
    factory, proc = fake_popen(stdout="copy me\n", returncode=10)
    with mock.patch("subprocess.Popen", factory):
        with mock.patch.object(menu, "copy_to_clipboard") as clip:
            with pytest.raises(SystemExit):
                menu.menu(["copy me"], prompt="p")
    # rofi custom-key exit code 10 copies the selection then exits.
    clip.assert_called_once_with("copy me")


def test_menu_returncode_10_with_empty_output_exits_without_copy():
    menu = make_menu()
    factory, proc = fake_popen(stdout="\n", returncode=10)
    with mock.patch("subprocess.Popen", factory):
        with mock.patch.object(menu, "copy_to_clipboard") as clip:
            with pytest.raises(SystemExit):
                menu.menu(["a"], prompt="p")
    clip.assert_not_called()


def test_menu_launch_arg_bypasses_subprocess():
    menu = make_menu()
    menu.launch_args = ["preselected", "second"]
    factory, proc = fake_popen()
    with mock.patch("subprocess.Popen", factory):
        out = menu.menu(["ignored"], prompt="p")
    # The first launch_arg short-circuits the menu; Popen is never called.
    assert out == "preselected"
    factory.assert_not_called()
    # The consumed arg is removed, leaving the remainder.
    assert menu.launch_args == ["second"]


# ---------------------------------------------------------------------------
# select()
# ---------------------------------------------------------------------------


def test_select_returns_matching_item():
    menu = make_menu()
    items = ["alpha", "beta", "gamma"]
    with mock.patch.object(menu, "menu", return_value="beta"):
        assert menu.select(items, prompt="p") == "beta"


def test_select_numeric_returns_index():
    menu = make_menu()
    items = ["alpha", "beta", "gamma"]
    with mock.patch.object(menu, "menu", return_value="gamma"):
        assert menu.select(items, prompt="p", numeric=True) == 2


def test_select_returns_minus_one_when_no_match():
    menu = make_menu()
    items = ["alpha", "beta"]
    with mock.patch.object(menu, "menu", return_value="zzz"):
        assert menu.select(items, prompt="p") == -1


def test_select_matches_on_substring_returning_first_item_found():
    menu = make_menu()
    items = ["one", "two", "three"]
    # "two" is a substring of the menu result, and items are scanned in order;
    # the first item whose text appears in the result wins.
    with mock.patch.object(menu, "menu", return_value="two selected"):
        assert menu.select(items, prompt="p") == "two"


def test_select_launch_arg_bypasses_menu_call():
    menu = make_menu()
    menu.launch_args = ["beta", "next"]
    items = ["alpha", "beta", "gamma"]
    with mock.patch.object(menu, "menu") as inner:
        result = menu.select(items, prompt="p")
    # select() consumes its own launch_arg and never calls menu().
    assert result == "beta"
    inner.assert_not_called()
    assert menu.launch_args == ["next"]


# ---------------------------------------------------------------------------
# message_open() / message_close()
# ---------------------------------------------------------------------------


def test_message_open_builds_argv_without_prompt():
    menu = make_menu({"menu": "dmenu", "menu_arguments": ["-b", "-i"]})
    factory, proc = fake_popen()
    with mock.patch("subprocess.Popen", factory):
        with mock.patch("os.setsid"):
            menu.message_open("hello")
    argv = factory.call_args[0][0]
    # Unlike menu(), message_open() does not append a -p prompt.
    assert argv == ["dmenu", "-b", "-i"]


def test_message_open_expands_environment_variables(monkeypatch):
    monkeypatch.setenv("DMENU_MSG_FONT", "terminus-12")
    menu = make_menu({"menu": "dmenu", "menu_arguments": ["-fn", "$DMENU_MSG_FONT"]})
    factory, proc = fake_popen()
    with mock.patch("subprocess.Popen", factory):
        with mock.patch("os.setsid"):
            menu.message_open("hi")
    argv = factory.call_args[0][0]
    assert argv == ["dmenu", "-fn", "terminus-12"]


def test_message_open_prefixes_please_wait_and_closes_stdin():
    menu = make_menu({"menu": "dmenu", "menu_arguments": []})
    factory, proc = fake_popen()
    with mock.patch("subprocess.Popen", factory):
        with mock.patch("os.setsid"):
            menu.message_open("building cache")
    # The message is coerced to str and prefixed with "Please wait: ".
    proc.stdin.write.assert_called_once_with("Please wait: building cache")
    proc.stdin.close.assert_called_once_with()


def test_message_open_coerces_non_string_message():
    menu = make_menu({"menu": "dmenu", "menu_arguments": []})
    factory, proc = fake_popen()
    with mock.patch("subprocess.Popen", factory):
        with mock.patch("os.setsid"):
            menu.message_open(12345)
    proc.stdin.write.assert_called_once_with("Please wait: 12345")


def test_message_open_stores_process_for_later_close():
    menu = make_menu({"menu": "dmenu", "menu_arguments": []})
    factory, proc = fake_popen()
    with mock.patch("subprocess.Popen", factory):
        with mock.patch("os.setsid"):
            menu.message_open("x")
    # The Popen handle is stashed on self.message so message_close() can kill it.
    assert menu.message is proc


def test_message_close_kills_process_group_when_message_present():
    menu = make_menu({"menu": "dmenu", "menu_arguments": []})
    factory, proc = fake_popen()
    with mock.patch("subprocess.Popen", factory):
        with mock.patch("os.setsid"):
            menu.message_open("x")
    with mock.patch("os.killpg") as killpg:
        menu.message_close()
    killpg.assert_called_once_with(proc.pid, d.signal.SIGTERM)


def test_message_close_is_a_noop_when_no_message_was_opened():
    menu = make_menu()
    # Fresh instance has never opened a message, so message_close() must not
    # attempt to kill anything.
    assert not hasattr(menu, "message")
    with mock.patch("os.killpg") as killpg:
        menu.message_close()
    killpg.assert_not_called()


# ---------------------------------------------------------------------------
# execute() - interactive_shell branch (menu-adjacent config behaviour)
# ---------------------------------------------------------------------------


def test_execute_interactive_shell_runs_command_via_login_shell(monkeypatch):
    monkeypatch.setenv("SHELL", "/bin/zsh")
    menu = make_menu({"interactive_shell": True})
    with mock.patch("subprocess.call", return_value=0) as call:
        menu.execute("firefox --new-window")
    # interactive_shell wraps the command in `$SHELL -i -c "<joined command>"`.
    call.assert_called_once_with(["/bin/zsh", "-i", "-c", "firefox --new-window"])


def test_execute_interactive_shell_falls_back_to_sh_when_shell_unset(monkeypatch):
    monkeypatch.delenv("SHELL", raising=False)
    menu = make_menu({"interactive_shell": True})
    with mock.patch("subprocess.call", return_value=0) as call:
        menu.execute("htop")
    call.assert_called_once_with(["/bin/sh", "-i", "-c", "htop"])


def test_execute_non_interactive_shell_calls_command_list_directly():
    menu = make_menu({"interactive_shell": False})
    with mock.patch("subprocess.call", return_value=0) as call:
        menu.execute("firefox --new-window")
    # Without interactive_shell the command list is passed straight to call().
    call.assert_called_once_with(["firefox", "--new-window"])


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
