import argparse
import asyncio
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

from sherpa.agent import Agent
from sherpa.browser import Browser
from sherpa.config import Settings
from sherpa.eval import evaluate_grounding
from sherpa.install_browser import ensure_chromium, install_chromium
from sherpa.models import OpenRouterClient
from sherpa.runlog import RunLog
from sherpa.types import Dimensions, GroundedPoint, ModelResult, StepResult
from sherpa.webvoyager import evaluate_webvoyager, load_verdicts, rescore_webvoyager_report

URL_RE = re.compile(r"https?://[^\s<>\"']+")
COMMANDS = {"run", "eval", "webvoyager", "init", "install"}


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


def extract_url(task: str) -> str | None:
    match = URL_RE.search(task)
    if match is None:
        return None
    return match.group(0).rstrip(".,);]")


def resolve_url(task: str, url: str | None) -> str:
    if url:
        return url
    found = extract_url(task)
    if found:
        return found
    raise SystemExit(
        "No start URL found. Pass --url https://… or include an http(s) URL in the task."
    )


def default_artifacts_dir() -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return Path("artifacts") / "runs" / stamp


def format_step_line(result: StepResult) -> str:
    action = result.action.value if result.action is not None else "—"
    parts = [f"step {result.step}", action, result.outcome]
    if result.target:
        parts.append(f"target={result.target[:60]}")
    if result.error_message:
        parts.append(result.error_message[:80])
    elif result.next_subgoal:
        parts.append(result.next_subgoal[:80])
    return " · ".join(parts)


def print_human_summary(
    *,
    result,
    task: str,
    url: str,
    artifacts: Path | None,
) -> None:
    print()
    print(f"Task: {task}")
    print(f"URL:  {url}")
    print(f"Outcome: {result.outcome}")
    if result.answer:
        print(f"Answer: {result.answer}")
    cost = result.usage.cost_usd
    print(f"Steps: {result.steps}  ·  ~${cost:.4f}  ·  {result.latency_ms}ms")
    if artifacts is not None:
        print(f"Artifacts: {artifacts}")


def add_task_run_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--url", help="Start URL (else taken from the task text)")
    visibility = parser.add_mutually_exclusive_group()
    visibility.add_argument(
        "--headed",
        action="store_true",
        default=None,
        help="Show the browser window (default)",
    )
    visibility.add_argument(
        "--headless",
        action="store_true",
        default=None,
        help="Hide the browser window",
    )
    parser.add_argument("--artifacts", type=Path, help="Artifact directory")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the full result JSON instead of a short summary",
    )
    parser.add_argument("--max-steps", type=positive_int)
    parser.add_argument("--max-corrections", type=positive_int)


def resolve_headed(args: argparse.Namespace) -> bool:
    if getattr(args, "headless", None):
        return False
    if getattr(args, "headed", None):
        return True
    return True


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="sherpa",
        description="Sherpa web agent — run a task, or use a research subcommand.",
    )
    commands = root.add_subparsers(dest="command")

    run = commands.add_parser("run", help="Run the browser agent on a task")
    run.add_argument("task", help="Natural-language task")
    run.add_argument(
        "legacy_url",
        nargs="?",
        help=argparse.SUPPRESS,
    )
    add_task_run_flags(run)

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
    webvoyager.add_argument(
        "--read-only",
        action="store_true",
        help="Block non GET/HEAD/OPTIONS browser requests",
    )
    webvoyager.add_argument(
        "--allow-write",
        action="store_true",
        help="Deprecated alias; unrestricted HTTP is the default",
    )
    webvoyager.add_argument("--headed", action="store_true")
    webvoyager.add_argument("--real-model", action="store_true")

    commands.add_parser("init", help="Create a local .env from .env.example")
    commands.add_parser(
        "install",
        help="Install Playwright Chromium (same idea as browser-use install)",
    )
    return root


def task_parser() -> argparse.ArgumentParser:
    """Parser for bare `sherpa \"task…\"` (no subcommand)."""
    root = argparse.ArgumentParser(prog="sherpa")
    root.add_argument("task", nargs="+", help="Natural-language task")
    add_task_run_flags(root)
    return root


def normalize_argv(argv: list[str] | None) -> tuple[str, list[str]]:
    """Return (mode, argv_for_parser) where mode is a command or 'task'."""
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in {"-h", "--help"}:
        return "help", args
    if args[0] in COMMANDS:
        return args[0], args
    return "task", args


def run_init() -> int:
    example = Path(".env.example")
    target = Path(".env")
    if target.exists():
        print(f"{target} already exists; leaving it unchanged.")
    elif example.is_file():
        target.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"Created {target} from {example}.")
    else:
        target.write_text("OPENROUTER_API_KEY=\n", encoding="utf-8")
        print(f"Created {target}.")
    print()
    print("Next steps:")
    print("  1. Put your OpenRouter key in .env (OPENROUTER_API_KEY=...)")
    print("  2. sherpa install          # Playwright Chromium")
    print('  3. sherpa "Confirm the heading on https://example.com"')
    return 0


def run_install() -> int:
    return install_chromium()


async def run_agent(args: argparse.Namespace) -> int:
    settings = Settings.from_env()
    settings.require_api_key()
    task = args.task if isinstance(args.task, str) else " ".join(args.task)
    url = resolve_url(task, getattr(args, "url", None) or getattr(args, "legacy_url", None))
    max_steps = args.max_steps or settings.max_steps
    max_corrections = args.max_corrections or settings.max_corrections
    models = OpenRouterClient(settings)
    viewport = Dimensions(width=settings.viewport_width, height=settings.viewport_height)
    artifact_dir: Path | None = args.artifacts or default_artifacts_dir()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    log = RunLog(artifact_dir / "steps.jsonl")
    as_json = bool(getattr(args, "json", False))
    headed = resolve_headed(args)

    def on_step(result: StepResult) -> None:
        if not as_json:
            print(format_step_line(result), flush=True)

    if not as_json:
        print(f"Starting: {task}")
        print(f"URL: {url}")
        print(f"Artifacts: {artifact_dir}")
        print()

    ensure_chromium(auto_install=True)

    async with Browser(viewport, headed=headed) as browser:
        result = await Agent(
            browser,
            models,
            max_steps=max_steps,
            max_corrections=max_corrections,
            run_log=log,
            screenshot_dir=artifact_dir,
            on_step=on_step,
        ).run(task, url)

    if as_json:
        print(json.dumps(result.model_dump(mode="json"), indent=2))
    else:
        print_human_summary(result=result, task=task, url=url, artifacts=artifact_dir)
    return 0 if result.outcome == "done" else 1


async def run_eval(args: argparse.Namespace) -> int:
    settings = Settings.from_env()
    if args.real_model:
        settings.require_api_key()
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
    if args.real_model:
        settings.require_api_key()
    report = await evaluate_webvoyager(
        args.manifest,
        real_model=args.real_model,
        settings=settings,
        output=args.output,
        artifacts=args.artifacts,
        max_cost_usd=args.max_cost_usd,
        headed=args.headed,
        verdicts=load_verdicts(args.judgments),
        allow_write=not args.read_only,
        max_steps=args.max_steps or settings.max_steps,
        max_corrections=args.max_corrections or settings.max_corrections,
    )
    print(json.dumps(report, indent=2))
    return 0


def main(argv: list[str] | None = None) -> None:
    mode, remaining = normalize_argv(argv)
    if mode == "help":
        parser().parse_args(remaining if remaining else ["--help"])
        return
    if mode == "task":
        args = task_parser().parse_args(remaining)
        args.command = "run"
        code = asyncio.run(run_agent(args))
        raise SystemExit(code)

    args = parser().parse_args(remaining)
    if args.command is None:
        parser().parse_args(["--help"])
        return
    if args.command == "init":
        raise SystemExit(run_init())
    if args.command == "install":
        raise SystemExit(run_install())
    handlers = {
        "run": run_agent,
        "eval": run_eval,
        "webvoyager": run_webvoyager,
    }
    code = asyncio.run(handlers[args.command](args))
    raise SystemExit(code)


if __name__ == "__main__":
    main()
