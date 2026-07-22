# Cost-Effective Web Agent — Build Plan

*A modular, vision-planning web agent with cheap-default grounding and cost-aware escalation. Fully rented (OpenRouter), no self-hosting required to start.*

---

## 1. Goal and constraints

Build a browser agent that completes **mixed** tasks (read/research *and* write/transactional) on the **open web**, that is **cost-effective without sacrificing accuracy**, and that runs entirely on **rented models via OpenRouter** — no GPU hosting at day one.

The core insight the whole design rests on: for web agents, **cost and accuracy are less opposed than they look**. Per-task cost is roughly `tokens-per-step × steps × retries`, and the largest hidden cost is *silent grounding/action failures* — every miss is a wasted expensive step. Fixing failures buys accuracy *and* cost at once. The genuine tension is narrow: it lives in (a) how you represent the page to the planner, and (b) how large a model you put at each role.

A second load-bearing fact, from the UGround paper's own error analysis: **planning errors dominate failures, not grounding errors** — the planner naming the wrong element, hallucinating one, or writing a description too vague to localize. So leverage concentrates on the *planner and the loop*, not on squeezing the grounder.

---

## 2. Architecture overview

This is a modular architecture in the SeeAct-V lineage (planner + separate grounder + pixel/DOM execution), extended with a DOM channel and cost-aware escalation.

```
                         ┌─────────────────────────────────────────┐
   TASK ───────────────► │              CONTROL LOOP                 │
                         │                                           │
   ┌─────────────┐       │  observe → plan → ground → precheck →     │
   │ OBSERVATION │◄──────┤  execute → verify → (escalate | reflect)  │
   │  cleaned DOM│       └─────────────────────────────────────────┘
   │  + screenshot│              │           │              │
   └─────────────┘              ▼           ▼              ▼
                         ┌──────────┐  ┌──────────┐  ┌──────────────┐
                         │ PLANNER  │  │ GROUNDER │  │  EXECUTOR    │
                         │ GLM-5V-  │  │ Qwen3-VL │  │  Playwright  │
                         │ Turbo    │  │ (default)│  │  DOM-handle  │
                         │ (vision) │  │  ↓ fail  │  │  preferred,  │
                         │          │  │ GLM-5V-  │  │  coord fallbk│
                         │          │  │ Turbo    │  │              │
                         │          │  │ (fallbk) │  │              │
                         └──────────┘  └──────────┘  └──────────────┘
```

### Model roster (all on OpenRouter, one API key)

| Role | Model | Slug | $/M in | $/M out | Notes |
|---|---|---|---|---|---|
| Planner (+ fallback grounder) | GLM-5V-Turbo | `z-ai/glm-5v-turbo` | 1.20 | 4.00 | Vision+DOM planner; native GUI grounding makes it a competent fallback grounder. ~203K ctx. Cached input ~$0.24/M. |
| Grounder (default) | Qwen3-VL-30B-A3B-Instruct | `qwen/qwen3-vl-30b-a3b-instruct` | 0.13 | 0.52 | 2D grounding + GUI automation; 3B active → fast/cheap. 8B variant even cheaper if accuracy holds. |
| (Optional text planner) | GLM-5.2 | `z-ai/glm-5.2` | 1.40 | 4.40 | Stronger text reasoner; only if you split "reason" from "see." Default plan uses GLM-5V-Turbo alone as the seeing planner. |

Grounder is ~8–9× cheaper than the planner/fallback per token. That gap is the entire economic justification for cheap-default grounding with escalation.

> **Honest note:** these prices and slugs drift. Confirm against the live OpenRouter listing before building. GLM-5V-Turbo's *element-level* grounding accuracy (ScreenSpot-style) was not independently published at design time — it leads *agent-level* benchmarks (WebVoyager, AndroidWorld). Treat its grounding quality as "good, unverified for our sites" until measured.

---

## 3. Design principles (the "why," so choices don't drift)

1. **The planner is the bottleneck — invest there.** Most failures are the planner choosing/describing the wrong element. Better element descriptions and a plan-time reality check beat grounder tuning.
2. **A planner must *see* the page.** Layout, modals, visual state drive decisions. GLM-5V-Turbo is multimodal, so it plans with the screenshot — this is why it's the planner, not a text-only model.
3. **Hybrid observation.** Cleaned DOM (exact text/labels/state) + downscaled screenshot (layout/what-covers-what). DOM is *best-effort enrichment*, never a hard dependency — open-web DOM is often obfuscated/incomplete.
4. **DOM-first grounding, VLM fallback.** A cleaned DOM already carries exact bounding boxes and selectors. When the planner's element resolves confidently to a DOM node, click it via Playwright's element handle (keeps auto-wait / scroll-into-view / actionability). Spend the VLM only on what the DOM can't expose (canvas, shadow DOM, obfuscated markup).
5. **Cheap-default, escalate on failure.** Ground with Qwen3-VL every step; escalate to GLM-5V-Turbo only on *detected* failure. Only pays off if the cheap grounder succeeds most of the time — measure the escalation rate.
6. **Verify after every act.** Grounding/action failures are *silent*. State-change detection is the reliability floor that stops silent misses from compounding into the "progress illusion."
7. **Unify the coordinate space.** DOM bboxes (CSS px), VLM output (image px), Playwright clicks (viewport CSS px) must all map to one canonical space (viewport CSS px). Get this wrong and DOM-clicks and VLM-clicks disagree by a scale factor.
8. **Cost concentrates in images.** Input images bill as input tokens, and the planner/fallback is ~9× the grounder. Downscale screenshots; use prompt caching for repeated context; keep the big model off the per-step path.

---

## 4. Components

### 4.1 Observation module
Captures both channels each time the planner is (re)invoked.

**Cleaned DOM** — keep per *interactive* node: `role/tag`, `visible text / accessible name`, `bounding box (viewport CSS px)`, `stable selector`, and `state` (disabled / checked / expanded / obscured / in-viewport). Keep enough surrounding text nodes for context. **Strip**: scripts, styles, SVG path data, data-URIs, tracking attributes, non-interactive noise. The retained bbox *is* the DOM-grounding path — no extra work.

**Screenshot** — downscaled; record the scale factor and `devicePixelRatio` for the coordinate transform. Only send to the planner when DOM is insufficient or the previous step failed (adaptive; text-only plan otherwise) — but since GLM-5V-Turbo is the planner, default to sending a lean screenshot each plan step.

### 4.2 Planner — GLM-5V-Turbo
**Input:** task, cleaned DOM (pruned), downscaled screenshot, action history.
**Output (strict schema):**
```json
{ "action": "click | type | select | scroll | done | infeasible",
  "element_description": "identity + type + text + location, or null for scroll/done",
  "value": "text for type / option for select, else null",
  "reasoning": "short" }
```
**Hardening (highest-leverage work):**
- **Constrain descriptions:** force identity+type+text+location ("the blue 'Submit' button at bottom-right of the form"), never "the submit button."
- **Plan-time self-check:** after naming an element, verify a matching node exists in the cleaned DOM *before* spending a grounding+action step. Catches hallucinated elements at the cheapest point.
- **Hierarchical planning:** plan a sub-goal, let cheaper roles execute several steps, re-invoke the planner on sub-goal completion or failure — not every step. Keeps the expensive model's call count low.

### 4.3 Grounder — Qwen3-VL (default)
**Input:** planner's `element_description` + screenshot. **Output:** `(x, y)` in image px → map to viewport CSS px.
- **Pre-action sanity check:** is `(x,y)` in-viewport? Is there a plausible interactive element near it? Does element type match intent? Cheap; catches gross misses.
- **Test-time zoom:** for small/icon targets, crop to the predicted region and re-ground (RegionFocus-style). Large accuracy gain on the hard cases, no retraining.

### 4.4 Executor — Playwright
- **DOM-handle-preferred:** if the described element resolves to a confident DOM node, click via element handle (auto-wait, scroll-into-view, actionability).
- **Coordinate fallback:** otherwise click the grounded `(x,y)`.
- **Action space:** click, type, select, scroll up/down, press-enter, navigate, wait. Note: with a real DOM channel you get reliable `select`/`type` via handles — *simpler and more robust* than the pure vision-only SeeAct-V action space, which had to strip these out.

### 4.5 Verifier + escalation
- **State-change detection:** after each act, diff URL / DOM / screenshot. No change ⇒ likely failure.
- **On failure:** re-ground with GLM-5V-Turbo *with added context* (DOM snippet, zoomed crop, richer description) — not an identical retry. Cap at one Turbo re-ground, then **re-plan** (the planner may have named the wrong element).
- **Loop detection:** same element/action repeated ⇒ break and re-plan.
- **Data capture:** every (cheap-fail → Turbo-success) case is a labeled hard example (screenshot + description + correct coord). Log it — this is your future grounder fine-tuning set. The fallback doubles as data collection.

### 4.6 Infrastructure layer (where open-web agents actually die)
The model rarely kills an open-web run; logins, 2FA, CAPTCHA, Cloudflare, and slow loads do.
- **Managed browser/session** (e.g. Browserbase) or hardened local Playwright with explicit wait/stability handling.
- **Pre-commit guard** before irreversible actions (purchase/submit/delete): a cheap confirmation check. High accuracy protection, near-zero cost.
- **Graduated fallback**, never hard-fail: DOM-resolve → VLM-ground → re-observe → re-plan.

---

## 5. Control loop (design pseudocode — not implementation)

```
state = init(task)
while not done and steps < MAX:
    obs = observe()                      # cleaned DOM + downscaled screenshot
    if need_plan(state):                 # hierarchical: not every step
        plan = planner(task, obs, history)     # GLM-5V-Turbo
        if plan.action in (done, infeasible): break
        if not dom_has(plan.element_description, obs.dom):   # plan-time self-check
            reflect(); continue

    coord, via = resolve(plan.element_description, obs)      # DOM-first
    if via == NONE:
        coord = grounder(plan.element_description, obs.image) # Qwen3-VL
        if not precheck(coord, obs): 
            coord = ground_fallback(...)   # GLM-5V-Turbo, added context

    if irreversible(plan.action): guard(plan)     # pre-commit confirm
    execute(plan.action, coord, plan.value)        # Playwright

    if not state_changed(obs, observe()):          # verify
        coord = ground_fallback(...)               # escalate once
        execute(...) 
        if still_failed(): reflect_or_replan()
    history.append(plan, outcome, cost, error_type)  # instrument everything
```

---

## 6. Data contracts (freeze these early — they make components swappable)

- **Cleaned DOM node:** `{ tag, role, name, text, bbox:[x,y,w,h] (viewport CSS px), selector, state:{disabled,checked,expanded,obscured,in_viewport} }`
- **Planner output:** schema in §4.2.
- **Grounder I/O:** in `{ description, image }` → out `{ x, y }` (image px) → normalize to viewport CSS px.
- **Canonical coordinate space:** viewport CSS pixels. All DOM bboxes and VLM outputs map into it; Playwright acts in it. Unit-test the transform against `devicePixelRatio` and screenshot scale.

Because the planner→grounder interface is just `element_description → coords`, **any grounder is swappable** without touching the planner. This is why the grounder choice can be deferred and A/B'd, not agonized over up front.

---

## 7. Cost model

Per-step cost ≈ `planner_call (only when re-planning) + grounder_call (every step) + occasional Turbo escalation`.

- Grounder every step at $0.13/$0.52 is cheap; planner at $1.20/$4 is called rarely (hierarchical).
- **Break-even for escalation:** the design saves money only if the cheap grounder succeeds *most* of the time. At ~85%+ Qwen3-VL success, Turbo fires on ~15% of steps → clear win. At ~60%, you pay cheap-call + Turbo-call + wasted click on every hard step → worse than Turbo-only. **The escalation rate is the metric that decides whether this architecture pays off.**
- **Levers:** downscale screenshots (biggest input-token lever), prompt caching (~$0.24/M cached cuts repeated context 60–80%), DOM pruning (fewer input tokens), hierarchical planning (fewer expensive calls), session caching of grounded elements and successful action macros per domain.

---

## 8. Evaluation strategy (build this *first*)

Three tiers, mirroring how SeeAct-V itself was tested:

1. **Grounder harness (component).** ~30–100 (screenshot, instruction, ground-truth box) cases from *your real target sites*. Feed each to a grounder, score "coord ∈ box," report hit-rate + cost per model. Turns "which grounder?" into a number. Use it to A/B Qwen3-VL vs alternatives.
2. **Cached offline replay (loop).** Capture screenshot + cleaned DOM + correct element box at each step of real tasks *once*; replay planner+grounder against the cache — cheap, reproducible, no live browser. This is your regression suite for prompt/model changes.
3. **Live end-to-end.** Full loop on live sites; score functional task success (key-node completion). Noisier and less reproducible (network, bot checks) — keep most iteration on tier 2.

**Metrics to log per step:** error type (planner / grounding / execution / infra), DOM-resolve-rate vs VLM-fallback-rate, escalation rate, step count, cost per task. Build a small eval set from real target sites. **You cannot tell which improvement matters without this**, and the failure taxonomy will almost certainly confirm the planner/loop is the bottleneck — pointing effort where it pays.

---

## 9. Build phases

- **Phase 0 — Instrumentation + eval harness.** The grounder harness and the logging/taxonomy. Everything else is undecidable without it. *First.*
- **Phase 1 — Skeleton loop, vision-only.** GLM-5V-Turbo planner + Qwen3-VL grounder + Playwright, coordinate-only execution. Reference: read `boyugou/Mind2Web_Live_SeeAct_V` (a WebCanvas fork — the loop structure and action space are worth borrowing; it already has DOM/vision reward modes). Swapping the planner is a `--planning_text_model`-style parameter change; the grounder swap is a localized endpoint change. Decide: fork-and-strip vs write-clean. Milestone: it completes one real task.
- **Phase 2 — DOM channel + DOM-first grounding.** Add the cleaned-DOM observation and DOM-handle resolution with VLM fallback. This is real work, not config.
- **Phase 3 — Verify loop + Turbo escalation.** State-change detection, failure triggers, one-shot Turbo re-ground with added context, re-plan, loop caps, pre-commit guard. This is the reliability jump.
- **Phase 4 — Infra + cost hardening.** Managed sessions, login/CAPTCHA handling, prompt caching, screenshot downscaling, element/macro caching. Tune the escalation rate.
- **Phase 5 (later lever) — Fine-tune the grounder.** Use the hard cases collected by the fallback (Phase 3) to fine-tune the cheap grounder on your sites' screenshots (the UGround lesson: domain grounding data helps a lot). This is when self-hosting the grounder starts to make sense — the one component where the economics favor it.

---

## 10. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Silent grounding/action failure | Verify-after-act (§4.5) — non-negotiable |
| Open-web infra (CAPTCHA, 2FA, Cloudflare) | Managed browser + graduated fallback + human-in-loop for edge cases |
| Coordinate-space mismatch bug | Single canonical space + unit tests on the transform |
| Cost blowup | Monitor escalation rate; downscale images; caching; hierarchical planning |
| Planner blindness | Vision planner (GLM-5V-Turbo) — already solved by design |
| Grounder underperforms on icons | Test-time zoom; DOM-first resolution avoids the VLM entirely when DOM is good |
| Model price/availability drift | All-OpenRouter, swappable via frozen data contracts |
| Escalation rate too high → net loss | If cheap grounder < ~85%, switch to better grounder or Turbo-only; decision is data-driven |

---

## 11. Open questions to resolve with data (not opinion)

1. **Qwen3-VL grounding hit-rate on your target sites** (grounder harness). Decides whether the cheap-default holds.
2. **Modular vs monolithic.** GLM-5V-Turbo can plan *and* ground. Is the modular split (cheaper per step) actually beating just running GLM-5V-Turbo end-to-end, given real escalation rates? Validate the break-even.
3. **DOM reliability per target site.** Determines the DOM-resolve-rate — i.e., how often you avoid the VLM entirely. Drives both cost and accuracy.

---

*Bottom line:* the accuracy-protecting investments (a seeing planner, plan-time self-check, verify loop) and the cost-saving ones (DOM-first grounding, cheap-default with escalation, image downscaling, caching) are the *same short list*, because the thing that wastes money — silent failures and calling the big model too often — is the same thing that drops accuracy. Build the eval harness first; let the escalation rate and failure taxonomy drive every subsequent decision.
