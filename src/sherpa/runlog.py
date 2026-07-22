import json
from pathlib import Path

from sherpa.types import StepResult


class RunLog:
    def __init__(self, path: Path | None) -> None:
        self.path = path

    def append(self, result: StepResult) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as output:
            output.write(json.dumps(result.model_dump(mode="json"), separators=(",", ":")) + "\n")
