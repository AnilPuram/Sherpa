"""Minimal .env loader: set unset keys only; no dependency on python-dotenv."""

from __future__ import annotations

from pathlib import Path


def load_env_file(path: Path | None = None) -> Path | None:
    """Load KEY=VALUE pairs from a .env file without overriding existing env vars.

    Returns the path loaded, or None if no file was found / readable.
    """
    candidate = path if path is not None else Path.cwd() / ".env"
    if not candidate.is_file():
        return None
    try:
        text = candidate.read_text(encoding="utf-8")
    except OSError:
        return None

    import os

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key or key in os.environ:
            continue
        os.environ[key] = _unquote(value.strip())
    return candidate


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value
