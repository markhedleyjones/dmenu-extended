#! /usr/bin/env python3

import sys
from os import path

import mock

# Add src directory to path to import dmenu_extended
sys.path.insert(0, path.join(path.dirname(__file__), "..", "src"))
import dmenu_extended as d

menu = d.dmenu()


def test_required_variables_available():
    assert d.path_cache[-len("dmenu-extended") :] == "dmenu-extended"


def test_command_to_list():
    assert menu.command_to_list(["a", "b", "c"]) == ["a", "b", "c"]
    assert menu.command_to_list("a b c") == ["a", "b", "c"]
    assert menu.command_to_list(["a", "b c"]) == ["a", "b", "c"]
    assert menu.command_to_list(["a", "b", "c", "aö"]) == ["a", "b", "c", "a\xf6"]
    assert menu.command_to_list("a b c aö") == ["a", "b", "c", "a\xf6"]
    assert menu.command_to_list(["a", "b c aö"]) == ["a", "b", "c", "a\xf6"]
    assert menu.command_to_list('xdg-open "/home/user/aö/"') == [
        "xdg-open",
        "/home/user/a\xf6/",
    ]
    assert menu.command_to_list("xdg-open /home/user/aö/") == [
        "xdg-open",
        "/home/user/a\xf6/",
    ]
    assert menu.command_to_list('xdg-open "/home/user/aö/filename"') == [
        "xdg-open",
        "/home/user/a\xf6/filename",
    ]
    assert menu.command_to_list('xdg-open "/home/user/aö/file name"') == [
        "xdg-open",
        "/home/user/a\xf6/file name",
    ]
    assert menu.command_to_list("xdg-open /home/user/aö/filename") == [
        "xdg-open",
        "/home/user/a\xf6/filename",
    ]
    assert menu.command_to_list("xdg-open /home/user/aö/file name") == [
        "xdg-open",
        "/home/user/a\xf6/file",
        "name",
    ]
    assert menu.command_to_list('xdg-open "/home/user/aö/foldername/"') == [
        "xdg-open",
        "/home/user/a\xf6/foldername/",
    ]
    assert menu.command_to_list('xdg-open "/home/user/aö/folder name/"') == [
        "xdg-open",
        "/home/user/a\xf6/folder name/",
    ]
    assert menu.command_to_list("xdg-open /home/user/aö/folder name/") == [
        "xdg-open",
        "/home/user/a\xf6/folder",
        "name/",
    ]
    assert menu.command_to_list("xdg-open /home/user/aö/foldername/") == [
        "xdg-open",
        "/home/user/a\xf6/foldername/",
    ]
    assert menu.command_to_list('xdg-open "/home/user/aö/"foldernam "e/"') == [
        "xdg-open",
        "/home/user/a\xf6/foldernam",
        "e/",
    ]
    assert menu.command_to_list(
        'xdg-open "/home/user/1983 - BVerfG - Volkszahlungsurteil - 1983.pdf"'
    ) == [
        "xdg-open",
        "/home/user/1983 - BVerfG - Volkszahlungsurteil - 1983.pdf",
    ]


def test_scan_binaries_file_in_system_path():
    with mock.patch.object(menu, "system_path", new=lambda: ["/bin", "/bin/cp"]):
        assert isinstance(menu.scan_binaries(), list)


def test_copy_to_clipboard_wl_copy():
    with mock.patch("subprocess.run") as mock_run:
        mock_run.return_value = mock.Mock(returncode=0)
        result = menu.copy_to_clipboard("test text")
        assert result is True
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert args[0] == "wl-copy"


def test_copy_to_clipboard_xclip():
    with mock.patch("subprocess.run") as mock_run:

        def side_effect(cmd, **kwargs):
            if cmd[0] == "wl-copy":
                raise FileNotFoundError()
            return mock.Mock(returncode=0)

        mock_run.side_effect = side_effect
        result = menu.copy_to_clipboard("test text")
        assert result is True
        assert mock_run.call_count == 2
        args = mock_run.call_args[0][0]
        assert args[0] == "xclip"
        assert "-selection" in args
        assert "clipboard" in args


def test_copy_to_clipboard_xsel():
    with mock.patch("subprocess.run") as mock_run:

        def side_effect(cmd, **kwargs):
            if cmd[0] in ["wl-copy", "xclip"]:
                raise FileNotFoundError()
            return mock.Mock(returncode=0)

        mock_run.side_effect = side_effect
        result = menu.copy_to_clipboard("test text")
        assert result is True
        assert mock_run.call_count == 3
        args = mock_run.call_args[0][0]
        assert args[0] == "xsel"
        assert "--clipboard" in args
        assert "--input" in args


def test_copy_to_clipboard_no_tool_available():
    with mock.patch("subprocess.run") as mock_run:
        mock_run.side_effect = FileNotFoundError()
        result = menu.copy_to_clipboard("test text")
        assert result is False
        assert mock_run.call_count == 3
