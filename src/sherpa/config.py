import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    api_key: str | None
    planner_model: str
    grounder_model: str
    planner_reasoning_effort: str = "high"
    max_steps: int = 20
    max_corrections: int = 5
    timeout_seconds: float = 45.0
    viewport_width: int = 1280
    viewport_height: int = 720
    planner_input_per_million: float = 0.14
    planner_output_per_million: float = 1.00
    grounder_input_per_million: float = 0.10
    grounder_output_per_million: float = 0.20

    def __post_init__(self) -> None:
        if self.max_steps <= 0:
            raise ValueError("max_steps must be greater than zero")
        if self.max_corrections <= 0:
            raise ValueError("max_corrections must be greater than zero")
        if self.planner_reasoning_effort not in {
            "none",
            "minimal",
            "low",
            "medium",
            "high",
            "xhigh",
            "max",
        }:
            raise ValueError("planner_reasoning_effort is invalid")

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            api_key=os.getenv("OPENROUTER_API_KEY"),
            planner_model=os.getenv("SHERPA_PLANNER_MODEL", "qwen/qwen3.5-35b-a3b"),
            grounder_model=os.getenv("SHERPA_GROUNDER_MODEL", "bytedance/ui-tars-1.5-7b"),
            planner_reasoning_effort=os.getenv(
                "SHERPA_PLANNER_REASONING_EFFORT",
                "high",
            ),
            max_steps=int(os.getenv("SHERPA_MAX_STEPS", "20")),
            max_corrections=int(os.getenv("SHERPA_MAX_CORRECTIONS", "5")),
            timeout_seconds=float(os.getenv("SHERPA_TIMEOUT_SECONDS", "45")),
            viewport_width=int(os.getenv("SHERPA_VIEWPORT_WIDTH", "1280")),
            viewport_height=int(os.getenv("SHERPA_VIEWPORT_HEIGHT", "720")),
        )

    def model_prices(self, model: str) -> tuple[float, float]:
        if model == self.planner_model:
            return self.planner_input_per_million, self.planner_output_per_million
        if model == self.grounder_model:
            return self.grounder_input_per_million, self.grounder_output_per_million
        return 0.0, 0.0
