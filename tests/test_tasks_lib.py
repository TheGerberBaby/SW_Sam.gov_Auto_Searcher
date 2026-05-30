"""Tests for scripts/tasks_lib.py."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from textwrap import dedent


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "tasks_lib.py"
SPEC = importlib.util.spec_from_file_location("tasks_lib", MODULE_PATH)
tasks_lib = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = tasks_lib
SPEC.loader.exec_module(tasks_lib)


def write_task(dir_path: Path, task_id: str, **fields) -> Path:
    fields.setdefault("id", task_id)
    fields.setdefault("title", task_id)
    fields.setdefault("status", "planned")
    fields.setdefault("priority", "high")
    fields.setdefault("effort", "M")
    fields.setdefault("type", "infrastructure")
    fields.setdefault("dependencies", [])
    fields.setdefault("tags", [])
    fields.setdefault("owner", "jeremy")
    fields.setdefault("created", "2026-05-29")
    fields.setdefault("updated", "2026-05-29")
    path = dir_path / f"{task_id}.md"
    path.write_text(tasks_lib.serialize_frontmatter(fields) + "\n## Notes\n\n(empty)\n", encoding="utf-8")
    return path


class TasksLibTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        # Point tasks_lib at the temp directory
        self._orig = tasks_lib.TASKS_DIR
        tasks_lib.TASKS_DIR = self.dir

    def tearDown(self):
        tasks_lib.TASKS_DIR = self._orig

    def test_parse_frontmatter_inline_array(self):
        text = dedent("""\
            ---
            id: 001-foo
            title: Foo
            status: planned
            dependencies: [001-a, 001-b]
            tags: []
            ---

            body
            """)
        fields, body = tasks_lib.parse_frontmatter(text)
        self.assertEqual(fields["dependencies"], ["001-a", "001-b"])
        self.assertEqual(fields["tags"], [])
        self.assertIn("body", body)

    def test_load_and_list_tasks(self):
        write_task(self.dir, "001-foo")
        write_task(self.dir, "002-bar", status="done")
        tasks = tasks_lib.list_tasks()
        self.assertEqual([t.id for t in tasks], ["001-foo", "002-bar"])
        self.assertEqual(tasks_lib.list_tasks(status="done")[0].id, "002-bar")

    def test_unblocked_respects_dependencies(self):
        write_task(self.dir, "001-base", status="planned")
        write_task(self.dir, "002-dep", status="planned", dependencies=["001-base"])
        unblocked = tasks_lib.next_unblocked()
        self.assertEqual([t.id for t in unblocked], ["001-base"])

        # Now mark the base done
        tasks_lib.set_status("001-base", "done")
        unblocked = tasks_lib.next_unblocked()
        self.assertEqual({t.id for t in unblocked}, {"002-dep"})

    def test_unblocked_skips_blocked_and_terminal(self):
        write_task(self.dir, "001-go", status="planned")
        write_task(self.dir, "002-block", status="blocked")
        write_task(self.dir, "003-done", status="done")
        write_task(self.dir, "004-drop", status="dropped")
        ids = [t.id for t in tasks_lib.next_unblocked()]
        self.assertEqual(ids, ["001-go"])

    def test_validate_flags_missing_dep(self):
        write_task(self.dir, "001-foo", dependencies=["nonexistent"])
        issues = tasks_lib.validate_all()
        self.assertTrue(any(i.severity == "error" and "nonexistent" in i.message for i in issues))

    def test_validate_flags_cycle(self):
        write_task(self.dir, "001-a", dependencies=["002-b"])
        write_task(self.dir, "002-b", dependencies=["001-a"])
        issues = tasks_lib.validate_all()
        self.assertTrue(any(i.field == "dependencies" and "cycle" in i.message for i in issues))

    def test_validate_flags_bad_status(self):
        write_task(self.dir, "001-foo", status="bogus")
        issues = tasks_lib.validate_all()
        self.assertTrue(any(i.severity == "error" and i.field == "status" for i in issues))

    def test_set_status_updates_frontmatter_and_appends_note(self):
        write_task(self.dir, "001-foo", status="planned")
        tasks_lib.set_status("001-foo", "in-progress", note="kicking off")
        task = tasks_lib.get_task("001-foo")
        self.assertEqual(task.status, "in-progress")
        self.assertIn("kicking off", task.body)

    def test_set_status_rejects_bad_status(self):
        write_task(self.dir, "001-foo")
        with self.assertRaises(ValueError):
            tasks_lib.set_status("001-foo", "bogus")

    def test_next_id_after_picks_next_number(self):
        write_task(self.dir, "001-foo")
        write_task(self.dir, "005-bar")
        self.assertEqual(tasks_lib.next_id_after(), "006")

    def test_priority_ordering_in_unblocked(self):
        write_task(self.dir, "001-low", priority="low")
        write_task(self.dir, "002-high", priority="high")
        write_task(self.dir, "003-med", priority="medium")
        ids = [t.id for t in tasks_lib.next_unblocked()]
        self.assertEqual(ids, ["002-high", "003-med", "001-low"])


if __name__ == "__main__":
    unittest.main()
