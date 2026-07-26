import re
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit

from sherpa.browser import Browser
from sherpa.coordinates import image_to_viewport, require_in_viewport
from sherpa.models import ModelResponseError
from sherpa.runlog import RunLog
from sherpa.types import (
    Action,
    AgentRunResult,
    BrowserObservation,
    Dimensions,
    DomChange,
    DomHistoryEntry,
    DomSnapshot,
    GroundedPoint,
    ModelResult,
    ModelUsage,
    PlannerAction,
    ProgressEntry,
    StepResult,
    VerificationResult,
)


class Models(Protocol):
    async def plan(
        self,
        *,
        task: str,
        image: bytes,
        image_size: Dimensions,
        progress: list[ProgressEntry],
        memories: list[str],
        dom_history: list[DomHistoryEntry],
        feedback: str | None = None,
    ) -> ModelResult: ...

    async def ground(
        self,
        *,
        description: str,
        image: bytes,
        image_size: Dimensions,
    ) -> ModelResult: ...

    async def verify(
        self,
        *,
        task: str,
        proposed_answer: str | None,
        image: bytes,
        image_size: Dimensions,
        progress: list[ProgressEntry],
        memories: list[str],
        milestone_images: list[bytes],
        dom: DomSnapshot,
        dom_change: DomChange,
    ) -> ModelResult: ...


class Agent:
    def __init__(
        self,
        browser: Browser,
        models: Models,
        *,
        max_steps: int,
        max_corrections: int = 3,
        run_log: RunLog | None = None,
        screenshot_dir: Path | None = None,
    ) -> None:
        self.browser = browser
        self.models = models
        self.max_steps = max_steps
        self.max_corrections = max_corrections
        self.run_log = run_log or RunLog(None)
        self.screenshot_dir = screenshot_dir

    async def run(self, task: str, start_url: str) -> AgentRunResult:
        await self.browser.navigate(start_url)
        progress: list[ProgressEntry] = []
        dom_history: list[DomHistoryEntry] = []
        memories: list[str] = []
        milestone_images: list[bytes] = []
        corrections = 0
        feedback: str | None = None
        observation: BrowserObservation | None = None
        total_usage = ModelUsage()
        total_latency_ms = 0
        recorded_steps = 0
        blocked_seen = 0

        def record(result: StepResult) -> None:
            nonlocal total_usage, total_latency_ms, recorded_steps
            self.run_log.append(result)
            total_usage = _add_usage(total_usage, result.usage)
            total_latency_ms += result.latency_ms
            recorded_steps += 1

        def finish(outcome: str, answer: str | None = None) -> AgentRunResult:
            return AgentRunResult(
                outcome=outcome,
                answer=answer,
                steps=recorded_steps,
                latency_ms=total_latency_ms,
                usage=total_usage,
            )

        for step in range(1, self.max_steps + 1):
            planned: ModelResult | None = None
            ground_result: ModelResult | None = None
            ground_results: list[ModelResult] = []
            verification_result: ModelResult | None = None
            before: BrowserObservation | None = observation
            dom_history_chars = sum(_dom_history_entry_chars(item) for item in dom_history)
            try:
                if observation is None:
                    screenshot_path = (
                        self.screenshot_dir / f"step-{step:02}.png"
                        if self.screenshot_dir
                        else None
                    )
                    observation = await self.browser.observe(path=screenshot_path)
                before = observation
                image = before.screenshot
                image_size = self.browser.viewport
                history_entry = _dom_history_entry(before, step)
                if history_entry is not None:
                    dom_history.append(history_entry)
                dom_history_chars = sum(_dom_history_entry_chars(item) for item in dom_history)
                planned = await self.models.plan(
                    task=task,
                    image=image,
                    image_size=image_size,
                    progress=progress,
                    memories=memories,
                    dom_history=dom_history,
                    feedback=feedback,
                )
                if not isinstance(planned.value, PlannerAction):
                    raise TypeError("planner returned the wrong result type")
                action = planned.value

                stagnation = None
                if action.action is Action.MEMORIZE:
                    if _contains_memory(memories, action.value or ""):
                        stagnation = ("stagnation", "That visual fact is already memorized.")
                elif action.action not in {Action.DONE, Action.INFEASIBLE}:
                    stagnation = _stagnation_reason(action, progress, before)
                if stagnation:
                    outcome, reason = stagnation
                    record(
                        StepResult(
                            step=step,
                            action=action.action,
                            model=planned.model,
                            latency_ms=planned.latency_ms,
                            usage=planned.usage,
                            planner_input_tokens=planned.usage.input_tokens,
                            **_protocol_fields(planned),
                            outcome=outcome,
                            error_category=outcome,
                            error_message=reason,
                            **_observation_fields(
                                before, before, context_chars=dom_history_chars
                            ),
                            **_progress_fields(action),
                        )
                    )
                    progress.append(
                        _progress_entry(action, step, outcome, before, before)
                    )
                    progress = progress[-8:]
                    corrections += 1
                    feedback = (
                        f"Recovery level {corrections}: {reason} Choose a different action "
                        "category, use a recovery action, or pursue another subgoal."
                    )
                    if corrections >= self.max_corrections:
                        return finish("correction_limit")
                    observation = await _refresh_observation(self.browser, before)
                    continue

                if action.action is Action.DONE:
                    gate_missing = _enumeration_gate(task, action.value)
                    if gate_missing is not None:
                        verdict = VerificationResult(
                            accepted=False,
                            reason="Answer fails enumeration requirements.",
                            missing_evidence=[gate_missing],
                        )
                        usage = planned.usage
                        latency_ms = planned.latency_ms
                        model = planned.model
                        protocol = _protocol_fields(planned)
                    else:
                        verification_result = await self.models.verify(
                            task=task,
                            proposed_answer=action.value,
                            image=image,
                            image_size=image_size,
                            progress=progress,
                            memories=memories,
                            milestone_images=milestone_images,
                            dom=before.dom,
                            dom_change=before.change,
                        )
                        if not isinstance(verification_result.value, VerificationResult):
                            raise TypeError("verifier returned the wrong result type")
                        verdict = verification_result.value
                        usage = _add_usage(planned.usage, verification_result.usage)
                        latency_ms = planned.latency_ms + verification_result.latency_ms
                        model = _model_names(planned, verification_result)
                        protocol = _protocol_fields(planned, verification_result)
                        if verdict.accepted:
                            answer = verdict.corrected_answer or action.value
                            post_missing = _enumeration_gate(task, answer)
                            if post_missing is not None:
                                verdict = VerificationResult(
                                    accepted=False,
                                    reason="Answer fails enumeration requirements.",
                                    missing_evidence=[post_missing],
                                )
                            else:
                                record(
                                    StepResult(
                                        step=step,
                                        action=action.action,
                                        model=model,
                                        latency_ms=latency_ms,
                                        usage=usage,
                                        planner_input_tokens=planned.usage.input_tokens,
                                        **protocol,
                                        outcome="done",
                                        **_observation_fields(
                                            before, before, context_chars=dom_history_chars
                                        ),
                                        verifier_reason=verdict.reason,
                                        missing_evidence=list(verdict.missing_evidence),
                                        **_progress_fields(action),
                                    )
                                )
                                return finish("done", answer)

                    record(
                        StepResult(
                            step=step,
                            action=action.action,
                            model=model,
                            latency_ms=latency_ms,
                            usage=usage,
                            planner_input_tokens=planned.usage.input_tokens,
                            **protocol,
                            outcome="verification_rejected",
                            error_category="verification",
                            error_message=", ".join(verdict.missing_evidence) or verdict.reason,
                            **_observation_fields(
                                before, before, context_chars=dom_history_chars
                            ),
                            verifier_reason=verdict.reason,
                            missing_evidence=list(verdict.missing_evidence),
                            **_progress_fields(action),
                        )
                    )
                    progress.append(
                        _progress_entry(
                            action,
                            step,
                            "verification_rejected",
                            before,
                            before,
                        )
                    )
                    progress = progress[-8:]
                    corrections += 1
                    missing = "; ".join(verdict.missing_evidence)
                    feedback = (
                        f"Final answer rejected: {verdict.reason}"
                        + (f" Missing evidence: {missing}." if missing else "")
                        + " If sufficient evidence is already visible, finish from that "
                        "evidence rather than exploring further."
                    )
                    if corrections >= self.max_corrections:
                        return finish("correction_limit")
                    observation = await _refresh_observation(self.browser, before)
                    continue

                if action.action is Action.INFEASIBLE:
                    record(
                        StepResult(
                            step=step,
                            action=action.action,
                            model=planned.model,
                            latency_ms=planned.latency_ms,
                            usage=planned.usage,
                            planner_input_tokens=planned.usage.input_tokens,
                            **_protocol_fields(planned),
                            outcome="infeasible",
                            **_observation_fields(
                                before, before, context_chars=dom_history_chars
                            ),
                            **_progress_fields(action),
                        )
                    )
                    return finish("infeasible")

                if action.action is Action.MEMORIZE:
                    memory = (action.value or "").strip()
                    memories.append(memory)
                    memories = memories[-8:]
                    record(
                        StepResult(
                            step=step,
                            action=action.action,
                            model=planned.model,
                            latency_ms=planned.latency_ms,
                            usage=planned.usage,
                            planner_input_tokens=planned.usage.input_tokens,
                            **_protocol_fields(planned),
                            outcome="memorized",
                            memory=memory,
                            **_observation_fields(
                                before, before, context_chars=dom_history_chars
                            ),
                            **_progress_fields(action),
                        )
                    )
                    progress.append(
                        _progress_entry(action, step, "memorized", before, before)
                    )
                    progress = progress[-8:]
                    milestone_images.append(image)
                    milestone_images = milestone_images[-2:]
                    corrections = 0
                    feedback = None
                    continue

                point = None
                if action.needs_target():
                    ground_result = await self.models.ground(
                        description=action.element_description or "",
                        image=image,
                        image_size=image_size,
                    )
                    ground_results.append(ground_result)
                    if not isinstance(ground_result.value, GroundedPoint):
                        raise TypeError("grounder returned the wrong result type")
                    point = image_to_viewport(
                        ground_result.value,
                        image_size,
                        self.browser.viewport,
                    )
                    require_in_viewport(point, self.browser.viewport)

                await self.browser.execute(action, point)
                next_path = (
                    self.screenshot_dir / f"step-{step + 1:02}.png"
                    if self.screenshot_dir and step < self.max_steps
                    else None
                )
                after = await self.browser.observe(previous=before, path=next_path)
                changed = _observation_changed(before, after)
                observation = after
                after_image = after.screenshot
                usage = _usage_with_results(planned.usage, ground_results)
                outcome = "executed" if changed else "no_state_change"
                record(
                    StepResult(
                        step=step,
                        action=action.action,
                        model=_model_names_with_results(planned, ground_results),
                        latency_ms=planned.latency_ms
                        + sum(item.latency_ms for item in ground_results),
                        usage=usage,
                        planner_input_tokens=planned.usage.input_tokens,
                        grounding_attempts=len(ground_results),
                        **_protocol_fields(planned, *ground_results),
                        point=point,
                        outcome=outcome,
                        error_category=None if changed else "verification",
                        **_observation_fields(
                            before, after, context_chars=dom_history_chars
                        ),
                        **_progress_fields(action),
                    )
                )
                progress.append(
                    _progress_entry(action, step, outcome, before, after)
                )
                progress = progress[-8:]
                blocked_requests = getattr(self.browser, "blocked_requests", [])
                blocked_feedback = _blocked_request_feedback(
                    blocked_requests, blocked_seen
                )
                if blocked_feedback is not None:
                    blocked_seen = len(blocked_requests)
                preview_feedback = _preview_error_feedback(after)
                if not changed:
                    corrections += 1
                    feedback = (
                        blocked_feedback
                        or preview_feedback
                        or (
                            "The last action caused no visible page change. Reassess the "
                            "target or choose a different action."
                        )
                    )
                    if corrections >= self.max_corrections:
                        return finish("correction_limit")
                    continue
                if action.completed_subgoal:
                    milestone_images.append(after_image)
                    milestone_images = milestone_images[-2:]
                corrections = 0
                feedback = blocked_feedback or preview_feedback
            except Exception as exc:
                corrections += 1
                after = await _refresh_observation(self.browser, before)
                observation = after or before
                error_usage = planned.usage if planned else ModelUsage()
                error_latency = planned.latency_ms if planned else 0
                error_models: list[str] = [planned.model] if planned else []
                for result in ground_results:
                    error_usage = _add_usage(error_usage, result.usage)
                    error_latency += result.latency_ms
                    error_models.append(result.model)
                if verification_result is not None:
                    error_usage = _add_usage(error_usage, verification_result.usage)
                    error_latency += verification_result.latency_ms
                    error_models.append(verification_result.model)
                if isinstance(exc, ModelResponseError):
                    error_usage = _add_usage(error_usage, exc.usage)
                    error_latency += exc.latency_ms
                    if exc.model:
                        error_models.append(exc.model)
                protocol_fields = _protocol_fields(
                    *(
                        [planned]
                        if planned is not None
                        else []
                    ),
                    *ground_results,
                    *(
                        [verification_result]
                        if verification_result is not None
                        else []
                    ),
                )
                if isinstance(exc, ModelResponseError):
                    protocol_fields["model_attempts"] += exc.model_attempts
                    protocol_fields["protocol_retry"] = (
                        protocol_fields["protocol_retry"] or exc.protocol_retry
                    )
                    protocol_fields["finish_reason"] = _merge_diagnostic(
                        protocol_fields["finish_reason"],
                        exc.finish_reason,
                    )
                    protocol_fields["protocol_error_category"] = _merge_diagnostic(
                        protocol_fields["protocol_error_category"],
                        exc.protocol_error_category,
                    )
                record(
                    StepResult(
                        step=step,
                        action=planned.value.action
                        if planned and isinstance(planned.value, PlannerAction)
                        else None,
                        model=",".join(error_models) or None,
                        latency_ms=error_latency,
                        usage=error_usage,
                        planner_input_tokens=planned.usage.input_tokens if planned else 0,
                        grounding_attempts=len(ground_results),
                        **protocol_fields,
                        outcome="error",
                        error_category=_error_category(exc),
                        error_message=str(exc),
                        **_observation_fields(
                            before, observation, context_chars=dom_history_chars
                        ),
                        **(
                            _progress_fields(planned.value)
                            if planned and isinstance(planned.value, PlannerAction)
                            else {}
                        ),
                    )
                )
                if planned and isinstance(planned.value, PlannerAction) and before:
                    progress.append(
                        _progress_entry(
                            planned.value,
                            step,
                            "error",
                            before,
                            observation or before,
                        )
                    )
                    progress = progress[-8:]
                feedback = (
                    f"The previous attempt failed ({_error_category(exc)}). "
                    "Reassess the refreshed screenshot and DOM change, then try a valid "
                    "next action."
                )
                if corrections >= self.max_corrections:
                    return finish("correction_limit")

        return finish("max_steps")


def _normalize(value: str | None) -> str:
    return " ".join((value or "").lower().split())


def _signature(action: PlannerAction) -> tuple[Action, str, str]:
    return (
        action.action,
        _normalize(action.element_description),
        _normalize(action.value),
    )


def _category(action: Action | None) -> str:
    if action in {Action.SCROLL, Action.SCROLL_HOME, Action.SCROLL_END}:
        return "scroll"
    if action is Action.GO_BACK:
        return "recovery"
    return action.value if action else "none"


def _stagnation_reason(
    action: PlannerAction,
    progress: list[ProgressEntry],
    current: BrowserObservation,
) -> tuple[str, str] | None:
    recent = progress[-6:]
    attempted = [
        item for item in recent if item.outcome in {"executed", "no_state_change"}
    ]
    signature = _signature(action)
    matching = [
        item
        for item in attempted
        if (
            item.action,
            _normalize(item.target),
            _normalize(item.value),
        )
        == signature
    ]
    repeated_state = sum(_entry_state(item) == _observation_state(current) for item in attempted)
    if repeated_state >= 2 and matching:
        return "cycle", "This action has already been tried from the same screenshot state."
    search_stall = _search_scroll_stagnation(action, attempted, current)
    if search_stall is not None:
        return search_stall
    if action.action is Action.SCROLL:
        trailing = attempted[-3:]
        if len(trailing) == 3 and all(
            item.action is Action.SCROLL
            and _normalize(item.value) == _normalize(action.value)
            and not item.completed_subgoal
            for item in trailing
        ):
            return "stagnation", "Three same-direction scrolls produced no completed subgoal."
    elif len(matching) >= 2:
        return "cycle", "The same action and target already occurred twice recently."

    category = _category(action.action)
    window = attempted[-4:]
    if category not in {"scroll", "recovery"} and len(window) == 4 and all(
        _category(item.action) == category and not item.completed_subgoal for item in window
    ):
        return (
            "stagnation",
            f"The recent history is dominated by {category} actions without a completed subgoal.",
        )

    next_subgoal = _normalize(action.next_subgoal)
    prior = attempted[-2:]
    if next_subgoal and len(prior) == 2 and all(
        _normalize(item.next_subgoal) == next_subgoal and not item.completed_subgoal
        for item in prior
    ):
        return "stagnation", "The same next subgoal has repeated without visible progress."
    return None


def _canonical_url(url: str | None) -> str:
    if not url:
        return ""
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}{parts.path}"


def _is_search_exploration(action: Action | None, target: str | None = None) -> bool:
    if action in {Action.SCROLL, Action.SCROLL_HOME, Action.SCROLL_END}:
        return True
    if action is Action.CLICK:
        return bool(
            re.search(r"\b(page|pagination|next|previous)\b", _normalize(target))
            or re.fullmatch(r"\d+", _normalize(target))
        )
    return False


def _search_scroll_stagnation(
    action: PlannerAction,
    attempted: list[ProgressEntry],
    current: BrowserObservation,
) -> tuple[str, str] | None:
    if not _is_search_exploration(action.action, action.element_description):
        return None
    window = attempted[-3:]
    if len(window) < 3:
        return None
    if not all(
        _is_search_exploration(item.action, item.target) and not item.completed_subgoal
        for item in window
    ):
        return None
    urls = {_canonical_url(item.url_after or item.url_before) for item in window}
    current_url = _canonical_url(current.url)
    if len(urls) != 1 or current_url not in urls or not current_url:
        return None
    if any(item.action is Action.TYPE for item in attempted[-4:]):
        return None
    return (
        "stagnation",
        "Same URL with repeated scrolling/pagination and no query change. "
        "Change the query, filters, or route; do not keep scrolling the same results.",
    )


def _enumeration_gate(task: str, answer: str | None) -> str | None:
    """Reject answers that omit an explicitly requested item count or under-list a claimed count."""
    required = _required_enumerated_items(task)
    items = _distinct_answer_items(answer or "")
    if required is not None and len(items) < required:
        return (
            f"Enumerate at least {required} distinct visible items in the answer "
            f"(found {len(items)})."
        )
    claimed = _claimed_enumerated_count(answer or "")
    if claimed is not None and len(items) < claimed:
        return (
            f"Answer claims {claimed} items but only enumerates {len(items)} distinct items."
        )
    return None


def _required_enumerated_items(task: str) -> int | None:
    """Only enforce a minimum when the task states an explicit item cardinality."""
    lower = task.lower()
    patterns = (
        r"(?:answer|list|name|give|provide|return)\s+(\d+)\b",
        r"\b(\d+)\s+of\s+them\b",
        r"\bat least\s+(\d+)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, lower)
        if match:
            return int(match.group(1))
    return None


def _claimed_enumerated_count(answer: str) -> int | None:
    """Detect 'N ...: a, b, c' claims within a single clause, not separate totals."""
    for clause in re.split(r"[.\n]", answer):
        match = re.search(r"\b(\d+)\s+(?:\w+\s+){0,4}\w+\s*:\s*\S", clause.lower())
        if match:
            return int(match.group(1))
    return None


_CLAIM_PREFIX_RE = re.compile(
    r"^(?:there are|there is|are|is|found)?\s*\d+\s+(?:\w+\s+){0,4}\w+\s*:\s*",
    re.IGNORECASE,
)


def _distinct_answer_items(answer: str) -> list[str]:
    text = answer.strip()
    if not text:
        return []
    numbered = re.findall(r"(?:^|\n)\s*(?:\d+[\).]|[-*])\s*(.+)", text)
    if len(numbered) >= 2:
        return _unique_items(numbered)
    parts = re.split(r"\n|;|,(?!\d)|(?:\s+and\s+)|(?:\s+\+\s+)", text)
    cleaned: list[str] = []
    for part in parts:
        item = part.strip(" .")
        item = _CLAIM_PREFIX_RE.sub("", item).strip(" .:")
        if len(item) >= 3 and not re.fullmatch(r"\d+", item):
            cleaned.append(item)
    return _unique_items(cleaned)


def _unique_items(items: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for item in items:
        key = _normalize(item)
        if key and key not in seen:
            seen.add(key)
            unique.append(item.strip())
    return unique


def _blocked_request_feedback(
    blocked_requests: list[dict[str, str]],
    seen: int,
) -> str | None:
    if len(blocked_requests) <= seen:
        return None
    newest = blocked_requests[seen:]
    sample = newest[0]
    host = urlsplit(sample.get("url", "")).netloc or "unknown-host"
    method = sample.get("method", "POST")
    return (
        f"Read-only policy blocked {len(newest)} write request(s) "
        f"(e.g. {method} {host}). Use already-visible content or a GET navigation; do not "
        "retry the blocked action."
    )


_LOAD_FAILURE_RE = re.compile(
    r"(?:unable|failed|could not|couldn't)\s+to\s+load|"
    r"failed\s+to\s+load|"
    r"error\s+loading|"
    r"something went wrong|"
    r"please (?:close and )?try again|"
    r"try again later",
    re.IGNORECASE,
)


def _preview_error_feedback(observation: BrowserObservation) -> str | None:
    text = " ".join(
        part
        for part in (
            observation.dom.content_markdown,
            observation.dom.controls_text,
        )
        if part
    )
    if not _LOAD_FAILURE_RE.search(text):
        return None
    return (
        "A detail view or overlay failed to load. Prefer answering from already-visible "
        "content when it is sufficient, or choose a different target."
    )


def _contains_memory(memories: list[str], candidate: str) -> bool:
    normalized = _normalize(candidate)
    return bool(normalized) and any(_normalize(item) == normalized for item in memories)


def _progress_fields(action: PlannerAction) -> dict[str, object]:
    return {
        "target": action.element_description,
        "value": action.value,
        "observation": action.observation,
        "progress_made": action.progress_made,
        "completed_subgoal": action.completed_subgoal,
        "next_subgoal": action.next_subgoal,
    }


def _progress_entry(
    action: PlannerAction,
    step: int,
    outcome: str,
    before: BrowserObservation,
    after: BrowserObservation,
) -> ProgressEntry:
    observed_change = _observation_changed(before, after)
    evidence_saved = action.action is Action.MEMORIZE
    validated_progress = action.progress_made and (observed_change or evidence_saved)
    return ProgressEntry(
        step=step,
        action=action.action,
        target=action.element_description,
        value=action.value,
        observation=action.observation,
        progress_made=validated_progress,
        completed_subgoal=action.completed_subgoal if validated_progress else None,
        next_subgoal=action.next_subgoal,
        outcome=outcome,
        state_before=before.screenshot_fingerprint,
        state_after=after.screenshot_fingerprint,
        dom_before=before.dom.fingerprint,
        dom_after=after.dom.fingerprint,
        url_before=before.url,
        url_after=after.url,
        scroll_before=(before.scroll_x, before.scroll_y),
        scroll_after=(after.scroll_x, after.scroll_y),
    )


def _observation_changed(before: BrowserObservation, after: BrowserObservation) -> bool:
    return (
        before.url != after.url
        or (before.scroll_x, before.scroll_y) != (after.scroll_x, after.scroll_y)
        or after.change.meaningful
        or before.screenshot_fingerprint != after.screenshot_fingerprint
    )


def _observation_state(observation: BrowserObservation) -> tuple[object, ...]:
    return (
        observation.screenshot_fingerprint,
        observation.dom.fingerprint,
        observation.url,
        round(observation.scroll_x),
        round(observation.scroll_y),
    )


def _entry_state(entry: ProgressEntry) -> tuple[object, ...]:
    return (
        entry.state_after,
        entry.dom_after,
        entry.url_after,
        *(entry.scroll_after or (None, None)),
    )


def _dom_error(dom: DomSnapshot) -> str | None:
    errors = [error for error in (dom.controls_error, dom.content_error) if error]
    return "; ".join(dict.fromkeys(errors)) or None


def _dom_truncated(dom: DomSnapshot) -> bool:
    return dom.controls_truncated or dom.content_truncated


def _dom_history_entry(
    observation: BrowserObservation,
    step: int,
) -> DomHistoryEntry | None:
    dom_error = _dom_error(observation.dom)
    if observation.change.page_changed or dom_error:
        return DomHistoryEntry(
            step=step,
            url=observation.url,
            mode="full",
            controls_text=observation.dom.controls_text,
            main_content=observation.dom.content_markdown,
            truncated=_dom_truncated(observation.dom),
            error=dom_error,
        )
    if observation.change.summary:
        return DomHistoryEntry(
            step=step,
            url=observation.url,
            mode="diff",
            semantic_changes=observation.change.summary,
            truncated=observation.change.truncated,
        )
    return None


def _dom_history_entry_chars(entry: DomHistoryEntry) -> int:
    return len(entry.controls_text) + len(entry.main_content) + len(entry.semantic_changes)


def _observation_fields(
    before: BrowserObservation | None,
    after: BrowserObservation | None,
    *,
    context_chars: int | None = None,
) -> dict[str, object]:
    current = after or before
    change = current.change if current else DomChange()
    planner_change = before.change if before else DomChange()
    full_context = bool(
        before
        and (planner_change.page_changed or _dom_error(before.dom))
    )
    context_mode = (
        "full"
        if full_context
        else "diff"
        if planner_change.summary
        else "unchanged"
        if before
        else None
    )
    if context_chars is None:
        context_chars = 0
        if before:
            context_chars = before.dom.controls_char_count
            context_chars += (
            before.dom.content_char_count if full_context else len(planner_change.summary)
            )
    return {
        "state_before": before.screenshot_fingerprint if before else None,
        "state_after": after.screenshot_fingerprint if after else None,
        "dom_before": before.dom.fingerprint if before else None,
        "dom_after": after.dom.fingerprint if after else None,
        "url_before": before.url if before else None,
        "url_after": after.url if after else None,
        "scroll_before": (before.scroll_x, before.scroll_y) if before else None,
        "scroll_after": (after.scroll_x, after.scroll_y) if after else None,
        "dom_truncated": _dom_truncated(current.dom) if current else False,
        "dom_error": _dom_error(current.dom) if current else None,
        "dom_added": change.added,
        "dom_removed": change.removed,
        "dom_changed": change.changed,
        "dom_content_added": change.content_added,
        "dom_content_removed": change.content_removed,
        "dom_content_changed": change.content_changed,
        "dom_raw_controls": current.dom.raw_control_count if current else 0,
        "dom_controls": current.dom.control_count if current else 0,
        "dom_control_chars": current.dom.controls_char_count if current else 0,
        "dom_content_chars": current.dom.content_char_count if current else 0,
        "dom_diff_chars": len(planner_change.summary),
        "dom_context_chars": context_chars,
        "dom_context_mode": context_mode,
        "dom_controls_truncated": current.dom.controls_truncated if current else False,
        "dom_content_truncated": current.dom.content_truncated if current else False,
    }


async def _refresh_observation(
    browser: Browser,
    previous: BrowserObservation | None,
) -> BrowserObservation | None:
    try:
        return await browser.observe(previous=previous)
    except Exception:
        return previous


def _add_usage(first: ModelUsage, second: ModelUsage | None) -> ModelUsage:
    if second is None:
        return first
    return ModelUsage(
        input_tokens=first.input_tokens + second.input_tokens,
        output_tokens=first.output_tokens + second.output_tokens,
        cost_usd=first.cost_usd + second.cost_usd,
    )


def _usage_with_results(first: ModelUsage, results: list[ModelResult]) -> ModelUsage:
    usage = first
    for result in results:
        usage = _add_usage(usage, result.usage)
    return usage


def _model_names(first: ModelResult, second: ModelResult | None) -> str:
    return first.model if second is None else f"{first.model},{second.model}"


def _model_names_with_results(first: ModelResult, results: list[ModelResult]) -> str:
    return ",".join([first.model, *(result.model for result in results)])


def _protocol_fields(*results: ModelResult) -> dict[str, object]:
    attempts = sum(result.model_attempts for result in results)
    return {
        "model_attempts": max(1, attempts),
        "protocol_retry": any(result.protocol_retry for result in results),
        "finish_reason": _join_diagnostics(
            [result.finish_reason for result in results]
        ),
        "protocol_error_category": _join_diagnostics(
            [result.protocol_error_category for result in results]
        ),
    }


def _join_diagnostics(values: list[object]) -> str | None:
    unique: list[str] = []
    for value in values:
        if value and str(value) not in unique:
            unique.append(str(value))
    return ",".join(unique) or None


def _merge_diagnostic(left: object, right: str | None) -> str | None:
    return _join_diagnostics([left, right])


def _error_category(error: Exception) -> str:
    module = type(error).__module__
    if module.startswith("playwright"):
        return "execution"
    if isinstance(error, (ValueError, TypeError)):
        return "grounding"
    return "model"
