import json

import pytest

from sherpa.config import Settings
from sherpa.models import ModelResponseError, OpenRouterClient
from sherpa.types import Action, Dimensions, GroundedPoint


def settings() -> Settings:
    return Settings(
        api_key=None,
        planner_model="planner",
        grounder_model="grounder",
    )


def response(content: dict, *, input_tokens: int = 100, output_tokens: int = 10) -> dict:
    return {
        "choices": [{"message": {"content": json.dumps(content)}}],
        "usage": {"prompt_tokens": input_tokens, "completion_tokens": output_tokens},
    }


@pytest.mark.asyncio
async def test_planner_parses_strict_action_and_usage() -> None:
    async def request(_: dict) -> dict:
        return response(
            {
                "action": "click",
                "element_description": "the blue Complete button at bottom center",
                "value": None,
                "reasoning": "Completes the form.",
            }
        )

    result = await OpenRouterClient(settings(), request).plan(
        task="Complete the form",
        image=b"png",
        image_size=Dimensions(width=100, height=100),
        history=[],
    )

    assert result.value.action is Action.CLICK
    assert result.usage.input_tokens == 100


@pytest.mark.asyncio
async def test_grounder_accepts_box_and_returns_center() -> None:
    async def request(_: dict) -> dict:
        return response({"box": [100, 200, 300, 600], "label": "button"})

    result = await OpenRouterClient(settings(), request).ground(
        description="button",
        image=b"png",
        image_size=Dimensions(width=100, height=100),
    )

    assert result.value == GroundedPoint(x=20, y=40)


@pytest.mark.asyncio
async def test_grounder_accepts_qwen_corner_pair_shape() -> None:
    async def request(_: dict) -> dict:
        return response({"x": [100, 200], "y": [300, 600]})

    result = await OpenRouterClient(settings(), request).ground(
        description="button",
        image=b"png",
        image_size=Dimensions(width=100, height=100),
    )

    assert result.value == GroundedPoint(x=20, y=40)


@pytest.mark.asyncio
async def test_grounder_accepts_qwen_bbox_2d() -> None:
    async def request(_: dict) -> dict:
        return response({"bbox_2d": [100, 200, 300, 600]})

    result = await OpenRouterClient(settings(), request).ground(
        description="button",
        image=b"png",
        image_size=Dimensions(width=100, height=100),
    )

    assert result.value == GroundedPoint(x=20, y=40)


@pytest.mark.asyncio
async def test_grounder_rejects_target_that_is_not_visible() -> None:
    async def request(_: dict) -> dict:
        return response({"bbox_2d": None})

    with pytest.raises(ModelResponseError, match="not safely visible"):
        await OpenRouterClient(settings(), request).ground(
            description="button",
            image=b"png",
            image_size=Dimensions(width=100, height=100),
        )


@pytest.mark.asyncio
async def test_grounder_rejects_unknown_shape() -> None:
    async def request(_: dict) -> dict:
        return response({"coordinates": [10, 20]})

    with pytest.raises(ModelResponseError, match="expected x/y or box"):
        await OpenRouterClient(settings(), request).ground(
            description="button",
            image=b"png",
            image_size=Dimensions(width=100, height=100),
        )


def test_cost_uses_configured_model_prices() -> None:
    configured = Settings(
        api_key=None,
        planner_model="planner",
        grounder_model="grounder",
        planner_input_per_million=1,
        planner_output_per_million=2,
    )
    client = OpenRouterClient(configured, request=lambda _: None)  # type: ignore[arg-type]

    usage = client._usage(  # noqa: SLF001
        {"usage": {"prompt_tokens": 1_000_000, "completion_tokens": 500_000}},
        "planner",
    )

    assert usage.cost_usd == 2


def test_cost_prefers_openrouter_reported_amount() -> None:
    client = OpenRouterClient(settings(), request=lambda _: None)  # type: ignore[arg-type]

    usage = client._usage(  # noqa: SLF001
        {
            "usage": {
                "prompt_tokens": 1_000_000,
                "completion_tokens": 500_000,
                "cost": 0.42,
            }
        },
        "planner",
    )

    assert usage.cost_usd == 0.42


def test_gpt5_payload_disables_reasoning_for_atomic_planning() -> None:
    configured = Settings(
        api_key=None,
        planner_model="openai/gpt-5.5",
        grounder_model="grounder",
    )
    client = OpenRouterClient(configured, request=lambda _: None)  # type: ignore[arg-type]

    payload = client._payload(  # noqa: SLF001
        model=configured.planner_model,
        system="Return JSON.",
        text="Choose one action.",
        image=b"png",
        max_tokens=512,
    )

    assert payload["reasoning"] == {"effort": "none", "exclude": True}
    assert "temperature" not in payload


def test_qwen35_payload_disables_reasoning_for_atomic_planning() -> None:
    configured = Settings(
        api_key=None,
        planner_model="qwen/qwen3.5-35b-a3b",
        grounder_model="grounder",
    )
    client = OpenRouterClient(configured, request=lambda _: None)  # type: ignore[arg-type]

    payload = client._payload(  # noqa: SLF001
        model=configured.planner_model,
        system="Return JSON.",
        text="Choose one action.",
        image=b"png",
        max_tokens=512,
    )

    assert payload["reasoning"] == {"effort": "none", "exclude": True}
    assert payload["temperature"] == 0


def test_identical_duplicate_json_is_accepted() -> None:
    content = '{"x": 1, "y": 2}\n{"x": 1, "y": 2}'

    parsed = OpenRouterClient._content_json(  # noqa: SLF001
        {"choices": [{"message": {"content": content}}]}
    )

    assert parsed == {"x": 1, "y": 2}


def test_different_trailing_json_is_rejected() -> None:
    content = '{"x": 1, "y": 2}\n{"x": 3, "y": 4}'

    with pytest.raises(ModelResponseError):
        OpenRouterClient._content_json(  # noqa: SLF001
            {"choices": [{"message": {"content": content}}]}
        )


def test_trailing_markdown_fence_is_ignored() -> None:
    content = '{"action": "done"}`\n\n{"action": "done"}'

    parsed = OpenRouterClient._content_json(  # noqa: SLF001
        {"choices": [{"message": {"content": content}}]}
    )

    assert parsed == {"action": "done"}
