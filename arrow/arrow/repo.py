"""Read/write opportunities and related tables (no HTTP)."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from arrow.db import connect, default_db_path, init_schema
from arrow.normalize import row_to_sam_shape

# Upper bound for list_recent / search_title / list_saved (local SQLite).
MAX_LIST_LIMIT = 50000


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class OpportunityRepo:
    def __init__(self, db_path: Optional[Path] = None) -> None:
        self._path = db_path or default_db_path()
        self._conn = connect(self._path)
        init_schema(self._conn)

    @property
    def conn(self) -> sqlite3.Connection:
        return self._conn

    def close(self) -> None:
        self._conn.close()

    def count_opportunities(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) AS c FROM opportunities").fetchone()
        return int(row["c"]) if row else 0

    def get_raw_dict(self, notice_id: str) -> Optional[Dict[str, Any]]:
        """
        Full opportunity payload from raw_json (verbatim from last ingest).

        Bulk CSV ingest stores columns mapped in csv_row_to_sam_dict plus csvColumns in raw_json.
        List/search rows use row_to_sam_shape (slim); detail/export should use this method.
        """
        r = self._conn.execute(
            "SELECT * FROM opportunities WHERE notice_id = ?",
            (notice_id,),
        ).fetchone()
        if not r:
            return None
        raw = r["raw_json"]
        if raw:
            try:
                d = json.loads(raw)
                if isinstance(d, dict):
                    return d
            except Exception:
                pass
        return row_to_sam_shape(r)

    def list_recent(self, n: int) -> List[Dict[str, Any]]:
        n = max(1, min(n, MAX_LIST_LIMIT))
        cur = self._conn.execute(
            """
            SELECT * FROM opportunities
            ORDER BY COALESCE(posted_date, '') DESC, last_seen_at DESC
            LIMIT ?
            """,
            (n,),
        )
        return [row_to_sam_shape(r) for r in cur.fetchall()]

    def search_title(self, q: str, limit: int = 50) -> List[Dict[str, Any]]:
        q = (q or "").strip()
        if not q:
            return []
        limit = max(1, min(limit, MAX_LIST_LIMIT))
        like = f"%{q}%"
        cur = self._conn.execute(
            """
            SELECT * FROM opportunities
            WHERE title LIKE ? COLLATE NOCASE
            ORDER BY COALESCE(posted_date, '') DESC
            LIMIT ?
            """,
            (like, limit),
        )
        return [row_to_sam_shape(r) for r in cur.fetchall()]

    def search_notice_id(self, notice_id: str) -> List[Dict[str, Any]]:
        nid = (notice_id or "").strip()
        if not nid:
            return []
        cur = self._conn.execute(
            """
            SELECT * FROM opportunities
            WHERE notice_id = ? OR solicitation_number = ?
            LIMIT 20
            """,
            (nid, nid),
        )
        return [row_to_sam_shape(r) for r in cur.fetchall()]

    def list_newest_posted(self, n: int = 20) -> List[Dict[str, Any]]:
        """Newest solicitations by posted_date (same idea as list); tie-break first_seen_at."""
        n = max(1, min(n, 100))
        cur = self._conn.execute(
            """
            SELECT * FROM opportunities
            ORDER BY COALESCE(posted_date, '') DESC, first_seen_at DESC
            LIMIT ?
            """,
            (n,),
        )
        return [row_to_sam_shape(r) for r in cur.fetchall()]

    def list_changed_multi_snapshot(self, n: int = 20) -> List[Dict[str, Any]]:
        """Notices with more than one snapshot row (content changed at least once)."""
        n = max(1, min(n, 100))
        cur = self._conn.execute(
            """
            SELECT o.* FROM opportunities o
            WHERE (SELECT COUNT(*) FROM opportunity_snapshots s WHERE s.notice_id = o.notice_id) > 1
            ORDER BY o.last_seen_at DESC
            LIMIT ?
            """,
            (n,),
        )
        return [row_to_sam_shape(r) for r in cur.fetchall()]

    def last_sync_run(self) -> Optional[sqlite3.Row]:
        return self._conn.execute(
            """
            SELECT * FROM sync_runs
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()

    def save_item(self, notice_id: str, *, source: str = "repl", notes: Optional[str] = None) -> None:
        now = _utc_now_iso()
        self._conn.execute(
            """
            INSERT INTO saved_items (notice_id, saved_at, source, notes)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(notice_id) DO UPDATE SET
                saved_at = excluded.saved_at,
                source = excluded.source,
                notes = COALESCE(excluded.notes, saved_items.notes)
            """,
            (notice_id, now, source, notes),
        )

    def list_saved(self, limit: int = 50) -> List[Dict[str, Any]]:
        limit = max(1, min(limit, MAX_LIST_LIMIT))
        cur = self._conn.execute(
            """
            SELECT o.* FROM saved_items s
            JOIN opportunities o ON o.notice_id = s.notice_id
            ORDER BY s.saved_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [row_to_sam_shape(r) for r in cur.fetchall()]

    def remove_saved(self, notice_id: str) -> bool:
        cur = self._conn.execute("DELETE FROM saved_items WHERE notice_id = ?", (notice_id,))
        return (cur.rowcount or 0) > 0
