import os
from pathlib import Path

import pytest

from sherpa.cli import (
    extract_url,
    normalize_argv,
    parser,
    resolve_headed,
    resolve_url,
    run_init,
    task_parser,
)
from sherpa.config import Settings
from sherpa.envfile import load_env_file


def test_extract_url_from_task_text() -> None:
    assert extract_url("See https://example.com/path?q=1.") == "https://example.com/path?q=1"
    assert extract_url("no link here") is None


def test_resolve_url_prefers_flag_then_task() -> None:
    assert resolve_url("go https://a.com", "https://b.com") == "https://b.com"
    assert resolve_url("go https://a.com", None) == "https://a.com"
    with pytest.raises(SystemExit, match="--url"):
        resolve_url("no url in task", None)


def test_normalize_argv_routes_task_vs_commands() -> None:
    assert normalize_argv(["eval", "--real-model"])[0] == "eval"
    assert normalize_argv(["init"])[0] == "init"
    assert normalize_argv(["install"])[0] == "install"
    assert normalize_argv(["Confirm heading on https://example.com"])[0] == "task"
    assert normalize_argv(["--help"])[0] == "help"


def test_task_parser_defaults_and_headless() -> None:
    args = task_parser().parse_args(
        ["Confirm the heading", "--url", "https://example.com", "--json"]
    )
    assert " ".join(args.task) == "Confirm the heading"
    assert args.url == "https://example.com"
    assert args.json is True
    assert resolve_headed(args) is True

    headless = task_parser().parse_args(["task", "--headless"])
    assert resolve_headed(headless) is False


def test_run_subcommand_accepts_legacy_positional_url() -> None:
    args = parser().parse_args(
        ["run", "do the thing", "https://example.com", "--headless", "--json"]
    )
    assert args.task == "do the thing"
    assert args.legacy_url == "https://example.com"
    assert resolve_url(args.task, args.url or args.legacy_url) == "https://example.com"
    assert resolve_headed(args) is False


def test_load_env_file_does_not_override_existing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "OPENROUTER_API_KEY=from-file\nSHERPA_MAX_STEPS=9\n# comment\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENROUTER_API_KEY", "from-shell")
    monkeypatch.delenv("SHERPA_MAX_STEPS", raising=False)

    loaded = load_env_file(env_path)
    assert loaded == env_path
    assert os.environ["OPENROUTER_API_KEY"] == "from-shell"
    settings = Settings.from_env(env_file=tmp_path / "missing.env")
    assert settings.api_key == "from-shell"
    assert settings.max_steps == 9


def test_settings_from_env_loads_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("OPENROUTER_API_KEY=file-key\n", encoding="utf-8")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    settings = Settings.from_env(env_file=env_path)
    assert settings.api_key == "file-key"


def test_require_api_key_message(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    settings = Settings.from_env(env_file=tmp_path / "none.env")
    with pytest.raises(SystemExit, match="OPENROUTER_API_KEY"):
        settings.require_api_key()


def test_init_creates_env_without_clobber(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env.example").write_text("OPENROUTER_API_KEY=\n", encoding="utf-8")

    assert run_init() == 0
    assert (tmp_path / ".env").read_text(encoding="utf-8") == "OPENROUTER_API_KEY=\n"
    (tmp_path / ".env").write_text("OPENROUTER_API_KEY=keep\n", encoding="utf-8")
    assert run_init() == 0
    assert (tmp_path / ".env").read_text(encoding="utf-8") == "OPENROUTER_API_KEY=keep\n"
    assert "already exists" in capsys.readouterr().out


def test_webvoyager_parser_still_works() -> None:
    args = parser().parse_args(
        ["webvoyager", "--max-steps", "30", "--max-corrections", "7", "--read-only"]
    )
    assert args.max_steps == 30
    assert args.max_corrections == 7
    assert args.read_only is True
