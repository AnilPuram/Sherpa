# WebVoyager Run History

This is the central ledger for paid WebVoyager benchmark runs. Success is based on manual
judgments, not merely the agent returning `done`. Runs use 10 tasks unless explicitly noted.
Goals, methodology, repeated experiments, and failure analysis are consolidated in
`WEBVOYAGER_TESTS_AND_RESULTS.md`. Raw artifacts and judgments remain the evidence of record.

1. **Initial mixed-site subset — Qwen/Qwen — 12 steps / 3 corrections — HTTP read-only**
   - Completion: 90%; verified success: 60%
   - Input/output tokens: 89,962 / 4,125; cost: $0.02012873
   - Evidence: `artifacts/webvoyager-live.json`, `eval/webvoyager_judgments.json`

2. **Round 2 baseline — Qwen/Qwen — 12 / 3 — HTTP read-only**
   - Completion: 60%; verified success: 30%
   - Input/output tokens: 140,892 / 5,454; cost: $0.03087106
   - Evidence: `artifacts/webvoyager-round2-live.json`,
     `eval/webvoyager-round2-judgments.json`

3. **Agentic progress/verifier — Qwen/Qwen — 12 / 3 — HTTP read-only**
   - Completion: 40%; verified success: 40%
   - Input/output tokens: 215,802 / 13,880; cost: $0.05249080
   - Evidence: `artifacts/webvoyager-agentic-release-live.json`,
     `eval/webvoyager-agentic-judgments.json`

4. **UI-TARS screenshot-only — Qwen/UI-TARS — 12 / 3 — HTTP read-only**
   - Completion: 60%; verified success: 60%
   - Input/output tokens: 195,182 / 11,903; cost: $0.04672597
   - Evidence: `artifacts/webvoyager-ui-tars-round2-live.json`,
     `eval/webvoyager-ui-tars-round2-judgments.json`

5. **Verbose hybrid diagnostic — GLM/UI-TARS — 20 / 5 — unrestricted**
   - Completion: 0%; not adjudicated; invalid comparison because `.env` selected GLM
   - Input/output tokens: 1,109,608 / 40,320; cost: $1.11571660
   - Artifact: `artifacts/webvoyager-hybrid-round2-report.json`

6. **Verbose hybrid rerun — Qwen/UI-TARS — 20 / 5 — unrestricted**
   - Completion: 50%; verified success: 40%
   - Input/output tokens: 1,723,092 / 18,771; cost: $0.32208678
   - Evidence: `artifacts/webvoyager-hybrid-round2-qwen-scored.json`,
     `eval/webvoyager-hybrid-round2-judgments.json`

7. **Compact-DOM smoke — Qwen/UI-TARS — 12 / 3 — HTTP read-only — 3 tasks**
   - Completion: 33%; not adjudicated
   - Input/output tokens: 149,756 / 5,714; cost: $0.03474797
   - Artifact: `artifacts/webvoyager-compact-smoke-report.json`

8. **Compact latest-diff — Qwen/UI-TARS — 12 / 3 — HTTP read-only**
   - Completion: 40%; verified success: 40%
   - Input/output tokens: 390,626 / 15,096; cost: $0.09134301
   - Evidence: `artifacts/webvoyager-compact-round2-scored.json`,
     `eval/webvoyager-compact-round2-judgments.json`

9. **Accumulated DOM history — Qwen/UI-TARS — 12 / 3 — HTTP read-only**
   - Completion: 60%; verified success: 60%
   - Input/output tokens: 736,286 / 15,178; cost: $0.14007784
   - Evidence: `artifacts/webvoyager-history-round2-scored.json`,
     `eval/webvoyager-history-round2-judgments.json`

10. **Accumulated DOM history, larger budget — Qwen/UI-TARS — 20 / 5 — HTTP read-only**
    - Completion: 70%; verified success: 50%; uncertain: 10%
    - Input/output tokens: 804,594 / 16,296; cost: $0.15825974
    - Evidence: `artifacts/webvoyager-history-20x5-round2-scored.json`,
      `eval/webvoyager-history-20x5-round2-judgments.json`

11. **Grounding retry repeat 1 — Qwen/UI-TARS — 12 / 3 — HTTP read-only**
    - Completion: 50%; verified success: 30%; cost: $0.12297728
12. **Grounding retry repeat 2**
    - Completion: 70%; verified success: 50%; cost: $0.11347002
13. **Grounding retry repeat 3**
    - Completion: 50%; verified success: 30%; cost: $0.10848222
14. **Verifier/completion repeat 1 — Qwen/UI-TARS — 12 / 3 — HTTP read-only**
    - Completion: 70%; verified success: 70%; cost: $0.12561142
15. **Verifier/completion repeat 2**
    - Completion: 70%; verified success: 60%; cost: $0.09844729
16. **Verifier/completion repeat 3**
    - Completion: 50%; verified success: 40%; cost: $0.11495564
17. **Stall-breaking repeat 1 — Qwen/UI-TARS — 12 / 3 — HTTP read-only**
    - Completion: 60%; verified success: 50%; cost: $0.10581085
18. **Stall-breaking repeat 2**
    - Completion: 50%; verified success: 40%; cost: $0.09586959
19. **Stall-breaking repeat 3**
    - Completion: 70%; verified success: 30%; cost: $0.08830438
20. **Combined accuracy repeat 1 — Qwen/UI-TARS — 12 / 3 — HTTP read-only**
    - Completion: 60%; verified success: 40%; cost: $0.10384451
21. **Combined accuracy repeat 2**
    - Completion: 70%; verified success: 40%; cost: $0.07797827
22. **Combined accuracy repeat 3**
    - Completion: 50%; verified success: 30%; cost: $0.09622406
23. **Claude Sonnet 5 baseline — Claude Sonnet 5/UI-TARS — 12 / 3 — HTTP read-only**
    - Completion: 50%; verified success: 40%
    - Input/output tokens: 682,225 / 18,530; cost: $1.47870120
    - Passed: Apple--6, BBC News--6, ESPN--11, GitHub--3
    - Failed: Apple--12 (answer named support headings rather than two concrete repair
      methods), ArXiv--2, ArXiv--17, BBC News--5, Coursera--1, GitHub--12
    - Scored artifact: `artifacts/claude-sonnet5-baseline-round2-scored-report.json`
    - Judgments: `eval/claude-sonnet5-baseline-round2-judgments.json`
    - This is one run, so 40% is a directional result rather than a stable mean.
24. **Strict JSON recovery validation — Qwen/UI-TARS — 12 / 3 — HTTP read-only**
    - Completion: 60%; verified success: 50%
    - Input/output tokens: 430,257 / 10,256; cost: $0.08540017
    - Protocol recovery: 0 internal retries and 0 unrecovered malformed responses across 94
      model calls; all finish reasons were `stop`
    - Passed: Apple--12, BBC News--6, ESPN--11, GitHub--3, GitHub--12
    - Failed: Apple--6 (counted three product families instead of four separately offered
      variants), ArXiv--2, ArXiv--17, BBC News--5, Coursera--1
    - Scored artifact: `artifacts/json-recovery-qwen-round2-scored-report.json`
    - Judgments: `eval/json-recovery-qwen-round2-judgments.json`
    - The protocol acceptance target passed. The 50% strict score is one task below the prior
      single-run 60% Qwen result and remains within the observed run-to-run variance.
25. **High-reasoning validation — Qwen/UI-TARS — 12 / 3 — HTTP read-only**
    - Planner/verifier reasoning effort: `high`
    - Completion: 60%; verified success: 50%
    - Input/output tokens: 618,292 / 78,512; cost: $0.18698732
    - Protocol recovery: 6 internally recovered truncations across 120 model attempts
    - Passed: Apple--6, BBC News--6, ESPN--11, GitHub--3, GitHub--12
    - Failed: Apple--12 (generic repair label rather than two concrete methods), ArXiv--2,
      ArXiv--17, BBC News--5, Coursera--1
    - Scored artifact: `artifacts/qwen-reasoning-high-round2-scored-report.json`
    - Judgments: `eval/qwen-reasoning-high-round2-judgments.json`
    - High reasoning matched the prior 50% strict result but cost 2.19 times more and introduced
      six output-limit truncations. It did not improve this task set.
26. **Unrestricted access + agent fixes — Qwen/UI-TARS — 12 / 3 — unrestricted — reasoning none**
    - Completion: 50%; verified success: 60%
    - Input/output tokens: 562,042 / 13,463; cost: $0.10884136
    - Passed: Apple--6, ArXiv--2, BBC News--6, Coursera--1, ESPN--11, GitHub--3
    - Failed: Apple--12, ArXiv--17, BBC News--5, GitHub--12
    - Coursera completed under unrestricted HTTP (site API POSTs allowed).
    - ESPN produced a correct answer but was blocked mid-run by an over-strict enumeration gate
      that treated “30 teams” as a list-length claim; the gate was fixed after the run and ESPN
      was scored pass on answer quality.
    - Scored artifact: `artifacts/unrestricted-agent-fixes-round2-scored-report.json`
    - Judgments: `eval/unrestricted-agent-fixes-round2-judgments.json`
27. **Cross-agent bakeoff — Browser Use — Qwen3.5 via OpenRouter — max 20 steps — unrestricted**
    - Strict success: 60% (6/10); same task set as round 2
    - Model: `qwen/qwen3.5-35b-a3b` (DOM-index actuation, not pixel grounding)
    - Passed: Apple--12, ArXiv--2, ArXiv--17, BBC News--6, ESPN--11, GitHub--3
    - Failed: Apple--6, BBC News--5, Coursera--1, GitHub--12
    - Evidence: `artifacts/bakeoff-browser-use-round2/`,
      `eval/bakeoff-browser-use-round2-judgments.json`
28. **Cross-agent bakeoff — Magnitude — Qwen3.5 text (equal-planner) — 240s/task**
    - Strict success: 10% (1/10); Coursera--1 only
    - Mostly `max_steps` / empty answers; pixel path without a VL model
    - Evidence: `artifacts/bakeoff-magnitude-round2/`,
      `eval/bakeoff-magnitude-round2-judgments.json`
29. **Cross-agent bakeoff — Magnitude — Qwen2.5-VL-72B — 90s/task**
    - Strict success: 10% (1/10); BBC News--6 only; wall time ~9.5 minutes
    - VL improved over text-Qwen clicks somewhat but did not match Browser Use / Sherpa
    - Evidence: `artifacts/bakeoff-magnitude-qwen-vl-round2/`,
      `eval/bakeoff-magnitude-qwen-vl-round2-judgments.json`
    - Summary table and analysis: `eval/bakeoff-round2-comparison.md`

The consolidated report records the 12-run comparison and acceptance decisions. None of the
three levers met the acceptance gate, so their dormant implementation was removed while retaining
all artifacts and judgments.

## Current controlled comparison

The 12/3 and 20/5 accumulated-history runs use the same tasks, models, and access policy.
Increasing the budget raised verifier completion from 60% to 70%, but strict manual success fell
from 60% to 50% with one uncertain answer. The extra budget therefore increased unsupported
completion and cost rather than demonstrated task success.
