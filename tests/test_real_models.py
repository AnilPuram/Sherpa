import os
from pathlib import Path

import pytest

from sherpa.agent import Agent
from sherpa.browser import Browser
from sherpa.config import Settings
from sherpa.models import OpenRouterClient
from sherpa.runlog import RunLog
from sherpa.types import Dimensions


@pytest.mark.asyncio
async def test_real_models_complete_local_fixture(tmp_path: Path) -> None:
    if os.getenv("SHERPA_RUN_REAL_MODELS") != "1":
        pytest.skip("set SHERPA_RUN_REAL_MODELS=1 to permit paid model calls")
    settings = Settings.from_env()
    if not settings.api_key:
        pytest.skip("OPENROUTER_API_KEY is not set")

    fixture_url = (Path(__file__).parent / "fixtures/site/index.html").resolve().as_uri()
    viewport = Dimensions(width=settings.viewport_width, height=settings.viewport_height)
    async with Browser(viewport) as browser:
        result = await Agent(
            browser,
            OpenRouterClient(settings),
            max_steps=6,
            run_log=RunLog(tmp_path / "steps.jsonl"),
        ).run(
            "Type Sherpa in the Agent name input, click Complete, "
            "and finish when Success is visible.",
            fixture_url,
        )

    log = (tmp_path / "steps.jsonl").read_text(encoding="utf-8")
    assert result.outcome == "done", log
