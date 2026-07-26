"""CLI, config, and browser-install surface tests."""

from __future__ import annotations

import argparse
import os
import platform
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sherpa.cli import (
    extract_url,
    normalize_argv,
    parser,
    positive_int,
    resolve_headed,
    resolve_url,
    run_init,
    task_parser,
)
from sherpa.config import Settings
from sherpa.envfile import load_env_file
from sherpa.install_browser import (
    chromium_install_command,
    ensure_chromium,
    install_chromium,
)


def test_default_and_override_budgets(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("SHERPA_MAX_STEPS", raising=False)
    monkeypatch.delenv("SHERPA_MAX_CORRECTIONS", raising=False)
    monkeypatch.delenv("SHERPA_PLANNER_REASONING_EFFORT", raising=False)
    defaults = Settings.from_env(env_file=tmp_path / "missing.env")
    assert defaults.max_steps == 20
    assert defaults.max_corrections == 5
    assert defaults.planner_reasoning_effort == "high"

    monkeypatch.setenv("SHERPA_MAX_STEPS", "9")
    monkeypatch.setenv("SHERPA_MAX_CORRECTIONS", "4")
    monkeypatch.setenv("SHERPA_PLANNER_REASONING_EFFORT", "medium")
    overridden = Settings.from_env(env_file=tmp_path / "missing.env")
    assert overridden.max_steps == 9
    assert overridden.max_corrections == 4
    assert overridden.planner_reasoning_effort == "medium"


def test_settings_reject_invalid_budgets_and_effort() -> None:
    with pytest.raises(ValueError, match="greater than zero"):
        Settings(api_key=None, planner_model="p", grounder_model="g", max_steps=0)
    with pytest.raises(ValueError, match="reasoning_effort"):
        Settings(
            api_key=None,
            planner_model="p",
            grounder_model="g",
            planner_reasoning_effort="extreme",
        )


def test_load_env_respects_shell_and_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "OPENROUTER_API_KEY=from-file\nSHERPA_MAX_STEPS=9\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENROUTER_API_KEY", "from-shell")
    monkeypatch.delenv("SHERPA_MAX_STEPS", raising=False)
    assert load_env_file(env_path) == env_path
    assert os.environ["OPENROUTER_API_KEY"] == "from-shell"
    settings = Settings.from_env(env_file=tmp_path / "missing.env")
    assert settings.api_key == "from-shell"
    assert settings.max_steps == 9

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    key_only = tmp_path / "key.env"
    key_only.write_text("OPENROUTER_API_KEY=file-key\n", encoding="utf-8")
    assert Settings.from_env(env_file=key_only).api_key == "file-key"


def test_require_api_key_message(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(SystemExit, match="OPENROUTER_API_KEY"):
        Settings.from_env(env_file=tmp_path / "none.env").require_api_key()


def test_url_routing_and_parsers() -> None:
    assert extract_url("See https://example.com/path?q=1.") == "https://example.com/path?q=1"
    assert resolve_url("go https://a.com", "https://b.com") == "https://b.com"
    with pytest.raises(SystemExit, match="--url"):
        resolve_url("no url", None)

    assert normalize_argv(["eval"])[0] == "eval"
    assert normalize_argv(["install"])[0] == "install"
    assert normalize_argv(["Confirm https://example.com"])[0] == "task"

    args = task_parser().parse_args(
        ["Confirm the heading", "--url", "https://example.com", "--json"]
    )
    assert " ".join(args.task) == "Confirm the heading"
    assert resolve_headed(args) is True
    assert resolve_headed(task_parser().parse_args(["task", "--headless"])) is False

    run = parser().parse_args(
        ["run", "do the thing", "https://example.com", "--headless"]
    )
    assert resolve_url(run.task, run.url or run.legacy_url) == "https://example.com"

    wv = parser().parse_args(
        ["webvoyager", "--max-steps", "30", "--max-corrections", "7", "--read-only"]
    )
    assert wv.max_steps == 30 and wv.read_only is True
    with pytest.raises(argparse.ArgumentTypeError):
        positive_int("0")


def test_init_and_package_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env.example").write_text("OPENROUTER_API_KEY=\n", encoding="utf-8")
    assert run_init() == 0
    assert (tmp_path / ".env").read_text(encoding="utf-8") == "OPENROUTER_API_KEY=\n"
    (tmp_path / ".env").write_text("OPENROUTER_API_KEY=keep\n", encoding="utf-8")
    assert run_init() == 0
    assert "already exists" in capsys.readouterr().out

    root = Path(__file__).resolve().parents[1]
    text = (root / "pyproject.toml").read_text(encoding="utf-8")
    assert 'name = "sherpa-agent"' in text
    assert 'sherpa = "sherpa.cli:main"' in text


def test_chromium_install_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sherpa.install_browser.shutil.which",
        lambda name: "/usr/bin/uvx" if name == "uvx" else None,
    )
    cmd = chromium_install_command()
    assert cmd[:4] == ["uvx", "playwright", "install", "chromium"]
    assert "--no-shell" in cmd
    if platform.system() == "Linux":
        assert "--with-deps" in cmd

    monkeypatch.setattr("sherpa.install_browser.chromium_available", lambda: True)
    ensure_chromium(auto_install=True)

    monkeypatch.setattr("sherpa.install_browser.chromium_available", lambda: False)
    with pytest.raises(SystemExit, match="sherpa install"):
        ensure_chromium(auto_install=False)

    monkeypatch.setattr(
        "sherpa.install_browser.chromium_install_command",
        lambda: ["echo", "noop"],
    )
    monkeypatch.setattr(
        "sherpa.install_browser.subprocess.run",
        lambda *a, **k: MagicMock(returncode=0),
    )
    assert install_chromium(quiet=True) == 0
