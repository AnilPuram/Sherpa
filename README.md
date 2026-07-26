# Sherpa

Sherpa is a hybrid web agent: a planner reads the page (screenshot + compact controls/content),
a screenshot-only grounder picks click coordinates, and Playwright acts. Default models are
Qwen3.5-35B-A3B (planner/verifier) and UI-TARS-1.5-7B (grounder) via OpenRouter.

**PyPI:** [`sherpa-agent`](https://pypi.org/project/sherpa-agent/) · CLI command: `sherpa`

## Install

```bash
uv tool install sherpa-agent
sherpa install          # Playwright Chromium (+ Linux system deps)
sherpa init             # creates .env if missing
# edit .env → OPENROUTER_API_KEY=
sherpa "Confirm the page heading on https://example.com, then finish."
```

One-shot without a permanent install:

```bash
uvx --from sherpa-agent sherpa --help
```

`sherpa install` matches Browser Use (`uvx playwright install chromium`, with `--with-deps` on
Linux). If Chromium is missing when you run a task, Sherpa installs it automatically.

### Dev checkout

```bash
git clone https://github.com/AnilPuram/Sherpa.git
cd Sherpa
uv sync
uv run sherpa install
uv run sherpa init
uv run sherpa "Confirm the page heading on https://example.com"
```

## Usage

Config needs one key. Sherpa loads `.env` automatically (without overriding variables already set
in your shell).

```bash
# Start URL can be in the task, or passed explicitly:
sherpa "Confirm the page heading" --url https://example.com

# Headless + machine-readable result:
sherpa "…" --url https://example.com --headless --json
```

By default the browser is headed, steps print as they run, and artifacts go to
`artifacts/runs/<timestamp>/`.

### Models

Defaults work out of the box. Override in `.env` (OpenRouter model ids):

```bash
SHERPA_PLANNER_MODEL=qwen/qwen3.5-35b-a3b
SHERPA_GROUNDER_MODEL=bytedance/ui-tars-1.5-7b
SHERPA_PLANNER_REASONING_EFFORT=high
```

Or one-shot:

```bash
SHERPA_PLANNER_MODEL=anthropic/claude-sonnet-4 sherpa "…" --url https://example.com
```

## Verify offline

```bash
uv run ruff check .
uv run pytest
uv run sherpa eval
```

Use `--real-model` only when you intend paid OpenRouter calls for grounding eval:

```bash
uv run sherpa eval --real-model --output artifacts/eval.json
```

## Benchmarks / research

WebVoyager subset tooling, judgment rubrics, run history, and the cross-agent bakeoff live under
`eval/` and the docs below. Live WebVoyager still requires `--real-model` so offline scoring stays
safe and free.

```bash
uv run sherpa webvoyager --output artifacts/webvoyager-offline.json
uv run sherpa webvoyager --real-model --max-cost-usd 1.00 \
  --artifacts artifacts/webvoyager --output artifacts/webvoyager-live.json
```

See `WEBVOYAGER_TESTS_AND_RESULTS.md`, `WEBVOYAGER_RUN_HISTORY.md`, and
`eval/bakeoff-round2-comparison.md`.

## How it works

The loop keeps a bounded progress ledger and memories, recovers from grounding/execution errors,
and requires a separate verifier to accept every `done` answer. Defaults: 20 planner steps, 5
consecutive corrections, high planner reasoning effort. Details: `ARCHITECTURE.md`.

## Files

- `src/sherpa/cli.py`: simple task CLI + research subcommands
- `src/sherpa/install_browser.py`: `sherpa install` / auto Chromium setup
- `src/sherpa/agent.py`: bounded progress, recovery, and hybrid-observation agent loop
- `src/sherpa/models.py`: planner, grounder, and verifier OpenRouter boundary
- `src/sherpa/eval.py`: point-in-box grounding evaluation
- `src/sherpa/webvoyager.py`: offline validation and bounded live WebVoyager subset runner
- `ARCHITECTURE.md`: agent flow and component diagrams
- `eval/bakeoff-round2-comparison.md`: Sherpa vs Browser Use vs Magnitude bakeoff
- `scripts/bakeoff/`: external-agent bakeoff runners
