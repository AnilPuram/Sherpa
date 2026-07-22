import asyncio
import base64
import json
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
from pydantic import ValidationError

from sherpa.config import Settings
from sherpa.types import (
    Dimensions,
    GroundedPoint,
    ModelResult,
    ModelUsage,
    PlannerAction,
)

Request = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]

PLANNER_PROMPT = """You control a browser from the CURRENT screenshot.
Choose exactly one atomic next action that advances the task.

Before choosing:
1. Verify the target visibly exists now; do not rely on history or assumptions.
2. Check the previous action's visible result. Correct missing or wrong state before proceeding.
3. If the target is clipped, covered, or outside the viewport, scroll instead of targeting it.
4. For forms, work top-to-bottom on fully visible fields and preserve correct existing values.

Allowed actions: click, type, select, scroll, press_enter, done, infeasible.
- TYPE already clicks and focuses its target. Never CLICK an input merely to focus it before TYPE.
- SELECT clicks a dropdown, types the exact option text, and presses Enter. Use it instead of
  separate clicks when the requested option is known.
- For click/type/select, identify one target with role, exact visible label/text, current state, and
  location relative to nearby elements. The description must uniquely identify it to a grounder.
- For type/select, value is the exact text. For scroll, value is exactly "up" or "down".
- Scroll only when needed and by the minimum direction needed to expose the next target.
- Use done only when the current screenshot visibly proves every requested condition.
- Never perform an irreversible action unless the task explicitly requests it.

Return exactly one JSON object and nothing else:
{"action":"click|type|select|scroll|press_enter|done|infeasible",
 "element_description":"unique visible target description or null",
 "value":"text, up/down, or null",
 "reasoning":"one short sentence"}"""

GROUNDER_PROMPT = """Locate the described interactive element in the CURRENT screenshot.
- Match the element's role, exact visible label/text, state, and relative location.
- Return the control itself, not its label, surrounding text, or a nearby control.
- The entire target must be visible. If it is clipped, covered, ambiguous, or absent, return null.
- Use Qwen's native 0-1000 grid: [x_min, y_min, x_max, y_max].

Return exactly one JSON object and nothing else:
{"bbox_2d":[x_min,y_min,x_max,y_max]}
or, when no safe unique target is fully visible:
{"bbox_2d":null}"""


class ModelResponseError(RuntimeError):
    pass


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
        history: list[PlannerAction],
        feedback: str | None = None,
    ) -> ModelResult:
        context = {
            "task": task,
            "image_width": image_size.width,
            "image_height": image_size.height,
            "recent_actions": [item.model_dump(mode="json") for item in history[-4:]],
            "failure_feedback": feedback,
        }
        payload = self._payload(
            model=self.settings.planner_model,
            system=PLANNER_PROMPT,
            text=json.dumps(context, separators=(",", ":")),
            image=image,
            max_tokens=512,
        )
        response, latency_ms = await self._send(payload)
        data = self._content_json(response)
        try:
            action = PlannerAction.model_validate(data)
        except ValidationError as exc:
            raise ModelResponseError(f"Invalid planner response: {exc}") from exc
        return ModelResult(
            value=action,
            model=self.settings.planner_model,
            latency_ms=latency_ms,
            usage=self._usage(response, self.settings.planner_model),
        )

    async def ground(
        self,
        *,
        description: str,
        image: bytes,
        image_size: Dimensions,
    ) -> ModelResult:
        target = {
            "target": description,
            "image_width": image_size.width,
            "image_height": image_size.height,
        }
        payload = self._payload(
            model=self.settings.grounder_model,
            system=GROUNDER_PROMPT,
            text=json.dumps(target, separators=(",", ":")),
            image=image,
            max_tokens=160,
        )
        response, latency_ms = await self._send(payload)
        data = self._content_json(response)
        point = self._parse_point(data, image_size)
        return ModelResult(
            value=point,
            model=self.settings.grounder_model,
            latency_ms=latency_ms,
            usage=self._usage(response, self.settings.grounder_model),
        )

    def _payload(
        self,
        *,
        model: str,
        system: str,
        text: str,
        image: bytes,
        max_tokens: int,
    ) -> dict[str, Any]:
        encoded = base64.b64encode(image).decode("ascii")
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": text},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{encoded}"},
                        },
                    ],
                },
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0,
            "max_tokens": max_tokens,
            "stop": ["`", "\n\n"],
        }
        if model.startswith("openai/gpt-5"):
            payload["reasoning"] = {"effort": "none", "exclude": True}
            payload.pop("temperature")
        elif model.startswith("qwen/qwen3.5"):
            payload["reasoning"] = {"effort": "none", "exclude": True}
        return payload

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
    def _content_json(response: dict[str, Any]) -> dict[str, Any]:
        try:
            content = response["choices"][0]["message"]["content"]
            decoder = json.JSONDecoder()
            data, end = decoder.raw_decode(content)
            trailing = content[end:].strip()
            # GLM sometimes appends a fenced duplicate despite JSON mode.
            if trailing.startswith("`"):
                trailing = ""
            while trailing:
                duplicate, duplicate_end = decoder.raw_decode(trailing)
                if duplicate != data:
                    raise json.JSONDecodeError("unexpected content after JSON", content, end)
                trailing = trailing[duplicate_end:].strip()
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise ModelResponseError("Model did not return one JSON object") from exc
        if not isinstance(data, dict):
            raise ModelResponseError("Model JSON must be an object")
        return data

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
