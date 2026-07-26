"""Shared helpers for the cross-agent round-2 bakeoff."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

Outcome = Literal["done", "failed", "max_steps", "skipped", "error"]
Verdict = Literal["pass", "fail", "uncertain", "pending"]

DEFAULT_MANIFEST = Path("eval/webvoyager-round2.jsonl")
DEFAULT_MODEL = "qwen/qwen3.5-35b-a3b"


@dataclass(frozen=True)
class BakeoffTask:
    id: str
    web_name: str
    ques: str
    web: str


@dataclass
class BakeoffResult:
    id: str
    agent: str
    model: str
    answer: str | None
    outcome: Outcome
    steps: int
    cost_usd: float | None = None
    error: str | None = None
    track: str = "equal-planner"
    artifacts: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_tasks(manifest: Path = DEFAULT_MANIFEST) -> list[BakeoffTask]:
    tasks: list[BakeoffTask] = []
    seen: set[str] = set()
    text = manifest.read_text(encoding="utf-8")
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        raw = json.loads(line)
        task = BakeoffTask(
            id=str(raw["id"]),
            web_name=str(raw["web_name"]),
            ques=str(raw["ques"]),
            web=str(raw["web"]),
        )
        if task.id in seen:
            raise ValueError(f"Duplicate task id: {task.id}")
        if not task.ques.strip() or not task.web.strip():
            raise ValueError(f"Blank task fields on line {number}")
        seen.add(task.id)
        tasks.append(task)
    if not tasks:
        raise ValueError(f"Empty bakeoff manifest: {manifest}")
    return tasks


def safe_id(task_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", task_id)


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def write_result(path: Path, result: BakeoffResult) -> None:
    write_json(path, result.to_dict())


def load_results(report_path: Path) -> list[dict[str, Any]]:
    raw = json.loads(report_path.read_text(encoding="utf-8"))
    if isinstance(raw, dict) and "results" in raw:
        results = raw["results"]
    elif isinstance(raw, list):
        results = raw
    else:
        raise ValueError(f"Unrecognized bakeoff report shape: {report_path}")
    if not isinstance(results, list):
        raise ValueError(f"Bakeoff report results must be a list: {report_path}")
    return results


def load_verdicts(path: Path) -> dict[str, Verdict]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"Judgments must be an object: {path}")
    allowed = {"pass", "fail", "uncertain", "pending"}
    out: dict[str, Verdict] = {}
    for task_id, verdict in raw.items():
        if verdict not in allowed:
            raise ValueError(f"Invalid verdict {task_id}={verdict!r}")
        out[str(task_id)] = verdict  # type: ignore[assignment]
    return out


def empty_pending_judgments(tasks: list[BakeoffTask]) -> dict[str, Verdict]:
    return {task.id: "pending" for task in tasks}


def build_comparison(
    *,
    tasks: list[BakeoffTask],
    columns: dict[str, dict[str, Verdict]],
) -> str:
    agents = list(columns.keys())
    header = "| Task | " + " | ".join(agents) + " |"
    sep = "| --- | " + " | ".join("---" for _ in agents) + " |"
    rows = [header, sep]
    totals = {agent: {"pass": 0, "fail": 0, "uncertain": 0, "pending": 0} for agent in agents}
    for task in tasks:
        cells = []
        for agent in agents:
            verdict = columns[agent].get(task.id, "pending")
            totals[agent][verdict] = totals[agent].get(verdict, 0) + 1
            cells.append(verdict)
        rows.append(f"| {task.id} | " + " | ".join(cells) + " |")
    rows.append("")
    rows.append("## Strict pass rates")
    rows.append("")
    rows.append("| Agent | Pass | Fail | Uncertain | Pending | Strict |")
    rows.append("| --- | ---: | ---: | ---: | ---: | ---: |")
    n = len(tasks)
    for agent in agents:
        p = totals[agent]["pass"]
        f = totals[agent]["fail"]
        u = totals[agent]["uncertain"]
        pend = totals[agent]["pending"]
        scored = p + f + u
        strict = f"{p}/{n} ({100 * p / n:.0f}%)" if n else "n/a"
        if scored == 0:
            strict = f"0/{n} (pending)"
        rows.append(f"| {agent} | {p} | {f} | {u} | {pend} | {strict} |")
    return "\n".join(rows) + "\n"
