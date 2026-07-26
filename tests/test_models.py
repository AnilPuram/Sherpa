import json

import pytest

from sherpa.config import Settings
from sherpa.models import ModelResponseError, OpenRouterClient
from sherpa.types import (
    Action,
    Dimensions,
    DomChange,
    DomHistoryEntry,
    DomSnapshot,
    GroundedPoint,
    PlannerAction,
    VerificationResult,
)


def settings() -> Settings:
    return Settings(
        api_key=None,
        planner_model="planner",
        grounder_model="grounder",
    )


def test_qwen_planner_and_ui_tars_grounder_are_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("SHERPA_PLANNER_MODEL", "SHERPA_GROUNDER_MODEL"):
        monkeypatch.delenv(name, raising=False)

    configured = Settings.from_env()

    assert configured.planner_model == "qwen/qwen3.5-35b-a3b"
    assert configured.grounder_model == "bytedance/ui-tars-1.5-7b"
    assert configured.model_prices(configured.planner_model) == (0.14, 1.0)
    assert configured.model_prices(configured.grounder_model) == (0.10, 0.20)


def test_planner_action_accepts_target_alias() -> None:
    action = PlannerAction.model_validate({"action": "click", "target": "the visible button"})

    assert action.element_description == "the visible button"


def response(
    content: dict,
    *,
    input_tokens: int = 100,
    output_tokens: int = 10,
    finish_reason: str = "stop",
) -> dict:
    return {
        "choices": [
            {
                "message": {"content": json.dumps(content)},
                "finish_reason": finish_reason,
            }
        ],
        "usage": {"prompt_tokens": input_tokens, "completion_tokens": output_tokens},
    }


def text_response(content: str) -> dict:
    return {"choices": [{"message": {"content": content}}]}


@pytest.mark.asyncio
async def test_planner_parses_strict_action_and_usage() -> None:
    async def request(_: dict) -> dict:
        return response(
            {
                "action": "click",
                "element_description": "the blue Complete button at bottom center",
                "value": None,
                "reasoning": "Completes the form.",
                "observation": "The Complete button is visible.",
                "progress_made": True,
                "completed_subgoal": "Filled the form",
                "next_subgoal": "Submit the form",
            }
        )

    result = await OpenRouterClient(settings(), request).plan(
        task="Complete the form",
        image=b"png",
        image_size=Dimensions(width=100, height=100),
        progress=[],
        memories=[],
    )

    assert result.value.action is Action.CLICK
    assert result.value.completed_subgoal == "Filled the form"
    assert result.usage.input_tokens == 100
    assert result.model_attempts == 1
    assert result.protocol_retry is False
    assert result.finish_reason == "stop"


@pytest.mark.asyncio
async def test_planner_requests_provider_enforced_strict_schema() -> None:
    captured: dict = {}

    async def request(payload: dict) -> dict:
        captured.update(payload)
        return response({"action": "done", "value": "Answer"})

    await OpenRouterClient(settings(), request).plan(
        task="Find an answer",
        image=b"png",
        image_size=Dimensions(width=100, height=100),
        progress=[],
        memories=[],
    )

    response_format = captured["response_format"]
    schema = response_format["json_schema"]["schema"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["strict"] is True
    assert schema["additionalProperties"] is False
    assert schema["required"] == list(schema["properties"])
    assert captured["provider"] == {"require_parameters": True}
    assert captured["plugins"] == [{"id": "response-healing"}]
    assert "stop" not in captured


@pytest.mark.asyncio
async def test_planner_replays_initial_dom_and_all_later_diffs() -> None:
    captured: dict = {}

    async def request(payload: dict) -> dict:
        captured.update(payload)
        return response({"action": "done", "value": "Answer"})

    history = [
        DomHistoryEntry(
            step=1,
            url="https://example.com/",
            mode="full",
            controls_text='[link] "Products"',
            main_content="# Initial fact",
        ),
        DomHistoryEntry(
            step=2,
            url="https://example.com/",
            mode="diff",
            semantic_changes='+ [button] "Compare"',
        ),
    ]
    await OpenRouterClient(settings(), request).plan(
        task="Find the answer",
        image=b"png",
        image_size=Dimensions(width=100, height=100),
        progress=[],
        memories=[],
        dom_history=history,
    )

    context = json.loads(captured["messages"][1]["content"][0]["text"])
    assert context["page_context_history"] == [
        {
            "step": 1,
            "url": "https://example.com/",
            "mode": "full",
            "visible_controls": '[link] "Products"',
            "main_content": "# Initial fact",
            "truncated": False,
            "error": None,
        },
        {
            "step": 2,
            "url": "https://example.com/",
            "mode": "diff",
            "semantic_changes": '+ [button] "Compare"',
            "truncated": False,
            "error": None,
        },
    ]


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


@pytest.mark.asyncio
async def test_ui_tars_uses_native_prompt_and_parses_resized_point() -> None:
    captured: dict = {}
    configured = Settings(
        api_key=None,
        planner_model="planner",
        grounder_model="bytedance/ui-tars-1.5-7b",
    )

    async def request(payload: dict) -> dict:
        captured.update(payload)
        return text_response("Action: click(point='<point>56 84</point>')")

    result = await OpenRouterClient(configured, request).ground(
        description="the blue Complete button",
        image=b"png",
        image_size=Dimensions(width=100, height=100),
    )

    assert result.value == GroundedPoint(x=50, y=75)
    assert "response_format" not in captured
    assert "stop" not in captured
    assert [part["type"] for part in captured["messages"][1]["content"]] == [
        "image_url",
        "text",
    ]
    prompt = captured["messages"][1]["content"][1]["text"]
    assert "center or a representative point" in prompt
    assert "Action: click(point='<point>x y</point>')" in prompt


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        (
            "Action: click(point='<point>56, 28</point>')",
            GroundedPoint(x=50, y=25),
        ),
        (
            "Action: click(start_box='<|box_start|>(56,28)<|box_end|>')",
            GroundedPoint(x=50, y=25),
        ),
        ("Action: click(start_box='(56,28)')", GroundedPoint(x=50, y=25)),
    ],
)
def test_ui_tars_accepts_documented_point_formats(
    content: str,
    expected: GroundedPoint,
) -> None:
    point = OpenRouterClient._parse_ui_tars_point(  # noqa: SLF001
        content,
        Dimensions(width=100, height=100),
    )

    assert point == expected


def test_ui_tars_rejects_absent_target() -> None:
    with pytest.raises(ModelResponseError, match="not safely visible"):
        OpenRouterClient._parse_ui_tars_point(  # noqa: SLF001
            "Action: none()",
            Dimensions(width=100, height=100),
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


@pytest.mark.asyncio
async def test_malformed_planner_response_preserves_usage() -> None:
    async def request(_: dict) -> dict:
        return {
            "choices": [{"message": {"content": "not json"}}],
            "usage": {
                "prompt_tokens": 123,
                "completion_tokens": 7,
                "cost": 0.0042,
            },
        }

    with pytest.raises(ModelResponseError) as raised:
        await OpenRouterClient(settings(), request).plan(
            task="Find an answer",
            image=b"png",
            image_size=Dimensions(width=100, height=100),
            progress=[],
            memories=[],
        )

    assert raised.value.model == "planner"
    assert raised.value.usage.input_tokens == 246
    assert raised.value.usage.output_tokens == 14
    assert raised.value.usage.cost_usd == 0.0084
    assert raised.value.model_attempts == 2
    assert raised.value.protocol_retry is True
    assert raised.value.protocol_error_category == "invalid_json"


@pytest.mark.asyncio
async def test_planner_retries_protocol_failure_inside_one_decision() -> None:
    payloads: list[dict] = []

    async def request(payload: dict) -> dict:
        payloads.append(payload)
        if len(payloads) == 1:
            return {
                "choices": [{"message": {"content": "not json"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 2, "cost": 0.01},
            }
        return response(
            {"action": "done", "value": "Recovered"},
            input_tokens=12,
            output_tokens=3,
        )

    result = await OpenRouterClient(settings(), request).plan(
        task="Find an answer",
        image=b"png",
        image_size=Dimensions(width=100, height=100),
        progress=[],
        memories=[],
    )

    assert result.value == PlannerAction(action="done", value="Recovered")
    assert result.model_attempts == 2
    assert result.protocol_retry is True
    assert result.protocol_error_category == "invalid_json"
    assert result.usage.input_tokens == 22
    assert result.usage.output_tokens == 5
    assert result.usage.cost_usd == pytest.approx(0.01000468)
    assert payloads[1]["max_tokens"] == 2048
    assert "PROTOCOL RETRY" in payloads[1]["messages"][0]["content"]


@pytest.mark.asyncio
async def test_truncated_planner_response_is_retried_before_parsing() -> None:
    calls = 0

    async def request(_: dict) -> dict:
        nonlocal calls
        calls += 1
        if calls == 1:
            return {
                "choices": [
                    {
                        "message": {"content": '{"action":"done"'},
                        "finish_reason": "length",
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            }
        return response({"action": "done", "value": "Complete"})

    result = await OpenRouterClient(settings(), request).plan(
        task="Find an answer",
        image=b"png",
        image_size=Dimensions(width=100, height=100),
        progress=[],
        memories=[],
    )

    assert calls == 2
    assert result.protocol_error_category == "truncated"
    assert result.protocol_retry is True


@pytest.mark.asyncio
async def test_schema_invalid_planner_response_is_retried() -> None:
    calls = 0

    async def request(_: dict) -> dict:
        nonlocal calls
        calls += 1
        if calls == 1:
            return response({"action": "click", "element_description": None})
        return response({"action": "done", "value": "Complete"})

    result = await OpenRouterClient(settings(), request).plan(
        task="Find an answer",
        image=b"png",
        image_size=Dimensions(width=100, height=100),
        progress=[],
        memories=[],
    )

    assert calls == 2
    assert result.protocol_error_category == "schema_invalid"


@pytest.mark.asyncio
async def test_verifier_uses_multiple_images_and_parses_strict_result() -> None:
    captured: dict = {}

    async def request(payload: dict) -> dict:
        captured.update(payload)
        return response(
            {
                "accepted": True,
                "reason": "The screenshots visibly support the answer.",
                "corrected_answer": "Supported answer",
                "missing_evidence": [],
            }
        )

    result = await OpenRouterClient(settings(), request).verify(
        task="Find the answer",
        proposed_answer="Draft answer",
        image=b"current",
        image_size=Dimensions(width=100, height=100),
        progress=[],
        memories=["Visible fact"],
        milestone_images=[b"first", b"second"],
        dom=DomSnapshot(
            controls_text='[link] "Release"',
            content_markdown="# Release v1.0",
            fingerprint="dom",
        ),
        dom_change=DomChange(page_changed=True),
    )

    assert result.value == VerificationResult(
        accepted=True,
        reason="The screenshots visibly support the answer.",
        corrected_answer="Supported answer",
    )
    content = captured["messages"][1]["content"]
    assert [part["type"] for part in content] == [
        "text",
        "image_url",
        "image_url",
        "image_url",
    ]
    context = json.loads(content[0]["text"])
    assert context["dom_context_mode"] == "full"
    assert context["main_content"] == "# Release v1.0"


@pytest.mark.asyncio
async def test_malformed_verifier_response_preserves_usage() -> None:
    async def request(_: dict) -> dict:
        return {
            "choices": [{"message": {"content": "not json"}}],
            "usage": {"prompt_tokens": 50, "completion_tokens": 3, "cost": 0.002},
        }

    with pytest.raises(ModelResponseError) as raised:
        await OpenRouterClient(settings(), request).verify(
            task="Find the answer",
            proposed_answer="Draft",
            image=b"current",
            image_size=Dimensions(width=100, height=100),
            progress=[],
            memories=[],
            milestone_images=[],
            dom=DomSnapshot(fingerprint="dom"),
            dom_change=DomChange(),
        )

    assert raised.value.usage.input_tokens == 100
    assert raised.value.usage.cost_usd == 0.004


@pytest.mark.asyncio
async def test_rejected_verifier_discards_advisory_corrected_answer() -> None:
    async def request(_: dict) -> dict:
        return response(
            {
                "accepted": False,
                "reason": "More evidence is needed.",
                "corrected_answer": "unsupported suggestion",
                "missing_evidence": ["the requested value"],
            }
        )

    result = await OpenRouterClient(settings(), request).verify(
        task="Find the answer",
        proposed_answer="Draft",
        image=b"current",
        image_size=Dimensions(width=100, height=100),
        progress=[],
        memories=[],
        milestone_images=[],
        dom=DomSnapshot(fingerprint="dom"),
        dom_change=DomChange(),
    )

    assert result.value == VerificationResult(
        accepted=False,
        reason="More evidence is needed.",
        missing_evidence=["the requested value"],
    )


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


def test_claude_sonnet5_payload_disables_reasoning_and_lowers_verbosity() -> None:
    configured = Settings(
        api_key=None,
        planner_model="anthropic/claude-sonnet-5",
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
    assert payload["verbosity"] == "low"


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


def test_exact_markdown_fence_is_accepted() -> None:
    content = '```json\n{"action": "done"}\n```'

    parsed = OpenRouterClient._content_json(  # noqa: SLF001
        {"choices": [{"message": {"content": content}}]}
    )

    assert parsed == {"action": "done"}


def test_partial_markdown_fence_and_trailing_content_are_rejected() -> None:
    content = '{"action": "done"}`\n\n{"action": "done"}'

    with pytest.raises(ModelResponseError) as raised:
        OpenRouterClient._content_json(  # noqa: SLF001
            {"choices": [{"message": {"content": content}}]}
        )

    assert raised.value.protocol_error_category == "trailing_content"
