import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

# insert the hooks directory into sys.path using Path(__file__).resolve().parents[1] / "connector-template" / "hooks"
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "connector-template" / "hooks"))

from center_guard import DENY_MESSAGE, main


class TestCenterGuard(unittest.TestCase):
    def run_guard(self, payload, cwd=None, now=1000.0, extra_env=None):
        if cwd is not None and isinstance(payload, dict) and "cwd" not in payload:
            payload["cwd"] = str(cwd)
        raw_input = json.dumps(payload) if not isinstance(payload, str) else payload
        stdin = io.StringIO(raw_input)
        stderr = io.StringIO()

        saved_env = dict(os.environ)
        try:
            if extra_env is not None:
                os.environ.update(extra_env)
            else:
                os.environ.pop("CLAUDE_PROJECT_DIR", None)
            code = main(argv=[], stdin=stdin, stderr=stderr, now=now)
            return code, stderr.getvalue()
        finally:
            os.environ.clear()
            os.environ.update(saved_env)

    def test_guarded_edit_inside_scope_denied(self):
        """Guarded edit inside scope denied (exit 2, message mentions connector.py)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            proj = Path(tmpdir)
            config = {"context_scope": ["src", "tests"]}
            (proj / "project.config.json").write_text(json.dumps(config), encoding="utf-8")
            (proj / "src").mkdir()
            target = proj / "src" / "app.py"
            target.write_text("# code", encoding="utf-8")

            payload = {
                "tool_name": "Edit",
                "tool_input": {"file_path": str(target)},
                "cwd": str(proj),
            }
            code, stderr = self.run_guard(payload, now=1000.0)
            self.assertEqual(code, 2)
            self.assertIn("connector.py", stderr)
            self.assertIn(DENY_MESSAGE, stderr)

    def test_same_edit_outside_scope_allowed(self):
        """The same edit outside the scope allowed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            proj = Path(tmpdir)
            config = {"context_scope": ["src", "tests"]}
            (proj / "project.config.json").write_text(json.dumps(config), encoding="utf-8")
            (proj / "docs").mkdir()
            target = proj / "docs" / "readme.md"
            target.write_text("# docs", encoding="utf-8")

            payload = {
                "tool_name": "Edit",
                "tool_input": {"file_path": str(target)},
                "cwd": str(proj),
            }
            code, stderr = self.run_guard(payload, now=1000.0)
            self.assertEqual(code, 0)
            self.assertEqual(stderr, "")

            # Also verify editing a root-level file outside every scope entry
            root_file = proj / "config.txt"
            root_file.write_text("setting=1", encoding="utf-8")
            payload = {
                "tool_name": "Edit",
                "tool_input": {"file_path": str(root_file)},
                "cwd": str(proj),
            }
            code, stderr = self.run_guard(payload, now=1000.0)
            self.assertEqual(code, 0)
            self.assertEqual(stderr, "")

    def test_each_guarded_tool_write(self):
        """Guarded tool: Write inside scope denied, outside allowed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            proj = Path(tmpdir)
            config = {"context_scope": ["src"]}
            (proj / "project.config.json").write_text(json.dumps(config), encoding="utf-8")
            (proj / "src").mkdir()

            # Write inside scope -> denied (exit 2)
            payload = {
                "tool_name": "Write",
                "tool_input": {"file_path": str(proj / "src" / "new_module.py")},
                "cwd": str(proj),
            }
            code, stderr = self.run_guard(payload, now=1000.0)
            self.assertEqual(code, 2)
            self.assertIn("connector.py", stderr)

            # Write outside scope -> allowed (exit 0)
            payload = {
                "tool_name": "Write",
                "tool_input": {"file_path": str(proj / "build.log")},
                "cwd": str(proj),
            }
            code, stderr = self.run_guard(payload, now=1000.0)
            self.assertEqual(code, 0)
            self.assertEqual(stderr, "")

    def test_each_guarded_tool_multiedit(self):
        """Guarded tool: MultiEdit inside scope denied, outside allowed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            proj = Path(tmpdir)
            config = {"context_scope": ["src"]}
            (proj / "project.config.json").write_text(json.dumps(config), encoding="utf-8")
            (proj / "src").mkdir()

            # MultiEdit inside scope -> denied (exit 2)
            payload = {
                "tool_name": "MultiEdit",
                "tool_input": {"file_path": str(proj / "src" / "existing.py")},
                "cwd": str(proj),
            }
            code, stderr = self.run_guard(payload, now=1000.0)
            self.assertEqual(code, 2)
            self.assertIn("connector.py", stderr)

            # MultiEdit outside scope -> allowed (exit 0)
            payload = {
                "tool_name": "MultiEdit",
                "tool_input": {"file_path": str(proj / "scratch.txt")},
                "cwd": str(proj),
            }
            code, stderr = self.run_guard(payload, now=1000.0)
            self.assertEqual(code, 0)
            self.assertEqual(stderr, "")

    def test_each_guarded_tool_notebookedit(self):
        """Guarded tool: NotebookEdit inside scope denied (notebook_path), outside allowed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            proj = Path(tmpdir)
            config = {"context_scope": ["notebooks"]}
            (proj / "project.config.json").write_text(json.dumps(config), encoding="utf-8")
            (proj / "notebooks").mkdir()

            # NotebookEdit inside scope -> denied (exit 2)
            payload = {
                "tool_name": "NotebookEdit",
                "tool_input": {"notebook_path": str(proj / "notebooks" / "pipeline.ipynb")},
                "cwd": str(proj),
            }
            code, stderr = self.run_guard(payload, now=1000.0)
            self.assertEqual(code, 2)
            self.assertIn("connector.py", stderr)

            # NotebookEdit outside scope -> allowed (exit 0)
            payload = {
                "tool_name": "NotebookEdit",
                "tool_input": {"notebook_path": str(proj / "scratch.ipynb")},
                "cwd": str(proj),
            }
            code, stderr = self.run_guard(payload, now=1000.0)
            self.assertEqual(code, 0)
            self.assertEqual(stderr, "")

    def test_read_and_bash_allowed(self):
        """Read and Bash allowed (exit 0)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            proj = Path(tmpdir)
            config = {"context_scope": ["src"]}
            (proj / "project.config.json").write_text(json.dumps(config), encoding="utf-8")
            (proj / "src").mkdir()

            # Read inside scope
            payload = {
                "tool_name": "Read",
                "tool_input": {"file_path": str(proj / "src" / "app.py")},
                "cwd": str(proj),
            }
            code, stderr = self.run_guard(payload, now=1000.0)
            self.assertEqual(code, 0)
            self.assertEqual(stderr, "")

            # Bash inside scope / project
            payload = {
                "tool_name": "Bash",
                "tool_input": {"command": "git status"},
                "cwd": str(proj),
            }
            code, stderr = self.run_guard(payload, now=1000.0)
            self.assertEqual(code, 0)
            self.assertEqual(stderr, "")

    def test_relative_path(self):
        """Relative path resolution relative to cwd."""
        with tempfile.TemporaryDirectory() as tmpdir:
            proj = Path(tmpdir)
            config = {"context_scope": ["src"]}
            (proj / "project.config.json").write_text(json.dumps(config), encoding="utf-8")
            (proj / "src").mkdir()

            # Relative path from project root into scope -> denied
            payload = {
                "tool_name": "Edit",
                "tool_input": {"file_path": "src/app.py"},
                "cwd": str(proj),
            }
            code, stderr = self.run_guard(payload, now=1000.0)
            self.assertEqual(code, 2)
            self.assertIn("connector.py", stderr)

            # Relative path from subfolder src -> denied
            payload = {
                "tool_name": "Edit",
                "tool_input": {"file_path": "app.py"},
                "cwd": str(proj / "src"),
            }
            code, stderr = self.run_guard(payload, now=1000.0)
            self.assertEqual(code, 2)
            self.assertIn("connector.py", stderr)

            # Relative path outside scope -> allowed
            payload = {
                "tool_name": "Edit",
                "tool_input": {"file_path": "notes.md"},
                "cwd": str(proj),
            }
            code, stderr = self.run_guard(payload, now=1000.0)
            self.assertEqual(code, 0)
            self.assertEqual(stderr, "")

    def test_dotdot_traversal_escapes_scope(self):
        """'..' traversal that escapes the scope is allowed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            proj = Path(tmpdir)
            config = {"context_scope": ["src"]}
            (proj / "project.config.json").write_text(json.dumps(config), encoding="utf-8")
            (proj / "src").mkdir()
            (proj / "docs").mkdir()

            # Path syntax 'src/../docs/readme.txt' escapes 'src' scope into 'docs'
            payload = {
                "tool_name": "Edit",
                "tool_input": {"file_path": "src/../docs/readme.txt"},
                "cwd": str(proj),
            }
            code, stderr = self.run_guard(payload, now=1000.0)
            self.assertEqual(code, 0)
            self.assertEqual(stderr, "")

            # cwd is 'src', traversal '../docs/readme.txt' escapes 'src' scope
            payload = {
                "tool_name": "Edit",
                "tool_input": {"file_path": "../docs/readme.txt"},
                "cwd": str(proj / "src"),
            }
            code, stderr = self.run_guard(payload, now=1000.0)
            self.assertEqual(code, 0)
            self.assertEqual(stderr, "")

    def test_target_outside_project_root(self):
        """Target outside the project root is allowed."""
        with tempfile.TemporaryDirectory() as tmp1, tempfile.TemporaryDirectory() as tmp2:
            proj = Path(tmp1)
            other = Path(tmp2)
            config = {"context_scope": ["src"]}
            (proj / "project.config.json").write_text(json.dumps(config), encoding="utf-8")
            (proj / "src").mkdir()

            # Absolute path outside root
            outside_target = other / "other_project" / "src" / "file.py"
            payload = {
                "tool_name": "Edit",
                "tool_input": {"file_path": str(outside_target)},
                "cwd": str(proj),
            }
            code, stderr = self.run_guard(payload, now=1000.0)
            self.assertEqual(code, 0)
            self.assertEqual(stderr, "")

            # Relative path escaping project root
            payload = {
                "tool_name": "Edit",
                "tool_input": {"file_path": "../../some_global_file.py"},
                "cwd": str(proj),
            }
            code, stderr = self.run_guard(payload, now=1000.0)
            self.assertEqual(code, 0)
            self.assertEqual(stderr, "")

    def test_valid_override_allows(self):
        """Valid override allows edit inside scope."""
        with tempfile.TemporaryDirectory() as tmpdir:
            proj = Path(tmpdir)
            config = {"context_scope": ["src"]}
            (proj / "project.config.json").write_text(json.dumps(config), encoding="utf-8")
            (proj / "src").mkdir()

            override = {
                "created_at": 1000.0,
                "expires_at": 2800.0,  # 30 minutes (1800s <= 14400s)
                "reason": "urgent fix",
            }
            (proj / ".center-direct-edit.json").write_text(json.dumps(override), encoding="utf-8")

            payload = {
                "tool_name": "Edit",
                "tool_input": {"file_path": str(proj / "src" / "app.py")},
                "cwd": str(proj),
            }
            code, stderr = self.run_guard(payload, now=1500.0)
            self.assertEqual(code, 0)
            self.assertEqual(stderr, "")

    def test_expired_override_denies(self):
        """Expired override denies edit inside scope."""
        with tempfile.TemporaryDirectory() as tmpdir:
            proj = Path(tmpdir)
            config = {"context_scope": ["src"]}
            (proj / "project.config.json").write_text(json.dumps(config), encoding="utf-8")
            (proj / "src").mkdir()

            # Override expired at 1200.0
            override = {
                "created_at": 1000.0,
                "expires_at": 1200.0,
            }
            (proj / ".center-direct-edit.json").write_text(json.dumps(override), encoding="utf-8")

            payload = {
                "tool_name": "Edit",
                "tool_input": {"file_path": str(proj / "src" / "app.py")},
                "cwd": str(proj),
            }
            # now = 1300.0 (past expiration)
            code, stderr = self.run_guard(payload, now=1300.0)
            self.assertEqual(code, 2)
            self.assertIn("connector.py", stderr)

            # now = 1200.0 (exact expiration: not strictly in the future)
            code, stderr = self.run_guard(payload, now=1200.0)
            self.assertEqual(code, 2)
            self.assertIn("connector.py", stderr)

    def test_override_longer_than_4_hours_denies(self):
        """Override longer than 4 hours denies edit inside scope."""
        with tempfile.TemporaryDirectory() as tmpdir:
            proj = Path(tmpdir)
            config = {"context_scope": ["src"]}
            (proj / "project.config.json").write_text(json.dumps(config), encoding="utf-8")
            (proj / "src").mkdir()

            # 4 hours + 1 second (14401 seconds)
            override = {
                "created_at": 1000.0,
                "expires_at": 1000.0 + 14401.0,
            }
            (proj / ".center-direct-edit.json").write_text(json.dumps(override), encoding="utf-8")

            payload = {
                "tool_name": "Edit",
                "tool_input": {"file_path": str(proj / "src" / "app.py")},
                "cwd": str(proj),
            }
            code, stderr = self.run_guard(payload, now=2000.0)
            self.assertEqual(code, 2)
            self.assertIn("connector.py", stderr)

            # Exactly 4 hours (14400 seconds) is allowed
            override_exact = {
                "created_at": 1000.0,
                "expires_at": 1000.0 + 14400.0,
            }
            (proj / ".center-direct-edit.json").write_text(
                json.dumps(override_exact), encoding="utf-8"
            )
            code, stderr = self.run_guard(payload, now=2000.0)
            self.assertEqual(code, 0)
            self.assertEqual(stderr, "")

    def test_malformed_override_denies(self):
        """Malformed override denies edit inside scope."""
        with tempfile.TemporaryDirectory() as tmpdir:
            proj = Path(tmpdir)
            config = {"context_scope": ["src"]}
            (proj / "project.config.json").write_text(json.dumps(config), encoding="utf-8")
            (proj / "src").mkdir()

            payload = {
                "tool_name": "Edit",
                "tool_input": {"file_path": str(proj / "src" / "app.py")},
                "cwd": str(proj),
            }

            # 1. Invalid JSON syntax
            (proj / ".center-direct-edit.json").write_text("{bad json syntax", encoding="utf-8")
            code, stderr = self.run_guard(payload, now=1000.0)
            self.assertEqual(code, 2)
            self.assertIn("connector.py", stderr)

            # 2. JSON array instead of object
            (proj / ".center-direct-edit.json").write_text("[1, 2, 3]", encoding="utf-8")
            code, stderr = self.run_guard(payload, now=1000.0)
            self.assertEqual(code, 2)
            self.assertIn("connector.py", stderr)

            # 3. Missing created_at
            (proj / ".center-direct-edit.json").write_text(
                json.dumps({"expires_at": 2000.0}), encoding="utf-8"
            )
            code, stderr = self.run_guard(payload, now=1000.0)
            self.assertEqual(code, 2)
            self.assertIn("connector.py", stderr)

            # 4. Missing expires_at
            (proj / ".center-direct-edit.json").write_text(
                json.dumps({"created_at": 1000.0}), encoding="utf-8"
            )
            code, stderr = self.run_guard(payload, now=1000.0)
            self.assertEqual(code, 2)
            self.assertIn("connector.py", stderr)

            # 5. Non-numeric expires_at
            (proj / ".center-direct-edit.json").write_text(
                json.dumps({"created_at": 1000.0, "expires_at": "2000.0"}), encoding="utf-8"
            )
            code, stderr = self.run_guard(payload, now=1000.0)
            self.assertEqual(code, 2)
            self.assertIn("connector.py", stderr)

            # 6. Boolean created_at (bool is a subclass of int in Python)
            (proj / ".center-direct-edit.json").write_text(
                json.dumps({"created_at": True, "expires_at": 2000.0}), encoding="utf-8"
            )
            code, stderr = self.run_guard(payload, now=1000.0)
            self.assertEqual(code, 2)
            self.assertIn("connector.py", stderr)

            # 7. created_at > expires_at
            (proj / ".center-direct-edit.json").write_text(
                json.dumps({"created_at": 5000.0, "expires_at": 2000.0}), encoding="utf-8"
            )
            code, stderr = self.run_guard(payload, now=1000.0)
            self.assertEqual(code, 2)
            self.assertIn("connector.py", stderr)

    def test_malformed_stdin_returns_1(self):
        """Malformed stdin returns 1 with warning on stderr."""
        # 1. Invalid JSON
        code, stderr = self.run_guard("not valid json string", now=1000.0)
        self.assertEqual(code, 1)
        self.assertIn("Warning", stderr)

        # 2. JSON array instead of object
        code, stderr = self.run_guard("[1, 2, 3]", now=1000.0)
        self.assertEqual(code, 1)
        self.assertIn("Warning", stderr)

        # 3. JSON string instead of object
        code, stderr = self.run_guard('"hello world"', now=1000.0)
        self.assertEqual(code, 1)
        self.assertIn("Warning", stderr)

        # 4. Empty stdin
        code, stderr = self.run_guard("", now=1000.0)
        self.assertEqual(code, 1)
        self.assertIn("Warning", stderr)

    def test_no_project_config_json_allows(self):
        """No project.config.json found allows edits (exit 0)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            proj = Path(tmpdir)
            (proj / "src").mkdir()
            target = proj / "src" / "app.py"

            payload = {
                "tool_name": "Edit",
                "tool_input": {"file_path": str(target)},
                "cwd": str(proj),
            }
            code, stderr = self.run_guard(payload, now=1000.0)
            self.assertEqual(code, 0)
            self.assertEqual(stderr, "")

    def test_windows_style_case_difference(self):
        """Windows-style case difference (use os.path.normcase aware assertions that also pass on Linux)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            proj = Path(tmpdir)
            config = {"context_scope": ["src"]}
            (proj / "project.config.json").write_text(json.dumps(config), encoding="utf-8")
            (proj / "src").mkdir()

            # Target path with differing case: "SRC/app.py" vs scope "src"
            target_path = str(proj / "SRC" / "app.py")
            payload = {
                "tool_name": "Edit",
                "tool_input": {"file_path": target_path},
                "cwd": str(proj),
            }
            code, stderr = self.run_guard(payload, now=1000.0)

            # os.path.normcase aware assertion:
            # On Windows, normcase maps "SRC" to "src", so target is matched in scope (denied, code 2).
            # On Linux, normcase is case-sensitive ("SRC" != "src"), so target is outside scope (allowed, code 0).
            is_case_insensitive = os.path.normcase("SRC") == os.path.normcase("src")
            if is_case_insensitive:
                self.assertEqual(code, 2)
                self.assertIn("connector.py", stderr)
            else:
                self.assertEqual(code, 0)

    def test_claude_project_dir_env_var(self):
        """CLAUDE_PROJECT_DIR environment variable sets project root when cwd is outside."""
        with tempfile.TemporaryDirectory() as tmp1, tempfile.TemporaryDirectory() as tmp2:
            proj = Path(tmp1)
            outside_cwd = Path(tmp2)
            config = {"context_scope": ["src"]}
            (proj / "project.config.json").write_text(json.dumps(config), encoding="utf-8")
            (proj / "src").mkdir()

            payload = {
                "tool_name": "Edit",
                "tool_input": {"file_path": str(proj / "src" / "app.py")},
                "cwd": str(outside_cwd),
            }
            code, stderr = self.run_guard(
                payload, now=1000.0, extra_env={"CLAUDE_PROJECT_DIR": str(proj)}
            )
            self.assertEqual(code, 2)
            self.assertIn("connector.py", stderr)

    def test_context_scope_literal_whitespace_preserved(self):
        """Preserve literal scope paths with whitespace (e.g. ' src'). Editing <root>/ src/app.py is denied, while <root>/src/app.py is allowed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            proj = Path(tmpdir)
            config = {"context_scope": [" src"]}
            (proj / "project.config.json").write_text(json.dumps(config), encoding="utf-8")
            (proj / " src").mkdir()
            (proj / "src").mkdir()

            # Target inside literal " src" scope -> denied
            inside_target = proj / " src" / "app.py"
            inside_target.write_text("# code", encoding="utf-8")
            payload = {
                "tool_name": "Edit",
                "tool_input": {"file_path": str(inside_target)},
                "cwd": str(proj),
            }
            code, stderr = self.run_guard(payload, now=1000.0)
            self.assertEqual(code, 2)
            self.assertIn("connector.py", stderr)

            # Target in "src" (which is not in context_scope [" src"]) -> allowed
            outside_target = proj / "src" / "app.py"
            outside_target.write_text("# code", encoding="utf-8")
            payload = {
                "tool_name": "Edit",
                "tool_input": {"file_path": str(outside_target)},
                "cwd": str(proj),
            }
            code, stderr = self.run_guard(payload, now=1000.0)
            self.assertEqual(code, 0)
            self.assertEqual(stderr, "")


if __name__ == "__main__":
    unittest.main()
