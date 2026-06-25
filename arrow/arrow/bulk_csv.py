"""SAM.gov Contract Opportunities full CSV: cache locally and stream rows."""

from __future__ import annotations

import csv
import hashlib
import io
import shutil
from pathlib import Path
from typing import Any, Dict, Iterator, Optional


def default_cache_dir() -> Path:
    return Path.home() / ".arrow" / "cache"


def cache_bulk_csv(src: Path, *, dest_name: Optional[str] = None) -> Path:
    """Copy CSV into ~/.arrow/cache/ and return the destination path."""
    src = src.expanduser().resolve()
    if not src.is_file():
        raise FileNotFoundError(f"CSV not found: {src}")
    d = default_cache_dir()
    d.mkdir(parents=True, exist_ok=True)
    name = dest_name or src.name
    dest = d / name
    shutil.copy2(src, dest)
    latest = d / "latest.csv"
    try:
        if latest.exists() or latest.is_symlink():
            latest.unlink()
        latest.symlink_to(dest.name)
    except OSError:
        pass
    return dest


def file_fingerprint(path: Path) -> str:
    st = path.stat()
    h = hashlib.sha256()
    h.update(str(st.st_size).encode())
    h.update(str(int(st.st_mtime_ns)).encode())
    return h.hexdigest()[:16]


def csv_row_all_columns(row: Dict[str, Any]) -> Dict[str, str]:
    """Every non-empty CSV field (original header → value) for maximum fidelity in raw_json."""
    out: Dict[str, str] = {}
    for k, v in row.items():
        if not k:
            continue
        s = "" if v is None else str(v).strip()
        if s:
            out[str(k)] = s
    return out


def csv_row_to_sam_dict(row: Dict[str, Any]) -> Dict[str, Any]:
    """Map SAM full CSV columns to SAM-shaped keys plus csvColumns (full row) for raw_json."""

    def g(key: str) -> str:
        v = row.get(key)
        if v is None:
            return ""
        return str(v).strip()

    posted = g("PostedDate")
    posted_date = posted[:10] if len(posted) >= 10 else (posted or None)

    dept = g("Department/Ind.Agency")
    sub = g("Sub-Tier")
    office = g("Office")
    parts = [p for p in (dept, sub, office) if p]
    full_path = ".".join(parts) if parts else None

    cgac = g("CGAC")
    fpds = g("FPDS Code")
    aac = g("AAC Code")
    codes = [p for p in (cgac, fpds, aac) if p]
    path_code = ".".join(codes) if codes else None

    active = g("Active") or "No"
    naics = g("NaicsCode") or None

    out: Dict[str, Any] = {
        "noticeId": g("NoticeId"),
        "title": g("Title") or None,
        "solicitationNumber": g("Sol#") or None,
        "postedDate": posted_date,
        "responseDeadLine": g("ResponseDeadLine") or None,
        "fullParentPathName": full_path,
        "fullParentPathCode": path_code,
        "type": g("Type") or None,
        "baseType": g("BaseType") or None,
        "archiveType": g("ArchiveType") or None,
        "archiveDate": g("ArchiveDate") or None,
        "typeOfSetAside": g("SetASideCode") or None,
        "typeOfSetAsideDescription": g("SetASide") or None,
        "naicsCode": naics,
        "classificationCode": g("ClassificationCode") or None,
        "active": active,
        "uiLink": g("Link") or None,
        "description": g("Description") or None,
        "csvColumns": csv_row_all_columns(row),
        "ingestSource": "sam_gov_csv",
    }
    if naics:
        out["naicsCodes"] = [naics]
    return out


def _load_csv_text(path: Path) -> str:
    """Read whole file and decode (pick encoding once; avoids partial UTF-8 reads)."""
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def iter_csv_rows(path: Path) -> Iterator[Dict[str, Any]]:
    path = path.expanduser().resolve()
    text = _load_csv_text(path)
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        if not row:
            continue
        yield row
