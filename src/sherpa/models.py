import asyncio
import base64
import copy
import json
import re
import time
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from sherpa.config import Settings
from sherpa.types import (
    Dimensions,
    DomChange,
    DomHistoryEntry,
    DomSnapshot,
    GroundedPoint,
    ModelResult,
    ModelUsage,
    PlannerAction,
    ProgressEntry,
    VerificationResult,
)

Request = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
StructuredResult = TypeVar("StructuredResult", PlannerAction, VerificationResult)

PLANNER_PROMPT = """You control a browser from the CURRENT screenshot and PAGE CONTEXT HISTORY.
Choose exactly one atomic next action that advances the task.

Before choosing:
1. PAGE CONTEXT HISTORY is ordered oldest to newest. Reconstruct semantic state from each full
   snapshot and its later diffs. A new full entry after navigation starts the next page state.
2. Treat the current screenshot as authoritative for visibility and layout. History supports
   reading and progress, but only target controls visibly present in the current screenshot.
3. Describe targets using visible role, text, state, and location so the screenshot-only grounder
   can locate them. Never use internal DOM IDs or keys.
4. Check the previous action's visible result. Correct missing or wrong state before proceeding.
5. If the target is clipped, covered, or outside the viewport, scroll instead of targeting it.
6. For forms, work top-to-bottom on fully visible fields and preserve correct existing values.
7. Use the progress ledger, semantic changes, and memories. Do not repeat a failed strategy.
8. If a useful fact is visible but another page is still needed, memorize the fact.

Allowed actions: click, type, select, scroll, scroll_home, scroll_end, go_back, memorize,
press_enter, done, infeasible.
- TYPE already clicks and focuses its target. Never CLICK an input merely to focus it before TYPE.
- SELECT clicks a dropdown, types the exact option text, and presses Enter. Use it instead of
  separate clicks when the requested option is known.
- For click/type/select, identify one target with role, exact visible label/text, current state, and
  location relative to nearby elements. The description must uniquely identify it to a grounder.
- For type/select, value is the exact text. For scroll, value is exactly "up" or "down".
- For memorize, value is one concise fact visibly supported by the current screenshot.
- Use go_back, scroll_home, or scroll_end to escape an unproductive route.
- Scroll only when needed and by the minimum direction needed to expose the next target.
- Use done only when the current screenshot visibly proves every requested condition. For
  information-retrieval tasks, put the concise final answer in value.
- Never perform an irreversible action unless the task explicitly requests it.

Return exactly one JSON object and nothing else:
{"action":"click|type|select|scroll|scroll_home|scroll_end|go_back|memorize|press_enter|done|infeasible",
 "element_description":"unique visible target description or null",
 "value":"typed/selected text, up/down, final answer for done, or null",
 "reasoning":"one short sentence",
 "observation":"what the current screenshot visibly shows",
 "progress_made":true,
 "completed_subgoal":"newly completed subgoal or null",
 "next_subgoal":"single next objective or null"}"""

GROUNDER_PROMPT = """Locate the described interactive element in the CURRENT screenshot.
- Match the element's role, exact visible label/text, state, and relative location.
- Return the control itself, not its label, surrounding text, or a nearby control.
- The entire target must be visible. If it is clipped, covered, ambiguous, or absent, return null.
- Use Qwen's native 0-1000 grid: [x_min, y_min, x_max, y_max].

Return exactly one JSON object and nothing else:
{"bbox_2d":[x_min,y_min,x_max,y_max]}
or, when no safe unique target is fully visible:
{"bbox_2d":null}"""

UI_TARS_GROUNDER_PROMPT = """You are a precise GUI visual grounding model.

Identify the center or a representative point inside the visible interactive element described
below. Match its role, visible text, state, and relative location. Return the control itself, not
its label or surrounding text. This follows SeeAct-V's single-point visual-grounding method while
using UI-TARS's native action syntax.

Output exactly one line:
Action: click(point='<point>x y</point>')

If no matching interactive element is visibly present, output exactly:
Action: none()

Description: {description}"""

VERIFIER_PROMPT = """You are the final completion gate for a browser agent.
Judge from the supplied screenshots, current visible controls, current bounded main-content
Markdown, task, proposed answer, progress ledger, and explicitly memorized visual evidence.
Screenshots are authoritative for visibility/layout; compact page context is supplementary.
Do not use outside knowledge or assume an action succeeded.

Accept only when the evidence visibly proves every requested condition and the proposed answer is
specific, internally consistent, and contains no unsupported additions. If evidence is missing,
reject and list exactly what must still be found. A corrected answer is allowed only when accepted.

Return exactly one JSON object and nothing else:
{"accepted":true|false,
 "reason":"one concise evidence-based reason",
 "corrected_answer":"supported corrected answer or null",
 "missing_evidence":["specific missing item"]}"""

def _planner_dom_context(history: list[DomHistoryEntry] | None) -> dict[str, Any]:
    return {"page_context_history": _serialize_dom_history(history or [])}


def _verifier_dom_context(
    dom: DomSnapshot,
    change: DomChange,
) -> dict[str, Any]:
    return {
        "dom_context_mode": "full",
        "visible_controls": dom.controls_text,
        "main_content": dom.content_markdown,
        "semantic_changes": change.summary,
        "controls_truncated": dom.controls_truncated,
        "content_truncated": dom.content_truncated,
        "controls_error": dom.controls_error,
        "content_error": dom.content_error,
    }


def _serialize_dom_history(history: list[DomHistoryEntry]) -> list[dict[str, Any]]:
    return [
        {
            "step": entry.step,
            "url": entry.url,
            "mode": entry.mode,
            **(
                {
                    "visible_controls": entry.controls_text,
                    "main_content": entry.main_content,
                }
                if entry.mode == "full"
                else {"semantic_changes": entry.semantic_changes}
            ),
            "truncated": entry.truncated,
            "error": entry.error,
        }
        for entry in history
    ]


class ModelResponseError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        model: str | None = None,
        latency_ms: int = 0,
        usage: ModelUsage | None = None,
        model_attempts: int = 1,
        protocol_retry: bool = False,
        finish_reason: str | None = None,
        protocol_error_category: str | None = None,
    ) -> None:
        super().__init__(message)
        self.model = model
        self.latency_ms = latency_ms
        self.usage = usage or ModelUsage()
        self.model_attempts = model_attempts
        self.protocol_retry = protocol_retry
        self.finish_reason = finish_reason
        self.protocol_error_category = protocol_error_category


class OpenRouterClient:
    def __init__(self, settings: Settings, request: Request | None = None) -> None:
        if request is None and not settings.api_key:
            raise ValueError("OPENROUTER_API_KEY is required")
        self.settings = settings
        self._injected_request = request

    async def plan(
        self,
        *,
        task: str,
        image: bytes,
        image_size: Dimensions,
        progress: list[ProgressEntry],
        memories: list[str],
        dom_history: list[DomHistoryEntry] | None = None,
        feedback: str | None = None,
    ) -> ModelResult:
        dom_context = _planner_dom_context(dom_history)
        context = {
            "task": task,
            "image_width": image_size.width,
            "image_height": image_size.height,
            "recent_progress": [item.model_dump(mode="json") for item in progress[-8:]],
            "memories": memories[-8:],
            "failure_feedback": feedback,
            **dom_context,
        }
        payload = self._payload(
            model=self.settings.planner_model,
            system=PLANNER_PROMPT,
            text=json.dumps(context, separators=(",", ":")),
            image=image,
            max_tokens=1024,
            response_type=PlannerAction,
        )
        return await self._request_typed(
            payload,
            model=self.settings.planner_model,
            response_type=PlannerAction,
            response_label="planner",
        )

    async def verify(
        self,
        *,
        task: str,
        proposed_answer: str | None,
        image: bytes,
        image_size: Dimensions,
        progress: list[ProgressEntry],
        memories: list[str],
        milestone_images: list[bytes],
        dom: DomSnapshot,
        dom_change: DomChange,
    ) -> ModelResult:
        dom_context = _verifier_dom_context(dom, dom_change)
        context = {
            "task": task,
            "proposed_answer": proposed_answer,
            "image_width": image_size.width,
            "image_height": image_size.height,
            "recent_progress": [item.model_dump(mode="json") for item in progress[-8:]],
            "memories": memories[-8:],
            "image_order": ["current", *[f"milestone_{index + 1}" for index in range(2)]][
                : 1 + len(milestone_images[-2:])
            ],
            **dom_context,
        }
        payload = self._payload(
            model=self.settings.planner_model,
            system=VERIFIER_PROMPT,
            text=json.dumps(context, separators=(",", ":")),
            image=[image, *milestone_images[-2:]],
            max_tokens=512,
            response_type=VerificationResult,
        )
        return await self._request_typed(
            payload,
            model=self.settings.planner_model,
            response_type=VerificationResult,
            response_label="verifier",
        )

    async def ground(
        self,
        *,
        description: str,
        image: bytes | list[bytes],
        image_size: Dimensions,
    ) -> ModelResult:
        ui_tars = self.settings.grounder_model.startswith("bytedance/ui-tars")
        text = (
            UI_TARS_GROUNDER_PROMPT.format(description=description)
            if ui_tars
            else json.dumps(
                {
                    "target": description,
                    "image_width": image_size.width,
                    "image_height": image_size.height,
                },
                separators=(",", ":"),
            )
        )
        payload = self._payload(
            model=self.settings.grounder_model,
            system=(
                "Return only the requested UI-TARS grounding action."
                if ui_tars
                else GROUNDER_PROMPT
            ),
            text=text,
            image=image,
            max_tokens=96 if ui_tars else 160,
            json_mode=not ui_tars,
            image_first=ui_tars,
        )
        response, latency_ms = await self._send(payload)
        usage = self._usage(response, self.settings.grounder_model)
        try:
            point = (
                self._parse_ui_tars_point(self._content_text(response), image_size)
                if ui_tars
                else self._parse_point(self._content_json(response), image_size)
            )
        except ModelResponseError as exc:
            raise ModelResponseError(
                str(exc),
                model=self.settings.grounder_model,
                latency_ms=latency_ms,
                usage=usage,
                finish_reason=self._finish_reason(response),
                protocol_error_category=exc.protocol_error_category,
            ) from exc
        return ModelResult(
            value=point,
            model=self.settings.grounder_model,
            latency_ms=latency_ms,
            usage=usage,
            finish_reason=self._finish_reason(response),
        )

    def _payload(
        self,
        *,
        model: str,
        system: str,
        text: str,
        image: bytes | list[bytes],
        max_tokens: int,
        json_mode: bool = True,
        image_first: bool = False,
        response_type: type[BaseModel] | None = None,
    ) -> dict[str, Any]:
        images = image if isinstance(image, list) else [image]
        image_content: list[dict[str, Any]] = []
        for image_bytes in images:
            encoded = base64.b64encode(image_bytes).decode("ascii")
            image_content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{encoded}"},
                }
            )
        text_content = {"type": "text", "text": text}
        content = (
            [*image_content, text_content]
            if image_first
            else [text_content, *image_content]
        )
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": content,
                },
            ],
            "temperature": 0,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["plugins"] = [{"id": "response-healing"}]
            if response_type is None:
                payload["response_format"] = {"type": "json_object"}
            else:
                payload["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": response_type.__name__,
                        "strict": True,
                        "schema": self._wire_schema(response_type),
                    },
                }
                payload["provider"] = {"require_parameters": True}
        if model.startswith("openai/gpt-5"):
            payload["reasoning"] = {"effort": "none", "exclude": True}
            payload.pop("temperature")
        elif model.startswith("qwen/qwen3.5"):
            payload["reasoning"] = {"effort": "none", "exclude": True}
        elif model.startswith("anthropic/claude-sonnet-5"):
            payload["reasoning"] = {"effort": "none", "exclude": True}
            payload["verbosity"] = "low"
        return payload

    async def _request_typed(
        self,
        payload: dict[str, Any],
        *,
        model: str,
        response_type: type[StructuredResult],
        response_label: str,
    ) -> ModelResult:
        total_usage = ModelUsage()
        total_latency_ms = 0
        first_error_category: str | None = None
        retry_payload = payload
        finish_reason: str | None = None
        last_error: Exception | None = None

        for attempt in range(1, 3):
            response, latency_ms = await self._send(retry_payload)
            usage = self._usage(response, model)
            total_usage = _add_usage(total_usage, usage)
            total_latency_ms += latency_ms
            finish_reason = self._finish_reason(response)
            try:
                if finish_reason in {"length", "max_tokens"}:
                    raise ModelResponseError(
                        "Model response was truncated by the output token limit",
                        protocol_error_category="truncated",
                    )
                data = self._content_json(response)
                if response_type is VerificationResult and data.get("accepted") is False:
                    data["corrected_answer"] = None
                value = response_type.model_validate(data)
            except (ModelResponseError, ValidationError) as exc:
                last_error = exc
                category = (
                    exc.protocol_error_category
                    if isinstance(exc, ModelResponseError)
                    else "schema_invalid"
                )
                category = category or "invalid_json"
                first_error_category = first_error_category or category
                if attempt == 1:
                    retry_payload = self._protocol_retry_payload(
                        payload,
                        category=category,
                        detail=str(exc),
                    )
                    continue
                message = (
                    str(exc)
                    if isinstance(exc, ModelResponseError)
                    else f"Invalid {response_label} response: {exc}"
                )
                raise ModelResponseError(
                    message,
                    model=model,
                    latency_ms=total_latency_ms,
                    usage=total_usage,
                    model_attempts=attempt,
                    protocol_retry=True,
                    finish_reason=finish_reason,
                    protocol_error_category=category,
                ) from exc
            return ModelResult(
                value=value,
                model=model,
                latency_ms=total_latency_ms,
                usage=total_usage,
                model_attempts=attempt,
                protocol_retry=attempt > 1,
                finish_reason=finish_reason,
                protocol_error_category=first_error_category,
            )

        raise AssertionError(f"unreachable typed request failure: {last_error}")

    @staticmethod
    def _wire_schema(response_type: type[BaseModel]) -> dict[str, Any]:
        schema = copy.deepcopy(response_type.model_json_schema())

        def normalize(node: Any) -> None:
            if isinstance(node, dict):
                node.pop("default", None)
                node.pop("title", None)
                properties = node.get("properties")
                if isinstance(properties, dict):
                    node["required"] = list(properties)
                    node["additionalProperties"] = False
                for value in node.values():
                    normalize(value)
            elif isinstance(node, list):
                for value in node:
                    normalize(value)

        normalize(schema)
        return schema

    @staticmethod
    def _protocol_retry_payload(
        payload: dict[str, Any],
        *,
        category: str,
        detail: str,
    ) -> dict[str, Any]:
        retried = copy.deepcopy(payload)
        bounded_detail = " ".join(detail.split())[:500]
        retried["messages"][0]["content"] += (
            "\n\nPROTOCOL RETRY: The previous response failed "
            f"{category} validation ({bounded_detail}). Re-evaluate the same current evidence and "
            "return one complete object matching the supplied schema. Keep every string concise."
        )
        retried["max_tokens"] = max(1024, int(payload["max_tokens"]) * 2)
        return retried

    async def _send(self, payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
        started = time.monotonic()
        for attempt in range(2):
            try:
                if self._injected_request:
                    response = await self._injected_request(payload)
                else:
                    response = await self._http_request(payload)
                return response, round((time.monotonic() - started) * 1000)
            except httpx.TransportError:
                if attempt == 1:
                    raise
                await asyncio.sleep(0.25)
            except httpx.HTTPStatusError as exc:
                retryable = exc.response.status_code == 429 or exc.response.status_code >= 500
                if attempt == 1 or not retryable:
                    raise
                await asyncio.sleep(0.25)
        raise AssertionError("unreachable")

    async def _http_request(self, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self.settings.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/AnilPuram/Sherpa",
            "X-Title": "Sherpa",
        }
        async with httpx.AsyncClient(timeout=self.settings.timeout_seconds) as client:
            response = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            return response.json()

    @staticmethod
    def _content_text(response: dict[str, Any]) -> str:
        try:
            message = response["choices"][0]["message"]
            if message.get("refusal"):
                raise ModelResponseError(
                    "Model refused to provide structured output",
                    protocol_error_category="refusal",
                )
            content = message["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ModelResponseError(
                "Model did not return text content",
                protocol_error_category="empty",
            ) from exc
        if not isinstance(content, str) or not content.strip():
            raise ModelResponseError(
                "Model did not return text content",
                protocol_error_category="empty",
            )
        return content.strip()

    @staticmethod
    def _content_json(response: dict[str, Any]) -> dict[str, Any]:
        content = OpenRouterClient._content_text(response)
        fence = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", content, re.DOTALL | re.IGNORECASE)
        if fence:
            content = fence.group(1).strip()
        try:
            decoder = json.JSONDecoder()
            data, end = decoder.raw_decode(content)
            trailing = content[end:].strip()
            while trailing:
                try:
                    duplicate, duplicate_end = decoder.raw_decode(trailing)
                except json.JSONDecodeError as exc:
                    raise ModelResponseError(
                        "Model returned content after the JSON object",
                        protocol_error_category="trailing_content",
                    ) from exc
                if duplicate != data:
                    raise ModelResponseError(
                        "Model returned a different trailing JSON object",
                        protocol_error_category="trailing_content",
                    )
                trailing = trailing[duplicate_end:].strip()
        except json.JSONDecodeError as exc:
            raise ModelResponseError(
                "Model did not return valid JSON",
                protocol_error_category="invalid_json",
            ) from exc
        if not isinstance(data, dict):
            raise ModelResponseError(
                "Model JSON must be an object",
                protocol_error_category="schema_invalid",
            )
        return data

    @staticmethod
    def _finish_reason(response: dict[str, Any]) -> str | None:
        try:
            reason = response["choices"][0].get("finish_reason")
        except (KeyError, IndexError, TypeError):
            return None
        return str(reason) if reason is not None else None

    @staticmethod
    def _parse_ui_tars_point(content: str, image_size: Dimensions) -> GroundedPoint:
        if re.search(r"\bnone\s*\(\s*\)", content, re.IGNORECASE):
            raise ModelResponseError("Invalid grounder response: target is not safely visible")

        patterns = (
            r"<point>\s*(-?\d+(?:\.\d+)?)\s*[,\s]\s*(-?\d+(?:\.\d+)?)\s*</point>",
            r"<\|box_start\|>\s*\(\s*(-?\d+(?:\.\d+)?)\s*,\s*"
            r"(-?\d+(?:\.\d+)?)\s*\)\s*<\|box_end\|>",
            r"(?:start_box|point)\s*=\s*['\"]?\(\s*(-?\d+(?:\.\d+)?)\s*,\s*"
            r"(-?\d+(?:\.\d+)?)\s*\)",
            r"\(\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\)",
        )
        match = next(
            (candidate for pattern in patterns if (candidate := re.search(pattern, content))),
            None,
        )
        if match is None:
            raise ModelResponseError("Invalid grounder response: expected one UI-TARS point")

        x, y = (float(value) for value in match.groups())
        resized_width = max(28, round(image_size.width / 28) * 28)
        resized_height = max(28, round(image_size.height / 28) * 28)
        if not 0 <= x <= resized_width or not 0 <= y <= resized_height:
            raise ModelResponseError("Grounded point is outside the resized image")
        return GroundedPoint(
            x=x * image_size.width / resized_width,
            y=y * image_size.height / resized_height,
        )

    @staticmethod
    def _parse_point(data: dict[str, Any], image_size: Dimensions) -> GroundedPoint:
        try:
            if "bbox_2d" in data:
                if data["bbox_2d"] is None:
                    raise ValueError("target is not safely visible")
                left, top, right, bottom = data["bbox_2d"]
                if right <= left or bottom <= top:
                    raise ValueError("box must have positive area")
                normalized = GroundedPoint(x=(left + right) / 2, y=(top + bottom) / 2)
            elif "box" in data:
                left, top, right, bottom = data["box"]
                if right <= left or bottom <= top:
                    raise ValueError("box must have positive area")
                normalized = GroundedPoint(x=(left + right) / 2, y=(top + bottom) / 2)
            elif {"x", "y"} <= set(data) and all(
                isinstance(data[key], int | float) for key in ("x", "y")
            ):
                normalized = GroundedPoint(x=data["x"], y=data["y"])
            elif {"x", "y"} <= set(data):
                # Qwen occasionally emits the two box corners under x and y.
                first, second = data["x"], data["y"]
                left, top = first
                right, bottom = second
                normalized = GroundedPoint(x=(left + right) / 2, y=(top + bottom) / 2)
            else:
                raise ValueError("expected x/y or box")
        except (TypeError, ValueError, ValidationError) as exc:
            raise ModelResponseError(f"Invalid grounder response: {exc}") from exc
        if not 0 <= normalized.x <= 1000 or not 0 <= normalized.y <= 1000:
            raise ModelResponseError("Grounded point is outside the normalized image")
        return GroundedPoint(
            x=normalized.x * image_size.width / 1000,
            y=normalized.y * image_size.height / 1000,
        )

    def _usage(self, response: dict[str, Any], model: str) -> ModelUsage:
        raw = response.get("usage") or {}
        input_tokens = int(raw.get("prompt_tokens", 0))
        output_tokens = int(raw.get("completion_tokens", 0))
        input_price, output_price = self.settings.model_prices(model)
        estimated_cost = (input_tokens * input_price + output_tokens * output_price) / 1_000_000
        reported_cost = raw.get("cost")
        cost = float(reported_cost) if reported_cost is not None else estimated_cost
        return ModelUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
        )


def _add_usage(left: ModelUsage, right: ModelUsage) -> ModelUsage:
    return ModelUsage(
        input_tokens=left.input_tokens + right.input_tokens,
        output_tokens=left.output_tokens + right.output_tokens,
        cost_usd=left.cost_usd + right.cost_usd,
    )
