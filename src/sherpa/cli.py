import argparse
import asyncio
import json
from pathlib import Path

from sherpa.agent import Agent
from sherpa.browser import Browser
from sherpa.config import Settings
from sherpa.eval import evaluate_grounding
from sherpa.models import OpenRouterClient
from sherpa.runlog import RunLog
from sherpa.types import Dimensions, GroundedPoint, ModelResult


class CenterGrounder:
    async def ground(
        self,
        *,
        description: str,
        image: bytes,
        image_size: Dimensions,
    ) -> ModelResult:
        del description, image
        return ModelResult(
            value=GroundedPoint(x=image_size.width / 2, y=image_size.height / 2),
            model="fake-center",
            latency_ms=0,
        )


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="sherpa")
    commands = root.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run", help="Run the browser agent")
    run.add_argument("task")
    run.add_argument("url")
    run.add_argument("--headed", action="store_true")
    run.add_argument("--artifacts", type=Path)
    run.add_argument("--real-model", action="store_true")

    evaluate = commands.add_parser("eval", help="Evaluate grounding fixtures")
    evaluate.add_argument("--manifest", type=Path, default=Path("eval/grounding.jsonl"))
    evaluate.add_argument("--output", type=Path)
    evaluate.add_argument("--real-model", action="store_true")
    return root


async def run_agent(args: argparse.Namespace) -> int:
    if not args.real_model:
        raise SystemExit("sherpa run requires --real-model; paid calls are never implicit")
    settings = Settings.from_env()
    models = OpenRouterClient(settings)
    viewport = Dimensions(width=settings.viewport_width, height=settings.viewport_height)
    artifact_dir: Path | None = args.artifacts
    log = RunLog(artifact_dir / "steps.jsonl" if artifact_dir else None)
    async with Browser(viewport, headed=args.headed) as browser:
        outcome = await Agent(
            browser,
            models,
            max_steps=settings.max_steps,
            max_corrections=settings.max_corrections,
            run_log=log,
            screenshot_dir=artifact_dir,
        ).run(args.task, args.url)
    print(outcome)
    return 0 if outcome == "done" else 1


async def run_eval(args: argparse.Namespace) -> int:
    settings = Settings.from_env()
    grounder = OpenRouterClient(settings) if args.real_model else CenterGrounder()
    report = await evaluate_grounding(args.manifest, grounder.ground, output=args.output)
    print(json.dumps(report, indent=2))
    return 0 if report["errors"] == 0 else 1


def main() -> None:
    args = parser().parse_args()
    handler = run_agent if args.command == "run" else run_eval
    code = asyncio.run(handler(args))
    raise SystemExit(code)
