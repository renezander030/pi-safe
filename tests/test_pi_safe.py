#!/usr/bin/env python3
import argparse
import importlib.machinery
import pathlib
import uuid
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "bin" / "pi-safe"
pi_safe = importlib.machinery.SourceFileLoader("pi_safe", str(MODULE_PATH)).load_module()


class PiSafeUnitTests(unittest.TestCase):
    def test_no_args_defaults_to_run_current_directory(self):
        self.assertEqual(pi_safe.normalize_argv([]), ["run"])

    def test_bare_prompt_routes_to_run(self):
        self.assertEqual(pi_safe.normalize_argv(["review this"]), ["run", "review this"])

    def test_subcommands_stay_subcommands(self):
        self.assertEqual(pi_safe.normalize_argv(["diff", "abc123"]), ["diff", "abc123"])

    def test_help_shorthand_shows_help(self):
        self.assertEqual(pi_safe.normalize_argv(["help"]), ["--help"])

    def test_slash_sandbox_routes_to_status(self):
        self.assertEqual(pi_safe.normalize_argv(["/sandbox"]), ["status"])

    def test_status_lines_reports_wrapper_active(self):
        args = argparse.Namespace(
            bypass="0",
            wrapper="/Users/example/.local/bin/pi",
            pi_safe="/Users/example/.local/bin/pi-safe",
            real_pi="/opt/homebrew/bin/pi",
            safe_home=str(ROOT / "tmp" / "pi-safe-status-home"),
            from_wrapper=True,
        )

        lines = pi_safe.status_lines(args)

        self.assertIn("pi-safe wrapper: ACTIVE", lines[0])
        self.assertTrue(any("/opt/homebrew/bin/pi" in line for line in lines))

    def test_validate_project_root_rejects_home_directory(self):
        safe_home = (ROOT / "tmp" / "safe-home").resolve()

        with self.assertRaisesRegex(pi_safe.PiSafeError, "broad directory"):
            pi_safe.validate_project_root(pathlib.Path.home().resolve(), safe_home)

    def test_validate_project_root_rejects_pi_config_directory(self):
        safe_home = (ROOT / "tmp" / "safe-home").resolve()

        with self.assertRaisesRegex(pi_safe.PiSafeError, "broad directory"):
            pi_safe.validate_project_root(pathlib.Path.home().resolve() / ".pi", safe_home)

    def test_validate_project_root_rejects_safe_home_tree(self):
        safe_home = (ROOT / "tmp" / "safe-home").resolve()

        with self.assertRaisesRegex(pi_safe.PiSafeError, "pi-safe state"):
            pi_safe.validate_project_root(safe_home / "sessions", safe_home)

    def test_validate_project_root_accepts_nested_workspace(self):
        safe_home = (ROOT / "tmp" / "safe-home").resolve()

        pi_safe.validate_project_root(pathlib.Path.home().resolve() / "Documents" / "Codex" / "project", safe_home)

    def test_profile_denies_global_writes_and_allows_staging(self):
        profile = pi_safe.make_profile(pathlib.Path("/tmp/staging"), pathlib.Path("/tmp/writable"), False)
        self.assertIn("(deny file-write*)", profile)
        self.assertIn('(subpath "/tmp/staging")', profile)
        self.assertIn('(subpath "/tmp/writable")', profile)
        self.assertNotIn('(subpath "/private/tmp")', profile)

    def test_change_set_detects_add_modify_delete(self):
        root = ROOT / "tmp" / f"pi-safe-unit-{uuid.uuid4().hex}"
        original = root / "original"
        staging = root / "staging"
        original.mkdir(parents=True)
        staging.mkdir(parents=True)
        (original / "same.txt").write_text("same\n", encoding="utf-8")
        (staging / "same.txt").write_text("same\n", encoding="utf-8")
        (original / "modified.txt").write_text("old\n", encoding="utf-8")
        (staging / "modified.txt").write_text("new\n", encoding="utf-8")
        (original / "deleted.txt").write_text("gone\n", encoding="utf-8")
        (staging / "added.txt").write_text("added\n", encoding="utf-8")

        changes = {(c["kind"], c["path"]) for c in pi_safe.change_set(original, staging)}
        self.assertEqual(
            changes,
            {
                ("modified", "modified.txt"),
                ("deleted", "deleted.txt"),
                ("added", "added.txt"),
            },
        )

    def test_safe_copytree_excludes_safe_home_inside_project(self):
        root = ROOT / "tmp" / f"pi-safe-copy-{uuid.uuid4().hex}"
        project = root / "project"
        safe_home = project / ".pi-safe-state"
        dest = root / "copy"
        safe_home.mkdir(parents=True)
        (project / "keep.txt").write_text("keep\n", encoding="utf-8")
        (safe_home / "state.txt").write_text("state\n", encoding="utf-8")

        pi_safe.safe_copytree(project, dest, [], [safe_home])

        self.assertTrue((dest / "keep.txt").exists())
        self.assertFalse((dest / ".pi-safe-state").exists())

    def test_session_status_extension_written(self):
        root = ROOT / "tmp" / f"pi-safe-extension-{uuid.uuid4().hex}"
        project = root / "project"
        original = root / "original"
        staging = root / "staging"
        writable = root / "writable"
        for path in [project, original, staging, writable]:
            path.mkdir(parents=True)
        session = pi_safe.Session("unit", project, root, original, staging, writable, root / pi_safe.PROFILE)

        pi_safe.install_session_status_extension(session)

        package_json = writable / "pi-agent" / "extensions" / "pi-safe-status" / "package.json"
        index_ts = writable / "pi-agent" / "extensions" / "pi-safe-status" / "src" / "index.ts"
        self.assertTrue(package_json.exists())
        self.assertIn('"extensions": ["./src/index.ts"]', package_json.read_text(encoding="utf-8"))
        extension_source = index_ts.read_text(encoding="utf-8")
        self.assertIn('registerCommand("sandbox"', extension_source)
        self.assertIn('ctx.ui.setStatus("pi-safe", "pi-safe sandbox active")', extension_source)
        self.assertIn('pi.sendMessage({', extension_source)

    def test_pi_launch_args_load_session_status_extension_explicitly(self):
        root = ROOT / "tmp" / f"pi-safe-launch-{uuid.uuid4().hex}"
        project = root / "project"
        original = root / "original"
        staging = root / "staging"
        writable = root / "writable"
        for path in [project, original, staging, writable]:
            path.mkdir(parents=True)
        session = pi_safe.Session("unit", project, root, original, staging, writable, root / pi_safe.PROFILE)

        args = pi_safe.pi_launch_args(session, "/opt/homebrew/bin/pi", ["review this"])

        self.assertEqual(args[0], "/opt/homebrew/bin/pi")
        self.assertEqual(args[1], "--extension")
        self.assertEqual(args[2], str(writable / "pi-agent" / "extensions" / "pi-safe-status" / "src" / "index.ts"))
        self.assertEqual(args[3:], ["review this"])

    def test_apply_guard_blocks_symlink_changes(self):
        root = ROOT / "tmp" / f"pi-safe-symlink-{uuid.uuid4().hex}"
        project = root / "project"
        original = root / "original"
        staging = root / "staging"
        writable = root / "writable"
        for path in [project, original, staging, writable]:
            path.mkdir(parents=True)
        (original / "link").symlink_to("/tmp/outside")
        (staging / "link").symlink_to("/tmp/other")
        session = pi_safe.Session("unit", project, root, original, staging, writable, root / pi_safe.PROFILE)
        changes = pi_safe.change_set(original, staging)
        hazards = pi_safe.guard_apply(session, changes, allow_symlinks=False)
        self.assertTrue(any("symlink" in h for h in hazards))


if __name__ == "__main__":
    unittest.main()
