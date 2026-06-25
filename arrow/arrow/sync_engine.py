"""Sync bulk ContractOpportunitiesFullCSV into local SQLite."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from arrow.bulk_csv import cache_bulk_csv, csv_row_to_sam_dict, file_fingerprint, iter_csv_rows
from arrow.bulk_download import (
    download_full_contract_opportunities_csv,
    last_downloaded_sha256,
    save_last_full_csv_sha256,
)
from arrow.normalize import normalize_opportunity
from arrow.repo import OpportunityRepo


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _parse_stored_raw_json(conn: sqlite3.Connection, notice_id: str) -> Dict[str, Any]:
    r = conn.execute(
        "SELECT raw_json FROM opportunities WHERE notice_id = ?",
        (notice_id,),
    ).fetchone()
    if not r or not r["raw_json"]:
        return {}
    try:
        d = json.loads(r["raw_json"])
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _merge_bulk_csv_over_stored(existing: Dict[str, Any], csv_payload: Dict[str, Any]) -> Dict[str, Any]:
    """Refresh CSV-mapped fields and csvColumns without dropping extra keys already in raw_json."""
    out = dict(existing)
    for k, v in csv_payload.items():
        if k == "csvColumns":
            out[k] = v
            continue
        if v is None:
            continue
        if isinstance(v, str) and not v.strip():
            continue
        out[k] = v
    return out


def _upsert_opportunity(
    conn: sqlite3.Connection,
    norm_row: Dict[str, Any],
    new_hash: str,
    run_id: int,
    now: str,
    source: str,
) -> Tuple[int, int]:
    """Insert or update one opportunity. Returns (new_delta, changed_delta)."""
    nid = norm_row["notice_id"]
    old = conn.execute(
        """
        SELECT raw_json, normalized_hash, first_seen_at
        FROM opportunities WHERE notice_id = ?
        """,
        (nid,),
    ).fetchone()

    if old is None:
        conn.execute(
            """
            INSERT INTO opportunities (
                notice_id, solicitation_number, title, posted_date, response_deadline,
                agency_path_name, agency_path_code, notice_type, base_type, archive_date,
                set_aside_code, set_aside_description, naics_code, classification_code,
                active, link, description, raw_json, normalized_hash,
                first_seen_at, last_seen_at, last_source, sync_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')
            """,
            (
                nid,
                norm_row["solicitation_number"],
                norm_row["title"],
                norm_row["posted_date"],
                norm_row["response_deadline"],
                norm_row["agency_path_name"],
                norm_row["agency_path_code"],
                norm_row["notice_type"],
                norm_row["base_type"],
                norm_row["archive_date"],
                norm_row["set_aside_code"],
                norm_row["set_aside_description"],
                norm_row["naics_code"],
                norm_row["classification_code"],
                norm_row["active"],
                norm_row["link"],
                norm_row["description"],
                norm_row["raw_json"],
                new_hash,
                now,
                now,
                source,
            ),
        )
        return (1, 0)

    old_hash = str(old["normalized_hash"])
    if old_hash != new_hash:
        conn.execute(
            """
            INSERT INTO opportunity_snapshots (
                notice_id, sync_run_id, pulled_at, source_type, raw_json, normalized_hash
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (nid, run_id, now, source, old["raw_json"], old_hash),
        )
        conn.execute(
            """
            UPDATE opportunities SET
                solicitation_number = ?, title = ?, posted_date = ?, response_deadline = ?,
                agency_path_name = ?, agency_path_code = ?, notice_type = ?, base_type = ?,
                archive_date = ?, set_aside_code = ?, set_aside_description = ?,
                naics_code = ?, classification_code = ?, active = ?, link = ?, description = ?,
                raw_json = ?, normalized_hash = ?, last_seen_at = ?, last_source = ?,
                sync_status = 'active'
            WHERE notice_id = ?
            """,
            (
                norm_row["solicitation_number"],
                norm_row["title"],
                norm_row["posted_date"],
                norm_row["response_deadline"],
                norm_row["agency_path_name"],
                norm_row["agency_path_code"],
                norm_row["notice_type"],
                norm_row["base_type"],
                norm_row["archive_date"],
                norm_row["set_aside_code"],
                norm_row["set_aside_description"],
                norm_row["naics_code"],
                norm_row["classification_code"],
                norm_row["active"],
                norm_row["link"],
                norm_row["description"],
                norm_row["raw_json"],
                new_hash,
                now,
                source,
                nid,
            ),
        )
        return (0, 1)

    # Canonical fields unchanged, but merged raw_json may still differ (e.g. csvColumns refresh).
    if norm_row["raw_json"] != old["raw_json"]:
        conn.execute(
            """
            UPDATE opportunities SET raw_json = ?, last_seen_at = ?, last_source = ?
            WHERE notice_id = ?
            """,
            (norm_row["raw_json"], now, source, nid),
        )
    else:
        conn.execute(
            """
            UPDATE opportunities SET last_seen_at = ?, last_source = ?
            WHERE notice_id = ?
            """,
            (now, source, nid),
        )
    return (0, 0)


def _record_sync_error(conn: sqlite3.Connection, started: str, source_type: str, err: Exception) -> None:
    fin = _utc_now_iso()
    try:
        conn.execute(
            """
            INSERT INTO sync_runs (
                source_type, started_at, finished_at, status,
                total_seen, new_count, changed_count, missing_count, notes
            ) VALUES (?, ?, ?, 'error', 0, 0, 0, 0, ?)
            """,
            (source_type, started, fin, str(err)[:2000]),
        )
    except Exception:
        pass


def sync_from_bulk_csv(
    repo: OpportunityRepo,
    csv_path: Path | str,
    *,
    cache: bool = True,
) -> Dict[str, Any]:
    """
    Ingest SAM Contract Opportunities full CSV: copy to ~/.arrow/cache/ (optional), upsert DB.
    Marks sync_status='missing' for rows that were last seen from bulk but are not in this file.
    """
    src = Path(csv_path).expanduser().resolve()
    if not src.is_file():
        raise FileNotFoundError(f"CSV not found: {src}")

    read_path = cache_bulk_csv(src) if cache else src
    fp = file_fingerprint(read_path)

    conn = repo.conn
    started = _utc_now_iso()
    notes = f"csv={read_path.name} fp={fp} cached={cache}"

    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            """
            INSERT INTO sync_runs (source_type, started_at, status, total_seen, new_count, changed_count, missing_count)
            VALUES ('bulk_csv', ?, 'running', 0, 0, 0, 0)
            """,
            (started,),
        )
        row = conn.execute("SELECT last_insert_rowid() AS id").fetchone()
        run_id = int(row["id"]) if row else 0

        conn.execute(
            "CREATE TEMP TABLE IF NOT EXISTS bulk_seen (notice_id TEXT PRIMARY KEY NOT NULL)"
        )
        conn.execute("DELETE FROM bulk_seen")

        new_count = 0
        changed_count = 0
        total_seen = 0

        for csv_row in iter_csv_rows(read_path):
            merged = csv_row_to_sam_dict(csv_row)
            nid = str(merged.get("noticeId") or "").strip()
            if not nid:
                continue
            stored = _parse_stored_raw_json(conn, nid)
            if stored:
                merged = _merge_bulk_csv_over_stored(stored, merged)
            try:
                norm_row, new_hash = normalize_opportunity(merged)
            except ValueError:
                continue
            total_seen += 1
            now = _utc_now_iso()
            dn, dc = _upsert_opportunity(conn, norm_row, new_hash, run_id, now, "bulk_csv")
            new_count += dn
            changed_count += dc
            conn.execute("INSERT OR IGNORE INTO bulk_seen (notice_id) VALUES (?)", (nid,))

        cur = conn.execute(
            """
            UPDATE opportunities
            SET sync_status = 'missing'
            WHERE notice_id NOT IN (SELECT notice_id FROM bulk_seen)
              AND last_source = 'bulk_csv'
            """
        )
        missing_count = cur.rowcount if cur.rowcount is not None else 0

        finished = _utc_now_iso()
        conn.execute(
            """
            UPDATE sync_runs SET
                finished_at = ?, status = 'ok', total_seen = ?, new_count = ?, changed_count = ?,
                missing_count = ?, notes = ?
            WHERE id = ?
            """,
            (finished, total_seen, new_count, changed_count, missing_count, notes, run_id),
        )
        conn.execute("COMMIT")
    except Exception as e:
        conn.execute("ROLLBACK")
        _record_sync_error(conn, started, "bulk_csv", e)
        raise

    return {
        "run_id": run_id,
        "total_seen": total_seen,
        "new_count": new_count,
        "changed_count": changed_count,
        "missing_count": missing_count,
        "started_at": started,
        "finished_at": finished,
        "cached_path": str(read_path),
    }


def sync_full_csv_from_url(
    repo: OpportunityRepo,
    *,
    url: Optional[str] = None,
    skip_if_unchanged: bool = True,
) -> Dict[str, Any]:
    """
    Download the official ContractOpportunitiesFullCSV from SAM.gov, then bulk-ingest.

    When ``skip_if_unchanged`` is True and the downloaded bytes match the last successful
    ingest (sha256 in ~/.arrow/cache), the SQLite ingest is skipped (saves time on large files).

    Override URL with env ``ARROW_FULL_CSV_URL``.
    """
    path, digest = download_full_contract_opportunities_csv(url=url)
    if skip_if_unchanged and digest == last_downloaded_sha256():
        return {
            "skipped": True,
            "sha256": digest,
            "path": str(path),
            "cached_path": str(path),
            "run_id": None,
            "total_seen": 0,
            "new_count": 0,
            "changed_count": 0,
            "missing_count": 0,
            "started_at": "",
            "finished_at": "",
        }
    summary = sync_from_bulk_csv(repo, path, cache=False)
    save_last_full_csv_sha256(digest)
    summary["skipped"] = False
    summary["sha256"] = digest
    return summary
