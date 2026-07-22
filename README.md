# Sherpa

Sherpa is a small vision-only web agent. A planner chooses the next action from a screenshot,
a cheaper grounder returns its coordinates, and Playwright executes it. Phase 1 intentionally
has no DOM grounding, service, database, or plugin system.

The loop re-observes and re-plans after malformed model output, grounding/execution errors,
repeated actions, or no visible state change. `SHERPA_MAX_CORRECTIONS` caps consecutive recovery
attempts and `SHERPA_MAX_STEPS` caps the whole run.

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

Paid calls are never implicit: `sherpa run` refuses to start without `--real-model`. A run's
screenshots and compact `steps.jsonl` log are written only when `--artifacts` is provided.

## Files

- `src/sherpa/agent.py`: bounded screenshot-plan-ground-act loop
- `src/sherpa/models.py`: strict OpenRouter boundary
- `src/sherpa/eval.py`: point-in-box grounding evaluation
- `PROGRESS.md`: what is built, what is next, and known limits
- `web_agent_build_plan.md`: longer-term architecture
