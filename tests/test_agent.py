import json
from pathlib import Path

import pytest

from sherpa.agent import Agent
from sherpa.browser import Browser
from sherpa.models import ModelResponseError
from sherpa.runlog import RunLog
from sherpa.types import (
    Action,
    BrowserObservation,
    Dimensions,
    DomChange,
    DomHistoryEntry,
    DomNode,
    DomSnapshot,
    GroundedPoint,
    ModelResult,
    ModelUsage,
    PlannerAction,
    VerificationResult,
)


class CannedModels:
    def __init__(self) -> None:
        self.actions = iter(
            [
                PlannerAction(
                    action="type",
                    element_description="the Agent name input at center",
                    value="Sherpa",
                ),
                PlannerAction(
                    action="click",
                    element_description="the blue Complete button below the input",
                ),
                PlannerAction(action="done", value="Success"),
            ]
        )
        self.points = iter(
            [
                GroundedPoint(x=640, y=283),
                GroundedPoint(x=640, y=355),
            ]
        )

    async def plan(self, **_: object) -> ModelResult:
        return ModelResult(
            value=next(self.actions),
            model="fake-planner",
            latency_ms=1,
        )

    async def ground(self, **_: object) -> ModelResult:
        return ModelResult(
            value=next(self.points),
            model="fake-grounder",
            latency_ms=1,
        )

    async def verify(self, **_: object) -> ModelResult:
        return ModelResult(
            value=VerificationResult(accepted=True, reason="Visible success"),
            model="fake-planner",
            latency_ms=1,
        )


class FlakyModels(CannedModels):
    def __init__(self) -> None:
        super().__init__()
        type_action = PlannerAction(
            action="type",
            element_description="the Agent name input at center",
            value="Sherpa",
        )
        self.actions = iter(
            [
                type_action,
                type_action,
                PlannerAction(
                    action="click",
                    element_description="the blue Complete button below the input",
                ),
                PlannerAction(action="done"),
            ]
        )
        self.plan_failed = False
        self.ground_failed = False

    async def plan(self, **kwargs: object) -> ModelResult:
        if not self.plan_failed:
            self.plan_failed = True
            raise ModelResponseError("malformed response")
        return await super().plan(**kwargs)

    async def ground(self, **kwargs: object) -> ModelResult:
        if not self.ground_failed:
            self.ground_failed = True
            raise ModelResponseError("target not visible")
        return await super().ground(**kwargs)


class InternallyRetriedModels:
    async def plan(self, **_: object) -> ModelResult:
        return ModelResult(
            value=PlannerAction(action="done", value="Recovered answer"),
            model="planner",
            latency_ms=8,
            usage=ModelUsage(input_tokens=22, output_tokens=5, cost_usd=0.02),
            model_attempts=2,
            protocol_retry=True,
            finish_reason="stop",
            protocol_error_category="invalid_json",
        )

    async def verify(self, **_: object) -> ModelResult:
        return ModelResult(
            value=VerificationResult(accepted=True, reason="Visible evidence"),
            model="planner",
            latency_ms=2,
            usage=ModelUsage(input_tokens=5, output_tokens=1, cost_usd=0.005),
            finish_reason="stop",
        )

    async def ground(self, **_: object) -> ModelResult:
        raise AssertionError("done must not call the grounder")


class PaidGroundFailure:
    async def plan(self, **_: object) -> ModelResult:
        return ModelResult(
            value=PlannerAction(action="click", element_description="Complete button"),
            model="planner",
            latency_ms=3,
            usage=ModelUsage(input_tokens=10, output_tokens=2, cost_usd=0.01),
        )

    async def ground(self, **_: object) -> ModelResult:
        raise ModelResponseError(
            "malformed grounder response",
            model="grounder",
            latency_ms=4,
            usage=ModelUsage(input_tokens=20, output_tokens=1, cost_usd=0.02),
        )


class SequenceBrowser:
    def __init__(self) -> None:
        self.viewport = Dimensions(width=1280, height=720)
        self.state = 0
        self.blocked_requests: list[dict[str, str]] = []

    async def navigate(self, _: str) -> None:
        return None

    async def screenshot(self, _: Path | None = None) -> bytes:
        return f"state-{self.state}".encode()

    async def observe(
        self,
        previous: BrowserObservation | None = None,
        path: Path | None = None,
    ) -> BrowserObservation:
        del path
        fingerprint = f"state-{self.state}"
        dom = DomSnapshot(fingerprint="dom")
        return BrowserObservation(
            screenshot=fingerprint.encode(),
            screenshot_fingerprint=fingerprint,
            dom=dom,
            change=DomChange(),
            url="https://example.com",
            scroll_x=0.0,
            scroll_y=float(self.state * 100),
        )

    async def execute(self, *_: object) -> None:
        self.state += 1


class RejectedThenAcceptedModels:
    def __init__(self) -> None:
        self.plans = 0
        self.verifications = 0

    async def plan(self, **_: object) -> ModelResult:
        self.plans += 1
        return ModelResult(
            value=PlannerAction(
                action="done",
                value="bad" if self.plans == 1 else "good",
                observation="The answer is visible.",
                progress_made=True,
            ),
            model="planner",
            latency_ms=2,
            usage=ModelUsage(cost_usd=0.01),
        )

    async def ground(self, **_: object) -> ModelResult:
        raise AssertionError("done must not call ground")

    async def verify(self, **_: object) -> ModelResult:
        self.verifications += 1
        accepted = self.verifications == 2
        return ModelResult(
            value=VerificationResult(
                accepted=accepted,
                reason="supported" if accepted else "missing visible evidence",
                missing_evidence=[] if accepted else ["the requested value"],
            ),
            model="planner",
            latency_ms=3,
            usage=ModelUsage(cost_usd=0.02),
        )


class ScrollingModels:
    def __init__(self) -> None:
        self.calls = 0

    async def plan(self, **_: object) -> ModelResult:
        self.calls += 1
        return ModelResult(
            value=PlannerAction(
                action="scroll",
                value="down",
                observation=f"Section {self.calls}",
                next_subgoal=f"Find section {self.calls}",
            ),
            model="planner",
            latency_ms=1,
        )

    async def ground(self, **_: object) -> ModelResult:
        raise AssertionError("scroll must not call ground")

    async def verify(self, **_: object) -> ModelResult:
        raise AssertionError("scroll must not call verify")


class RepeatedClickModels:
    async def plan(self, **_: object) -> ModelResult:
        return ModelResult(
            value=PlannerAction(
                action="click",
                element_description="the same navigation tab",
                observation="The page changed but the goal is not complete.",
                next_subgoal="Open the correct section",
            ),
            model="planner",
            latency_ms=1,
        )

    async def ground(self, **_: object) -> ModelResult:
        return ModelResult(
            value=GroundedPoint(x=100, y=100),
            model="grounder",
            latency_ms=1,
        )

    async def verify(self, **_: object) -> ModelResult:
        raise AssertionError("click must not call verify")


class MemoryModels:
    def __init__(self) -> None:
        self.calls = 0
        self.context_sizes: list[tuple[int, int]] = []

    async def plan(self, **kwargs: object) -> ModelResult:
        progress = kwargs["progress"]
        memories = kwargs["memories"]
        assert isinstance(progress, list)
        assert isinstance(memories, list)
        self.context_sizes.append((len(progress), len(memories)))
        self.calls += 1
        action = (
            PlannerAction(
                action="memorize",
                value=f"fact {self.calls}",
                observation=f"Fact {self.calls} is visible.",
                progress_made=True,
                completed_subgoal=f"Saved fact {self.calls}",
                next_subgoal="Find another fact",
            )
            if self.calls <= 10
            else PlannerAction(action="infeasible")
        )
        return ModelResult(value=action, model="planner", latency_ms=1)

    async def ground(self, **_: object) -> ModelResult:
        raise AssertionError("memory must not call ground")

    async def verify(self, **_: object) -> ModelResult:
        raise AssertionError("memory must not call verify")


class DomOnlyBrowser(SequenceBrowser):
    async def observe(
        self,
        previous: BrowserObservation | None = None,
        path: Path | None = None,
    ) -> BrowserObservation:
        del path
        text = f'{{"ref":"n1","tag":"main","text":"state {self.state}"}}'
        dom = DomSnapshot(
            text=text,
            fingerprint=f"dom-{self.state}",
            nodes=(DomNode(key="main", text=text),),
        )
        change = DomChange()
        if previous is not None and previous.dom.fingerprint != dom.fingerprint:
            change = DomChange(summary=f"~ {text}", changed=1, meaningful=True)
        return BrowserObservation(
            screenshot=b"fixed",
            screenshot_fingerprint="fixed",
            dom=dom,
            change=change,
            url="https://example.com",
        )


class ClickThenInfeasibleModels:
    def __init__(self) -> None:
        self.calls = 0

    async def plan(self, **_: object) -> ModelResult:
        self.calls += 1
        action = (
            PlannerAction(action="click", element_description="button", progress_made=True)
            if self.calls == 1
            else PlannerAction(action="infeasible")
        )
        return ModelResult(value=action, model="planner", latency_ms=1)

    async def ground(self, **_: object) -> ModelResult:
        return ModelResult(
            value=GroundedPoint(x=10, y=10),
            model="grounder",
            latency_ms=1,
        )

    async def verify(self, **_: object) -> ModelResult:
        raise AssertionError("verify must not be called")


@pytest.mark.asyncio
async def test_agent_completes_local_task_and_logs_steps(tmp_path: Path) -> None:
    viewport = Dimensions(width=1280, height=720)
    log_path = tmp_path / "steps.jsonl"
    fixture_url = (Path(__file__).parent / "fixtures/site/index.html").resolve().as_uri()

    async with Browser(viewport) as browser:
        result = await Agent(
            browser,
            CannedModels(),
            max_steps=5,
            run_log=RunLog(log_path),
        ).run("Complete the form", fixture_url)
        assert browser.page is not None
        assert await browser.page.locator("#result").text_content() == "Success"

    records = [
        json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()
    ]
    assert result.outcome == "done"
    assert result.answer == "Success"
    assert result.steps == 3
    assert [record["outcome"] for record in records] == ["executed", "executed", "done"]
    assert records[0]["point"] == {"x": 640.0, "y": 283.0}


@pytest.mark.asyncio
async def test_type_replaces_existing_text() -> None:
    viewport = Dimensions(width=1280, height=720)
    fixture_url = (Path(__file__).parent / "fixtures/site/index.html").resolve().as_uri()

    async with Browser(viewport) as browser:
        await browser.navigate(fixture_url)
        assert browser.page is not None
        await browser.page.locator("#name").fill("old")
        await browser.execute(
            PlannerAction(
                action=Action.TYPE,
                element_description="Agent name input",
                value="Sherpa",
            ),
            GroundedPoint(x=640, y=283),
        )
        assert await browser.page.locator("#name").input_value() == "Sherpa"


@pytest.mark.asyncio
async def test_select_chooses_option_by_text() -> None:
    viewport = Dimensions(width=1280, height=720)

    async with Browser(viewport) as browser:
        assert browser.page is not None
        await browser.page.set_content(
            '<select style="position:absolute;left:100px;top:100px;width:200px;height:40px">'
            '<option>Choose</option><option>No</option></select>'
        )
        await browser.execute(
            PlannerAction(
                action=Action.SELECT,
                element_description="sponsorship dropdown",
                value="No",
            ),
            GroundedPoint(x=200, y=120),
        )
        assert await browser.page.locator("select").input_value() == "No"


@pytest.mark.asyncio
async def test_select_rejects_non_dropdown_target() -> None:
    viewport = Dimensions(width=1280, height=720)

    async with Browser(viewport) as browser:
        assert browser.page is not None
        await browser.page.set_content(
            '<button style="position:absolute;left:100px;top:100px;width:200px;height:40px">'
            "Submit</button>"
        )
        with pytest.raises(ValueError, match="not a dropdown"):
            await browser.execute(
                PlannerAction(
                    action=Action.SELECT,
                    element_description="sponsorship dropdown",
                    value="No",
                ),
                GroundedPoint(x=200, y=120),
            )


@pytest.mark.asyncio
async def test_scroll_home_and_end_recovery_actions() -> None:
    viewport = Dimensions(width=1280, height=720)

    async with Browser(viewport) as browser:
        assert browser.page is not None
        await browser.page.set_content('<div style="height:4000px">Long page</div>')
        await browser.execute(PlannerAction(action=Action.SCROLL_END), None)
        assert await browser.page.evaluate("scrollY") > 0
        await browser.execute(PlannerAction(action=Action.SCROLL_HOME), None)
        assert await browser.page.evaluate("scrollY") == 0


@pytest.mark.asyncio
async def test_agent_recovers_from_planner_failure(tmp_path: Path) -> None:
    viewport = Dimensions(width=1280, height=720)
    fixture_url = (Path(__file__).parent / "fixtures/site/index.html").resolve().as_uri()

    async with Browser(viewport) as browser:
        result = await Agent(
            browser,
            FlakyModels(),
            max_steps=5,
            max_corrections=3,
            run_log=RunLog(tmp_path / "steps.jsonl"),
        ).run("Complete the form", fixture_url)

    outcomes = [
        json.loads(line)["outcome"]
        for line in (tmp_path / "steps.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert result.outcome == "done"
    assert outcomes == ["error", "error", "executed", "executed", "done"]


@pytest.mark.asyncio
async def test_internal_protocol_retry_does_not_consume_agent_step_or_correction(
    tmp_path: Path,
) -> None:
    log_path = tmp_path / "steps.jsonl"
    result = await Agent(
        SequenceBrowser(),  # type: ignore[arg-type]
        InternallyRetriedModels(),
        max_steps=1,
        max_corrections=1,
        run_log=RunLog(log_path),
    ).run("Find the answer", "https://example.com")

    record = json.loads(log_path.read_text())
    assert result.outcome == "done"
    assert result.steps == 1
    assert record["outcome"] == "done"
    assert record["model_attempts"] == 3
    assert record["protocol_retry"] is True
    assert record["protocol_error_category"] == "invalid_json"


@pytest.mark.asyncio
async def test_agent_preserves_usage_when_grounder_fails(tmp_path: Path) -> None:
    viewport = Dimensions(width=1280, height=720)
    fixture_url = (Path(__file__).parent / "fixtures/site/index.html").resolve().as_uri()
    log_path = tmp_path / "steps.jsonl"

    async with Browser(viewport) as browser:
        result = await Agent(
            browser,
            PaidGroundFailure(),
            max_steps=1,
            max_corrections=1,
            run_log=RunLog(log_path),
        ).run("Click Complete", fixture_url)

    record = json.loads(log_path.read_text(encoding="utf-8"))
    assert result.outcome == "correction_limit"
    assert result.usage == ModelUsage(input_tokens=30, output_tokens=3, cost_usd=0.03)
    assert record["model"] == "planner,grounder"
    assert record["usage"]["cost_usd"] == 0.03


@pytest.mark.asyncio
async def test_agent_recovers_after_verifier_rejects_answer(tmp_path: Path) -> None:
    models = RejectedThenAcceptedModels()
    result = await Agent(
        SequenceBrowser(),  # type: ignore[arg-type]
        models,
        max_steps=3,
        run_log=RunLog(tmp_path / "steps.jsonl"),
    ).run("Find the answer", "https://example.com")

    records = [
        json.loads(line) for line in (tmp_path / "steps.jsonl").read_text().splitlines()
    ]
    assert result.outcome == "done"
    assert result.answer == "good"
    assert result.usage.cost_usd == pytest.approx(0.06)
    assert [record["outcome"] for record in records] == ["verification_rejected", "done"]
    assert records[0]["verifier_reason"] == "missing visible evidence"


@pytest.mark.asyncio
async def test_agent_blocks_fourth_unproductive_scroll(tmp_path: Path) -> None:
    result = await Agent(
        SequenceBrowser(),  # type: ignore[arg-type]
        ScrollingModels(),
        max_steps=4,
        run_log=RunLog(tmp_path / "steps.jsonl"),
    ).run("Find a result", "https://example.com")

    records = [
        json.loads(line) for line in (tmp_path / "steps.jsonl").read_text().splitlines()
    ]
    assert result.outcome == "max_steps"
    assert [record["outcome"] for record in records] == [
        "executed",
        "executed",
        "executed",
        "stagnation",
    ]
    assert records[-1]["error_category"] == "stagnation"


@pytest.mark.asyncio
async def test_agent_detects_multi_step_repeated_action_cycle(tmp_path: Path) -> None:
    result = await Agent(
        SequenceBrowser(),  # type: ignore[arg-type]
        RepeatedClickModels(),
        max_steps=3,
        run_log=RunLog(tmp_path / "steps.jsonl"),
    ).run("Navigate", "https://example.com")

    records = [
        json.loads(line) for line in (tmp_path / "steps.jsonl").read_text().splitlines()
    ]
    assert result.outcome == "max_steps"
    assert [record["outcome"] for record in records] == ["executed", "executed", "cycle"]


@pytest.mark.asyncio
async def test_progress_and_memory_are_bounded_to_eight_entries() -> None:
    models = MemoryModels()
    result = await Agent(
        SequenceBrowser(),  # type: ignore[arg-type]
        models,
        max_steps=11,
    ).run("Collect facts", "https://example.com")

    assert result.outcome == "infeasible"
    assert models.context_sizes[-1] == (8, 8)


@pytest.mark.asyncio
async def test_dom_only_change_counts_as_progress_and_is_not_logged_raw(tmp_path: Path) -> None:
    log_path = tmp_path / "steps.jsonl"
    result = await Agent(
        DomOnlyBrowser(),
        ClickThenInfeasibleModels(),
        max_steps=2,
        max_corrections=1,
        run_log=RunLog(log_path),
    ).run("Click the button", "https://example.com")

    records = [json.loads(line) for line in log_path.read_text().splitlines()]
    assert result.outcome == "infeasible"
    assert records[0]["outcome"] == "executed"
    assert records[0]["state_before"] == records[0]["state_after"]
    assert records[0]["dom_before"] != records[0]["dom_after"]
    assert '"text":"state' not in log_path.read_text()


@pytest.mark.asyncio
async def test_real_menu_expansion_reaches_next_plan_as_semantic_diff() -> None:
    class MenuModels:
        def __init__(self, point: GroundedPoint) -> None:
            self.point = point
            self.histories: list[list[DomHistoryEntry]] = []

        async def plan(self, **kwargs: object) -> ModelResult:
            history = kwargs["dom_history"]
            assert isinstance(history, list)
            self.histories.append(list(history))
            action = (
                PlannerAction(action="click", element_description="Solutions button")
                if len(self.histories) == 1
                else PlannerAction(action="infeasible")
            )
            return ModelResult(value=action, model="planner", latency_ms=1)

        async def ground(self, **_: object) -> ModelResult:
            return ModelResult(value=self.point, model="grounder", latency_ms=1)

        async def verify(self, **_: object) -> ModelResult:
            raise AssertionError("verify must not be called")

    viewport = Dimensions(width=800, height=600)
    fixture = (
        Path(__file__).parent / "fixtures" / "dom" / "03-nav-heavy.html"
    ).resolve().as_uri()
    async with Browser(viewport) as browser:
        await browser.navigate(fixture)
        assert browser.page is not None
        box = await browser.page.locator("#menu").bounding_box()
        assert box is not None
        models = MenuModels(
            GroundedPoint(x=box["x"] + box["width"] / 2, y=box["y"] + box["height"] / 2)
        )
        result = await Agent(browser, models, max_steps=2).run("Open solutions", fixture)

    assert result.outcome == "infeasible"
    assert [entry.mode for entry in models.histories[0]] == ["full"]
    assert [entry.mode for entry in models.histories[1]] == ["full", "diff"]
    assert "Teams" in models.histories[1][1].semantic_changes


@pytest.mark.asyncio
async def test_agent_accumulates_full_dom_then_diffs_and_skips_unchanged() -> None:
    class HistoryBrowser:
        viewport = Dimensions(width=800, height=600)

        def __init__(self) -> None:
            self.state = 0

        async def navigate(self, _: str) -> None:
            return None

        async def observe(
            self,
            previous: BrowserObservation | None = None,
            path: Path | None = None,
        ) -> BrowserObservation:
            del path
            full = previous is None
            changed = previous is not None and self.state == 1
            dom = DomSnapshot(
                controls_text='[button] "Next"',
                content_markdown="# Initial fact",
                fingerprint=f"dom-{self.state}",
            )
            return BrowserObservation(
                screenshot=f"state-{self.state}".encode(),
                screenshot_fingerprint=f"state-{self.state}",
                dom=dom,
                change=DomChange(
                    page_changed=full,
                    summary='+ [button] "Compare"' if changed else "",
                    meaningful=changed,
                ),
                url="https://example.com/",
            )

        async def execute(self, *_: object) -> None:
            self.state += 1

    class HistoryModels:
        def __init__(self) -> None:
            self.histories: list[list[DomHistoryEntry]] = []

        async def plan(self, **kwargs: object) -> ModelResult:
            history = kwargs["dom_history"]
            assert isinstance(history, list)
            self.histories.append(list(history))
            action = (
                PlannerAction(action="scroll", value="down")
                if len(self.histories) < 3
                else PlannerAction(action="infeasible")
            )
            return ModelResult(value=action, model="planner", latency_ms=1)

        async def ground(self, **_: object) -> ModelResult:
            raise AssertionError("scroll must not call ground")

        async def verify(self, **_: object) -> ModelResult:
            raise AssertionError("infeasible must not call verify")

    models = HistoryModels()
    result = await Agent(
        HistoryBrowser(),  # type: ignore[arg-type]
        models,
        max_steps=3,
    ).run("Find fact", "https://example.com/")

    assert result.outcome == "infeasible"
    assert [len(history) for history in models.histories] == [1, 2, 2]
    assert [entry.mode for entry in models.histories[-1]] == ["full", "diff"]
    assert models.histories[-1][0].main_content == "# Initial fact"


@pytest.mark.asyncio
async def test_sufficient_evidence_finishes_and_verifier_gets_current_dom() -> None:
    class EvidenceBrowser(SequenceBrowser):
        async def observe(
            self,
            previous: BrowserObservation | None = None,
            path: Path | None = None,
        ) -> BrowserObservation:
            del path
            return BrowserObservation(
                screenshot=b"course-result",
                screenshot_fingerprint="course-result",
                dom=DomSnapshot(
                    content_markdown=(
                        "# Programming for Everybody\nBeginner course, University of Michigan"
                    ),
                    fingerprint="course-dom",
                ),
                change=DomChange(page_changed=previous is None),
                url="https://example.com/search?q=python",
            )

        async def execute(self, *_: object) -> None:
            raise AssertionError("sufficient evidence must not trigger navigation")

    class EvidenceModels:
        content: str | None = None

        async def plan(self, **_: object) -> ModelResult:
            return ModelResult(
                value=PlannerAction(
                    action="done",
                    value="Programming for Everybody by University of Michigan (Beginner)",
                ),
                model="planner",
                latency_ms=1,
            )

        async def ground(self, **_: object) -> ModelResult:
            raise AssertionError("done must not ground")

        async def verify(self, **kwargs: object) -> ModelResult:
            value = kwargs.get("dom")
            assert isinstance(value, DomSnapshot)
            self.content = value.content_markdown
            return ModelResult(
                value=VerificationResult(accepted=True, reason="Result item proves the task"),
                model="planner",
                latency_ms=1,
            )

    models = EvidenceModels()
    result = await Agent(
        EvidenceBrowser(),  # type: ignore[arg-type]
        models,
        max_steps=1,
    ).run("Find a beginner Python course", "https://example.com/search?q=python")

    assert result.outcome == "done"
    assert models.content is not None
    assert models.content.startswith("# Programming for Everybody")


def test_enumeration_gate_requires_distinct_items() -> None:
    from sherpa.agent import _enumeration_gate

    assert _enumeration_gate(
        "What repair options are mentioned, answer 2 of them.",
        "Warranty only",
    )
    assert (
        _enumeration_gate(
            "What repair options are mentioned, answer 2 of them.",
            "Mail-in repair and in-store service",
        )
        is None
    )
    # Vague "how many" alone does not force a minimum list length.
    assert (
        _enumeration_gate(
            "Find headphones and how many models are currently available.",
            "There are 4 models currently available.",
        )
        is None
    )
    # Claimed "N ...: a, b" under-lists must fail.
    assert _enumeration_gate(
        "Find headphones and how many models are currently available.",
        "There are 4 models: Pro Max.",
    )
    assert (
        _enumeration_gate(
            "Find headphones and how many models are currently available.",
            "There are 4 models: Pro Max, Pro, Standard, and Standard ANC.",
        )
        is None
    )
    # A separate total must not be treated as the enumerated claim.
    assert (
        _enumeration_gate(
            "How many teams are there and list all the teams with 'New' in their name.",
            "There are 30 teams. The teams with 'New' in their name are: "
            "New York and New Orleans.",
        )
        is None
    )


def test_search_scroll_stagnation_requires_same_url_without_typing() -> None:
    from sherpa.agent import _search_scroll_stagnation
    from sherpa.types import ProgressEntry

    current = BrowserObservation(
        screenshot=b"png",
        screenshot_fingerprint="a",
        dom=DomSnapshot(fingerprint="d"),
        change=DomChange(),
        url="https://example.com/search?q=climate",
        scroll_x=0,
        scroll_y=100,
    )
    attempted = [
        ProgressEntry(
            step=index,
            action=Action.SCROLL,
            value="down",
            outcome="executed",
            state_before=f"before-{index}",
            state_after=f"after-{index}",
            url_before="https://example.com/search?q=climate",
            url_after="https://example.com/search?q=climate",
        )
        for index in range(1, 4)
    ]
    reason = _search_scroll_stagnation(
        PlannerAction(action=Action.SCROLL, value="down"),
        attempted,
        current,
    )
    assert reason is not None
    assert reason[0] == "stagnation"
    assert "Change the query" in reason[1]


@pytest.mark.asyncio
async def test_enumeration_gate_rejects_done_before_verifier(tmp_path: Path) -> None:
    class GateModels:
        def __init__(self) -> None:
            self.verified = False

        async def plan(self, **_: object) -> ModelResult:
            return ModelResult(
                value=PlannerAction(
                    action="done",
                    value="Warranty only",
                ),
                model="planner",
                latency_ms=1,
            )

        async def ground(self, **_: object) -> ModelResult:
            raise AssertionError("done must not ground")

        async def verify(self, **_: object) -> ModelResult:
            self.verified = True
            raise AssertionError("enumeration gate should reject before verify")

    models = GateModels()
    result = await Agent(
        SequenceBrowser(),  # type: ignore[arg-type]
        models,
        max_steps=1,
        max_corrections=1,
        run_log=RunLog(tmp_path / "steps.jsonl"),
    ).run(
        "What repair options are mentioned, answer 2 of them.",
        "https://example.com",
    )
    record = json.loads((tmp_path / "steps.jsonl").read_text(encoding="utf-8"))
    assert result.outcome == "correction_limit"
    assert models.verified is False
    assert record["outcome"] == "verification_rejected"
    assert record["missing_evidence"]
