import json
from pathlib import Path

import pytest

from sherpa.agent import Agent
from sherpa.browser import Browser
from sherpa.models import ModelResponseError
from sherpa.runlog import RunLog
from sherpa.types import (
    Action,
    Dimensions,
    GroundedPoint,
    ModelResult,
    PlannerAction,
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
                PlannerAction(action="done"),
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


@pytest.mark.asyncio
async def test_agent_completes_local_task_and_logs_steps(tmp_path: Path) -> None:
    viewport = Dimensions(width=1280, height=720)
    log_path = tmp_path / "steps.jsonl"
    fixture_url = (Path(__file__).parent / "fixtures/site/index.html").resolve().as_uri()

    async with Browser(viewport) as browser:
        outcome = await Agent(
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
    assert outcome == "done"
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
async def test_agent_recovers_from_planner_failure(tmp_path: Path) -> None:
    viewport = Dimensions(width=1280, height=720)
    fixture_url = (Path(__file__).parent / "fixtures/site/index.html").resolve().as_uri()

    async with Browser(viewport) as browser:
        outcome = await Agent(
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
    assert outcome == "done"
    assert outcomes == ["error", "error", "executed", "executed", "done"]
