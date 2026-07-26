from enum import StrEnum

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator


class Action(StrEnum):
    CLICK = "click"
    TYPE = "type"
    SELECT = "select"
    SCROLL = "scroll"
    SCROLL_HOME = "scroll_home"
    SCROLL_END = "scroll_end"
    GO_BACK = "go_back"
    MEMORIZE = "memorize"
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
    element_description: str | None = Field(
        default=None,
        validation_alias=AliasChoices("element_description", "target"),
    )
    value: str | None = None
    reasoning: str = ""
    observation: str = ""
    progress_made: bool = False
    completed_subgoal: str | None = None
    next_subgoal: str | None = None

    @model_validator(mode="after")
    def validate_action_fields(self) -> "PlannerAction":
        if self.needs_target() and not self.element_description:
            raise ValueError(f"{self.action} requires element_description")
        if self.action is Action.TYPE and self.value is None:
            raise ValueError("type requires value")
        if self.action is Action.SELECT and self.value is None:
            raise ValueError("select requires value")
        if self.action is Action.MEMORIZE and self.value is None:
            raise ValueError("memorize requires value")
        if self.action is Action.SCROLL and self.value not in {"up", "down"}:
            raise ValueError("scroll requires value 'up' or 'down'")
        return self

    def needs_target(self) -> bool:
        return self.action in {Action.CLICK, Action.TYPE, Action.SELECT}


class GroundedPoint(BaseModel):
    model_config = ConfigDict(frozen=True)

    x: float
    y: float


class DomNode(BaseModel):
    model_config = ConfigDict(frozen=True)

    key: str
    text: str
    interactive: bool = False
    in_viewport: bool = False


class ContentBlock(BaseModel):
    model_config = ConfigDict(frozen=True)

    key: str
    text: str


class DomSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    controls_text: str = Field(default="", exclude=True)
    content_markdown: str = Field(default="", exclude=True)
    controls_fingerprint: str = ""
    content_fingerprint: str = ""
    raw_control_count: int = Field(default=0, ge=0)
    control_count: int = Field(default=0, ge=0)
    content_block_count: int = Field(default=0, ge=0)
    controls_char_count: int = Field(default=0, ge=0)
    content_char_count: int = Field(default=0, ge=0)
    controls_truncated: bool = False
    content_truncated: bool = False
    controls_error: str | None = None
    content_error: str | None = None
    control_nodes: tuple[DomNode, ...] = Field(default=(), exclude=True)
    content_blocks: tuple[ContentBlock, ...] = Field(default=(), exclude=True)
    fingerprint: str


class DomChange(BaseModel):
    model_config = ConfigDict(frozen=True)

    controls_summary: str = Field(default="", exclude=True)
    content_summary: str = Field(default="", exclude=True)
    summary: str = Field(default="", exclude=True)
    added: int = Field(default=0, ge=0)
    removed: int = Field(default=0, ge=0)
    changed: int = Field(default=0, ge=0)
    content_added: int = Field(default=0, ge=0)
    content_removed: int = Field(default=0, ge=0)
    content_changed: int = Field(default=0, ge=0)
    truncated: bool = False
    meaningful: bool = False
    page_changed: bool = False
    scroll_suppressed: bool = False


class DomHistoryEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    step: int = Field(ge=1)
    url: str
    mode: str
    controls_text: str = Field(default="", exclude=True)
    main_content: str = Field(default="", exclude=True)
    semantic_changes: str = Field(default="", exclude=True)
    truncated: bool = False
    error: str | None = None


class BrowserObservation(BaseModel):
    model_config = ConfigDict(frozen=True)

    screenshot: bytes = Field(exclude=True)
    screenshot_fingerprint: str
    dom: DomSnapshot
    change: DomChange
    url: str
    scroll_x: float = 0
    scroll_y: float = 0


class ProgressEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    step: int = Field(ge=1)
    action: Action | None = None
    target: str | None = None
    value: str | None = None
    observation: str = ""
    progress_made: bool = False
    completed_subgoal: str | None = None
    next_subgoal: str | None = None
    outcome: str
    state_before: str
    state_after: str | None = None
    dom_before: str | None = None
    dom_after: str | None = None
    url_before: str | None = None
    url_after: str | None = None
    scroll_before: tuple[float, float] | None = None
    scroll_after: tuple[float, float] | None = None


class VerificationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    accepted: bool
    reason: str
    corrected_answer: str | None = None
    missing_evidence: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def corrected_answer_requires_acceptance(self) -> "VerificationResult":
        if self.corrected_answer is not None and not self.accepted:
            raise ValueError("corrected_answer requires accepted=true")
        return self


class ModelUsage(BaseModel):
    model_config = ConfigDict(frozen=True)

    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cost_usd: float = Field(default=0, ge=0)


class ModelResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    value: PlannerAction | GroundedPoint | VerificationResult
    model: str
    latency_ms: int = Field(ge=0)
    usage: ModelUsage = ModelUsage()
    model_attempts: int = Field(default=1, ge=1)
    protocol_retry: bool = False
    finish_reason: str | None = None
    protocol_error_category: str | None = None


class StepResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    step: int = Field(ge=1)
    action: Action | None = None
    model: str | None = None
    latency_ms: int = Field(default=0, ge=0)
    usage: ModelUsage = ModelUsage()
    planner_input_tokens: int = Field(default=0, ge=0)
    grounding_attempts: int = Field(default=0, ge=0)
    model_attempts: int = Field(default=1, ge=1)
    protocol_retry: bool = False
    finish_reason: str | None = None
    protocol_error_category: str | None = None
    point: GroundedPoint | None = None
    target: str | None = None
    value: str | None = None
    outcome: str
    error_category: str | None = None
    error_message: str | None = None
    observation: str = ""
    progress_made: bool = False
    completed_subgoal: str | None = None
    next_subgoal: str | None = None
    memory: str | None = None
    state_before: str | None = None
    state_after: str | None = None
    dom_before: str | None = None
    dom_after: str | None = None
    url_before: str | None = None
    url_after: str | None = None
    scroll_before: tuple[float, float] | None = None
    scroll_after: tuple[float, float] | None = None
    dom_truncated: bool = False
    dom_error: str | None = None
    dom_added: int = Field(default=0, ge=0)
    dom_removed: int = Field(default=0, ge=0)
    dom_changed: int = Field(default=0, ge=0)
    dom_content_added: int = Field(default=0, ge=0)
    dom_content_removed: int = Field(default=0, ge=0)
    dom_content_changed: int = Field(default=0, ge=0)
    dom_raw_controls: int = Field(default=0, ge=0)
    dom_controls: int = Field(default=0, ge=0)
    dom_control_chars: int = Field(default=0, ge=0)
    dom_content_chars: int = Field(default=0, ge=0)
    dom_diff_chars: int = Field(default=0, ge=0)
    dom_context_chars: int = Field(default=0, ge=0)
    dom_context_mode: str | None = None
    dom_controls_truncated: bool = False
    dom_content_truncated: bool = False
    verifier_reason: str | None = None


class AgentRunResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    outcome: str
    answer: str | None = None
    steps: int = Field(default=0, ge=0)
    latency_ms: int = Field(default=0, ge=0)
    usage: ModelUsage = ModelUsage()
