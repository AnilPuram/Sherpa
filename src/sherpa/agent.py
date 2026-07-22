from pathlib import Path
from typing import Protocol

from sherpa.browser import Browser
from sherpa.coordinates import image_to_viewport, require_in_viewport
from sherpa.runlog import RunLog
from sherpa.types import (
    Action,
    Dimensions,
    GroundedPoint,
    ModelResult,
    ModelUsage,
    PlannerAction,
    StepResult,
)


class Models(Protocol):
    async def plan(
        self,
        *,
        task: str,
        image: bytes,
        image_size: Dimensions,
        history: list[PlannerAction],
        feedback: str | None = None,
    ) -> ModelResult: ...

    async def ground(
        self,
        *,
        description: str,
        image: bytes,
        image_size: Dimensions,
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

    async def run(self, task: str, start_url: str) -> str:
        await self.browser.navigate(start_url)
        history: list[PlannerAction] = []
        previous_signature: tuple[Action, str | None, str | None] | None = None
        corrections = 0
        feedback: str | None = None

        for step in range(1, self.max_steps + 1):
            try:
                screenshot_path = (
                    self.screenshot_dir / f"step-{step:02}.png" if self.screenshot_dir else None
                )
                image = await self.browser.screenshot(screenshot_path)
                image_size = self.browser.viewport
                planned = await self.models.plan(
                    task=task,
                    image=image,
                    image_size=image_size,
                    history=history,
                    feedback=feedback,
                )
                if not isinstance(planned.value, PlannerAction):
                    raise TypeError("planner returned the wrong result type")
                action = planned.value
                target = action.element_description if action.needs_target() else None
                value = (
                    action.value
                    if action.action in {Action.TYPE, Action.SELECT, Action.SCROLL}
                    else None
                )
                signature = (action.action, target, value)
                if signature == previous_signature:
                    self.run_log.append(
                        StepResult(
                            step=step,
                            action=action.action,
                            model=planned.model,
                            latency_ms=planned.latency_ms,
                            usage=planned.usage,
                            outcome="loop",
                            error_category="repeated_action",
                        )
                    )
                    corrections += 1
                    feedback = (
                        "Repeated action was blocked. Reassess the screenshot and choose "
                        "another action."
                    )
                    if corrections >= self.max_corrections:
                        return "correction_limit"
                    continue

                if action.action in {Action.DONE, Action.INFEASIBLE}:
                    self.run_log.append(
                        StepResult(
                            step=step,
                            action=action.action,
                            model=planned.model,
                            latency_ms=planned.latency_ms,
                            usage=planned.usage,
                            outcome=action.action.value,
                        )
                    )
                    return action.action.value

                point = None
                ground_result = None
                if action.needs_target():
                    ground_result = await self.models.ground(
                        description=action.element_description or "",
                        image=image,
                        image_size=image_size,
                    )
                    if not isinstance(ground_result.value, GroundedPoint):
                        raise TypeError("grounder returned the wrong result type")
                    point = image_to_viewport(
                        ground_result.value,
                        image_size,
                        self.browser.viewport,
                    )
                    require_in_viewport(point, self.browser.viewport)

                await self.browser.execute(action, point)
                previous_signature = signature
                changed = await self.browser.screenshot() != image
                usage = _add_usage(planned.usage, ground_result.usage if ground_result else None)
                self.run_log.append(
                    StepResult(
                        step=step,
                        action=action.action,
                        model=_model_names(planned, ground_result),
                        latency_ms=planned.latency_ms
                        + (ground_result.latency_ms if ground_result else 0),
                        usage=usage,
                        point=point,
                        outcome="executed" if changed else "no_state_change",
                        error_category=None if changed else "verification",
                    )
                )
                if not changed:
                    corrections += 1
                    feedback = (
                        "The last action caused no visible page change. Reassess the target or "
                        "choose a different action."
                    )
                    if corrections >= self.max_corrections:
                        return "correction_limit"
                    continue
                history.append(action)
                previous_signature = None
                corrections = 0
                feedback = None
            except Exception as exc:
                corrections += 1
                self.run_log.append(
                    StepResult(
                        step=step,
                        outcome="error",
                        error_category=_error_category(exc),
                        error_message=str(exc),
                    )
                )
                feedback = (
                    f"The previous attempt failed ({_error_category(exc)}). "
                    "Reassess the current screenshot and try a valid next action."
                )
                if corrections >= self.max_corrections:
                    return "correction_limit"

        return "max_steps"
def _add_usage(first: ModelUsage, second: ModelUsage | None) -> ModelUsage:
    if second is None:
        return first
    return ModelUsage(
        input_tokens=first.input_tokens + second.input_tokens,
        output_tokens=first.output_tokens + second.output_tokens,
        cost_usd=first.cost_usd + second.cost_usd,
    )


def _model_names(first: ModelResult, second: ModelResult | None) -> str:
    return first.model if second is None else f"{first.model},{second.model}"


def _error_category(error: Exception) -> str:
    module = type(error).__module__
    if module.startswith("playwright"):
        return "execution"
    if isinstance(error, (ValueError, TypeError)):
        return "grounding"
    return "model"
