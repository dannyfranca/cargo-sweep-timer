import os
from pathlib import Path
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "bin" / "cargo-sweep-timer"


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="sweep-config-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = self.root / "config.env"
        self.cargo_calls = self.root / "cargo-calls"
        cargo = self.root / "cargo"
        cargo.write_text(
            '#!/usr/bin/env bash\n'
            'printf "%s\\n" "$*" >> "$CARGO_CALLS"\n'
            '[[ $* == "sweep --version" ]]\n'
        )
        cargo.chmod(0o755)
        self.env = os.environ.copy()
        self.env.pop("CARGO_SWEEP_TIMER_CONFIG", None)
        self.env.update(
            PATH=f"{self.root}:{self.env['PATH']}",
            CARGO_CALLS=str(self.cargo_calls),
            XDG_CONFIG_HOME=str(self.root / "config"),
            SWEEP_ROOTS="",
            SWEEP_TARGET_DIRS="",
            SWEEP_DAYS="1",
            DRY_RUN="1",
        )

    def run_script(self):
        return subprocess.run(
            [str(SCRIPT)], env=self.env, capture_output=True, text=True, timeout=10
        )

    def test_config_errors_stop_before_cargo_runs(self):
        self.env["CARGO_SWEEP_TIMER_CONFIG"] = str(self.config)
        for content in ("SWEEP_DAYS=(\n", "false\nSWEEP_DAYS=7\n"):
            with self.subTest(content=content):
                self.config.write_text(content)
                result = self.run_script()
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(self.cargo_calls.exists())

    def test_missing_explicit_config_stops_before_cargo_runs(self):
        self.env["CARGO_SWEEP_TIMER_CONFIG"] = str(self.config)
        result = self.run_script()
        self.assertEqual(result.returncode, 2)
        self.assertIn("config file not found:", result.stderr)
        self.assertFalse(self.cargo_calls.exists())

    def test_missing_default_config_is_optional(self):
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.cargo_calls.read_text(), "sweep --version\n")
