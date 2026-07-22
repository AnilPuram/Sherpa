import json
from pathlib import Path

import pytest

from sherpa.eval import evaluate_grounding, point_in_box
from sherpa.types import GroundedPoint, ModelResult, ModelUsage


def test_point_in_box_includes_edges() -> None:
    assert point_in_box(GroundedPoint(x=10, y=20), (10, 20, 30, 40))
    assert not point_in_box(GroundedPoint(x=9, y=20), (10, 20, 30, 40))


@pytest.mark.asyncio
async def test_evaluation_reports_accuracy_cost_and_errors(tmp_path: Path) -> None:
    (tmp_path / "screen.png").write_bytes(b"png")
    lines = [
        {
            "screenshot": "screen.png",
            "instruction": "hit",
            "box": [0, 0, 20, 20],
            "image_width": 100,
            "image_height": 100,
        },
        {
            "screenshot": "screen.png",
            "instruction": "error",
            "box": [0, 0, 20, 20],
            "image_width": 100,
            "image_height": 100,
        },
    ]
    manifest = tmp_path / "grounding.jsonl"
    manifest.write_text("\n".join(json.dumps(line) for line in lines), encoding="utf-8")

    async def ground(**kwargs) -> ModelResult:
        if kwargs["description"] == "error":
            raise RuntimeError("bad response")
        return ModelResult(
            value=GroundedPoint(x=10, y=10),
            model="fake",
            latency_ms=4,
            usage=ModelUsage(input_tokens=5, output_tokens=2, cost_usd=0.01),
        )

    report = await evaluate_grounding(manifest, ground)

    assert report == {
        "cases": 2,
        "hits": 1,
        "errors": 1,
        "error_details": [{"instruction": "error", "error": "RuntimeError: bad response"}],
        "accuracy": 0.5,
        "latency_ms": 4,
        "input_tokens": 5,
        "output_tokens": 2,
        "cost_usd": 0.01,
    }
