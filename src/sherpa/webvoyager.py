import json
import re
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field

from sherpa.agent import Agent, Models
from sherpa.browser import Browser
from sherpa.config import Settings
from sherpa.models import OpenRouterClient
from sherpa.runlog import RunLog
from sherpa.types import AgentRunResult, Dimensions, ModelUsage

Verdict = Literal["pass", "fail", "uncertain", "unreviewed"]
AccessPolicy = Literal["http_read_only", "unrestricted"]
BrowserFactory = Callable[..., Browser]


class WebVoyagerTask(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    web_name: str
    id: str
    ques: str
    web: str


class WebVoyagerTaskResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    web_name: str
    task: str
    url: str
    outcome: str
    answer: str | None = None
    steps: int = 0
    latency_ms: int = 0
    usage: ModelUsage = ModelUsage()
    access_policy: AccessPolicy = "http_read_only"
    max_steps: int = 20
    max_corrections: int = 5
    blocked_requests: list[dict[str, str]] = Field(default_factory=list)
    failure_counts: dict[str, int] = Field(default_factory=dict)
    dom_truncation_steps: int = 0
    dom_fallback_steps: int = 0
    dom_controls_truncation_steps: int = 0
    dom_content_truncation_steps: int = 0
    dom_context_modes: dict[str, int] = Field(default_factory=dict)
    dom_raw_controls: int = 0
    dom_retained_controls: int = 0
    dom_control_chars: int = 0
    dom_content_chars: int = 0
    dom_diff_chars: int = 0
    dom_context_char_samples: list[int] = Field(default_factory=list)
    planner_input_token_samples: list[int] = Field(default_factory=list)
    model_attempts: int = 0
    protocol_retry_steps: int = 0
    protocol_error_counts: dict[str, int] = Field(default_factory=dict)
    finish_reason_counts: dict[str, int] = Field(default_factory=dict)
    error: str | None = None
    verdict: Verdict = "unreviewed"


def load_webvoyager_tasks(manifest: Path) -> list[WebVoyagerTask]:
    tasks: list[WebVoyagerTask] = []
    seen: set[str] = set()
    for number, line in enumerate(manifest.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            task = WebVoyagerTask.model_validate_json(line)
        except ValueError as exc:
            raise ValueError(f"Invalid WebVoyager manifest line {number}: {exc}") from exc
        if task.id in seen:
            raise ValueError(f"Duplicate WebVoyager task id: {task.id}")
        parsed = urlparse(task.web)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError(f"Invalid WebVoyager task URL for {task.id}: {task.web}")
        if not task.ques.strip() or not task.web_name.strip():
            raise ValueError(f"Blank WebVoyager task field on line {number}")
        seen.add(task.id)
        tasks.append(task)
    if not tasks:
        raise ValueError("WebVoyager manifest is empty")
    return tasks


def load_verdicts(path: Path | None) -> dict[str, Verdict]:
    if path is None:
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("WebVoyager judgments must be a JSON object keyed by task id")
    verdicts: dict[str, Verdict] = {}
    allowed = {"pass", "fail", "uncertain"}
    for task_id, verdict in raw.items():
        if not isinstance(task_id, str) or verdict not in allowed:
            raise ValueError(f"Invalid WebVoyager judgment: {task_id!r}={verdict!r}")
        verdicts[task_id] = verdict
    return verdicts


async def evaluate_webvoyager(
    manifest: Path,
    *,
    real_model: bool,
    settings: Settings | None = None,
    output: Path | None = None,
    artifacts: Path | None = None,
    max_cost_usd: float = 1.0,
    headed: bool = False,
    verdicts: Mapping[str, Verdict] | None = None,
    models: Models | None = None,
    browser_factory: BrowserFactory = Browser,
    allow_write: bool = True,
    max_steps: int | None = None,
    max_corrections: int | None = None,
) -> dict[str, Any]:
    tasks = load_webvoyager_tasks(manifest)
    if max_cost_usd <= 0:
        raise ValueError("max_cost_usd must be greater than zero")
    active_settings = settings or Settings.from_env()
    effective_steps = max_steps or active_settings.max_steps
    effective_corrections = max_corrections or active_settings.max_corrections
    if effective_steps <= 0:
        raise ValueError("max_steps must be greater than zero")
    if effective_corrections <= 0:
        raise ValueError("max_corrections must be greater than zero")
    access_policy: AccessPolicy = "unrestricted" if allow_write else "http_read_only"
    if not real_model:
        report = _summarize(
            tasks,
            [],
            mode="offline",
            max_cost_usd=max_cost_usd,
            access_policy=access_policy,
            max_steps=effective_steps,
            max_corrections=effective_corrections,
            planner_reasoning_effort=active_settings.planner_reasoning_effort,
        )
        _write_report(report, output)
        return report

    active_models = models or OpenRouterClient(active_settings)
    viewport = Dimensions(
        width=active_settings.viewport_width,
        height=active_settings.viewport_height,
    )
    results: list[WebVoyagerTaskResult] = []
    total_cost = 0.0
    verdict_map = verdicts or {}

    for task in tasks:
        if total_cost >= max_cost_usd:
            break
        task_dir = artifacts / _safe_id(task.id) if artifacts else None
        try:
            async with browser_factory(
                viewport,
                headed=headed,
                read_only=not allow_write,
            ) as browser:
                run = await Agent(
                    browser,
                    active_models,
                    max_steps=effective_steps,
                    max_corrections=effective_corrections,
                    run_log=RunLog(task_dir / "steps.jsonl" if task_dir else None),
                    screenshot_dir=task_dir,
                ).run(task.ques, task.web)
                result = _task_result(
                    task,
                    run,
                    browser.blocked_requests,
                    verdict_map,
                    access_policy=access_policy,
                    max_steps=effective_steps,
                    max_corrections=effective_corrections,
                    step_metrics=_step_metrics(task_dir / "steps.jsonl" if task_dir else None),
                )
        except Exception as exc:
            result = WebVoyagerTaskResult(
                id=task.id,
                web_name=task.web_name,
                task=task.ques,
                url=task.web,
                outcome="error",
                error=f"{type(exc).__name__}: {exc}",
                verdict=verdict_map.get(task.id, "unreviewed"),
                access_policy=access_policy,
                max_steps=effective_steps,
                max_corrections=effective_corrections,
            )
        results.append(result)
        total_cost += result.usage.cost_usd
        if task_dir:
            _write_json(task_dir / "result.json", result.model_dump(mode="json"))

    report = _summarize(
        tasks,
        results,
        mode="live",
        max_cost_usd=max_cost_usd,
        planner_model=active_settings.planner_model,
        grounder_model=active_settings.grounder_model,
        access_policy=access_policy,
        max_steps=effective_steps,
        max_corrections=effective_corrections,
        planner_reasoning_effort=active_settings.planner_reasoning_effort,
    )
    _write_report(report, output)
    return report


def _task_result(
    task: WebVoyagerTask,
    run: AgentRunResult,
    blocked_requests: list[dict[str, str]],
    verdicts: Mapping[str, Verdict],
    *,
    access_policy: AccessPolicy,
    max_steps: int,
    max_corrections: int,
    step_metrics: dict[str, Any],
) -> WebVoyagerTaskResult:
    return WebVoyagerTaskResult(
        id=task.id,
        web_name=task.web_name,
        task=task.ques,
        url=task.web,
        outcome=run.outcome,
        answer=run.answer,
        steps=run.steps,
        latency_ms=run.latency_ms,
        usage=run.usage,
        access_policy=access_policy,
        max_steps=max_steps,
        max_corrections=max_corrections,
        blocked_requests=blocked_requests,
        failure_counts=step_metrics["failure_counts"],
        dom_truncation_steps=step_metrics["dom_truncation_steps"],
        dom_fallback_steps=step_metrics["dom_fallback_steps"],
        dom_controls_truncation_steps=step_metrics["dom_controls_truncation_steps"],
        dom_content_truncation_steps=step_metrics["dom_content_truncation_steps"],
        dom_context_modes=step_metrics["dom_context_modes"],
        dom_raw_controls=step_metrics["dom_raw_controls"],
        dom_retained_controls=step_metrics["dom_retained_controls"],
        dom_control_chars=step_metrics["dom_control_chars"],
        dom_content_chars=step_metrics["dom_content_chars"],
        dom_diff_chars=step_metrics["dom_diff_chars"],
        dom_context_char_samples=step_metrics["dom_context_char_samples"],
        planner_input_token_samples=step_metrics["planner_input_token_samples"],
        model_attempts=step_metrics["model_attempts"],
        protocol_retry_steps=step_metrics["protocol_retry_steps"],
        protocol_error_counts=step_metrics["protocol_error_counts"],
        finish_reason_counts=step_metrics["finish_reason_counts"],
        verdict=verdicts.get(task.id, "unreviewed"),
    )


def _summarize(
    tasks: list[WebVoyagerTask],
    results: list[WebVoyagerTaskResult],
    *,
    mode: str,
    max_cost_usd: float,
    planner_model: str | None = None,
    grounder_model: str | None = None,
    access_policy: AccessPolicy = "http_read_only",
    max_steps: int = 20,
    max_corrections: int = 5,
    planner_reasoning_effort: str = "high",
) -> dict[str, Any]:
    attempted = len(results)
    completed = sum(result.outcome == "done" for result in results)
    passes = sum(result.verdict == "pass" for result in results)
    failures = sum(result.verdict == "fail" for result in results)
    uncertain = sum(result.verdict == "uncertain" for result in results)
    unreviewed = sum(result.verdict == "unreviewed" for result in results)
    total_usage = ModelUsage(
        input_tokens=sum(result.usage.input_tokens for result in results),
        output_tokens=sum(result.usage.output_tokens for result in results),
        cost_usd=sum(result.usage.cost_usd for result in results),
    )
    success_rate = passes / attempted if attempted and not unreviewed else None
    failure_counts: dict[str, int] = {}
    for result in results:
        for name, count in result.failure_counts.items():
            failure_counts[name] = failure_counts.get(name, 0) + count
    cost_overshoot = max(0.0, total_usage.cost_usd - max_cost_usd)
    context_samples = [
        sample for result in results for sample in result.dom_context_char_samples
    ]
    planner_token_samples = [
        sample for result in results for sample in result.planner_input_token_samples
    ]
    context_modes: dict[str, int] = {}
    protocol_error_counts: dict[str, int] = {}
    finish_reason_counts: dict[str, int] = {}
    for result in results:
        for context_mode, count in result.dom_context_modes.items():
            context_modes[context_mode] = context_modes.get(context_mode, 0) + count
        for category, count in result.protocol_error_counts.items():
            protocol_error_counts[category] = protocol_error_counts.get(category, 0) + count
        for reason, count in result.finish_reason_counts.items():
            finish_reason_counts[reason] = finish_reason_counts.get(reason, 0) + count
    return {
        "mode": mode,
        "manifest_cases": len(tasks),
        "websites": sorted({task.web_name for task in tasks}),
        "attempted": attempted,
        "completed": completed,
        "completion_rate": completed / attempted if attempted else 0.0,
        "passes": passes,
        "failures": failures,
        "uncertain": uncertain,
        "unreviewed": unreviewed,
        "success_rate": success_rate,
        "latency_ms": sum(result.latency_ms for result in results),
        "input_tokens": total_usage.input_tokens,
        "output_tokens": total_usage.output_tokens,
        "cost_usd": round(total_usage.cost_usd, 8),
        "max_cost_usd": max_cost_usd,
        "cost_overshoot_usd": round(cost_overshoot, 8),
        "stopped_for_cost": attempted < len(tasks) and total_usage.cost_usd >= max_cost_usd,
        "access_policy": access_policy,
        "max_steps": max_steps,
        "max_corrections": max_corrections,
        "failure_counts": failure_counts,
        "dom_truncation_steps": sum(result.dom_truncation_steps for result in results),
        "dom_fallback_steps": sum(result.dom_fallback_steps for result in results),
        "dom_controls_truncation_steps": sum(
            result.dom_controls_truncation_steps for result in results
        ),
        "dom_content_truncation_steps": sum(
            result.dom_content_truncation_steps for result in results
        ),
        "dom_context_modes": context_modes,
        "dom_raw_controls": sum(result.dom_raw_controls for result in results),
        "dom_retained_controls": sum(result.dom_retained_controls for result in results),
        "dom_control_chars": sum(result.dom_control_chars for result in results),
        "dom_content_chars": sum(result.dom_content_chars for result in results),
        "dom_diff_chars": sum(result.dom_diff_chars for result in results),
        "dom_context_chars_mean": (
            round(sum(context_samples) / len(context_samples), 2) if context_samples else 0
        ),
        "dom_context_chars_p95": _percentile(context_samples, 0.95),
        "planner_input_tokens_per_step_mean": (
            round(sum(planner_token_samples) / len(planner_token_samples), 2)
            if planner_token_samples
            else 0
        ),
        "model_attempts": sum(result.model_attempts for result in results),
        "protocol_retry_steps": sum(result.protocol_retry_steps for result in results),
        "protocol_error_counts": protocol_error_counts,
        "finish_reason_counts": finish_reason_counts,
        "planner_model": planner_model,
        "grounder_model": grounder_model,
        "planner_reasoning_effort": planner_reasoning_effort,
        "results": [result.model_dump(mode="json") for result in results],
    }


def _safe_id(task_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", task_id)


def _step_metrics(path: Path | None) -> dict[str, Any]:
    metrics: dict[str, Any] = {
        "failure_counts": {},
        "dom_truncation_steps": 0,
        "dom_fallback_steps": 0,
        "dom_controls_truncation_steps": 0,
        "dom_content_truncation_steps": 0,
        "dom_context_modes": {},
        "dom_raw_controls": 0,
        "dom_retained_controls": 0,
        "dom_control_chars": 0,
        "dom_content_chars": 0,
        "dom_diff_chars": 0,
        "dom_context_char_samples": [],
        "planner_input_token_samples": [],
        "model_attempts": 0,
        "protocol_retry_steps": 0,
        "protocol_error_counts": {},
        "finish_reason_counts": {},
    }
    if path is None or not path.exists():
        return metrics
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        outcome = str(record.get("outcome", "unknown"))
        if outcome not in {"executed", "done", "memorized"}:
            counts = metrics["failure_counts"]
            counts[outcome] = counts.get(outcome, 0) + 1
        if record.get("dom_truncated"):
            metrics["dom_truncation_steps"] += 1
        if record.get("dom_error"):
            metrics["dom_fallback_steps"] += 1
        if record.get("dom_controls_truncated"):
            metrics["dom_controls_truncation_steps"] += 1
        if record.get("dom_content_truncated"):
            metrics["dom_content_truncation_steps"] += 1
        mode = record.get("dom_context_mode")
        if mode:
            modes = metrics["dom_context_modes"]
            modes[mode] = modes.get(mode, 0) + 1
        metrics["dom_raw_controls"] += int(record.get("dom_raw_controls") or 0)
        metrics["dom_retained_controls"] += int(record.get("dom_controls") or 0)
        metrics["dom_control_chars"] += int(record.get("dom_control_chars") or 0)
        metrics["dom_content_chars"] += int(record.get("dom_content_chars") or 0)
        metrics["dom_diff_chars"] += int(record.get("dom_diff_chars") or 0)
        metrics["dom_context_char_samples"].append(int(record.get("dom_context_chars") or 0))
        metrics["planner_input_token_samples"].append(
            int(record.get("planner_input_tokens") or 0)
        )
        metrics["model_attempts"] += int(record.get("model_attempts") or 1)
        if record.get("protocol_retry"):
            metrics["protocol_retry_steps"] += 1
        for category in _split_diagnostics(record.get("protocol_error_category")):
            counts = metrics["protocol_error_counts"]
            counts[category] = counts.get(category, 0) + 1
        for reason in _split_diagnostics(record.get("finish_reason")):
            counts = metrics["finish_reason_counts"]
            counts[reason] = counts.get(reason, 0) + 1
    return metrics


def _split_diagnostics(value: object) -> list[str]:
    return [part.strip() for part in str(value or "").split(",") if part.strip()]


def _percentile(values: list[int], percentile: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int((len(ordered) - 1) * percentile + 0.5)))
    return ordered[index]


def rescore_webvoyager_report(
    report_path: Path,
    verdicts: Mapping[str, Verdict],
    *,
    output: Path | None = None,
) -> dict[str, Any]:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    results = report.get("results")
    if not isinstance(results, list):
        raise ValueError("WebVoyager report has no results list")
    result_ids = {item.get("id") for item in results if isinstance(item, dict)}
    missing = sorted(str(task_id) for task_id in result_ids if task_id not in verdicts)
    if missing:
        raise ValueError(f"Missing judgments for: {', '.join(missing)}")
    for item in results:
        if isinstance(item, dict):
            item["verdict"] = verdicts[str(item["id"])]
    attempted = len(results)
    report["passes"] = sum(item.get("verdict") == "pass" for item in results)
    report["failures"] = sum(item.get("verdict") == "fail" for item in results)
    report["uncertain"] = sum(item.get("verdict") == "uncertain" for item in results)
    report["unreviewed"] = sum(item.get("verdict") == "unreviewed" for item in results)
    report["success_rate"] = report["passes"] / attempted if attempted else None
    _write_report(report, output)
    return report


def _write_report(report: dict[str, Any], output: Path | None) -> None:
    if output:
        _write_json(output, report)


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
