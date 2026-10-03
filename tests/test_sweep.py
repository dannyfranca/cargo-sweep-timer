import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "bin" / "cargo-sweep-timer"


class SweepTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="sweep-targets-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = self.root / "config.env"
        self.config.touch()
        self.env = os.environ.copy()
        for name in ("CARGO_TARGET_DIR", "RUSTC_WRAPPER", "RUSTC_WORKSPACE_WRAPPER"):
            self.env.pop(name, None)
        self.env.update(
            CARGO_HOME=str(self.root / "cargo-home"),
            CARGO_SWEEP_TIMER_CONFIG=str(self.config),
            SWEEP_ROOTS="",
            SWEEP_TARGET_DIRS="",
            SWEEP_DAYS="0",
            DRY_RUN="0",
        )

    def create_project(self, path):
        (path / "src").mkdir(parents=True)
        (path / "src" / "main.rs").write_text("fn main() {}\n")
        (path / "Cargo.toml").write_text(
            '[package]\nname="sweep-fixture"\nversion="0.0.0"\nedition="2021"\n'
        )
        return path

    def build_project(self, project, target):
        result = subprocess.run(
            ["cargo", "build", "--offline", "--manifest-path", str(project / "Cargo.toml"),
             "--target-dir", str(target)],
            env=self.env, capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        artifacts = [path for path in (target / "debug" / "deps").glob("sweep_fixture-*")
                     if path.suffix != ".d"]
        self.assertEqual(len(artifacts), 1)
        artifact = artifacts[0]
        self.assertTrue(artifact.is_file())
        return artifact

    def run_script(self, *args):
        return subprocess.run(
            [str(SCRIPT), *args], env=self.env, capture_output=True, text=True, timeout=60
        )

    def test_hidden_projects_shared_targets_and_dry_run(self):
        projects = self.root / "projects with spaces"
        hidden = self.create_project(projects / ".worktrees" / "project")
        shared_project = self.create_project(self.root / "shared-project")
        shared_target = self.root / "shared target"
        artifacts = [
            self.build_project(hidden, hidden / "target"),
            self.build_project(shared_project, shared_target),
        ]
        untouched = self.build_project(shared_project, self.root / "unselected target")
        self.config.write_text('SWEEP_DAYS=invalid\nSWEEP_ROOTS=""\nSWEEP_TARGET_DIRS=""\nDRY_RUN=0\n')
        self.env.update(SWEEP_ROOTS=str(projects), SWEEP_TARGET_DIRS=str(shared_target))

        for args, dry_run in ((["--dry-run"], "0"), ([], "1")):
            with self.subTest(args=args, dry_run=dry_run):
                self.env["DRY_RUN"] = dry_run
                result = self.run_script(*args)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("Would clean:", result.stdout)
                self.assertTrue(all(path.is_file() for path in artifacts))

        self.env["DRY_RUN"] = "0"
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(all(not path.exists() for path in artifacts))
        self.assertTrue(untouched.is_file())

    def test_logged_cleanup_error_fails_and_next_target_is_swept(self):
        broken = self.root / "broken target"
        (broken / "debug").mkdir(parents=True)
        (broken / "debug" / ".fingerprint").write_text("not a directory\n")
        project = self.create_project(self.root / "project")
        target = self.root / "valid target"
        artifact = self.build_project(project, target)
        self.env["SWEEP_TARGET_DIRS"] = f"{broken}:{target}"
        result = self.run_script()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("[ERROR] Failed to clean", result.stdout)
        self.assertIn("1 sweep(s) failed", result.stderr)
        self.assertFalse(artifact.exists())

    def stub_cargo(self, output, status):
        cargo = self.root / "cargo"
        cargo.write_text(
            '#!/usr/bin/env bash\n'
            '[[ $* == "sweep --version" ]] && exit 0\n'
            f"printf '%s\\n' {shlex.quote(output)}\nexit {status}\n"
        )
        cargo.chmod(0o755)
        self.env.update(PATH=f"{self.root}:{self.env['PATH']}", SWEEP_ROOTS=str(self.root))

    def test_failed_cargo_command_reports_failure(self):
        self.stub_cargo("sweep command failed", 9)
        result = self.run_script()
        self.assertEqual(result.returncode, 1)
        self.assertIn("sweep command failed", result.stdout)
        self.assertIn("1 sweep(s) failed", result.stderr)

    def test_removal_warnings_report_failure(self):
        warning = '[WARN] Failed to remove: "artifact" Permission denied (os error 13)'
        for output, expected_status in (
            (warning, 1),
            (f"[INFO] Starting sweep\n{warning}", 1),
            ("[WARN] Skipping missing target", 0),
        ):
            with self.subTest(output=output):
                self.stub_cargo(output, 0)
                result = self.run_script()
                self.assertEqual(result.returncode, expected_status, result.stdout + result.stderr)
                self.assertEqual("1 sweep(s) failed" in result.stderr, expected_status == 1)
