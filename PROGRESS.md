# Progress

## Goal
Build the smallest reliable vision-only web agent that can plan with one model, ground with
another, act through Playwright, and report accuracy and cost.

## Built and verified
- Python package, core contracts, environment configuration, coordinate conversion, and JSONL
  run logging.
- One OpenRouter client for the GLM planner and Qwen grounder, including bounded transient
  retries, provider-reported cost extraction, Qwen 0–1000 coordinate conversion, and strict
  action parsing.
- `sherpa eval` point-in-box evaluation with offline and paid modes.
- Bounded Playwright screenshot → plan → ground → act loop and `sherpa run` CLI.
- Self-correcting recovery for malformed model output, grounding/execution failures, repeated
  actions, and no visible state change, with consecutive-correction and total-step caps.
- Deterministic local fixture and browser test.
- Offline verification: Ruff passes; 23 tests pass and the paid test skips by default.
- Paid verification on 2026-07-21:
  - Grounder fixture: 2/2 hits, no errors, $0.00027794.
  - Real-model local browser task: completed.
  - Read-only `https://example.com` smoke task: completed in one planner step, $0.0021808.
  - Qwen3.5 planner Greenhouse task: completed in seven attempts with one malformed response;
    successful calls recorded 19.9 seconds of model latency and at least $0.003163.

## Next
- Phase 2: add a small cleaned-DOM observation and DOM-first element resolution.
- Add explicit guarded file-upload and pre-submit confirmation flows before transactional use.
- Reduce malformed planner responses with provider-native structured output when supported.
- Add features only when a real task or measured failure requires them.

## Decisions
- Python 3.12, async Playwright, OpenRouter, Pydantic, and HTTPX.
- One CLI and one model client. No service, database, plugin system, or DOM grounding yet.
- Paid model calls always require an explicit CLI flag.
- Qwen grounding uses its native normalized 0–1000 coordinates and converts once at the model
  boundary.

## Known limits
- Phase 1 is vision-only and coordinate-based.
- Live websites can change or block automation.
- Verification is screenshot-based; subtle state changes and animated pages can produce false
  positives or negatives until DOM-aware verification is added.
- A 2026-07-21 Greenhouse dry-run completed the requested First Name, Last Name, and Email fields
  in eight steps after the recovery-loop changes. Submission requests were blocked and no
  application was created.
- Prompt hardening based on SeeAct, UGround, and Qwen guidance kept grounding at 2/2 hits
  ($0.00030641). A broader Greenhouse run filled required fields through Location in 20 attempts
  ($0.060691) before dropdown retries reached the correction cap.
- Resume/CV upload is not implemented. Live upload and submission were not attempted.
