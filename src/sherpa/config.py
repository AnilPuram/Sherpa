import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    api_key: str | None
    planner_model: str
    grounder_model: str
    max_steps: int = 12
    max_corrections: int = 3
    timeout_seconds: float = 45.0
    viewport_width: int = 1280
    viewport_height: int = 720
    planner_input_per_million: float = 1.20
    planner_output_per_million: float = 4.00
    grounder_input_per_million: float = 0.13
    grounder_output_per_million: float = 0.52

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            api_key=os.getenv("OPENROUTER_API_KEY"),
            planner_model=os.getenv("SHERPA_PLANNER_MODEL", "z-ai/glm-5v-turbo"),
            grounder_model=os.getenv(
                "SHERPA_GROUNDER_MODEL", "qwen/qwen3-vl-30b-a3b-instruct"
            ),
            max_steps=int(os.getenv("SHERPA_MAX_STEPS", "12")),
            max_corrections=int(os.getenv("SHERPA_MAX_CORRECTIONS", "3")),
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
