# WebVoyager Tests and Results

## Purpose

This document consolidates Sherpa's WebVoyager validation from 2026-07-21 through 2026-07-25.
The goals were to measure task success and cost, isolate failures caused by websites from failures
caused by the agent, improve grounding and planning context, test recovery and verification
strategies, compare planners, and make model-output parsing reliable.

These are controlled smoke tests, not an official WebVoyager score. The official dataset contains
643 tasks across 15 websites. Sherpa used two checked-in 10-task subsets and one 3-task smoke
subset. Live pages and time-sensitive answers have changed since the benchmark was published.

## Evaluation method

- `eval/webvoyager.jsonl` is the first 10-task subset, spanning 10 sites. It intentionally excludes
  tasks requiring login, purchase, booking, cart changes, posting, or form submission.
- `eval/webvoyager-round2.jsonl` is a second 10-task subset from the six sites that loaded reliably
  in round 1. It reduces known CAPTCHA and Cloudflare effects.
- `eval/webvoyager-compact-smoke.jsonl` contains three round-2 tasks used only as a compact-DOM
  integration gate.
- Source provenance is recorded in `eval/WEBVOYAGER_SOURCE.md`.
- Manual scoring follows `eval/WEBVOYAGER_JUDGMENT_RUBRIC.md`. A pass must answer every requested
  condition and be supported by recorded evidence. A verifier-accepted `done` is not automatically
  a pass.
- Completion means the agent or verifier accepted a final answer. Strict success means a human
  judgment marked the task `pass`. `Uncertain` is excluded from strict success.
- Unless stated otherwise, runs were sequential in headless Chromium, used a $1 pre-task cost
  ceiling, and blocked HTTP methods other than GET, HEAD, and OPTIONS.
- Raw reports, per-step traces, screenshots, and judgments remain under `artifacts/` and `eval/`.
  `WEBVOYAGER_RUN_HISTORY.md` is the compact chronological cost ledger.

## Offline and supporting validation

The initial offline command loaded and validated all 10 round-1 records without opening a browser,
creating a model client, accessing a website, consuming tokens, or incurring cost. Equivalent
offline records were later produced for round 2 and the agentic configuration.

Supporting checks used during development included deterministic browser fixtures, point-in-box
grounding tests, compact-DOM golden fixtures, model payload/parser tests, usage-accounting tests,
agent-loop recovery tests, WebVoyager rescoring tests, Ruff, and the full pytest suite. Paid
non-WebVoyager smoke checks also confirmed the local browser loop, `example.com`, Qwen grounding,
and UI-TARS grounding before benchmark runs. The final post-cleanup suite result appears under
“Final repository verification.”

## Primary live runs

The first ten entries below correspond to ledger runs 1–10. Entries 11–14 correspond to ledger
runs 23–26; ledger runs 11–22 are the repeated accuracy experiments summarized separately.

| # | Goal and configuration | Completion | Strict result | Tokens in/out | Cost | Evidence |
|---|---|---:|---:|---:|---:|---|
| 1 | Establish an offline/cost baseline on the mixed-site subset. Qwen3.5 planner, Qwen3-VL grounder, screenshot-only, 12 steps/3 corrections, read-only. | 9/10 (90%) | 6/10 (60%) | 89,962 / 4,125 | $0.02012873 | `artifacts/webvoyager-live.json`; `eval/webvoyager_judgments.json` |
| 2 | Remove known blocked sites and measure agent failures on round 2. Qwen3.5/Qwen3-VL, screenshot-only, 12/3, read-only. | 6/10 (60%) | 3/10 (30%) | 140,892 / 5,454 | $0.03087106 | `artifacts/webvoyager-round2-live.json`; `eval/webvoyager-round2-judgments.json` |
| 3 | Test bounded progress memory, cycle/stagnation handling, recovery, and final-answer verification. Qwen3.5/Qwen3-VL, 12/3, read-only. | 4/10 (40%) | 4/10 (40%) | 215,802 / 13,880 | $0.05249080 | `artifacts/webvoyager-agentic-release-live.json`; `eval/webvoyager-agentic-judgments.json` |
| 4 | Isolate grounding quality by replacing Qwen3-VL with UI-TARS. Qwen3.5/UI-TARS, screenshot-only, 12/3, read-only. | 6/10 (60%) | 6/10 (60%) | 195,182 / 11,903 | $0.04672597 | `artifacts/webvoyager-ui-tars-round2-live.json`; `eval/webvoyager-ui-tars-round2-judgments.json` |
| 5 | Diagnostic first verbose-DOM invocation. GLM was inherited from `.env`, UI-TARS grounder, 20/5, unrestricted. Invalid model comparison; retained to measure the misconfiguration. | 0/10 (0%) | Not adjudicated | 1,109,608 / 40,320 | $1.11571660 | `artifacts/webvoyager-hybrid-round2-report.json` |
| 6 | Test screenshot plus verbose cleaned DOM with the intended models. Qwen3.5/UI-TARS, 20/5, unrestricted. | 5/10 (50%) | 4/10 (40%) | 1,723,092 / 18,771 | $0.32208678 | `artifacts/webvoyager-hybrid-round2-qwen-scored.json`; `eval/webvoyager-hybrid-round2-judgments.json` |
| 7 | Gate the compact two-channel DOM implementation on three tasks. Qwen3.5/UI-TARS, 12/3, read-only. | 1/3 (33%) | Not adjudicated | 149,756 / 5,714 | $0.03474797 | `artifacts/webvoyager-compact-smoke-report.json` |
| 8 | Measure compact visible-controls/main-content context with only the latest semantic diff. Qwen3.5/UI-TARS, 12/3, read-only. | 4/10 (40%) | 4/10 (40%) | 390,626 / 15,096 | $0.09134301 | `artifacts/webvoyager-compact-round2-scored.json`; `eval/webvoyager-compact-round2-judgments.json` |
| 9 | Restore stateless planner context by replaying the initial compact snapshot and every later semantic diff. Qwen3.5/UI-TARS, 12/3, read-only. | 6/10 (60%) | 6/10 (60%) | 736,286 / 15,178 | $0.14007784 | `artifacts/webvoyager-history-round2-scored.json`; `eval/webvoyager-history-round2-judgments.json` |
| 10 | Test whether more budget fixes accumulated-history failures. Qwen3.5/UI-TARS, 20/5, read-only. | 7/10 (70%) | 5 pass, 1 uncertain (50% strict) | 804,594 / 16,296 | $0.15825974 | `artifacts/webvoyager-history-20x5-round2-scored.json`; `eval/webvoyager-history-20x5-round2-judgments.json` |
| 11 | Compare Claude Sonnet 5 as planner while retaining UI-TARS and the 12/3 read-only baseline. | 5/10 (50%) | 4/10 (40%) | 682,225 / 18,530 | $1.47870120 | `artifacts/claude-sonnet5-baseline-round2-scored-report.json`; `eval/claude-sonnet5-baseline-round2-judgments.json` |
| 12 | Validate strict schema requests, response healing, conservative parsing, and one internal protocol retry with Qwen3.5/UI-TARS, 12/3, read-only. | 6/10 (60%) | 5/10 (50%) | 430,257 / 10,256 | $0.08540017 | `artifacts/json-recovery-qwen-round2-scored-report.json`; `eval/json-recovery-qwen-round2-judgments.json` |
| 13 | Test Qwen3.5 high reasoning effort for planning and verification with UI-TARS, 12/3, read-only. | 6/10 (60%) | 5/10 (50%) | 618,292 / 78,512 | $0.18698732 | `artifacts/qwen-reasoning-high-round2-scored-report.json`; `eval/qwen-reasoning-high-round2-judgments.json` |
| 14 | Default unrestricted HTTP, hardened SELECT, enumeration gate, finish-from-evidence prompts, search-URL stagnation feedback, and bounded settle waits. Qwen3.5/UI-TARS, 12/3, reasoning none. | 5/10 (50%) | 6/10 (60%) | 562,042 / 13,463 | $0.10884136 | `artifacts/unrestricted-agent-fixes-round2-scored-report.json`; `eval/unrestricted-agent-fixes-round2-judgments.json` |

### What each architecture test showed

- The round-1 60% result included three site-blocking failures. Round 2 removed those sites and
  exposed seven agent reasoning, navigation, grounding, or answer-quality failures.
- Progress memory and verification raised strict success from 30% to 40% and completion precision
  from 50% to 100%, but increased cost by 70%.
- UI-TARS eliminated the seven grounding/model format errors seen in the prior agentic run,
  improved strict success from 40% to 60%, and reduced cost from $0.05249080 to $0.04672597.
- Verbose hybrid DOM did not help. It saturated its 24k-character allowance on 52% of steps,
  increased input tokens by 783% over screenshot-only UI-TARS, and produced 29 cycle blocks.
- Compact DOM reduced input tokens by 77%, cost by 72%, and cycle blocks by 83% relative to verbose
  DOM while retaining privacy and reliable capture. Latest-diff-only context still scored 40%.
- Replaying the initial snapshot and all later diffs restored 60% strict success, proving that
  stateless latest-diff-only planner calls had lost necessary context. It cost 3.8 times as many
  input tokens as screenshot-only UI-TARS without improving its score.
- Increasing the history run from 12/3 to 20/5 raised completion to 70% but reduced strict success
  to 50% with one uncertain answer. The extra budget extended weak strategies and increased false
  completion instead of improving demonstrated task success.
- Claude Sonnet 5 scored 40% and cost $1.47870120. Its run recorded 18 malformed/non-parseable
  responses in 65 steps, making protocol reliability a major confounder as well as making the run
  much more expensive than Qwen.
- The Qwen JSON-recovery validation recorded zero unrecovered malformed responses across 94 model
  calls; every finish reason was `stop`. Its 50% strict score was one task below the prior 60%
  single-run Qwen result and remained within observed run-to-run variance. The protocol goal
  passed even though task reasoning and live-site failures remained.
- High Qwen reasoning produced the same 60% completion and 50% strict success as the preceding
  non-reasoning validation. Output tokens rose from 10,256 to 78,512, cost rose 2.19 times from
  $0.08540017 to $0.18698732, latency rose from 190.1 to 628.7 seconds, and six high-reasoning
  outputs hit the token limit before succeeding on an internal retry.
- Unrestricted HTTP plus agent fixes restored 60% strict success. Coursera--1 passed after site
  API POSTs were allowed. ESPN--11 produced a correct answer that an over-strict enumeration gate
  rejected during the run; that gate was narrowed afterward. ArXiv--17 and BBC News--5 remained
  hard failures.

## Agentic development runs

Four unscored tuning runs preceded the final agentic release. They exposed a Qwen target-field
compatibility issue, over-strict repeated-state handling, verifier parsing problems, and retry
accounting defects.

| Run | Completion | Cost | Evidence |
|---|---:|---:|---|
| `webvoyager-agentic` | 2/10 | $0.03450093 | `artifacts/webvoyager-agentic-live.json` |
| `webvoyager-agentic-fixed` | 2/10 | $0.05593990 | `artifacts/webvoyager-agentic-fixed-live.json` |
| `webvoyager-agentic-final` | 5/10 | $0.04584308 | `artifacts/webvoyager-agentic-final-live.json` |
| `webvoyager-agentic-final2` | 2/10 | $0.05779106 | `artifacts/webvoyager-agentic-final2-live.json` |

These four development runs cost $0.19407497. Including the $0.05249080 release run, agentic
development and validation cost $0.24656577.

## Repeated accuracy experiments

Four candidate levers were tested independently or together on the same ten round-2 tasks. Each
checkpoint used Qwen3.5/UI-TARS, 12 steps, 3 corrections, read-only browsing, and three paid
repeats. Acceptance required at least 70% mean strict success and 100% completion precision.
Every repeat was manually scored.

| Candidate | Strict success by repeat | Mean/range | Completion precision | Total cost | Decision |
|---|---|---:|---:|---:|---|
| Re-ground once after no state change | 30%, 50%, 30% | 36.7% / 30–50% | 64.7% | $0.34492952 | Rejected |
| Stricter completion/verifier prompt | 70%, 60%, 40% | 56.7% / 40–70% | 89.5% | $0.33901435 | Rejected |
| Earlier stall and search-reformulation feedback | 50%, 40%, 30% | 40.0% / 30–50% | 66.7% | $0.28998482 | Rejected |
| All three candidates combined | 40%, 40%, 30% | 36.7% / 30–40% | 61.1% | $0.27804684 | Rejected |

The 12 repeats executed 120 paid tasks and cost $1.25197553. The best single repeat was 70%, but
the gain did not reproduce. The best three-repeat mean was 56.7%. Prompt strictness still accepted
incorrect Apple repair headings and AirPods counts; unconstrained re-grounding did not reliably
recover missed targets; reformulation feedback did not create better routes; and the combined
policy increased unsupported completion. None met the acceptance gate, so the experimental
implementation was removed after retaining its artifacts and judgments.

Artifacts and scored reports use `accuracy-ground`, `accuracy-verifier`, `accuracy-stall`, and
`accuracy-combined` prefixes under `artifacts/`; corresponding judgments remain under `eval/`.

## Failure post-mortem

The 20-step/5-correction run gave the clearest step-level evidence:

- **Apple--6:** the agent had the evidence by step 2 but collapsed two separately offered AirPods 4
  variants into one family. This was a semantic counting and verification failure, not a budget
  problem.
- **Apple--12:** the planner and verifier accepted support-page headings as concrete repair methods
  at step 2. More steps were unused because completion was accepted prematurely.
- **ArXiv--17:** the correct paper was visible at step 9, but UI-TARS missed the result link.
  Steps 10–20 repeated clicks and scrolling without selecting a materially different target.
- **BBC News--5:** after page 1 lacked the requested older article, the agent scanned two more
  result pages instead of reformulating the query or changing routes. Step 20 ended with malformed
  output in the pre-recovery implementation.
- **Coursera--1:** sufficient course evidence was visible at step 4, but the agent unnecessarily
  tried to open a broad card. Five ineffective retries then exhausted the correction budget.

Across runs, the persistent hard tasks were ArXiv--17, BBC News--5, Coursera--1, and Apple--12.
The dominant remaining causes are target-level grounding misses, weak route/search strategy,
failure to finish from sufficient evidence, and semantic verification errors. Larger numerical
budgets and lightweight prompt/retry changes did not address those causes.

Two failures in the JSON-recovery run were external: ArXiv displayed a rate-limit page. The other
three failures were agent-level: inefficient BBC scrolling/search, repeated Coursera grounding,
and incorrect AirPods answer granularity. No failure in that run was caused by malformed JSON.

## Aggregate results and conclusions

- The ledger contains 26 scored or diagnostic entries: 14 primary/configuration runs and 12
  accuracy repeats. Four additional agentic tuning runs were paid but unscored.
- These 30 paid invocations represent 293 task executions: 133 across the 14 primary/configuration
  runs, 120 accuracy-repeat tasks, and 40 agentic tuning tasks.
- The explicitly recorded WebVoyager costs sum to $5.31842905: $3.87237855 for the 14 primary
  runs (including the invalid GLM diagnostic and compact smoke), $1.25197553 for accuracy repeats,
  and $0.19407497 for the four extra tuning runs.
- The best reproducible single-configuration round-2 result was 60% strict success, reached by
  screenshot-only UI-TARS and accumulated compact DOM history at 12/3.
- The best single repeat was 70%, but the best three-repeat checkpoint mean was 56.7%. Single
  10-task runs are directional and have substantial variance.
- UI-TARS was the clearest measured improvement. Compact DOM fixed context bloat, and accumulated
  history fixed context loss, but neither beat UI-TARS screenshot-only accuracy.
- More steps/corrections did not improve strict success. Rejected retry, verifier-prompt, and
  stall-feedback experiments were removed rather than retained as dormant production branches.
- Strict JSON recovery solved the malformed-output failure mode for the controlled Qwen run without
  consuming agent steps or corrections. Remaining failures are now attributable to external site
  state or agent reasoning/grounding rather than response parsing.
- High planner reasoning did not improve strict success in its first controlled run and materially
  increased cost, latency, output tokens, and protocol truncation. It should not be treated as an
  accuracy improvement without repeated evidence.
- Default unrestricted HTTP is now appropriate for SPA benchmarks that rely on GraphQL/XHR POSTs.
  Deterministic enumeration gates must distinguish total counts from listed subsets.

## Final repository verification

After documentation and dead-code cleanup:

- `uv run ruff check .`: passed.
- `uv run pytest`: 79 passed and one opt-in paid real-model test skipped.

The retained suite covers the production compact-DOM/history path, UI-TARS and compatibility
grounding formats, strict JSON schema recovery, protocol usage accounting, browser execution,
final verification, WebVoyager offline/live report construction, and manual rescoring.

