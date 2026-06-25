"""Optional `.env` loading. Uses `python-dotenv` when installed; otherwise a tiny parser."""

from __future__ import annotations

import os
from pathlib import Path


def _apply_env_file(path: Path) -> None:
    if not path.is_file():
        return
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith("export "):
            s = s[7:].strip()
        if "=" not in s:
            continue
        key, _, val = s.partition("=")
        key = key.strip()
        if not key or key in os.environ:
            continue
        val = val.strip().strip("'").strip('"')
        os.environ.setdefault(key, val)


def load_dotenv_if_present() -> None:
    """Load `.env` from cwd and `~/.arrow/.env` without overriding existing variables."""
    try:
        from dotenv import load_dotenv  # type: ignore[import-untyped]

        load_dotenv(Path.cwd() / ".env", override=False)
        p = Path.home() / ".arrow" / ".env"
        if p.is_file():
            load_dotenv(p, override=False)
    except ImportError:
        _apply_env_file(Path.cwd() / ".env")
        _apply_env_file(Path.home() / ".arrow" / ".env")
