"""Deterministic contract–profile fit scores (no LLM)."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List

from arrow.analysis import naive_deterministic_fit


def rank_rows_by_profile(profile: Dict[str, Any], rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return a new list sorted by fit score descending; each row gains _fit_total and _fit_det."""
    out: List[Dict[str, Any]] = []
    for r in rows:
        d = deepcopy(r)
        det = naive_deterministic_fit(profile, d)
        d["_fit_total"] = float(det.get("total") if det.get("total") is not None else 0.0)
        d["_fit_det"] = det
        out.append(d)
    out.sort(key=lambda x: float(x.get("_fit_total") if x.get("_fit_total") is not None else 0.0), reverse=True)
    return out


def without_fit_metadata(row: Dict[str, Any]) -> Dict[str, Any]:
    """Strip ranking UI fields before export / JSON detail."""
    return {k: v for k, v in row.items() if k not in ("_fit_total", "_fit_det")}
