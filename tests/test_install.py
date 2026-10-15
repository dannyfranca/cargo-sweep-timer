import json
import os
from pathlib import Path
import plistlib
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[1]


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="sweep-install-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.commands = self.root / 'commands with % and "'
        self.commands.mkdir()
        self.log = self.root / "commands.jsonl"
        stub = self.commands / "stub"
        stub.write_text(
            f"#!/bin/sh\nexec {shlex.quote(sys.executable)} {shlex.quote(str(self.commands / 'stub.py'))} \"$0\" \"$@\"\n"
        )
        stub.chmod(0o755)
        (self.commands / "stub.py").write_text(
            'import json, os, sys\n'
            'from pathlib import Path\n'
            'command = Path(sys.argv[1]).name\n'
            'args = sys.argv[2:]\n'
            'with open(os.environ["COMMAND_LOG"], "a") as log:\n'
            '    log.write(json.dumps([command, *args]) + "\\n")\n'
            'if command == "systemctl" and "stop" in args:\n'
            '    sys.exit(int(os.environ.get("STOP_STATUS", "0")))\n'
            'if command == "systemctl" and "show" in args:\n'
            '    print(os.environ.get("SERVICE_STATE", "active"))\n'
            '    sys.exit(int(os.environ.get("SHOW_STATUS", "0")))\n'
            'if command == "uname":\n'
            '    print(os.environ.get("UNAME", "Linux"))\n'
            'if command == "launchctl" and args[0] == "bootout":\n'
            '    sys.exit(int(os.environ.get("BOOTOUT_STATUS", "0")))\n'
            'if command == "launchctl" and args[0] == "print":\n'
            '    prints = sum(json.loads(line)[:2] == ["launchctl", "print"] for line in open(os.environ["COMMAND_LOG"]))\n'
            '    loaded = prints <= int(os.environ.get("PRINT_LOADED_CALLS", "0"))\n'
            '    sys.exit(0 if loaded else int(os.environ.get("PRINT_STATUS", "113")))\n'
            'if command == "install" and args[-1] != str(Path.home() / ".local/bin/cargo-sweep-timer"):\n'
            '    os.execv(os.environ["REAL_INSTALL"], ["install", *args])\n'
        )
        for command in ("cargo", "systemctl", "launchctl", "uname", "install", "rm"):
            (self.commands / command).symlink_to(stub)
        sleep = self.commands / "sleep"
        sleep.write_text("#!/bin/sh\n")
        sleep.chmod(0o755)
        self.config_home = self.root / "config"
        self.home = self.root / "home"
        self.env = os.environ.copy()
        self.env.pop("SWEEP_TIME", None)
        self.env.update(
            HOME=str(self.home),
            PATH=f"{self.commands}:{self.env['PATH']}",
            XDG_CONFIG_HOME=str(self.config_home),
            CARGO_HOME=str(self.root / "custom cargo"),
            COMMAND_LOG=str(self.log),
            REAL_INSTALL=shutil.which("install"),
        )

    def run_script(self, name, expected_status=0, timeout=10):
        result = subprocess.run(
            [str(REPO / name)], env=self.env, capture_output=True, text=True, timeout=timeout
        )
        self.assertEqual(result.returncode, expected_status, result.stdout + result.stderr)
        self.stderr = result.stderr
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    @unittest.skipUnless(shutil.which("systemd-analyze"), "needs systemd-analyze")
    def test_installed_service_preserves_cargo_search_paths(self):
        self.run_script("install.sh")
        service = self.config_home / "systemd/user/cargo-sweep-timer.service"
        path = f"{self.env['CARGO_HOME']}/bin:{self.env['PATH']}"
        service.write_text(service.read_text().replace(
            "ExecStart=%h/.local/bin/cargo-sweep-timer", "ExecStart=/usr/bin/true"
        ))
        result = subprocess.run(
            ["systemd-analyze", "--user", "verify", str(service), str(self.timer())],
            env={**self.env, "SYSTEMD_LOG_LEVEL": "debug"},
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(f"Environment: PATH={path}\n", result.stdout + result.stderr)

    def timer(self):
        return self.config_home / "systemd/user/cargo-sweep-timer.timer"

    def config(self):
        return self.config_home / "cargo-sweep-timer/config.env"

    def test_timer_runs_at_ten_by_default(self):
        self.run_script("install.sh")
        self.assertIn("OnCalendar=*-*-* 10:00:00\n", self.timer().read_text())
        self.assertIn("SWEEP_TIME=10:00\n", self.config().read_text())

    def test_timer_uses_the_time_from_the_config_or_the_environment(self):
        self.config().parent.mkdir(parents=True)
        for config, environment, expected in (
            ("SWEEP_TIME=21:30\n", None, "21:30"),
            ("SWEEP_TIME=21:30\n", "7:05", "07:05"),
            ("SWEEP_DAYS=3\n", None, "10:00"),
            ("SWEEP_TIME=21:30\n", "", "10:00"),
        ):
            with self.subTest(config=config, environment=environment):
                self.config().write_text(config)
                self.env.pop("SWEEP_TIME", None)
                if environment is not None:
                    self.env["SWEEP_TIME"] = environment
                self.run_script("install.sh")
                self.assertIn(f"OnCalendar=*-*-* {expected}:00\n", self.timer().read_text())
                self.assertEqual(self.stderr, "")

    def test_install_stops_when_the_config_fails_to_load(self):
        self.config().parent.mkdir(parents=True)
        self.config().write_text("false\nSWEEP_TIME=14:00\n")
        for environment in (None, "07:00"):
            with self.subTest(environment=environment):
                self.log.unlink(missing_ok=True)
                if environment is not None:
                    self.env["SWEEP_TIME"] = environment
                calls = self.run_script("install.sh", expected_status=1)
                self.assertIn(f"could not load config: {self.config()}", self.stderr)
                self.assertFalse(any(call[0] in ("install", "systemctl") for call in calls))
                self.assertFalse(self.timer().exists())

    def test_invalid_time_falls_back_to_ten(self):
        for value in ("24:00", "10:60", "10", "noon", "10:00:00"):
            with self.subTest(value=value):
                self.env["SWEEP_TIME"] = value
                self.run_script("install.sh")
                self.assertIn("OnCalendar=*-*-* 10:00:00\n", self.timer().read_text())
                self.assertIn(f"SWEEP_TIME must be HH:MM in 24-hour time, got: {value}", self.stderr)

    def test_uninstall_stops_service_before_removing_files(self):
        calls = self.run_script("uninstall.sh")
        stop = calls.index(["systemctl", "--user", "stop", "cargo-sweep-timer.service"])
        remove = next(index for index, call in enumerate(calls) if call[0] == "rm")
        self.assertLess(stop, remove)
        self.assertLess(calls.index(["systemctl", "--user", "disable", "--now", "cargo-sweep-timer.timer"]), stop)

    def test_uninstall_keeps_files_when_stop_or_state_check_fails(self):
        for state, show_status in (("active", "0"), ("inactive", "1")):
            with self.subTest(state=state, show_status=show_status):
                self.log.unlink(missing_ok=True)
                self.env.update(STOP_STATUS="1", SERVICE_STATE=state, SHOW_STATUS=show_status)
                calls = self.run_script("uninstall.sh", expected_status=1)
                self.assertFalse(any(call[0] == "rm" for call in calls))

    def test_uninstall_allows_an_already_inactive_service(self):
        self.env.update(STOP_STATUS="1", SERVICE_STATE="inactive")
        calls = self.run_script("uninstall.sh")
        self.assertTrue(any(call[0] == "rm" for call in calls))

    def agent_plist(self):
        return self.home / "Library/LaunchAgents/com.dannyfranca.cargo-sweep-timer.plist"

    def test_macos_agent_preserves_cargo_search_paths_and_config(self):
        self.env.update(UNAME="Darwin", HOME=str(self.root / "home & <dir>"))
        self.home = Path(self.env["HOME"])
        calls = self.run_script("install.sh")
        with self.agent_plist().open("rb") as plist:
            agent = plistlib.load(plist)
        self.assertEqual(agent["ProgramArguments"], ["/bin/bash", f"{self.home}/.local/bin/cargo-sweep-timer"])
        self.assertEqual(agent["EnvironmentVariables"], {
            "PATH": f"{self.env['CARGO_HOME']}/bin:{self.env['PATH']}",
            "XDG_CONFIG_HOME": str(self.config_home),
            "CARGO_SWEEP_TIMER_LOG": f"{self.home}/Library/Logs/cargo-sweep-timer.log",
        })
        self.assertIn(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(self.agent_plist())], calls)
        self.assertFalse(any(call[0] == "systemctl" for call in calls))

    def test_macos_agent_runs_at_the_configured_time(self):
        self.env.update(UNAME="Darwin")
        for environment, hour, minute in ((None, 10, 0), ("07:05", 7, 5), ("bad", 10, 0)):
            with self.subTest(environment=environment):
                self.env.pop("SWEEP_TIME", None)
                if environment is not None:
                    self.env["SWEEP_TIME"] = environment
                self.run_script("install.sh")
                with self.agent_plist().open("rb") as plist:
                    agent = plistlib.load(plist)
                self.assertEqual(agent["StartCalendarInterval"], {"Hour": hour, "Minute": minute})

    def test_macos_install_creates_the_agent_log_dir(self):
        self.env.update(UNAME="Darwin", BOOTOUT_STATUS="3", PRINT_STATUS="113")
        self.run_script("install.sh")
        self.assertTrue((self.home / "Library/Logs").is_dir())

    def test_macos_install_keeps_files_when_old_agent_stays_loaded(self):
        self.env.update(UNAME="Darwin", BOOTOUT_STATUS="1", PRINT_STATUS="0")
        calls = self.run_script("install.sh", expected_status=1)
        self.assertFalse(any(call[0] == "install" for call in calls))
        self.assertFalse(any(call[:2] == ["launchctl", "bootstrap"] for call in calls))
        self.assertFalse(self.agent_plist().exists())

    def test_macos_install_waits_for_the_old_agent_to_exit(self):
        self.env.update(UNAME="Darwin", PRINT_LOADED_CALLS="3")
        calls = self.run_script("install.sh")
        prints = [index for index, call in enumerate(calls) if call[:2] == ["launchctl", "print"]]
        bootstrap = next(index for index, call in enumerate(calls) if call[:2] == ["launchctl", "bootstrap"])
        self.assertEqual(len(prints), 4)
        self.assertLess(prints[-1], bootstrap)

    def test_macos_install_stops_when_the_old_agent_does_not_exit(self):
        self.env.update(UNAME="Darwin", PRINT_STATUS="0")
        # The wait polls launchctl 50 times, and each stub call starts Python.
        calls = self.run_script("install.sh", expected_status=1, timeout=60)
        self.assertFalse(any(call[0] == "install" for call in calls))
        self.assertFalse(any(call[:2] == ["launchctl", "bootstrap"] for call in calls))

    def test_macos_uninstall_unloads_agent_before_removing_files(self):
        self.env.update(UNAME="Darwin")
        calls = self.run_script("uninstall.sh")
        unload = calls.index(["launchctl", "bootout", f"gui/{os.getuid()}/com.dannyfranca.cargo-sweep-timer"])
        remove = next(index for index, call in enumerate(calls) if call[0] == "rm")
        self.assertLess(unload, remove)

    def test_macos_uninstall_keeps_files_when_agent_stays_loaded(self):
        self.env.update(UNAME="Darwin", BOOTOUT_STATUS="1", PRINT_STATUS="0")
        calls = self.run_script("uninstall.sh", expected_status=1)
        self.assertFalse(any(call[0] == "rm" for call in calls))

    def test_macos_uninstall_waits_for_the_agent_to_exit(self):
        self.env.update(UNAME="Darwin", PRINT_LOADED_CALLS="3")
        calls = self.run_script("uninstall.sh")
        prints = [index for index, call in enumerate(calls) if call[:2] == ["launchctl", "print"]]
        remove = next(index for index, call in enumerate(calls) if call[0] == "rm")
        self.assertEqual(len(prints), 4)
        self.assertLess(prints[-1], remove)

    def test_macos_uninstall_keeps_files_when_the_agent_does_not_exit(self):
        self.env.update(UNAME="Darwin", PRINT_STATUS="0")
        # The wait polls launchctl 50 times, and each stub call starts Python.
        calls = self.run_script("uninstall.sh", expected_status=1, timeout=60)
        self.assertFalse(any(call[0] == "rm" for call in calls))

    def test_macos_uninstall_allows_an_unloaded_agent(self):
        self.env.update(UNAME="Darwin", BOOTOUT_STATUS="113", PRINT_STATUS="113")
        calls = self.run_script("uninstall.sh")
        self.assertTrue(any(call[0] == "rm" for call in calls))

    def test_macos_uninstall_keeps_files_when_agent_state_is_unknown(self):
        self.env.update(UNAME="Darwin", BOOTOUT_STATUS="1", PRINT_STATUS="1")
        calls = self.run_script("uninstall.sh", expected_status=1)
        self.assertFalse(any(call[0] == "rm" for call in calls))
