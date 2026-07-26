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
from sherpa.webvoyager import evaluate_webvoyager, load_verdicts, rescore_webvoyager_report


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


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be greater than zero")
    return parsed


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="sherpa")
    commands = root.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run", help="Run the browser agent")
    run.add_argument("task")
    run.add_argument("url")
    run.add_argument("--headed", action="store_true")
    run.add_argument("--artifacts", type=Path)
    run.add_argument("--real-model", action="store_true")
    run.add_argument("--max-steps", type=positive_int)
    run.add_argument("--max-corrections", type=positive_int)

    evaluate = commands.add_parser("eval", help="Evaluate grounding fixtures")
    evaluate.add_argument("--manifest", type=Path, default=Path("eval/grounding.jsonl"))
    evaluate.add_argument("--output", type=Path)
    evaluate.add_argument("--real-model", action="store_true")

    webvoyager = commands.add_parser("webvoyager", help="Run the WebVoyager smoke benchmark")
    webvoyager.add_argument(
        "--manifest",
        type=Path,
        default=Path("eval/webvoyager.jsonl"),
    )
    webvoyager.add_argument("--output", type=Path)
    webvoyager.add_argument("--artifacts", type=Path)
    webvoyager.add_argument("--judgments", type=Path)
    webvoyager.add_argument("--score-report", type=Path)
    webvoyager.add_argument("--max-cost-usd", type=float, default=1.0)
    webvoyager.add_argument("--max-steps", type=positive_int)
    webvoyager.add_argument("--max-corrections", type=positive_int)
    webvoyager.add_argument("--allow-write", action="store_true")
    webvoyager.add_argument("--headed", action="store_true")
    webvoyager.add_argument("--real-model", action="store_true")
    return root


async def run_agent(args: argparse.Namespace) -> int:
    if not args.real_model:
        raise SystemExit("sherpa run requires --real-model; paid calls are never implicit")
    settings = Settings.from_env()
    max_steps = args.max_steps or settings.max_steps
    max_corrections = args.max_corrections or settings.max_corrections
    models = OpenRouterClient(settings)
    viewport = Dimensions(width=settings.viewport_width, height=settings.viewport_height)
    artifact_dir: Path | None = args.artifacts
    log = RunLog(artifact_dir / "steps.jsonl" if artifact_dir else None)
    async with Browser(viewport, headed=args.headed) as browser:
        result = await Agent(
            browser,
            models,
            max_steps=max_steps,
            max_corrections=max_corrections,
            run_log=log,
            screenshot_dir=artifact_dir,
        ).run(args.task, args.url)
    print(json.dumps(result.model_dump(mode="json"), indent=2))
    return 0 if result.outcome == "done" else 1


async def run_eval(args: argparse.Namespace) -> int:
    settings = Settings.from_env()
    grounder = OpenRouterClient(settings) if args.real_model else CenterGrounder()
    report = await evaluate_grounding(args.manifest, grounder.ground, output=args.output)
    print(json.dumps(report, indent=2))
    return 0 if report["errors"] == 0 else 1


async def run_webvoyager(args: argparse.Namespace) -> int:
    if args.score_report:
        if args.judgments is None:
            raise SystemExit("--score-report requires --judgments")
        report = rescore_webvoyager_report(
            args.score_report,
            load_verdicts(args.judgments),
            output=args.output,
        )
        print(json.dumps(report, indent=2))
        return 0
    settings = Settings.from_env()
    report = await evaluate_webvoyager(
        args.manifest,
        real_model=args.real_model,
        settings=settings,
        output=args.output,
        artifacts=args.artifacts,
        max_cost_usd=args.max_cost_usd,
        headed=args.headed,
        verdicts=load_verdicts(args.judgments),
        allow_write=args.allow_write,
        max_steps=args.max_steps or settings.max_steps,
        max_corrections=args.max_corrections or settings.max_corrections,
    )
    print(json.dumps(report, indent=2))
    return 0


def main() -> None:
    args = parser().parse_args()
    handlers = {
        "run": run_agent,
        "eval": run_eval,
        "webvoyager": run_webvoyager,
    }
    handler = handlers[args.command]
    code = asyncio.run(handler(args))
    raise SystemExit(code)
