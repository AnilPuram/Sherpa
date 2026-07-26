import sys
from pathlib import Path

BAKEOFF = Path(__file__).resolve().parents[1] / "scripts" / "bakeoff"
sys.path.insert(0, str(BAKEOFF))

from common import (  # noqa: E402
    BakeoffResult,
    build_comparison,
    empty_pending_judgments,
    load_tasks,
    safe_id,
)


def test_load_round2_tasks() -> None:
    tasks = load_tasks(Path("eval/webvoyager-round2.jsonl"))
    assert len(tasks) == 10
    assert tasks[0].id == "Apple--6"
    assert tasks[-1].id == "GitHub--12"


def test_safe_id_and_pending_judgments() -> None:
    tasks = load_tasks(Path("eval/webvoyager-round2.jsonl"))
    assert safe_id("BBC News--5") == "BBC_News--5"
    pending = empty_pending_judgments(tasks)
    assert pending["Coursera--1"] == "pending"
    assert len(pending) == 10


def test_build_comparison_counts_sherpa_baseline() -> None:
    tasks = load_tasks(Path("eval/webvoyager-round2.jsonl"))
    sherpa = {
        "Apple--6": "pass",
        "Apple--12": "fail",
        "ArXiv--2": "pass",
        "ArXiv--17": "fail",
        "BBC News--5": "fail",
        "BBC News--6": "pass",
        "Coursera--1": "pass",
        "ESPN--11": "pass",
        "GitHub--3": "pass",
        "GitHub--12": "fail",
    }
    pending = empty_pending_judgments(tasks)
    md = build_comparison(
        tasks=tasks,
        columns={"Sherpa": sherpa, "Browser Use": pending, "Magnitude": pending},
    )
    assert "| Apple--6 | pass | pending | pending |" in md
    assert "6/10 (60%)" in md


def test_result_dict_shape() -> None:
    result = BakeoffResult(
        id="Apple--6",
        agent="browser-use",
        model="qwen/qwen3.5-35b-a3b",
        answer="four",
        outcome="done",
        steps=3,
    )
    payload = result.to_dict()
    assert payload["track"] == "equal-planner"
    assert payload["cost_usd"] is None
