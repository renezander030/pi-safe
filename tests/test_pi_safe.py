#!/usr/bin/env python3
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
