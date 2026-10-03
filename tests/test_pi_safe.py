#!/usr/bin/env python3
import argparse
import contextlib
import io
import importlib.machinery
import pathlib
import subprocess
import uuid
import unittest
from unittest import mock


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

    def test_safe_copytree_excludes_default_heavy_directories(self):
        root = ROOT / "tmp" / f"pi-safe-copy-heavy-{uuid.uuid4().hex}"
        project = root / "project"
        dest = root / "copy"
        (project / "src").mkdir(parents=True)
        (project / ".venv" / "lib").mkdir(parents=True)
        (project / "node_modules" / "pkg").mkdir(parents=True)
        (project / "src" / "keep.py").write_text("print('keep')\n", encoding="utf-8")
        (project / ".venv" / "lib" / "skip.py").write_text("skip\n", encoding="utf-8")
        (project / "node_modules" / "pkg" / "skip.js").write_text("skip\n", encoding="utf-8")

        pi_safe.safe_copytree(project, dest, pi_safe.DEFAULT_EXCLUDES)

        self.assertTrue((dest / "src" / "keep.py").exists())
        self.assertFalse((dest / ".venv").exists())
        self.assertFalse((dest / "node_modules").exists())

    def test_project_ignore_patterns_exclude_slashed_directories(self):
        root = ROOT / "tmp" / f"pi-safe-copy-ignore-{uuid.uuid4().hex}"
        project = root / "project"
        dest = root / "copy"
        (project / "src").mkdir(parents=True)
        (project / "out").mkdir(parents=True)
        (project / "nested" / "cache").mkdir(parents=True)
        (project / "src" / "keep.py").write_text("print('keep')\n", encoding="utf-8")
        (project / "out" / "skip.wav").write_text("skip\n", encoding="utf-8")
        (project / "nested" / "cache" / "skip.txt").write_text("skip\n", encoding="utf-8")
        (project / "debug.log").write_text("skip\n", encoding="utf-8")
        (project / ".claudecodeignore").write_text(
            "# generated files\n/out/\nnested/cache/\n*.log\n!ignored-negation\n",
            encoding="utf-8",
        )

        excludes = pi_safe.DEFAULT_EXCLUDES + pi_safe.project_ignore_patterns(project)
        pi_safe.safe_copytree(project, dest, excludes)

        self.assertTrue((dest / "src" / "keep.py").exists())
        self.assertTrue((dest / ".claudecodeignore").exists())
        self.assertFalse((dest / "out").exists())
        self.assertFalse((dest / "nested" / "cache").exists())
        self.assertFalse((dest / "debug.log").exists())

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
        self.assertEqual(args[3:], ["--no-approve", "review this"])

    def test_pi_launch_args_respects_explicit_project_trust_flag(self):
        root = ROOT / "tmp" / f"pi-safe-launch-approve-{uuid.uuid4().hex}"
        project = root / "project"
        original = root / "original"
        staging = root / "staging"
        writable = root / "writable"
        for path in [project, original, staging, writable]:
            path.mkdir(parents=True)
        session = pi_safe.Session("unit", project, root, original, staging, writable, root / pi_safe.PROFILE)

        args = pi_safe.pi_launch_args(session, "/opt/homebrew/bin/pi", ["--approve", "review this"])

        self.assertIn("--extension", args)
        self.assertNotIn("--no-approve", args)
        self.assertEqual(args[-2:], ["--approve", "review this"])

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


class SessionStorageTests(unittest.TestCase):
    def setUp(self):
        self.root = ROOT / "tmp" / f"storage-{uuid.uuid4().hex}"
        self.project = self.root / "project"
        self.project.mkdir(parents=True)
        (self.project / "source.txt").write_text("original\n")
        self.safe_home = self.root / "state"
        processes = mock.patch.object(pi_safe.subprocess, "check_output", return_value="")
        processes.start()
        self.addCleanup(processes.stop)

    def session(self, name="one"):
        return pi_safe.create_session(self.project, self.safe_home, name, [], False)

    def cleanup_args(self, *names, yes=False, discard=False):
        return argparse.Namespace(safe_home=str(self.safe_home), sessions=list(names or ["one"]),
                                  yes=yes, discard_changes=discard)

    def fake_trash(self, command, **kwargs):
        self.assertEqual(command[0], "/test/trash")
        target = pathlib.Path(command[1])
        dest = self.root / "trash" / target.name
        dest.parent.mkdir(exist_ok=True)
        target.rename(dest)
        return subprocess.CompletedProcess(command, 0)

    def run_args(self, *extra):
        return pi_safe.build_parser().parse_args(["run", "--project", str(self.project),
                                                "--safe-home", str(self.safe_home), "--pi", "/test/pi", *extra])

    def test_copy_failure_is_discoverable_when_trash_unavailable(self):
        real_copy = pi_safe.safe_copytree
        calls = 0
        def fail_second(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("copy interrupted")
            return real_copy(*args, **kwargs)
        with mock.patch.object(pi_safe, "safe_copytree", side_effect=fail_second), \
             mock.patch.object(pi_safe, "find_trash", return_value=None):
            with self.assertRaisesRegex(OSError, "copy interrupted"):
                self.session()
        root = self.safe_home / "sessions" / "one"
        self.assertTrue((root / "original" / "source.txt").exists())
        self.assertEqual(pi_safe.session_data(root)["state"], "failed")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            pi_safe.list_sessions(self.safe_home)
        self.assertIn("one\t", out.getvalue())
        self.assertIn("failed", out.getvalue())

    def test_partial_copy_is_trashed_on_failure(self):
        with mock.patch.object(pi_safe, "safe_copytree", side_effect=OSError("copy interrupted")), \
             mock.patch.object(pi_safe, "find_trash", return_value="/test/trash"), \
             mock.patch.object(pi_safe.subprocess, "run", side_effect=self.fake_trash):
            with self.assertRaises(OSError):
                self.session()
        self.assertFalse((self.safe_home / "sessions" / "one").exists())
        self.assertTrue((self.root / "trash" / "one" / pi_safe.MANIFEST).exists())
        self.assertEqual((self.project / "source.txt").read_text(), "original\n")

    def test_manifest_and_lock_exist_before_first_copy(self):
        def inspect_then_interrupt(*args, **kwargs):
            root = self.safe_home / "sessions" / "one"
            self.assertEqual(pi_safe.session_data(root)["state"], "creating")
            with self.assertRaisesRegex(pi_safe.PiSafeError, "active"):
                pi_safe.cmd_cleanup(self.cleanup_args(yes=True, discard=True))
            raise KeyboardInterrupt()
        with mock.patch.object(pi_safe, "safe_copytree", side_effect=inspect_then_interrupt), \
             mock.patch.object(pi_safe, "find_trash", return_value="/test/trash"), \
             mock.patch.object(pi_safe.subprocess, "run", side_effect=self.fake_trash):
            with self.assertRaises(KeyboardInterrupt):
                self.session()
        self.assertTrue((self.root / "trash" / "one" / pi_safe.MANIFEST).exists())

    def test_unchanged_legacy_session_can_be_cleaned(self):
        session = self.session()
        data = pi_safe.session_data(session.root)
        data.pop("state")
        data.pop("pid")
        pi_safe.write_json(session.root / pi_safe.MANIFEST, data)
        with mock.patch.object(pi_safe, "find_trash", return_value="/test/trash"), \
             mock.patch.object(pi_safe.subprocess, "run", side_effect=self.fake_trash):
            pi_safe.cmd_cleanup(self.cleanup_args(yes=True))
        self.assertFalse(session.root.exists())

    def test_trash_failure_retains_failed_manifest(self):
        with mock.patch.object(pi_safe, "safe_copytree", side_effect=OSError("copy interrupted")), \
             mock.patch.object(pi_safe, "find_trash", return_value="/test/trash"), \
             mock.patch.object(pi_safe.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "trash")):
            with self.assertRaises(OSError):
                self.session()
        self.assertEqual(pi_safe.session_data(self.safe_home / "sessions" / "one")["state"], "failed")

    def test_session_list_includes_missing_and_corrupt_manifests(self):
        for name in ["missing", "corrupt"]:
            root = self.safe_home / "sessions" / name
            root.mkdir(parents=True)
            (root / "asset").write_bytes(b"x" * 1024)
        (self.safe_home / "sessions" / "corrupt" / pi_safe.MANIFEST).write_text("{")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            pi_safe.list_sessions(self.safe_home)
        self.assertIn("missing\t", out.getvalue())
        self.assertIn("corrupt\t", out.getvalue())
        self.assertIn("incomplete", out.getvalue())
        self.assertIn("Session storage:", out.getvalue())

    def test_cleanup_preview_preserves_session(self):
        session = self.session()
        with mock.patch.object(pi_safe.subprocess, "run") as trash:
            self.assertEqual(pi_safe.cmd_cleanup(self.cleanup_args()), 0)
            trash.assert_not_called()
        self.assertTrue(session.root.exists())

    def test_cleanup_only_trashes_named_session(self):
        one = self.session()
        two = self.session("two")
        with mock.patch.object(pi_safe, "find_trash", return_value="/test/trash"), \
             mock.patch.object(pi_safe.subprocess, "run", side_effect=self.fake_trash):
            self.assertEqual(pi_safe.cmd_cleanup(self.cleanup_args(yes=True)), 0)
        self.assertFalse(one.root.exists())
        self.assertTrue(two.root.exists())
        self.assertTrue((self.root / "trash" / "one" / "staging" / "source.txt").exists())
        self.assertTrue((self.project / "source.txt").exists())

    def test_cleanup_blocks_changed_session_even_with_yes(self):
        session = self.session()
        (session.staging / "source.txt").write_text("unapplied\n")
        with mock.patch.object(pi_safe.subprocess, "run") as trash:
            with self.assertRaisesRegex(pi_safe.PiSafeError, "staged changes retained"):
                pi_safe.cmd_cleanup(self.cleanup_args(yes=True))
            trash.assert_not_called()
        self.assertTrue(session.root.exists())

    def test_cleanup_can_explicitly_discard_changes(self):
        session = self.session()
        (session.staging / "source.txt").write_text("unapplied\n")
        with mock.patch.object(pi_safe, "find_trash", return_value="/test/trash"), \
             mock.patch.object(pi_safe.subprocess, "run", side_effect=self.fake_trash):
            pi_safe.cmd_cleanup(self.cleanup_args(yes=True, discard=True))
        self.assertEqual((self.root / "trash" / "one" / "staging" / "source.txt").read_text(), "unapplied\n")

    def test_cleanup_incomplete_session_requires_discard(self):
        root = self.safe_home / "sessions" / "one"
        (root / "original").mkdir(parents=True)
        with self.assertRaisesRegex(pi_safe.PiSafeError, "incomplete session"):
            pi_safe.cmd_cleanup(self.cleanup_args(yes=True))
        with mock.patch.object(pi_safe, "find_trash", return_value="/test/trash"), \
             mock.patch.object(pi_safe.subprocess, "run", side_effect=self.fake_trash):
            pi_safe.cmd_cleanup(self.cleanup_args(yes=True, discard=True))
        self.assertTrue((self.root / "trash" / "one" / "original").exists())

    def test_cleanup_never_overrides_running_session(self):
        session = self.session()
        pi_safe.set_session_state(session.root, "running")
        with self.assertRaisesRegex(pi_safe.PiSafeError, "active"):
            pi_safe.cmd_cleanup(self.cleanup_args(yes=True, discard=True))
        self.assertTrue(session.root.exists())

    def test_cleanup_blocks_live_legacy_agent(self):
        session = self.session()
        data = pi_safe.session_data(session.root)
        data.pop("state")
        data.pop("pid")
        pi_safe.write_json(session.root / pi_safe.MANIFEST, data)
        with mock.patch.object(pi_safe.subprocess, "check_output", return_value=f"pi --extension {session.writable}/extension.ts\n"):
            with self.assertRaisesRegex(pi_safe.PiSafeError, "active"):
                pi_safe.cmd_cleanup(self.cleanup_args(yes=True, discard=True))

    def test_cleanup_holds_back_when_process_check_fails(self):
        session = self.session()
        with mock.patch.object(pi_safe.subprocess, "check_output", side_effect=OSError("ps denied")):
            with self.assertRaisesRegex(pi_safe.PiSafeError, "cannot verify"):
                pi_safe.cmd_cleanup(self.cleanup_args(yes=True, discard=True))
        self.assertTrue(session.root.exists())

    def test_session_list_does_not_follow_symlink_root(self):
        self.safe_home.mkdir()
        (self.safe_home / "sessions").symlink_to(self.project, target_is_directory=True)
        with self.assertRaisesRegex(pi_safe.PiSafeError, "symlink"):
            pi_safe.list_sessions(self.safe_home)

    def test_cleanup_holds_back_locked_session(self):
        session = self.session()
        with pi_safe.session_lock(session.root):
            with self.assertRaisesRegex(pi_safe.PiSafeError, "active"):
                pi_safe.cmd_cleanup(self.cleanup_args(yes=True, discard=True))

    def test_cleanup_validates_entire_batch_before_trash(self):
        one = self.session()
        two = self.session("two")
        (two.staging / "source.txt").write_text("unapplied\n")
        with mock.patch.object(pi_safe.subprocess, "run") as trash:
            with self.assertRaises(pi_safe.PiSafeError):
                pi_safe.cmd_cleanup(self.cleanup_args("one", "two", yes=True))
            trash.assert_not_called()
        self.assertTrue(one.root.exists())

    def test_cleanup_does_not_follow_session_symlink(self):
        (self.safe_home / "sessions").mkdir(parents=True)
        (self.safe_home / "sessions" / "one").symlink_to(self.project, target_is_directory=True)
        with self.assertRaisesRegex(pi_safe.PiSafeError, "symlink"):
            pi_safe.cmd_cleanup(self.cleanup_args(yes=True, discard=True))
        self.assertTrue(self.project.exists())

    def test_session_ids_cannot_escape_sessions_root(self):
        for name in ["..", "../project", str(self.project), ".", ""]:
            with self.assertRaises(pi_safe.PiSafeError):
                pi_safe.session_root(self.safe_home, name)

    def test_cleanup_without_trash_has_no_delete_fallback(self):
        session = self.session()
        with mock.patch.object(pi_safe, "find_trash", return_value=None):
            with self.assertRaisesRegex(pi_safe.PiSafeError, "trash is unavailable"):
                pi_safe.cmd_cleanup(self.cleanup_args(yes=True))
        self.assertTrue(session.root.exists())

    def test_copy_estimate_respects_ignores_and_does_not_follow_links(self):
        (self.project / "media").mkdir()
        (self.project / "media" / "big.bin").write_bytes(b"x" * 8192)
        (self.project / "linked-media").symlink_to(self.project / "media", target_is_directory=True)
        state = self.project / ".state"
        state.mkdir()
        (state / "cached.bin").write_bytes(b"x" * 4096)
        expected = (self.project / "source.txt").stat().st_size + (self.project / "linked-media").lstat().st_size
        self.assertEqual(pi_safe.copy_size(self.project, ["media"], state), expected)

    def test_dry_run_creates_no_session_tree(self):
        with mock.patch.object(pi_safe, "create_session") as create:
            self.assertEqual(pi_safe.cmd_run(self.run_args("--dry-run")), 0)
            create.assert_not_called()
        self.assertFalse(self.safe_home.exists())

    def test_missing_pi_does_not_leave_session_copies(self):
        with mock.patch.object(pi_safe, "find_pi", side_effect=pi_safe.PiSafeError("Pi missing")):
            with self.assertRaisesRegex(pi_safe.PiSafeError, "Pi missing"):
                pi_safe.cmd_run(self.run_args())
        self.assertFalse(self.safe_home.exists())

    def test_large_copy_is_blocked_before_creating_state(self):
        with mock.patch.object(pi_safe, "COPY_WARNING_BYTES", 1):
            with self.assertRaisesRegex(pi_safe.PiSafeError, "budget exceeded"):
                pi_safe.cmd_run(self.run_args())
        self.assertFalse(self.safe_home.exists())

    def test_accumulated_storage_budget_is_enforced(self):
        session = self.session()
        with mock.patch.object(pi_safe, "STORAGE_WARNING_BYTES", 1):
            with self.assertRaisesRegex(pi_safe.PiSafeError, "budget exceeded"):
                pi_safe.cmd_run(self.run_args())
        self.assertEqual(list(session.root.parent.iterdir()), [session.root])

    def test_insufficient_space_is_blocked_before_creating_state(self):
        with mock.patch.object(pi_safe.shutil, "disk_usage", return_value=argparse.Namespace(free=0)):
            with self.assertRaisesRegex(pi_safe.PiSafeError, "insufficient free space"):
                pi_safe.cmd_run(self.run_args("--allow-large-copy"))
        self.assertFalse(self.safe_home.exists())

    def test_allow_large_copy_launches_and_retains_finished_session(self):
        with mock.patch.object(pi_safe, "COPY_WARNING_BYTES", 1), \
             mock.patch.object(pi_safe, "run_sandboxed_pi", return_value=7):
            self.assertEqual(pi_safe.cmd_run(self.run_args("--allow-large-copy", "--session", "one")), 7)
        self.assertEqual(pi_safe.session_data(self.safe_home / "sessions" / "one")["state"], "finished")

    def test_runner_failure_preserves_work_and_releases_lock(self):
        with mock.patch.object(pi_safe, "run_sandboxed_pi", side_effect=OSError("runner failed")):
            with self.assertRaises(OSError):
                pi_safe.cmd_run(self.run_args("--session", "one"))
        root = self.safe_home / "sessions" / "one"
        self.assertTrue((root / "staging" / "source.txt").exists())
        self.assertEqual(pi_safe.session_data(root)["state"], "finished")
        with pi_safe.session_lock(root):
            pass


if __name__ == "__main__":
    unittest.main()
