"""Company context for ranking / why-fit (stored under ~/.arrow/)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from arrow.db import default_db_path


def default_profile_path() -> Path:
    return default_db_path().parent / "company_profile.json"


def load_company_profile(path: Path | None = None) -> Dict[str, Any]:
    p = path or default_profile_path()
    if not p.is_file():
        return {
            "mission": "",
            "target_naics": [],
            "notes": "",
        }
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {
            "mission": "",
            "target_naics": [],
            "notes": "",
        }
    if not isinstance(raw, dict):
        return {
            "mission": "",
            "target_naics": [],
            "notes": "",
        }
    out = {
        "mission": str(raw.get("mission") or "").strip(),
        "target_naics": _as_str_list(raw.get("target_naics")),
        "notes": str(raw.get("notes") or "").strip(),
    }
    return out


def _as_str_list(v: Any) -> List[str]:
    if v is None:
        return []
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    s = str(v).strip()
    if not s:
        return []
    return [p.strip() for p in s.replace(";", ",").split(",") if p.strip()]


def save_company_profile(data: Dict[str, Any], path: Path | None = None) -> None:
    p = path or default_profile_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    clean = {
        "mission": str(data.get("mission") or "").strip(),
        "target_naics": _as_str_list(data.get("target_naics")),
        "notes": str(data.get("notes") or "").strip(),
    }
    p.write_text(json.dumps(clean, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def init_company_profile_file(path: Path | None = None) -> Path:
    p = path or default_profile_path()
    if not p.exists():
        save_company_profile(load_company_profile(p), p)
    return p
