import json
import os
from pathlib import Path
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
            'if command == "install" and args[-1] != str(Path.home() / ".local/bin/cargo-sweep-timer"):\n'
            '    os.execv(os.environ["REAL_INSTALL"], ["install", *args])\n'
        )
        for command in ("cargo", "systemctl", "install", "rm"):
            (self.commands / command).symlink_to(stub)
        self.config_home = self.root / "config"
        self.env = os.environ.copy()
        self.env.update(
            PATH=f"{self.commands}:{self.env['PATH']}",
            XDG_CONFIG_HOME=str(self.config_home),
            CARGO_HOME=str(self.root / "custom cargo"),
            COMMAND_LOG=str(self.log),
            REAL_INSTALL=shutil.which("install"),
        )

    def run_script(self, name):
        result = subprocess.run(
            [str(REPO / name)], env=self.env, capture_output=True, text=True, timeout=10
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def test_installed_service_preserves_cargo_search_paths(self):
        self.run_script("install.sh")
        service = self.config_home / "systemd/user/cargo-sweep-timer.service"
        path = f"{self.env['CARGO_HOME']}/bin:{self.env['PATH']}"
        service.write_text(service.read_text().replace(
            "ExecStart=%h/.local/bin/cargo-sweep-timer", "ExecStart=/usr/bin/true"
        ))
        result = subprocess.run(
            ["systemd-analyze", "--user", "verify", str(service)],
            env={**self.env, "SYSTEMD_LOG_LEVEL": "debug"},
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(f"Environment: PATH={path}\n", result.stdout + result.stderr)

    def test_uninstall_stops_service_before_removing_files(self):
        calls = self.run_script("uninstall.sh")
        stop = calls.index(["systemctl", "--user", "stop", "cargo-sweep-timer.service"])
        remove = next(index for index, call in enumerate(calls) if call[0] == "rm")
        self.assertLess(stop, remove)
        self.assertLess(calls.index(["systemctl", "--user", "disable", "--now", "cargo-sweep-timer.timer"]), stop)
