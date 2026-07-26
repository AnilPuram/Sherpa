import argparse
from pathlib import Path

import pytest

from sherpa.cli import parser, positive_int
from sherpa.config import Settings


def test_default_execution_budgets_are_twenty_and_five(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("SHERPA_MAX_STEPS", raising=False)
    monkeypatch.delenv("SHERPA_MAX_CORRECTIONS", raising=False)
    monkeypatch.delenv("SHERPA_PLANNER_REASONING_EFFORT", raising=False)

    settings = Settings.from_env(env_file=tmp_path / "missing.env")

    assert settings.max_steps == 20
    assert settings.max_corrections == 5
    assert settings.planner_reasoning_effort == "high"


def test_environment_execution_budgets_override_defaults(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SHERPA_MAX_STEPS", "9")
    monkeypatch.setenv("SHERPA_MAX_CORRECTIONS", "4")
    monkeypatch.setenv("SHERPA_PLANNER_REASONING_EFFORT", "medium")

    settings = Settings.from_env(env_file=tmp_path / "missing.env")

    assert settings.max_steps == 9
    assert settings.max_corrections == 4
    assert settings.planner_reasoning_effort == "medium"


@pytest.mark.parametrize(("field", "value"), [("max_steps", 0), ("max_corrections", -1)])
def test_settings_reject_non_positive_budgets(field: str, value: int) -> None:
    values = {"max_steps": 20, "max_corrections": 5, field: value}

    with pytest.raises(ValueError, match="greater than zero"):
        Settings(api_key=None, planner_model="planner", grounder_model="grounder", **values)


def test_settings_reject_invalid_reasoning_effort() -> None:
    with pytest.raises(ValueError, match="reasoning_effort"):
        Settings(
            api_key=None,
            planner_model="planner",
            grounder_model="grounder",
            planner_reasoning_effort="extreme",
        )


def test_cli_budget_overrides_and_read_only_mode() -> None:
    args = parser().parse_args(
        [
            "webvoyager",
            "--max-steps",
            "30",
            "--max-corrections",
            "7",
            "--read-only",
        ]
    )

    assert args.max_steps == 30
    assert args.max_corrections == 7
    assert args.read_only is True

    default_args = parser().parse_args(["webvoyager"])
    assert default_args.read_only is False


def test_positive_int_rejects_zero() -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        positive_int("0")
