# Cross-agent WebVoyager round-2 bakeoff

Compare Browser Use and Magnitude to Sherpa on `eval/webvoyager-round2.jsonl` with
`eval/WEBVOYAGER_JUDGMENT_RUBRIC.md`.

**Results and analysis:** [`eval/bakeoff-round2-comparison.md`](../../eval/bakeoff-round2-comparison.md)
(also summarized in `WEBVOYAGER_TESTS_AND_RESULTS.md` and ledger entries 27–29).

## Setup

```bash
set -a; source .env; set +a   # OPENROUTER_API_KEY
uv pip install browser-use && uv run playwright install chromium
cd scripts/bakeoff/magnitude && bun install && cd -
```

## Run (paid; `--real-model` / sequential wrapper required)

```bash
# Browser Use (DOM-index; default model qwen/qwen3.5-35b-a3b)
uv run python scripts/bakeoff/run_browser_use.py --real-model

# Magnitude with Qwen VL + tight per-task timeout (~90s)
BAKEOFF_PLANNER_MODEL=qwen/qwen2.5-vl-72b-instruct \
BAKEOFF_MAGNITUDE_ARTIFACTS=artifacts/bakeoff-magnitude-qwen-vl-round2 \
BAKEOFF_MAGNITUDE_OUTPUT=artifacts/bakeoff-magnitude-qwen-vl-round2/report.json \
TIMEOUT_SEC=90 \
uv run python scripts/bakeoff/run_magnitude_sequential.py
```

After editing judgment JSON files, regenerate the scores table (narrative stays in
`eval/bakeoff-round2-comparison.md`):

```bash
uv run python scripts/bakeoff/compare_bakeoff.py
```

`node_modules/` is gitignored; run `bun install` under `magnitude/` locally when needed.
