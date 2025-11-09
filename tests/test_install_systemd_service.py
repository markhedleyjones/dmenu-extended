#!/usr/bin/env python3

import os
import shutil

import install_systemd_service
import mock
import pytest

test_path = os.path.dirname(os.path.abspath(__file__))


def test_generate_valid_service_files():
    def check_service_file(lines, _):
        expected_lines = [
            "[Unit]",
            "Description=Update dmenu-extended cache",
            "Wants=dmenu-extended-update-db.timer",
            "[Service]",
            "Type=oneshot",
            "ExecStart=dmenu_extended_cache_build",
            "[Install]",
            "WantedBy=multi-user.target",
        ]
        for line, expected_line in zip(lines, expected_lines):
            assert line == expected_line

    def check_timer_file(lines, expected_mins):
        expected_lines = [
            "[Unit]",
            f"Description=Run dmenu-extended-update-db.service every {expected_mins} minutes",
            "Requires=dmenu-extended-update-db.service",
            "[Timer]",
            "Unit=dmenu-extended-update-db.service",
            f"OnCalendar=*:0/{expected_mins}",
            "[Install]",
            "WantedBy=timers.target",
        ]
        for line, expected_line in zip(lines, expected_lines):
            assert line == expected_line

    installer = install_systemd_service.ServiceInstaller()
    path_test_install = os.path.join(test_path, "test_install_dir")
    with mock.patch.object(
        installer,
        "get_install_path",
        new=lambda: path_test_install,
    ):
        file_checker_functions = {
            "service": check_service_file,
            "timer": check_timer_file,
        }

        test_install_parameters = [(20, 20), (15, 15), (None, 20), (-5, 20)]
        for rebuild_interval_parameter, expected_mins in test_install_parameters:
            if rebuild_interval_parameter is None or rebuild_interval_parameter < 1:
                with pytest.raises(Exception):
                    installer.install(rebuild_interval_parameter)
            else:
                installer.install(rebuild_interval_parameter)
                files = {}
                for filetype, checker_func in file_checker_functions.items():
                    path = os.path.join(
                        path_test_install, installer.filenames[filetype]
                    )
                    with open(path) as f:
                        files[filetype] = [
                            line for line in f.read().split("\n") if line.strip() != ""
                        ]
                    checker_func(files[filetype], expected_mins)
                shutil.rmtree(path_test_install)
