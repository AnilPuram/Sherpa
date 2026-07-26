import json
from pathlib import Path

import pytest

from sherpa.config import Settings
from sherpa.types import (
    BrowserObservation,
    DomChange,
    DomSnapshot,
    ModelResult,
    ModelUsage,
    PlannerAction,
    VerificationResult,
)
from sherpa.webvoyager import (
    evaluate_webvoyager,
    load_webvoyager_tasks,
    rescore_webvoyager_report,
)


def write_manifest(path: Path, count: int = 3) -> Path:
    cases = [
        {
            "web_name": f"Site {number}",
            "id": f"Site--{number}",
            "ques": f"Find answer {number}",
            "web": f"https://example.com/{number}",
        }
        for number in range(count)
    ]
    path.write_text("\n".join(json.dumps(case) for case in cases), encoding="utf-8")
    return path


class DoneModels:
    calls = 0

    async def plan(self, **_: object) -> ModelResult:
        self.calls += 1
        return ModelResult(
            value=PlannerAction(action="done", value=f"answer {self.calls}"),
            model="planner",
            latency_ms=5,
            usage=ModelUsage(input_tokens=10, output_tokens=2, cost_usd=0.6),
            model_attempts=2,
            protocol_retry=True,
            finish_reason="stop",
            protocol_error_category="invalid_json",
        )

    async def ground(self, **_: object) -> ModelResult:
        raise AssertionError("done must not call the grounder")

    async def verify(self, **_: object) -> ModelResult:
        return ModelResult(
            value=VerificationResult(accepted=True, reason="Answer is visible"),
            model="planner",
            latency_ms=1,
            finish_reason="stop",
        )


class FakeBrowser:
    created_kwargs: list[dict[str, object]] = []

    def __init__(self, viewport: object, **kwargs: object) -> None:
        self.viewport = viewport
        self.blocked_requests: list[dict[str, str]] = []
        self.created_kwargs.append(kwargs)

    async def __aenter__(self) -> "FakeBrowser":
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def navigate(self, _: str) -> None:
        return None

    async def screenshot(self, _: Path | None = None) -> bytes:
        return b"image"

    async def observe(
        self,
        previous: BrowserObservation | None = None,
        path: Path | None = None,
    ) -> BrowserObservation:
        del previous, path
        return BrowserObservation(
            screenshot=b"image",
            screenshot_fingerprint="image",
            dom=DomSnapshot(fingerprint="dom"),
            change=DomChange(page_changed=True),
            url="https://example.com",
        )

    async def execute(self, *_: object) -> None:
        raise AssertionError("done must not execute a browser action")


def test_manifest_rejects_duplicate_ids(tmp_path: Path) -> None:
    manifest = write_manifest(tmp_path / "tasks.jsonl", count=1)
    line = manifest.read_text(encoding="utf-8")
    manifest.write_text(f"{line}\n{line}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Duplicate"):
        load_webvoyager_tasks(manifest)


@pytest.mark.asyncio
async def test_offline_mode_validates_without_models_or_cost(tmp_path: Path) -> None:
    report = await evaluate_webvoyager(
        write_manifest(tmp_path / "tasks.jsonl"),
        real_model=False,
        output=tmp_path / "report.json",
    )

    assert report["mode"] == "offline"
    assert report["manifest_cases"] == 3
    assert report["attempted"] == 0
    assert report["cost_usd"] == 0
    assert report["success_rate"] is None
    assert json.loads((tmp_path / "report.json").read_text()) == report


@pytest.mark.asyncio
async def test_live_mode_aggregates_results_and_stops_before_next_task(tmp_path: Path) -> None:
    models = DoneModels()
    FakeBrowser.created_kwargs.clear()
    report = await evaluate_webvoyager(
        write_manifest(tmp_path / "tasks.jsonl"),
        real_model=True,
        settings=Settings(api_key=None, planner_model="planner", grounder_model="grounder"),
        artifacts=tmp_path / "artifacts",
        max_cost_usd=1.0,
        verdicts={"Site--0": "pass", "Site--1": "fail", "Site--2": "pass"},
        models=models,
        browser_factory=FakeBrowser,  # type: ignore[arg-type]
    )

    assert models.calls == 2
    assert report["mode"] == "live"
    assert report["attempted"] == 2
    assert report["completed"] == 2
    assert report["completion_rate"] == 1
    assert report["success_rate"] == 0.5
    assert report["cost_usd"] == 1.2
    assert report["stopped_for_cost"] is True
    assert report["cost_overshoot_usd"] == pytest.approx(0.2)
    assert report["access_policy"] == "http_read_only"
    assert report["dom_context_modes"] == {"full": 2}
    assert report["planner_input_tokens_per_step_mean"] == 10
    assert report["model_attempts"] == 6
    assert report["protocol_retry_steps"] == 2
    assert report["protocol_error_counts"] == {"invalid_json": 2}
    assert report["finish_reason_counts"] == {"stop": 2}
    assert all(kwargs["read_only"] is True for kwargs in FakeBrowser.created_kwargs)
    assert (tmp_path / "artifacts" / "Site--0" / "result.json").exists()


@pytest.mark.asyncio
async def test_allow_write_constructs_unrestricted_browser(tmp_path: Path) -> None:
    FakeBrowser.created_kwargs.clear()
    report = await evaluate_webvoyager(
        write_manifest(tmp_path / "tasks.jsonl", count=1),
        real_model=True,
        settings=Settings(api_key=None, planner_model="planner", grounder_model="grounder"),
        models=DoneModels(),
        browser_factory=FakeBrowser,  # type: ignore[arg-type]
        allow_write=True,
        max_steps=7,
        max_corrections=2,
    )

    assert FakeBrowser.created_kwargs[0]["read_only"] is False
    assert report["access_policy"] == "unrestricted"
    assert report["max_steps"] == 7
    assert report["max_corrections"] == 2


def test_report_can_be_rescored_without_paid_rerun(tmp_path: Path) -> None:
    report_path = tmp_path / "report.json"
    output = tmp_path / "rescored.json"
    report_path.write_text(
        json.dumps(
            {
                "results": [
                    {"id": "one", "verdict": "unreviewed"},
                    {"id": "two", "verdict": "unreviewed"},
                ]
            }
        )
    )

    rescored = rescore_webvoyager_report(
        report_path,
        {"one": "pass", "two": "fail"},
        output=output,
    )

    assert rescored["success_rate"] == 0.5
    assert json.loads(output.read_text()) == rescored
