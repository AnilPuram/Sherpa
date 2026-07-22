import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from sherpa.types import Dimensions, GroundedPoint, ModelResult

Ground = Callable[..., Awaitable[ModelResult]]


class GroundingCase(BaseModel):
    model_config = ConfigDict(frozen=True)

    screenshot: str
    instruction: str
    box: tuple[float, float, float, float]
    image_width: int = Field(gt=0)
    image_height: int = Field(gt=0)


def point_in_box(point: GroundedPoint, box: tuple[float, float, float, float]) -> bool:
    left, top, right, bottom = box
    return left <= point.x <= right and top <= point.y <= bottom


async def evaluate_grounding(
    manifest: Path,
    ground: Ground,
    *,
    output: Path | None = None,
) -> dict[str, Any]:
    cases = _load_cases(manifest)
    hits = 0
    errors = 0
    error_details: list[dict[str, str]] = []
    latency_ms = 0
    input_tokens = 0
    output_tokens = 0
    cost_usd = 0.0

    for case in cases:
        try:
            result = await ground(
                description=case.instruction,
                image=(manifest.parent / case.screenshot).read_bytes(),
                image_size=Dimensions(width=case.image_width, height=case.image_height),
            )
            if not isinstance(result.value, GroundedPoint):
                raise TypeError("grounder returned the wrong result type")
            hits += point_in_box(result.value, case.box)
            latency_ms += result.latency_ms
            input_tokens += result.usage.input_tokens
            output_tokens += result.usage.output_tokens
            cost_usd += result.usage.cost_usd
        except Exception as exc:  # One bad case should not hide the rest of the evaluation.
            errors += 1
            error_details.append(
                {"instruction": case.instruction, "error": f"{type(exc).__name__}: {exc}"}
            )

    total = len(cases)
    report = {
        "cases": total,
        "hits": hits,
        "errors": errors,
        "error_details": error_details,
        "accuracy": hits / total if total else 0.0,
        "latency_ms": latency_ms,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": round(cost_usd, 8),
    }
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def _load_cases(manifest: Path) -> list[GroundingCase]:
    cases: list[GroundingCase] = []
    for number, line in enumerate(manifest.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            cases.append(GroundingCase.model_validate_json(line))
        except ValueError as exc:
            raise ValueError(f"Invalid manifest line {number}: {exc}") from exc
    if not cases:
        raise ValueError("Grounding manifest is empty")
    return cases
