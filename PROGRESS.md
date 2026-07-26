# Progress

## Goal
Build the smallest reliable hybrid-observation web agent that can plan with one model, ground
visually with another, act through Playwright, and report accuracy and cost.

## Built and verified
- Python package, core contracts, environment configuration, coordinate conversion, and JSONL
  run logging.
- One OpenRouter client for the Qwen3.5 planner and UI-TARS-1.5-7B grounder, including bounded
  transient retries, provider-reported cost extraction, model-specific coordinate conversion,
  and strict action parsing.
- `sherpa eval` point-in-box evaluation with offline and paid modes.
- Bounded Playwright screenshot + compact visible-controls/main-content channels → plan → visual
  ground → act loop and `sherpa run` CLI. Stateless planner calls replay accumulated semantic
  history: an initial/full snapshot followed by bounded diffs; unchanged observations add no DOM
  entry. Sensitive values are reduced to filled/empty state and raw page content is not logged.
- Bounded eight-entry progress ledger, eight durable visual memories, two milestone screenshots,
  and recovery actions for browser history plus page start/end.
- Multi-step cycle and stagnation handling for recurring actions, unproductive scrolls, repeated
  screenshot states, and stalled subgoals, with correction and total-step caps.
- Same-planner final-answer verifier that rejects unsupported completion and preserves verifier
  token, latency, and cost accounting.
- Deterministic local fixture and browser test.
- Explicit WebVoyager HTTP read-only/unrestricted policies, 20-step/5-correction defaults, CLI
  budget overrides, policy/budget/failure reporting, and post-run manual rescoring.
- Offline verification: Ruff passes; 74 retained tests pass and one paid real-model test skips by
  default.
- Paid validation from 2026-07-21 through 2026-07-25 covered 28 WebVoyager invocations and 273
  task executions for $5.02260037, including four unscored tuning runs and one invalid GLM
  diagnostic retained for cost accountability.
- The best reproducible round-2 result was 60% strict success with Qwen3.5/UI-TARS. UI-TARS
  eliminated the prior malformed-grounder failures and was the clearest measured improvement.
- Compact DOM fixed the verbose-context cost defect. Replaying the initial snapshot and all later
  diffs fixed latest-diff context loss, but matched rather than exceeded the 60% screenshot-only
  result at substantially higher input cost.
- A 20-step/5-correction run increased completion but reduced strict success. Twelve repeated
  grounding/verifier/stall experiments also failed their acceptance gate and were removed from
  production code after retaining all artifacts and judgments.
- Strict JSON-schema recovery produced zero unrecovered malformed responses across 94 model calls
  in its controlled Qwen run. Remaining failures were external site state or agent
  reasoning/grounding failures.
- `WEBVOYAGER_TESTS_AND_RESULTS.md` contains every goal, configuration, result, cost, judgment,
  and failure diagnosis. `WEBVOYAGER_RUN_HISTORY.md` remains the compact chronological ledger.

## Next
- Replace unconstrained coordinate retry with candidate-aware hit validation; design deterministic
  task-specific evidence checks before another verifier prompt experiment.
- Add explicit guarded file-upload and pre-submit confirmation flows before transactional use.
- Preserve more bounded visual evidence for the verifier without sending unbounded screenshots.
- Add features only when a real task or measured failure requires them.

## Decisions
- Python 3.12, async Playwright, OpenRouter, Pydantic, and HTTPX.
- One CLI and one model client. No service, database, plugin system, or DOM-coordinate grounding.
- No DOM-advisor LLM yet; deterministic compact cleaning is measured first so its effect is clear.
- Paid model calls always require an explicit CLI flag.
- UI-TARS grounding uses its native action syntax and Qwen2.5-VL resized-image coordinates,
  converted once at the model boundary.

## Known limits
- Grounding remains screenshot-only and coordinate-based; cleaned DOM is planner/verifier context.
- Live websites can change or block automation.
- DOM extraction is best-effort; inaccessible frames and highly dynamic pages can still produce
  incomplete or noisy observations.
- A 2026-07-21 Greenhouse dry-run completed the requested First Name, Last Name, and Email fields
  in eight steps after the recovery-loop changes. Submission requests were blocked and no
  application was created.
- Prompt hardening based on SeeAct, UGround, and Qwen guidance kept grounding at 2/2 hits
  ($0.00030641). A broader Greenhouse run filled required fields through Location in 20 attempts
  ($0.060691) before dropdown retries reached the correction cap.
- Resume/CV upload is not implemented. Live upload and submission were not attempted.
