import platform
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sherpa.cli import normalize_argv, parser
from sherpa.install_browser import (
    chromium_install_command,
    ensure_chromium,
    install_chromium,
)


def test_install_command_prefers_uvx(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sherpa.install_browser.shutil.which",
        lambda name: "/usr/bin/uvx" if name == "uvx" else None,
    )
    cmd = chromium_install_command()
    assert cmd[:4] == ["uvx", "playwright", "install", "chromium"]
    assert "--no-shell" in cmd
    if platform.system() == "Linux":
        assert "--with-deps" in cmd
    else:
        assert "--with-deps" not in cmd


def test_install_command_falls_back_to_python_module(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sherpa.install_browser.shutil.which", lambda _name: None)
    monkeypatch.setattr("sherpa.install_browser.sys.executable", "/venv/bin/python")
    cmd = chromium_install_command()
    assert cmd[:5] == ["/venv/bin/python", "-m", "playwright", "install", "chromium"]


def test_normalize_argv_routes_install() -> None:
    assert normalize_argv(["install"])[0] == "install"
    args = parser().parse_args(["install"])
    assert args.command == "install"


def test_ensure_chromium_skips_when_available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sherpa.install_browser.chromium_available", lambda: True)
    ensure_chromium(auto_install=True)  # no raise


def test_ensure_chromium_auto_installs(monkeypatch: pytest.MonkeyPatch) -> None:
    available = {"ok": False}

    def fake_available() -> bool:
        return available["ok"]

    def fake_install(*, quiet: bool = False) -> int:
        del quiet
        available["ok"] = True
        return 0

    monkeypatch.setattr("sherpa.install_browser.chromium_available", fake_available)
    monkeypatch.setattr("sherpa.install_browser.install_chromium", fake_install)
    ensure_chromium(auto_install=True)
    assert available["ok"] is True


def test_ensure_chromium_errors_without_auto_install(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sherpa.install_browser.chromium_available", lambda: False)
    with pytest.raises(SystemExit, match="sherpa install"):
        ensure_chromium(auto_install=False)


def test_install_chromium_runs_subprocess(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        "sherpa.install_browser.chromium_install_command",
        lambda: ["echo", "noop"],
    )
    completed = MagicMock(returncode=0)
    monkeypatch.setattr(
        "sherpa.install_browser.subprocess.run",
        lambda *a, **k: completed,
    )
    assert install_chromium() == 0
    assert "Installing Chromium" in capsys.readouterr().out


def test_wheel_exposes_sherpa_script() -> None:
    # Packaging sanity: entry point declared in pyproject (read from disk).
    text = Path("pyproject.toml").read_text(encoding="utf-8")
    assert 'sherpa = "sherpa.cli:main"' in text
    assert 'name = "sherpa-agent"' in text
