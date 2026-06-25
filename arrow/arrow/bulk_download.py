"""Download SAM.gov Contract Opportunities full CSV (public, no API key)."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Optional, Tuple

import requests

from arrow.bulk_csv import default_cache_dir
from arrow.ipv4_preference import enable_ipv4_preference

# Official public extract (updated on a schedule; typically every few hours).
DEFAULT_FULL_CSV_URL = (
    "https://sam.gov/api/prod/fileextractservices/v1/api/download/"
    "Contract%20Opportunities/datagov/ContractOpportunitiesFullCSV.csv?privacy=Public"
)

_DEFAULT_UA = "Arrow/0.2 (+https://sam.gov) contract-opportunities-csv"


def full_csv_url() -> str:
    return (os.environ.get("ARROW_FULL_CSV_URL") or DEFAULT_FULL_CSV_URL).strip() or DEFAULT_FULL_CSV_URL


def _sha256_state_path() -> Path:
    return default_cache_dir() / ".ContractOpportunitiesFullCSV.sha256"


def last_downloaded_sha256() -> Optional[str]:
    p = _sha256_state_path()
    if not p.is_file():
        return None
    try:
        return p.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def save_last_full_csv_sha256(digest_hex: str) -> None:
    p = _sha256_state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(digest_hex + "\n", encoding="utf-8")


def download_full_contract_opportunities_csv(
    *,
    url: Optional[str] = None,
    dest_path: Optional[Path] = None,
    timeout: float = 1200.0,
    chunk_size: int = 8 * 1024 * 1024,
) -> Tuple[Path, str]:
    """
    Stream-download the full CSV into ~/.arrow/cache/ (atomic replace).

    Returns (resolved_path, sha256_hex of file bytes).
    """
    enable_ipv4_preference()
    u = (url or full_csv_url()).strip()
    out = (dest_path or (default_cache_dir() / "ContractOpportunitiesFullCSV.csv")).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".part")

    h = hashlib.sha256()
    session = requests.Session()
    session.headers.update({"User-Agent": os.environ.get("ARROW_HTTP_USER_AGENT") or _DEFAULT_UA})

    with session.get(u, stream=True, timeout=timeout) as r:
        r.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(chunk_size=chunk_size):
                if chunk:
                    h.update(chunk)
                    f.write(chunk)

    digest = h.hexdigest()
    tmp.replace(out)

    # Symlink ~/.arrow/cache/latest.csv → this file (same as manual cache flow).
    latest = out.parent / "latest.csv"
    try:
        if latest.exists() or latest.is_symlink():
            latest.unlink()
        latest.symlink_to(out.name)
    except OSError:
        pass

    return out, digest
