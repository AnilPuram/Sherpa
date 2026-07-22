from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Action(StrEnum):
    CLICK = "click"
    TYPE = "type"
    SELECT = "select"
    SCROLL = "scroll"
    PRESS_ENTER = "press_enter"
    DONE = "done"
    INFEASIBLE = "infeasible"


class Dimensions(BaseModel):
    model_config = ConfigDict(frozen=True)

    width: int = Field(gt=0)
    height: int = Field(gt=0)


class PlannerAction(BaseModel):
    model_config = ConfigDict(frozen=True)

    action: Action
    element_description: str | None = None
    value: str | None = None
    reasoning: str = ""

    @model_validator(mode="after")
    def validate_action_fields(self) -> "PlannerAction":
        if self.needs_target() and not self.element_description:
            raise ValueError(f"{self.action} requires element_description")
        if self.action is Action.TYPE and self.value is None:
            raise ValueError("type requires value")
        if self.action is Action.SELECT and self.value is None:
            raise ValueError("select requires value")
        if self.action is Action.SCROLL and self.value not in {"up", "down"}:
            raise ValueError("scroll requires value 'up' or 'down'")
        return self

    def needs_target(self) -> bool:
        return self.action in {Action.CLICK, Action.TYPE, Action.SELECT}


class GroundedPoint(BaseModel):
    model_config = ConfigDict(frozen=True)

    x: float
    y: float


class ModelUsage(BaseModel):
    model_config = ConfigDict(frozen=True)

    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cost_usd: float = Field(default=0, ge=0)


class ModelResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    value: PlannerAction | GroundedPoint
    model: str
    latency_ms: int = Field(ge=0)
    usage: ModelUsage = ModelUsage()


class StepResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    step: int = Field(ge=1)
    action: Action | None = None
    model: str | None = None
    latency_ms: int = Field(default=0, ge=0)
    usage: ModelUsage = ModelUsage()
    point: GroundedPoint | None = None
    outcome: str
    error_category: str | None = None
    error_message: str | None = None
