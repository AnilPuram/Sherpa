# Sherpa

Sherpa is a small hybrid-observation web agent. A planner chooses the next action from a viewport
screenshot plus two compact semantic channels: currently visible controls and main-content
Markdown. A cheaper screenshot-only grounder returns coordinates, so DOM data never bypasses
visual grounding.

The default pair is the Qwen3.5-35B-A3B planner and UI-TARS-1.5-7B grounder. Both can be
overridden through the environment. Qwen planning and verification use high reasoning effort by
default; set `SHERPA_PLANNER_REASONING_EFFORT` to `none`, `minimal`, `low`, `medium`, `high`,
`xhigh`, or `max` to change it.

The loop keeps a bounded eight-entry progress ledger, up to eight observed memories, and
two milestone screenshots. It re-observes and re-plans after malformed model output,
grounding/execution errors, repeated-action cycles, or stagnation. A separate same-planner visual
and DOM verification pass must accept every `done` answer. `SHERPA_MAX_CORRECTIONS` defaults to
five consecutive recovery attempts and `SHERPA_MAX_STEPS` defaults to twenty planner iterations.
Because planner calls are stateless, every request replays the accumulated page-context history:
the initial/full snapshot followed by every later semantic diff. A new DOM entry is not added when
the page is unchanged. Controls are capped at 4k characters, main content at 8k, and each diff at
3k. Raw content and form values are never written to run logs.

## Setup

```bash
uv sync
uv run playwright install chromium
cp .env.example .env
```

Set `OPENROUTER_API_KEY` in your shell before a real-model command. Sherpa does not load `.env`
implicitly:

```bash
set -a; source .env; set +a
```

## Verify offline

```bash
uv run ruff check .
uv run pytest
uv run sherpa eval
```

The default evaluation uses a no-network center-point grounder. Use `--real-model` only when
you intend to make paid OpenRouter calls:

```bash
uv run sherpa eval --real-model --output artifacts/eval.json
```

The real-model local integration test is also opt-in:

```bash
SHERPA_RUN_REAL_MODELS=1 uv run pytest tests/test_real_models.py
```

## WebVoyager smoke benchmark

The checked-in subset contains 10 unchanged, read-only information-retrieval tasks from the
official 643-task WebVoyager dataset. The default mode only validates local records, makes no
network or model calls, and costs $0:

```bash
uv run sherpa webvoyager --output artifacts/webvoyager-offline.json
```

Live execution is explicit and sequential. By default it allows all HTTP methods (including site
API POSTs needed by modern SPAs), writes one artifact directory per task, and stops before
starting another task after the cost ceiling has been reached:

```bash
uv run sherpa webvoyager \
  --real-model \
  --max-cost-usd 1.00 \
  --artifacts artifacts/webvoyager \
  --output artifacts/webvoyager-live.json
```

Use `--read-only` to block browser requests other than GET, HEAD, and OPTIONS for safer demos.
Unrestricted mode can still submit forms or mutate accounts if the agent chooses those actions.
`--allow-write` is a deprecated no-op alias because unrestricted HTTP is already the default.
Execution limits can be overridden with `--max-steps` and `--max-corrections`.

After manually reviewing a completed run, apply a fresh judgments file without repeating paid work:

```bash
uv run sherpa webvoyager \
  --score-report artifacts/webvoyager-live.json \
  --judgments eval/webvoyager-new-judgments.json \
  --output artifacts/webvoyager-scored.json
```

`completion_rate` measures verifier-accepted completion. Manual labels supplied with `--judgments`
produce `success_rate`. `WEBVOYAGER_TESTS_AND_RESULTS.md` consolidates every offline check, paid
run, repeated experiment, cost, judgment, and failure diagnosis. `WEBVOYAGER_RUN_HISTORY.md` is
the compact chronological ledger. These small live-site subsets are not official WebVoyager
scores.

A cross-agent bakeoff (Sherpa vs Browser Use vs Magnitude on the same round-2 tasks) is summarized
in `eval/bakeoff-round2-comparison.md`; runners live under `scripts/bakeoff/`.

## Run

The deterministic local task is:

```bash
uv run sherpa run \
  "Type Sherpa in the Agent name input, click Complete, and finish when Success is visible." \
  "file://$(pwd)/tests/fixtures/site/index.html" \
  --real-model --artifacts artifacts/local
```

The opt-in public smoke task is read-only:

```bash
uv run sherpa run \
  "Confirm the page heading says Example Domain, then finish without clicking anything." \
  "https://example.com" \
  --real-model --artifacts artifacts/public-smoke
```

Paid calls are never implicit: `sherpa run` refuses to start without `--real-model`. A run prints
a structured result containing its answer, usage, and outcome. Screenshots and the compact
`steps.jsonl` log are written only when `--artifacts` is provided.

## Files

- `src/sherpa/agent.py`: bounded progress, recovery, and hybrid-observation agent loop
- `src/sherpa/models.py`: strict planner, grounder, and final-verifier OpenRouter boundary
- `src/sherpa/eval.py`: point-in-box grounding evaluation
- `src/sherpa/webvoyager.py`: offline validation and bounded live WebVoyager subset runner
- `ARCHITECTURE.md`: complete agent flow and component diagrams
- `WEBVOYAGER_TESTS_AND_RESULTS.md`: consolidated goals, results, costs, and failure analysis
- `WEBVOYAGER_RUN_HISTORY.md`: chronological benchmark run ledger
- `eval/bakeoff-round2-comparison.md`: Sherpa vs Browser Use vs Magnitude round-2 bakeoff
- `scripts/bakeoff/`: external-agent bakeoff runners
- `eval/WEBVOYAGER_JUDGMENT_RUBRIC.md`: manual pass/fail/uncertain scoring rules
- `eval/WEBVOYAGER_SOURCE.md`: benchmark subset provenance
