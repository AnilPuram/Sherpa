#!/usr/bin/env python3
"""Rebuild the scores table section for the round-2 bakeoff (does not replace analysis)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import DEFAULT_MANIFEST, build_comparison, load_tasks, load_verdicts  # noqa: E402


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("eval/bakeoff-round2-scores-table.md"),
        help="Generated scores table only; narrative stays in bakeoff-round2-comparison.md",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    tasks = load_tasks(args.manifest)
    columns = {
        "Sherpa": load_verdicts(Path("eval/bakeoff-sherpa-round2-judgments.json")),
        "Browser Use": load_verdicts(Path("eval/bakeoff-browser-use-round2-judgments.json")),
        "Magnitude (text Qwen)": load_verdicts(
            Path("eval/bakeoff-magnitude-round2-judgments.json")
        ),
        "Magnitude (Qwen2.5-VL)": load_verdicts(
            Path("eval/bakeoff-magnitude-qwen-vl-round2-judgments.json")
        ),
    }
    body = build_comparison(tasks=tasks, columns=columns)
    preamble = (
        "# Bakeoff round-2 scores table\n\n"
        "Auto-generated from judgment JSON files. Narrative findings live in "
        "`eval/bakeoff-round2-comparison.md`.\n\n"
    )
    args.output.write_text(preamble + body, encoding="utf-8")
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
