"""Normalize SAM-shaped opportunity dicts into canonical DB rows + stable hash."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, Tuple

from arrow.canonical import canonical_opportunity


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _as_bool_active(v: Any) -> int:
    if isinstance(v, bool):
        return 1 if v else 0
    s = str(v).strip().lower()
    if s in ("yes", "true", "1", "y"):
        return 1
    return 0


def _first_naics(raw: Dict[str, Any]) -> str:
    code = raw.get("naicsCode")
    if code is not None and str(code).strip():
        return str(code).strip()
    codes = raw.get("naicsCodes")
    if isinstance(codes, list) and codes:
        return str(codes[0]).strip()
    return ""


def normalize_opportunity(raw: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
    """Return (db_row_dict, normalized_hash). db_row_dict values match opportunities columns."""
    notice_id = str(raw.get("noticeId") or "").strip()
    if not notice_id:
        raise ValueError("missing noticeId")

    canon = canonical_opportunity(raw)

    row = {
        "notice_id": notice_id,
        "solicitation_number": str(canon.get("solicitationNumber") or "").strip() or None,
        "title": str(canon.get("title") or "").strip() or None,
        "posted_date": str(canon.get("postedDate") or "").strip() or None,
        "response_deadline": str(canon.get("responseDeadLine") or "").strip() or None,
        "agency_path_name": str(canon.get("fullParentPathName") or "").strip() or None,
        "agency_path_code": str(canon.get("fullParentPathCode") or "").strip() or None,
        "notice_type": str(canon.get("type") or "").strip() or None,
        "base_type": str(canon.get("baseType") or "").strip() or None,
        "archive_date": str(canon.get("archiveDate") or "").strip() or None,
        "set_aside_code": str(canon.get("typeOfSetAside") or "").strip() or None,
        "set_aside_description": str(canon.get("typeOfSetAsideDescription") or "").strip() or None,
        "naics_code": _first_naics(canon) or None,
        "classification_code": str(canon.get("classificationCode") or "").strip() or None,
        "active": _as_bool_active(canon.get("active")),
        "link": str(canon.get("uiLink") or "").strip() or None,
        "description": str(canon.get("description") or "").strip() or None,
        "raw_json": json.dumps(canon, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
    }

    canonical = {
        "notice_id": row["notice_id"],
        "solicitation_number": row["solicitation_number"],
        "title": row["title"],
        "posted_date": row["posted_date"],
        "response_deadline": row["response_deadline"],
        "agency_path_name": row["agency_path_name"],
        "agency_path_code": row["agency_path_code"],
        "notice_type": row["notice_type"],
        "base_type": row["base_type"],
        "archive_date": row["archive_date"],
        "set_aside_code": row["set_aside_code"],
        "set_aside_description": row["set_aside_description"],
        "naics_code": row["naics_code"],
        "classification_code": row["classification_code"],
        "active": row["active"],
        "link": row["link"],
        "description": row["description"],
    }
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    h = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return row, h


def row_to_sam_shape(row: Any) -> Dict[str, Any]:
    """Rebuild SAM-shaped dict for REPL/TUI from DB row or dict."""

    def g(key: str) -> Any:
        if isinstance(row, dict):
            return row.get(key)
        return row[key]

    active = g("active")
    active_s = "Yes" if (active == 1 or active is True) else "No"

    return {
        "noticeId": g("notice_id"),
        "solicitationNumber": g("solicitation_number") or "",
        "title": g("title") or "",
        "postedDate": g("posted_date") or "",
        "responseDeadLine": g("response_deadline") or "",
        "fullParentPathName": g("agency_path_name") or "",
        "fullParentPathCode": g("agency_path_code") or "",
        "type": g("notice_type") or "",
        "baseType": g("base_type") or "",
        "archiveDate": g("archive_date") or "",
        "typeOfSetAside": g("set_aside_code") or "",
        "typeOfSetAsideDescription": g("set_aside_description") or "",
        "naicsCode": g("naics_code") or "",
        "classificationCode": g("classification_code") or "",
        "active": active_s,
        "uiLink": g("link") or "",
        "description": g("description") or "",
    }
