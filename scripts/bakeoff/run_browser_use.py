#!/usr/bin/env python3
"""Run WebVoyager round-2 tasks with Browser Use (equal-planner track)."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from contextlib import suppress
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    DEFAULT_MANIFEST,
    DEFAULT_MODEL,
    BakeoffResult,
    load_tasks,
    safe_id,
    write_json,
    write_result,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument(
        "--artifacts",
        type=Path,
        default=Path("artifacts/bakeoff-browser-use-round2"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/bakeoff-browser-use-round2/report.json"),
    )
    parser.add_argument(
        "--model",
        default=os.getenv("BAKEOFF_PLANNER_MODEL", DEFAULT_MODEL),
        help="OpenRouter model id (same planner track)",
    )
    parser.add_argument("--max-steps", type=int, default=20)
    parser.add_argument("--task-id", action="append", default=None)
    parser.add_argument("--headed", action="store_true")
    parser.add_argument(
        "--real-model",
        action="store_true",
        help="Required to make paid Browser Use / OpenRouter calls",
    )
    return parser.parse_args()


def _build_task_prompt(ques: str, url: str) -> str:
    return (
        f"Start at {url}. Complete this information-retrieval task and finish with a "
        f"concise final answer only when the page evidence supports it.\n\nTask: {ques}"
    )


async def _run_one(
    *,
    task_id: str,
    ques: str,
    url: str,
    model: str,
    max_steps: int,
    headed: bool,
    task_dir: Path,
) -> BakeoffResult:
    try:
        from browser_use import Agent, BrowserSession
        from browser_use.llm.openrouter.chat import ChatOpenRouter
    except ImportError as exc:
        return BakeoffResult(
            id=task_id,
            agent="browser-use",
            model=model,
            answer=None,
            outcome="error",
            steps=0,
            error=(
                f"browser-use is not installed ({exc}). "
                "Install with: uv pip install browser-use && uv run playwright install chromium"
            ),
            artifacts=str(task_dir),
        )

    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        return BakeoffResult(
            id=task_id,
            agent="browser-use",
            model=model,
            answer=None,
            outcome="error",
            steps=0,
            error="OPENROUTER_API_KEY is not set",
            artifacts=str(task_dir),
        )

    llm = ChatOpenRouter(model=model, api_key=api_key, temperature=0.0)
    browser = BrowserSession(headless=not headed)
    agent = Agent(
        task=_build_task_prompt(ques, url),
        llm=llm,
        browser=browser,
        initial_actions=[{"navigate": {"url": url, "new_tab": False}}],
        use_vision=True,
        max_actions_per_step=1,
    )
    try:
        history = await agent.run(max_steps=max_steps)
    except Exception as exc:  # noqa: BLE001 - surface any provider/browser failure
        return BakeoffResult(
            id=task_id,
            agent="browser-use",
            model=model,
            answer=None,
            outcome="error",
            steps=0,
            error=f"{type(exc).__name__}: {exc}",
            artifacts=str(task_dir),
        )
    finally:
        close = getattr(browser, "stop", None) or getattr(browser, "close", None)
        if close is not None:
            with suppress(Exception):
                await close()

    steps = len(getattr(history, "history", []) or [])
    answer = history.final_result() if hasattr(history, "final_result") else None
    is_done = bool(history.is_done()) if hasattr(history, "is_done") else bool(answer)
    if is_done and answer:
        outcome: str = "done"
    elif steps >= max_steps:
        outcome = "max_steps"
    else:
        outcome = "failed"

    history_path = task_dir / "history.json"
    try:
        if hasattr(history, "model_dump"):
            write_json(history_path, history.model_dump(mode="json"))
        elif hasattr(history, "save_to_file"):
            history.save_to_file(str(history_path))
    except Exception as exc:  # noqa: BLE001
        (task_dir / "history_error.txt").write_text(str(exc), encoding="utf-8")

    return BakeoffResult(
        id=task_id,
        agent="browser-use",
        model=model,
        answer=answer,
        outcome=outcome,  # type: ignore[arg-type]
        steps=steps,
        cost_usd=None,
        error=None,
        track="equal-planner",
        artifacts=str(task_dir),
    )


async def _main_async(args: argparse.Namespace) -> int:
    if not args.real_model:
        raise SystemExit(
            "scripts/bakeoff/run_browser_use.py requires --real-model; "
            "paid OpenRouter calls are never implicit"
        )

    tasks = load_tasks(args.manifest)
    if args.task_id:
        wanted = set(args.task_id)
        tasks = [task for task in tasks if task.id in wanted]
        missing = wanted - {task.id for task in tasks}
        if missing:
            raise SystemExit(f"Unknown task id(s): {sorted(missing)}")

    args.artifacts.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []
    for task in tasks:
        task_dir = args.artifacts / safe_id(task.id)
        task_dir.mkdir(parents=True, exist_ok=True)
        print(f"[browser-use] {task.id}", flush=True)
        result = await _run_one(
            task_id=task.id,
            ques=task.ques,
            url=task.web,
            model=args.model,
            max_steps=args.max_steps,
            headed=args.headed,
            task_dir=task_dir,
        )
        write_result(task_dir / "result.json", result)
        results.append(result.to_dict())
        print(
            f"  outcome={result.outcome} steps={result.steps} "
            f"answer={(result.answer or '')[:120]!r}",
            flush=True,
        )

    report = {
        "agent": "browser-use",
        "track": "equal-planner",
        "model": args.model,
        "manifest": str(args.manifest),
        "max_steps": args.max_steps,
        "results": results,
    }
    write_json(args.output, report)
    print(f"Wrote {args.output}", flush=True)
    return 0


def main() -> None:
    args = _parse_args()
    raise SystemExit(asyncio.run(_main_async(args)))


if __name__ == "__main__":
    main()
