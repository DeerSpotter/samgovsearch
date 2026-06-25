"""Start local Ollama when Arrow launches (optional; can disable with ARROW_NO_AUTO_OLLAMA=1)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from typing import Optional

from arrow.ollama_client import ollama_tags


def ensure_ollama_running(*, quiet: bool = True) -> bool:
    """
    If Ollama already responds on OLLAMA_HOST, return True.

    Otherwise, if `ollama` is on PATH and ARROW_NO_AUTO_OLLAMA is not set, spawn `ollama serve`
    in the background and poll until /api/tags works (or give up).
    """
    try:
        ollama_tags(timeout=2.0)
        return True
    except Exception:
        pass

    if os.environ.get("ARROW_NO_AUTO_OLLAMA", "").strip().lower() in ("1", "true", "yes"):
        return False
    if not shutil.which("ollama"):
        return False
    try:
        subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        return False

    for _ in range(24):
        time.sleep(0.5)
        try:
            ollama_tags(timeout=3.0)
            if not quiet:
                print("  [arrow] Ollama is up (started ollama serve).", file=sys.stderr)
            return True
        except Exception:
            continue
    return False
