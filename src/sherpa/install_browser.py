"""Install Playwright Chromium the Browser Use way (uvx playwright install)."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


def chromium_install_command() -> list[str]:
    """Build the install command; prefer uvx like Browser Use."""
    if shutil.which("uvx"):
        cmd = ["uvx", "playwright", "install", "chromium"]
    else:
        cmd = [sys.executable, "-m", "playwright", "install", "chromium"]
    if platform.system() == "Linux":
        cmd.append("--with-deps")
    cmd.append("--no-shell")
    return cmd


def chromium_executable() -> Path | None:
    """Return the Playwright Chromium path if it exists on disk."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None
    try:
        with sync_playwright() as playwright:
            path = Path(playwright.chromium.executable_path)
    except Exception:
        return None
    return path if path.is_file() else None


def chromium_available() -> bool:
    return chromium_executable() is not None


def install_chromium(*, quiet: bool = False) -> int:
    """Download Chromium (+ Linux system deps). Returns the process exit code."""
    cmd = chromium_install_command()
    if not quiet:
        print("Installing Chromium via Playwright…")
        print(" ".join(cmd))
        print("This may take a few minutes.\n")
    env = os.environ.copy()
    result = subprocess.run(cmd, env=env, check=False)
    if not quiet:
        if result.returncode == 0:
            print("\nChromium install complete.")
            print('Ready: sherpa "Confirm the heading on https://example.com"')
        else:
            print("\nChromium install failed.", file=sys.stderr)
            print("Try: uvx playwright install chromium", file=sys.stderr)
    return result.returncode


def ensure_chromium(*, auto_install: bool = True) -> None:
    """Exit with a clear message, or auto-install, when Chromium is missing."""
    if chromium_available():
        return
    if auto_install:
        print("Playwright Chromium not found; installing…\n")
        code = install_chromium()
        if code == 0 and chromium_available():
            return
        raise SystemExit(
            "Chromium is still missing after install. Run: sherpa install"
        )
    raise SystemExit(
        "Playwright Chromium not found. Run: sherpa install\n"
        "(or: uvx playwright install chromium)"
    )
