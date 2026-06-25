"""Map raw SAM.gov opportunity objects into a stable, SAM-shaped canonical dict for storage."""

from __future__ import annotations

from typing import Any, Dict, List


def _active_string(v: Any) -> str:
    if isinstance(v, bool):
        return "Yes" if v else "No"
    s = str(v).strip().lower()
    if s in ("yes", "true", "1", "y"):
        return "Yes"
    if s in ("no", "false", "0", "n"):
        return "No"
    return str(v).strip() if v is not None and str(v).strip() else "No"


# Preferred key order (SAM-shaped workspace dict + Arrow merge fields at end).
_CANONICAL_ORDER: List[str] = [
    "noticeId",
    "title",
    "solicitationNumber",
    "fullParentPathName",
    "fullParentPathCode",
    "postedDate",
    "responseDeadLine",
    "archiveDate",
    "type",
    "baseType",
    "archiveType",
    "typeOfSetAside",
    "typeOfSetAsideDescription",
    "naicsCode",
    "naicsCodes",
    "classificationCode",
    "active",
    "award",
    "pointOfContact",
    "description",
    "organizationType",
    "officeAddress",
    "placeOfPerformance",
    "additionalInfoLink",
    "uiLink",
    "links",
    "resourceLinks",
    "organizationHierarchy",
    "ingestSource",
    "csvColumns",
]


def canonical_opportunity(raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize arbitrary SAM-shaped dict (e.g. from bulk CSV mapping) into one consistent object.

    - Uses SAM field names (not DB column names).
    - Fills a fixed set of keys (null when absent) so payloads are comparable.
    - Copies any extra keys from the input (forward compatibility).
    """
    if not isinstance(raw, dict):
        raise TypeError("canonical_opportunity expects a dict")

    out: Dict[str, Any] = {}

    for k in _CANONICAL_ORDER:
        if k == "active":
            out[k] = _active_string(raw["active"]) if "active" in raw else "No"
            continue
        if k == "responseDeadLine":
            v = raw.get("responseDeadLine")
            if v is None and raw.get("responseDeadline") is not None:
                v = raw.get("responseDeadline")
            out[k] = v
            continue
        out[k] = raw.get(k)

    # Derive naicsCodes when only naicsCode exists.
    if out.get("naicsCodes") is None and out.get("naicsCode"):
        code = str(out["naicsCode"]).strip()
        if code:
            out["naicsCodes"] = [code]

    placed = set(_CANONICAL_ORDER)
    for k, v in raw.items():
        if k in placed:
            continue
        if k == "responseDeadline":
            continue
        out[k] = v

    return out
