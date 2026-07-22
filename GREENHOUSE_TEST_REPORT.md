# Greenhouse Application Test Report

## Scope

Sherpa was tested against the SpaceXAI Greenhouse application page using harmless test values.
Every live run blocked non-read HTTP requests. No resume was uploaded and no application was
submitted.

The tests had two goals:

1. Prove that a vision-only planner and grounder can navigate and fill a real application form.
2. Identify why a full application takes many steps and where retries are spent.

## What the successful short run did

The first complete acceptance run filled First Name, Last Name, and Email in eight browser steps:

1. Clicked the page's Apply button.
2. Clicked near the application fields to bring the form into a usable viewport.
3. Typed `Test` into First Name.
4. Clicked the Last Name field.
5. Typed `Applicant`.
6. Clicked the Email field.
7. Typed `test@example.com`.
8. Re-observed the page, verified all three visible values, and returned `done`.

This run took 49.7 seconds of recorded model latency and had a list-price estimate of $0.024971.
It did not encounter a correction.

## What the broader required-field run did

The most informative full-form run made 20 attempts. Fourteen actions executed, four planner
responses were malformed, and two repeated actions were blocked.

The useful actions were:

1. Open the application form.
2. Fill First Name.
3. Fill Last Name.
4. Fill Email.
5. Open Country.
6. Retry after malformed model output.
7. Choose the United States country option.
8. Fill Phone.
9. Fill Full Legal Name.
10. Scroll to the next section.
11. Fill Full Legal Name in Native Language.
12. Retry after malformed model output.
13. Continue through the middle section.
14. Scroll toward the lower required fields.
15. Fill Your Location.
16. Retry after malformed model output.
17. Attempt the sponsorship dropdown.
18. Retry after malformed model output.
19. Block a repeated sponsorship action.
20. Block the same repeated action again and stop at the correction cap.

At the stop point, the following required values were visibly correct:

- First Name
- Last Name
- Email
- Country
- Phone
- Full Legal Name
- Full Legal Name in Native Language
- Your Location

The run stopped before completing:

- US employment sponsorship
- SpaceXAI employment history
- Exceptional work
- How the applicant heard about the role
- Resume/CV
- Final submission

The run recorded 295.4 seconds of model latency and a $0.060691 list-price estimate.

## Why it required so many steps

### One atomic browser action per step

Sherpa deliberately takes one action, captures a new screenshot, and replans. A long form needs
separate actions for typing, scrolling, opening dropdowns, choosing options, uploading, and final
verification. This improves recoverability but increases step count.

### Most targeted actions call two models

A targeted action normally uses:

1. GLM-5V-Turbo to choose and describe the action.
2. Qwen3-VL to ground that description to screen coordinates.

Scroll and terminal actions generally need only the planner. Therefore 20 browser steps can
represent substantially more than 20 model calls.

### The form is longer than one viewport

The application spans multiple screens. The planner must scroll, reorient from a new screenshot,
and locate the next required field. The lower-field test needed multiple successful scrolls before
the requested controls were visible.

### Vision-only control loses exact form semantics

Screenshots show appearance, but not exact input type, required state, option values, or whether a
custom control is a dropdown. This caused extra clicks and made custom Greenhouse dropdowns much
harder than text inputs.

### Malformed planner responses consumed attempts

GLM sometimes emitted duplicated, fenced, truncated, or otherwise invalid JSON. In the broad run,
four of 20 attempts ended this way. The self-correcting loop continued, but each malformed response
still consumed time and a paid model call.

### Clipped targets caused grounding misses

Early runs tried to type into First Name while the field was only partly visible at the bottom of
the screenshot. Qwen returned a point below the usable control, so typing did not reach the input.
The prompt now tells the planner to scroll before targeting clipped controls and lets the grounder
reject unsafe targets.

### Dropdown behavior needed its own action

Initially the planner had to improvise dropdown selection as multiple clicks. This repeatedly
stalled at sponsorship. A `select` action was added to click a verified dropdown, type the option,
and press Enter. A DOM-backed safety check now prevents Enter from being sent when the grounded
target is not actually a select or combobox.

### Loop detection needed state awareness

The first loop detector blocked repeated scrolls even when each scroll revealed a different part
of the page. It also blocked a valid retry after grounding failed. It now records repetition only
after an executed action causes no visible state change.

## What took multiple attempts

### Apply and form loading

The first run clicked Apply but replanned while the form was still loading. A short post-action
settling delay was added.

### Coordinate contract

The first grounding evaluation scored 0% because Qwen uses a normalized 1000 by 1000 grid rather
than image pixels. Converting its native coordinates at the model boundary restored 2/2 fixture
hits.

### Planner JSON compatibility

GLM returned duplicate JSON objects, occasional trailing Markdown fences, extra metadata fields,
and truncated output. Parsing and token limits were adjusted while still validating the action
schema.

### First Name

Several early attempts missed First Name because it was clipped. The successful self-correcting
run eventually filled it correctly.

### Scrolling

One run overscrolled past the requested fields. Another stopped because repeated scrolling was
mistaken for a loop. The planner prompt and loop policy were tightened.

### Required dropdowns

The sponsorship and employment-history controls required repeated experiments. The initial action
space had no select operation. The first select implementation could press Enter after a bad
grounding and trigger native form validation, although network blocking prevented submission. A
dropdown-role guard was then added.

### Full required-field completion

The broad run reached Location but hit the correction cap at sponsorship. A separate lower-form
run exercised select and scrolling but reached its 20-step cap before proving all four lower
controls correct.

## Which model performed better

The two models have different jobs, so this is not a direct head-to-head comparison. Based on the
observed runs, Qwen3-VL was more reliable in its specialized grounding role than GLM-5V-Turbo was
in the planning role.

### Qwen3-VL-30B-A3B-Instruct: strongest component so far

Qwen performed well once its native coordinate contract was implemented correctly:

- It scored 2/2 on the current grounding fixture after conversion from its normalized 0–1000
  coordinate grid.
- It generally located fully visible text inputs and buttons accurately on the live Greenhouse
  page.
- It is substantially cheaper than the planner at the configured OpenRouter prices:
  $0.13/M input tokens and $0.52/M output tokens.
- Its failures were concentrated around clipped controls, controls at viewport boundaries, and
  ambiguous custom dropdowns.

The 2/2 fixture result is encouraging but too small to establish a production accuracy rate. The
next evaluation set should contain at least 30–100 targets, especially clipped fields, dropdowns,
small icons, and repeated form controls.

### GLM-5V-Turbo: capable but less consistent

GLM demonstrated useful visual planning:

- It completed the read-only `example.com` task in one step.
- It completed the three-field Greenhouse dry-run in eight steps.
- It could navigate a long form, preserve previously filled values, and progress through Location.

Its weaknesses caused most of the observed wasted attempts:

- It sometimes emitted duplicated, fenced, truncated, or malformed JSON.
- It occasionally planned against clipped controls or scrolled too far.
- It struggled to recover efficiently around custom dropdowns.
- Planner calls dominated latency and cost because GLM is priced at $1.20/M input tokens and
  $4.00/M output tokens.

Not every malformed response can be attributed with certainty because early error logs did not
preserve which model failed. Direct diagnostics did repeatedly reproduce malformed and duplicated
JSON from GLM, so planner-output reliability is the clearest measured weakness.

### GPT-5.5: faster and more direct, but substantially more expensive

GPT-5.5 was tested on the same three-field Greenhouse task with Qwen3-VL retained as the
grounder. The final run disabled reasoning for this atomic planning workload and omitted the
unsupported temperature parameter.

The run completed correctly in seven attempts:

- It used five executed browser actions plus the final `done` response.
- One planner response was not parseable, despite JSON mode.
- The final screenshot visibly confirmed First Name, Last Name, and Email.
- Recorded model latency was 31.0 seconds, compared with GLM's 49.7 seconds.
- Successful calls recorded 15,462 input tokens, 698 output tokens, and $0.066776.

The recorded cost is 2.67 times GLM's $0.024971 for the successful eight-step run. It is only a
lower bound because the malformed GPT-5.5 call's usage was not retained. GPT-5.5's OpenRouter list
price is $5/M input tokens and $30/M output tokens, compared with GLM's configured $1.20/M input
and $4/M output.

An initial GPT-5.5 run with default reasoning behavior also completed in seven attempts, but had
two unparseable planner responses and recorded at least $0.057025. Disabling reasoning reduced
the malformed-response count from two to one, but did not eliminate the issue.

This is one repeated task, not a statistically meaningful benchmark. GPT-5.5 showed better action
economy and lower recorded model latency, but not enough reliability improvement to justify its
higher cost as the default planner.

### Qwen3.5-35B-A3B: fastest and cheapest planner tested

Qwen3.5-35B-A3B was tested as the planner with the existing Qwen3-VL grounder. Reasoning was
disabled for the atomic planning task.

The run completed correctly in seven attempts:

- It used five executed browser actions plus the final `done` response.
- One planner response was not parseable, despite JSON mode.
- The final screenshot visibly confirmed First Name, Last Name, and Email.
- Recorded model latency was 19.9 seconds, compared with GLM's 49.7 seconds and GPT-5.5's
  31.0 seconds.
- Successful calls recorded 14,346 input tokens, 537 output tokens, and $0.003163.

The recorded cost was 87% lower than GLM's $0.024971 and 95% lower than GPT-5.5's $0.066776.
It is a lower bound because the malformed call's usage was not retained. Qwen3.5-35B-A3B's
OpenRouter list price is $0.14/M input tokens and $1/M output tokens.

This single run makes Qwen3.5 the strongest replacement candidate, but it does not establish a
reliability advantage: both Qwen3.5 and the configured GPT-5.5 run had one malformed response,
while the selected GLM acceptance run had none.

### Current conclusion

Keep Qwen3-VL as the default grounder. It is inexpensive and performed well on fully visible
targets. Keep GLM as the default planner until the comparison is repeated, but prioritize
Qwen3.5-35B-A3B in the next A/B evaluation: it completed the same task faster and at a fraction of
the recorded cost. GPT-5.5 was faster than GLM but cost at least 2.67 times as much and still
produced malformed output. The larger improvement opportunity is to preserve failed-call usage,
add DOM context so the planner makes fewer visual guesses, and build a replay set large enough for
a meaningful A/B test.

Do not replace either model based only on these runs. First build a larger replay set and compare:

- Planner valid-JSON rate.
- Correct next-action rate.
- Grounding point-in-box accuracy.
- Median latency.
- Provider-reported cost per successful step.
- End-to-end task completion rate.

## Run history

- Initial dry-run: 2 attempts, stopped on malformed output, $0.002553.
- Second dry-run: 3 attempts, stopped on malformed output, $0.005683.
- Third dry-run: 5 attempts, partially filled fields, $0.013117.
- Overscroll dry-run: 5 attempts, stopped on malformed output, $0.012803.
- Self-correcting three-field run: 8 steps, completed, $0.024971.
- First broader required-field run: 8 attempts, correction cap, $0.021831.
- Second broader required-field run: 20 attempts, reached Location, $0.060691.
- First lower-field run: 5 attempts, scroll loop, $0.014958.
- Second lower-field run: 20 attempts, step cap, $0.054953.
- First GPT-5.5 three-field run: 7 attempts, 2 malformed responses, at least $0.057025.
- GPT-5.5 no-reasoning three-field run: 7 attempts, 1 malformed response, at least $0.066776.
- Qwen3.5 three-field run: 7 attempts, 1 malformed response, at least $0.003163.

The original GLM/Qwen development runs used 76 recorded attempts and approximately $0.21156 at
the original list-price calculation. The two GPT-5.5 comparisons added 14 attempts and at least
$0.12380. The Qwen3.5 comparison added seven attempts and at least $0.00316, bringing known
experimental tuning cost to approximately $0.33852. This is not the expected cost of one
application.

These historical costs have two caveats:

1. They were computed from list token prices and did not account for OpenRouter cache discounts.
2. Malformed responses were logged after parsing failed, so their usage was not retained; those
   paid calls are missing from the totals.

Sherpa now prefers OpenRouter's provider-reported billed cost for future successful calls.

## Estimated complete application

With the current vision-only design, a legitimate complete application is estimated at:

- 30 to 36 browser steps.
- Roughly 45 to 60 model calls because targeted actions use both planner and grounder.
- Approximately 7 to 9 minutes at the observed latency.
- Approximately $0.09 to $0.12 with GLM at list price.
- A rough GPT-5.5 extrapolation is at least $0.24 to $0.32, but a full-form GPT-5.5 run has not
  been measured and failed-call usage would make the actual amount higher.
- A rough Qwen3.5 extrapolation from the short-run cost ratio is $0.01 to $0.02, but a full-form
  Qwen3.5 run has not been measured and failed-call usage would make the actual amount higher.

The estimate includes:

- Opening the form.
- Eight required text-entry actions.
- Four required dropdown selections.
- Three to five scroll/reorientation actions.
- Resume upload.
- Final submit.
- Final state verification.
- Several expected correction attempts.

## Why submission was not tested

The live tests used dummy identity data. Submitting that data would create a deceptive application.
Resume upload may also transfer a file before final submission. Both operations were excluded, and
all non-read network requests were blocked.

Before legitimate submission is supported, Sherpa still needs:

1. A guarded file-upload action.
2. DOM-aware dropdown and field verification.
3. A pre-submit review showing every value and requiring explicit confirmation.
4. Usage preservation for failed model responses so cost accounting is complete.
