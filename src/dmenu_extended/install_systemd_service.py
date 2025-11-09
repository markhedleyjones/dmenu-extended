#!/usr/bin/env python3

import argparse
import os
import subprocess


def run_systemd_command(user_command, silent=False):
    command = ["systemctl", "--user"] + user_command
    if silent:
        return (
            subprocess.call(
                command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            == 0
        )
    else:
        return subprocess.call(command) == 0


def find_executable(executable_name):
    executable_paths = [
        "/usr/local/bin",
        "/usr/bin",
        os.path.expanduser("~/.local/bin"),
    ]
    for executable_path in executable_paths:
        path = os.path.join(executable_path, executable_name)
        if os.path.isfile(path):
            return path


def detect_systemd_user_paths():
    systemd_user_paths = []
    if "XDG_CONFIG_HOME" in os.environ:
        systemd_user_paths.append(f"{os.environ['XDG_CONFIG_HOME']}/systemd/user")
    if "HOME" in os.environ:
        systemd_user_paths.append(f"{os.environ['HOME']}/.config/systemd/user")
        systemd_user_paths.append(f"{os.environ['HOME']}/.local/share/systemd/user")
    if "XDG_RUNTIME_DIR" in os.environ:
        systemd_user_paths.append(f"{os.environ['XDG_RUNTIME_DIR']}/systemd/user")
    if "XDG_DATA_HOME" in os.environ:
        systemd_user_paths.append(f"{os.environ['XDG_DATA_HOME']}/systemd/user")
    return systemd_user_paths


class ServiceInstaller:
    def __init__(self):
        self.filenames = {
            key: f"dmenu-extended-update-db.{key}" for key in ["service", "timer"]
        }
        self.filenames["target"] = "dmenu_extended_cache_build"

    def generate_install_files(self, rebuild_interval_mins):
        if rebuild_interval_mins is None or rebuild_interval_mins < 1:
            raise Exception("Invalid rebuild interval")
        return {
            self.filenames["service"]: "\n".join(
                [
                    "[Unit]",
                    "Description=Update dmenu-extended cache",
                    f"Wants={self.filenames['timer']}",
                    "",
                    "[Service]",
                    "Type=oneshot",
                    f"ExecStart={self.filenames['target']}",
                    "",
                    "[Install]",
                    "WantedBy=multi-user.target",
                    "",
                ]
            ),
            self.filenames["timer"]: "\n".join(
                [
                    "[Unit]",
                    (
                        f"Description=Run {self.filenames['service']} every {rebuild_interval_mins} minutes"
                    ),
                    f"Requires={self.filenames['service']}",
                    "",
                    "[Timer]",
                    f"Unit={self.filenames['service']}",
                    f"OnCalendar=*:0/{rebuild_interval_mins}",
                    "",
                    "[Install]",
                    "WantedBy=timers.target",
                    "",
                ]
            ),
        }

    @staticmethod
    def get_install_path():
        if "XDG_DATA_HOME" in os.environ:
            return f"{os.environ['XDG_DATA_HOME']}/systemd/user"
        elif "HOME" in os.environ:
            return f"{os.environ['HOME']}/.local/share/systemd/user"

    def install(self, rebuild_interval_mins=20):
        executable_path = find_executable(self.filenames["target"])
        if not executable_path:
            raise Exception(
                f"Could not find target executable ({self.filenames['target']})"
            )

        install_path = self.get_install_path()
        if not os.path.isdir(install_path):
            print(f"Creating systemd user directory: {install_path}")
            os.makedirs(install_path)

        for filename, contents in self.generate_install_files(
            rebuild_interval_mins
        ).items():
            path = os.path.join(install_path, filename)
            print(f"Installing {filename} to {install_path}")
            with open(path, "w") as f:
                f.write(contents)

    def remove(self):
        run_systemd_command(["daemon-reload"])
        removed_files = []
        for filename in self.generate_install_files().keys():
            if filename.endswith(".timer") and run_systemd_command(
                ["is-enabled", filename], silent=True
            ):
                print(f"Stopping {filename} ...")
                run_systemd_command(["stop", filename])
                run_systemd_command(["disable", filename])

            for possible_install_path in detect_systemd_user_paths():
                path = os.path.join(possible_install_path, filename)
                if os.path.exists(path):
                    removed_files.append(path)
                    os.remove(path)
        if removed_files:
            for path in removed_files:
                print(f"Removed {path}")
        else:
            print("No systemd files found to remove")

    def start(self):
        run_systemd_command(["daemon-reload"])
        target = f"{self.filenames}.timer"
        if run_systemd_command(["start", target]) and run_systemd_command(
            ["enable", target]
        ):
            print(f"Started {target}")


def run():
    def parse_args():
        parser = argparse.ArgumentParser(
            description="Install dmenu-extended systemd services"
        )
        parser.add_argument(
            "--remove", action="store_true", help="Remove systemd services"
        )
        parser.add_argument(
            "--start", action="store_true", help="Start systemd services"
        )
        parser.add_argument(
            "--rebuild-interval-mins",
            type=int,
            default=20,
            help="How often to update the cache (in minutes)",
        )
        return parser.parse_args()

    def prompt_to_start(service_target):
        print("The systemd service has been installed.")
        if input("Do you want to enable it now? [y/N] ").lower() == "y":
            run_systemd_command(["daemon-reload"])
            if run_systemd_command(["start", service_target]) and run_systemd_command(
                ["enable", service_target]
            ):
                print(f"Started {service_target}")

    if os.geteuid() == 0:
        print("This script must be run as a non-root user.")
        exit(1)

    args = parse_args()
    service_installer = ServiceInstaller()

    if args.remove:
        service_installer.remove()
    else:
        service_installer.install(args.rebuild_interval_mins)
        if args.start or prompt_to_start(service_installer.filenames["timer"]):
            service_installer.start()


if __name__ == "__main__":
    run()
