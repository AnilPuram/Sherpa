#!/usr/bin/env python3
"""Run Magnitude one task at a time with a hard process timeout."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BAKEOFF = Path(__file__).resolve().parent
MAG_DIR = BAKEOFF / "magnitude"
MANIFEST = ROOT / "eval" / "webvoyager-round2.jsonl"
DEFAULT_MODEL = os.getenv(
    "BAKEOFF_PLANNER_MODEL",
    "qwen/qwen2.5-vl-72b-instruct",
)


def safe_id(task_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", task_id)


def load_ids() -> list[str]:
    ids: list[str] = []
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        if line.strip():
            ids.append(json.loads(line)["id"])
    return ids


def kill_browsers() -> None:
    subprocess.run(["pkill", "-f", "ms-playwright"], check=False, capture_output=True)
    subprocess.run(["pkill", "-f", "run_magnitude.ts"], check=False, capture_output=True)
    time.sleep(2)


def main() -> int:
    artifacts = Path(
        os.environ.get(
            "BAKEOFF_MAGNITUDE_ARTIFACTS",
            str(ROOT / "artifacts" / "bakeoff-magnitude-round2"),
        )
    )
    output = Path(
        os.environ.get(
            "BAKEOFF_MAGNITUDE_OUTPUT",
            str(artifacts / "report.json"),
        )
    )
    timeout_sec = int(os.environ.get("TIMEOUT_SEC", "90"))
    model = os.environ.get("BAKEOFF_PLANNER_MODEL", DEFAULT_MODEL)
    bun = str(Path.home() / ".bun" / "bin" / "bun")
    if not Path(bun).exists():
        bun = "bun"

    artifacts.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["PATH"] = f"{Path.home() / '.bun' / 'bin'}:{env.get('PATH', '')}"

    results: list[dict] = []
    for task_id in load_ids():
        task_dir = artifacts / safe_id(task_id)
        task_dir.mkdir(parents=True, exist_ok=True)
        result_path = task_dir / "result.json"
        print(f"[magnitude] {task_id} (timeout {timeout_sec}s)", flush=True)
        cmd = [
            bun,
            "run",
            "run_magnitude.ts",
            "--real-model",
            "--task-id",
            task_id,
            "--timeout-sec",
            str(timeout_sec),
            "--model",
            model,
            "--artifacts",
            str(artifacts),
            "--output",
            str(task_dir / "task-report.json"),
        ]
        try:
            completed = subprocess.run(
                cmd,
                cwd=MAG_DIR,
                env=env,
                timeout=timeout_sec + 60,
                check=False,
            )
            status = completed.returncode
        except subprocess.TimeoutExpired:
            status = 124
            kill_browsers()

        if result_path.exists():
            payload = json.loads(result_path.read_text(encoding="utf-8"))
        else:
            payload = {
                "id": task_id,
                "agent": "magnitude",
                "model": model,
                "answer": None,
                "outcome": "max_steps" if status in {124, 142, 143} else "error",
                "steps": 0,
                "cost_usd": None,
                "error": f"process exited status={status} without result.json",
                "track": "equal-planner",
                "artifacts": str(task_dir),
            }
            result_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        results.append(payload)
        print(
            f"  outcome={payload.get('outcome')} "
            f"answer={json.dumps(((payload.get('answer') or '')[:100]))}",
            flush=True,
        )
        kill_browsers()

    report = {
        "agent": "magnitude",
        "track": "equal-planner",
        "model": model,
        "manifest": str(MANIFEST),
        "max_steps": 20,
        "timeout_sec": timeout_sec,
        "results": results,
    }
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {output}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
