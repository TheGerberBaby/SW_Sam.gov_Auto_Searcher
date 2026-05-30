"""Markdown-task-as-code parser + CLI for the Stage 1 spine.

Each file in `tasks/` is a single markdown task with YAML frontmatter
between `---` fences. The fields are documented in `tasks/README.md`.

We deliberately use a minimal stdlib-only YAML subset (scalar values,
inline arrays, no nested mappings) instead of pulling in PyYAML. This
keeps the spine functional from any agent or scheduled job without
extra installs, and the schema we use is intentionally flat.

Public surface:

    list_tasks(...) -> list[Task]
    next_unblocked(...) -> list[Task]
    validate_all() -> list[ValidationIssue]
    set_status(task_id, new_status, note=None) -> Task
    Task dataclass + ValidationIssue dataclass

CLI subcommands:

    list / show / validate / unblocked / status / next-id
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from datetime import date
from pathlib import Path
from typing import Any, Iterable

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TASKS_DIR = PROJECT_ROOT / "tasks"

VALID_STATUSES = {
    "planned", "in-progress", "blocked", "pending", "done", "dropped", "unknown",
}
VALID_PRIORITIES = {"high", "medium", "low"}
VALID_EFFORTS = {"S", "M", "L"}
VALID_TYPES = {
    "certification", "registration", "bid", "infrastructure", "research",
}
TERMINAL_STATUSES = {"done", "dropped"}


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class Task:
    id: str
    title: str
    status: str
    priority: str
    effort: str
    type: str
    dependencies: list[str]
    tags: list[str]
    owner: str
    created: str
    updated: str
    body: str
    path: Path

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["path"] = str(self.path)
        return d

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES


@dataclass
class ValidationIssue:
    task_id: str
    severity: str  # "error" | "warning"
    field: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Minimal frontmatter parser
# ---------------------------------------------------------------------------


_FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n?(.*)\Z", re.DOTALL)


def _parse_scalar(raw: str) -> Any:
    raw = raw.strip()
    if raw == "":
        return ""
    # quoted string
    if (raw.startswith('"') and raw.endswith('"')) or (raw.startswith("'") and raw.endswith("'")):
        return raw[1:-1]
    # inline array
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1].strip()
        if not inner:
            return []
        return [_parse_scalar(part) for part in _split_top_level_commas(inner)]
    # booleans
    if raw.lower() in {"true", "yes"}:
        return True
    if raw.lower() in {"false", "no"}:
        return False
    # numbers
    if re.fullmatch(r"-?\d+", raw):
        return int(raw)
    if re.fullmatch(r"-?\d+\.\d+", raw):
        return float(raw)
    return raw


def _split_top_level_commas(s: str) -> list[str]:
    parts: list[str] = []
    depth = 0
    current: list[str] = []
    for ch in s:
        if ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    if current:
        parts.append("".join(current).strip())
    return parts


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    yaml_block, body = match.group(1), match.group(2)
    fields: dict[str, Any] = {}
    for raw_line in yaml_block.splitlines():
        line = raw_line.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        fields[key.strip()] = _parse_scalar(value)
    return fields, body


def serialize_frontmatter(fields: dict[str, Any]) -> str:
    lines = ["---"]
    for key, value in fields.items():
        if isinstance(value, list):
            inner = ", ".join(str(v) for v in value)
            lines.append(f"{key}: [{inner}]")
        elif isinstance(value, bool):
            lines.append(f"{key}: {'true' if value else 'false'}")
        else:
            lines.append(f"{key}: {value}")
    lines.append("---")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Task loading
# ---------------------------------------------------------------------------


def _path_for(task_id: str) -> Path:
    return TASKS_DIR / f"{task_id}.md"


def load_task(path: Path) -> Task:
    text = path.read_text(encoding="utf-8")
    fields, body = parse_frontmatter(text)
    deps_raw = fields.get("dependencies") or []
    if isinstance(deps_raw, str):
        deps_raw = [d.strip() for d in deps_raw.split(",") if d.strip()]
    tags_raw = fields.get("tags") or []
    if isinstance(tags_raw, str):
        tags_raw = [t.strip() for t in tags_raw.split(",") if t.strip()]
    return Task(
        id=str(fields.get("id") or path.stem),
        title=str(fields.get("title") or path.stem),
        status=str(fields.get("status") or "unknown"),
        priority=str(fields.get("priority") or "medium"),
        effort=str(fields.get("effort") or "M"),
        type=str(fields.get("type") or "infrastructure"),
        dependencies=[str(d) for d in deps_raw],
        tags=[str(t) for t in tags_raw],
        owner=str(fields.get("owner") or "jeremy"),
        created=str(fields.get("created") or ""),
        updated=str(fields.get("updated") or ""),
        body=body,
        path=path,
    )


def list_tasks(
    status: str | None = None,
    tag: str | None = None,
    type_filter: str | None = None,
) -> list[Task]:
    if not TASKS_DIR.exists():
        return []
    tasks: list[Task] = []
    for path in sorted(TASKS_DIR.glob("*.md")):
        if path.name.lower() == "readme.md":
            continue
        try:
            task = load_task(path)
        except Exception as exc:  # noqa: BLE001
            print(f"WARN: failed to parse {path.name}: {exc}", file=sys.stderr)
            continue
        if status and task.status != status:
            continue
        if tag and tag not in task.tags:
            continue
        if type_filter and task.type != type_filter:
            continue
        tasks.append(task)
    return tasks


def get_task(task_id: str) -> Task | None:
    path = _path_for(task_id)
    if not path.exists():
        return None
    return load_task(path)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_all() -> list[ValidationIssue]:
    tasks = list_tasks()
    ids = {task.id for task in tasks}
    issues: list[ValidationIssue] = []
    for task in tasks:
        if task.id != task.path.stem:
            issues.append(ValidationIssue(
                task.id, "error", "id",
                f"id field {task.id!r} does not match filename stem {task.path.stem!r}",
            ))
        if task.status not in VALID_STATUSES:
            issues.append(ValidationIssue(
                task.id, "error", "status",
                f"status {task.status!r} not in {sorted(VALID_STATUSES)}",
            ))
        if task.priority not in VALID_PRIORITIES:
            issues.append(ValidationIssue(
                task.id, "warning", "priority",
                f"priority {task.priority!r} not in {sorted(VALID_PRIORITIES)}",
            ))
        if task.effort not in VALID_EFFORTS:
            issues.append(ValidationIssue(
                task.id, "warning", "effort",
                f"effort {task.effort!r} not in {sorted(VALID_EFFORTS)}",
            ))
        if task.type not in VALID_TYPES:
            issues.append(ValidationIssue(
                task.id, "warning", "type",
                f"type {task.type!r} not in {sorted(VALID_TYPES)}",
            ))
        for dep in task.dependencies:
            if dep not in ids:
                issues.append(ValidationIssue(
                    task.id, "error", "dependencies",
                    f"dependency {dep!r} does not exist",
                ))
        # Cycle detection on this task
        cycle = _find_cycle(task.id, tasks)
        if cycle:
            issues.append(ValidationIssue(
                task.id, "error", "dependencies",
                f"dependency cycle: {' -> '.join(cycle)}",
            ))
    return issues


def _find_cycle(start: str, tasks: list[Task]) -> list[str] | None:
    by_id = {t.id: t for t in tasks}
    seen: list[str] = []

    def visit(node: str) -> list[str] | None:
        if node in seen:
            return seen[seen.index(node):] + [node]
        seen.append(node)
        task = by_id.get(node)
        if task:
            for dep in task.dependencies:
                cycle = visit(dep)
                if cycle:
                    return cycle
        seen.pop()
        return None

    return visit(start)


# ---------------------------------------------------------------------------
# "Never hard-block" scheduling
# ---------------------------------------------------------------------------


def next_unblocked(limit: int = 10) -> list[Task]:
    """Return tasks whose dependencies are all `done` (or whose deps are
    missing entirely), in priority then file order. The "never hard-block"
    rule: blocked/pending/done/dropped tasks are not surfaced as
    next-actionable.
    """
    tasks = list_tasks()
    by_id = {t.id: t for t in tasks}
    actionable_states = {"planned", "in-progress", "unknown"}
    priority_rank = {"high": 0, "medium": 1, "low": 2}

    def deps_satisfied(task: Task) -> bool:
        for dep in task.dependencies:
            dep_task = by_id.get(dep)
            if dep_task is None:
                continue  # unknown dep — log via validate
            if dep_task.status != "done":
                return False
        return True

    candidates = [t for t in tasks if t.status in actionable_states and deps_satisfied(t)]
    candidates.sort(key=lambda t: (priority_rank.get(t.priority, 9), t.id))
    return candidates[:limit]


# ---------------------------------------------------------------------------
# Status mutation
# ---------------------------------------------------------------------------


def set_status(task_id: str, new_status: str, note: str | None = None) -> Task:
    if new_status not in VALID_STATUSES:
        raise ValueError(f"invalid status {new_status!r}; valid: {sorted(VALID_STATUSES)}")
    path = _path_for(task_id)
    if not path.exists():
        raise FileNotFoundError(f"no task at {path}")
    text = path.read_text(encoding="utf-8")
    fields, body = parse_frontmatter(text)
    if not fields:
        raise ValueError(f"task {task_id} has no frontmatter")
    fields["status"] = new_status
    fields["updated"] = date.today().isoformat()
    new_text = serialize_frontmatter(fields) + body
    if note:
        timestamp = date.today().isoformat()
        appendix = f"\n\n_[{timestamp}] {note}_\n"
        if not new_text.endswith("\n"):
            new_text += "\n"
        new_text += appendix
    path.write_text(new_text, encoding="utf-8")
    return load_task(path)


def next_id_after(prefix: str = "") -> str:
    nums: list[int] = []
    for path in TASKS_DIR.glob("*.md"):
        if path.name.lower() == "readme.md":
            continue
        match = re.match(r"^(\d+)-", path.stem)
        if match:
            nums.append(int(match.group(1)))
    next_num = (max(nums) + 1) if nums else 1
    return f"{next_num:03d}"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _print_table(tasks: Iterable[Task]) -> None:
    tasks = list(tasks)
    if not tasks:
        print("(no matching tasks)")
        return
    width_id = max(len(t.id) for t in tasks)
    width_status = max(len(t.status) for t in tasks)
    for task in tasks:
        deps = ",".join(task.dependencies) or "-"
        print(f"  [{task.priority[0].upper()}] {task.status:<{width_status}}  {task.id:<{width_id}}  {task.title}")
        if task.dependencies:
            print(f"      deps: {deps}")


def _cli() -> None:
    parser = argparse.ArgumentParser(description="Markdown task spine for the SW Contracting Bots project.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="List tasks (grouped by status by default).")
    p_list.add_argument("--status")
    p_list.add_argument("--tag")
    p_list.add_argument("--type", dest="type_filter")
    p_list.add_argument("--json", action="store_true")

    p_show = sub.add_parser("show", help="Print a single task.")
    p_show.add_argument("task_id")
    p_show.add_argument("--json", action="store_true")

    sub.add_parser("validate", help="Validate frontmatter across the tasks/ directory.")

    p_unb = sub.add_parser("unblocked", help="Surface next-actionable tasks per the never-hard-block rule.")
    p_unb.add_argument("--limit", type=int, default=10)
    p_unb.add_argument("--json", action="store_true")

    p_status = sub.add_parser("status", help="Update status of a task.")
    p_status.add_argument("task_id")
    p_status.add_argument("new_status", choices=sorted(VALID_STATUSES))
    p_status.add_argument("--note")

    sub.add_parser("next-id", help="Print the next numeric task id (e.g. 008).")

    args = parser.parse_args()

    if args.cmd == "list":
        tasks = list_tasks(status=args.status, tag=args.tag, type_filter=args.type_filter)
        if args.json:
            print(json.dumps([t.to_dict() for t in tasks], indent=2))
            return
        if args.status or args.tag or args.type_filter:
            _print_table(tasks)
            return
        groups: dict[str, list[Task]] = {}
        for task in tasks:
            groups.setdefault(task.status, []).append(task)
        order = ["in-progress", "planned", "blocked", "pending", "unknown", "done", "dropped"]
        for status_key in order:
            if status_key not in groups:
                continue
            print(f"\n{status_key.upper()} ({len(groups[status_key])})")
            _print_table(groups[status_key])
        for status_key, items in groups.items():
            if status_key in order:
                continue
            print(f"\n{status_key.upper()} ({len(items)})")
            _print_table(items)
        print()
    elif args.cmd == "show":
        task = get_task(args.task_id)
        if not task:
            raise SystemExit(f"no task {args.task_id!r}")
        if args.json:
            print(json.dumps(task.to_dict(), indent=2))
            return
        print(f"{task.id}  [{task.status}]  {task.title}")
        print(f"  priority={task.priority}  effort={task.effort}  type={task.type}")
        print(f"  deps={','.join(task.dependencies) or '-'}  tags={','.join(task.tags) or '-'}")
        print(f"  path={task.path}")
        print("\n" + task.body.strip())
    elif args.cmd == "validate":
        issues = validate_all()
        if not issues:
            print("✓ all task frontmatter valid")
            return
        for issue in issues:
            marker = "ERR " if issue.severity == "error" else "WARN"
            print(f"  {marker} {issue.task_id:<32} {issue.field:<14} {issue.message}")
        raise SystemExit(1 if any(i.severity == "error" for i in issues) else 0)
    elif args.cmd == "unblocked":
        tasks = next_unblocked(limit=args.limit)
        if args.json:
            print(json.dumps([t.to_dict() for t in tasks], indent=2))
            return
        if not tasks:
            print("(nothing actionable — every task is blocked, pending, or terminal)")
            return
        print(f"\nNext-actionable workstreams ({len(tasks)}):\n")
        _print_table(tasks)
        print()
    elif args.cmd == "status":
        task = set_status(args.task_id, args.new_status, note=args.note)
        print(f"{task.id} -> {task.status}")
    elif args.cmd == "next-id":
        print(next_id_after())


if __name__ == "__main__":
    _cli()
