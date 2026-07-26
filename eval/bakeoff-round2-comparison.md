# Cross-agent round-2 bakeoff

Same 10 tasks from `eval/webvoyager-round2.jsonl`, scored with
`eval/WEBVOYAGER_JUDGMENT_RUBRIC.md`. Not an official WebVoyager leaderboard score.

## Strict results

| Agent | Model / track | Strict |
| --- | --- | ---: |
| Sherpa (baseline) | Qwen3.5 + UI-TARS (prior unrestricted fixes run) | 6/10 (60%) |
| Browser Use | `qwen/qwen3.5-35b-a3b` (OpenRouter), DOM-index actions | 6/10 (60%) |
| Magnitude | `qwen/qwen3.5-35b-a3b` (equal-planner, not VL) | 1/10 (10%) |
| Magnitude | `qwen/qwen2.5-vl-72b-instruct`, 90s/task | 1/10 (10%) |

| Task | Sherpa | Browser Use | Magnitude (text Qwen) | Magnitude (Qwen2.5-VL) |
| --- | --- | --- | --- | --- |
| Apple--6 | pass | fail | fail | fail |
| Apple--12 | fail | pass | fail | fail |
| ArXiv--2 | pass | pass | fail | fail |
| ArXiv--17 | fail | pass | fail | fail |
| BBC News--5 | fail | fail | fail | fail |
| BBC News--6 | pass | pass | fail | pass |
| Coursera--1 | pass | fail | pass | fail |
| ESPN--11 | pass | pass | fail | fail |
| GitHub--3 | pass | pass | fail | fail |
| GitHub--12 | fail | fail | fail | fail |

## Fail overlap (Sherpa vs Browser Use)

- Both fail: BBC News--5, GitHub--12
- Only Sherpa fails: Apple--12, ArXiv--17
- Only Browser Use fails: Apple--6, Coursera--1

Same score, different misses.

## Findings

1. **DOM-index actuation matched Sherpa** on this IR subset when both used Qwen3.5-class planning.
   Browser Use mostly resolves clicks by element index, so a non-VL planner still acts reliably.
2. **Pure vision (Magnitude) is not automatically better.** With text Qwen as the clicker it
   mostly timed out scrolling. With Qwen2.5-VL and 90s caps it still scored 1/10 — better click
   attempts, but incomplete answers and planning failures remained.
3. **Vision helps coverage of bad DOM; DOM helps accuracy when a11y/controls are good.** Published
   Magnitude-style scores assume strong visually grounded models (e.g. Claude), not this equal-Qwen
   setup.
4. Sherpa’s hybrid (compact DOM for planning + screenshot-only UI-TARS grounding) tied the
   strongest bakeoff peer under these constraints.

## Evidence

| Run | Artifacts | Judgments |
| --- | --- | --- |
| Sherpa baseline | prior unrestricted round-2 artifacts | `eval/bakeoff-sherpa-round2-judgments.json` (copy of unrestricted) |
| Browser Use | `artifacts/bakeoff-browser-use-round2/` | `eval/bakeoff-browser-use-round2-judgments.json` |
| Magnitude text Qwen | `artifacts/bakeoff-magnitude-round2/` | `eval/bakeoff-magnitude-round2-judgments.json` |
| Magnitude Qwen2.5-VL | `artifacts/bakeoff-magnitude-qwen-vl-round2/` | `eval/bakeoff-magnitude-qwen-vl-round2-judgments.json` |

Harness: `scripts/bakeoff/` (see `scripts/bakeoff/README.md`).
