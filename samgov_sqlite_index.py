from __future__ import annotations

import csv
import json
import os
import shutil
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import samgovsearch as base
import samgovsearch_unified as unified
from samgov_api_cache import SamGovApiCache, default_cache_root, normalize_notice_id, parse_iso_datetime, utc_now_iso

SCHEMA_VERSION = 1
DB_FILE_NAME = "samgov_index.sqlite"


JsonDict = Dict[str, Any]


@dataclass
class IndexSummary:
    db_path: Path
    notice_count: int
    attachment_count: int
    last_rebuild_utc: str


def default_index_path(cache: Optional[SamGovApiCache] = None) -> Path:
    root = cache.root if cache is not None else default_cache_root()
    return root / DB_FILE_NAME


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def json_loads_list(value: Any) -> List[Any]:
    if not value:
        return []
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(str(value))
    except Exception:
        return []
    return parsed if isinstance(parsed, list) else []


def normalize_text(value: Any) -> str:
    return base.normalize_text(value)


def attachment_total_mb(item: JsonDict) -> Optional[float]:
    total_bytes = unified.parse_int_like(item.get("samgovsearchAttachmentTotalBytes"))
    if total_bytes is not None:
        return total_bytes / (1024 * 1024)

    raw = item.get("attachment_total_mb")
    if raw is not None:
        try:
            return float(raw)
        except Exception:
            return None
    return None


def attachment_names_from_item(item: JsonDict) -> List[str]:
    names = item.get("samgovsearchAttachmentNames")
    if isinstance(names, list):
        return [normalize_text(name) for name in names if normalize_text(name)]

    names = item.get("attachmentNames")
    if isinstance(names, list):
        return [normalize_text(name) for name in names if normalize_text(name)]

    return []


def resource_links_from_item(item: JsonDict) -> List[str]:
    links = base.extract_resource_links(item)
    if links:
        return links
    value = item.get("resource_links")
    if isinstance(value, list):
        return [normalize_text(link) for link in value if normalize_text(link)]
    return []


def attachment_count_from_item(item: JsonDict) -> int:
    links = resource_links_from_item(item)
    if links:
        return len(links)
    count = unified.parse_int_like(item.get("attachmentCount") or item.get("attachment_count"))
    return int(count or 0)


def source_label_from_record(record: JsonDict, item: JsonDict) -> str:
    return normalize_text(record.get("source") or item.get("samgovsearchSource") or item.get("source"))


def saved_at_from_record(record: JsonDict) -> str:
    return normalize_text(record.get("saved_at_utc") or record.get("savedAt") or "")


class SamGovSQLiteIndex:
    """SQLite search index built from the existing JSON cache.

    The JSON cache remains the canonical source. SQLite is the fast local
    searchable index over notices and attachment names.
    """

    def __init__(self, cache: Optional[SamGovApiCache] = None, db_path: Optional[Path] = None) -> None:
        self.cache = cache or SamGovApiCache.default()
        self.db_path = db_path or default_index_path(self.cache)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.ensure_schema()

    @classmethod
    def default(cls) -> "SamGovSQLiteIndex":
        return cls(SamGovApiCache.default())

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def ensure_schema(self) -> None:
        with closing(self.connect()) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS notices (
                    notice_id TEXT PRIMARY KEY,
                    title TEXT,
                    solicitation_number TEXT,
                    notice_type TEXT,
                    posted_date TEXT,
                    response_deadline TEXT,
                    active TEXT,
                    organization TEXT,
                    naics_code TEXT,
                    classification_code TEXT,
                    attachment_count INTEGER DEFAULT 0,
                    attachment_total_mb REAL,
                    attachment_names_text TEXT,
                    attachment_names_json TEXT,
                    resource_links_json TEXT,
                    description TEXT,
                    ui_link TEXT,
                    source TEXT,
                    saved_at_utc TEXT,
                    indexed_at_utc TEXT NOT NULL,
                    raw_json TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS notices_fts USING fts5(
                    notice_id UNINDEXED,
                    title,
                    solicitation_number,
                    notice_type,
                    organization,
                    naics_code,
                    classification_code,
                    attachment_names_text,
                    description,
                    content='notices',
                    content_rowid='rowid'
                )
                """
            )
            conn.execute(
                """
                CREATE TRIGGER IF NOT EXISTS notices_ai AFTER INSERT ON notices BEGIN
                    INSERT INTO notices_fts(
                        rowid, notice_id, title, solicitation_number, notice_type, organization,
                        naics_code, classification_code, attachment_names_text, description
                    )
                    VALUES (
                        new.rowid, new.notice_id, new.title, new.solicitation_number, new.notice_type,
                        new.organization, new.naics_code, new.classification_code,
                        new.attachment_names_text, new.description
                    );
                END
                """
            )
            conn.execute(
                """
                CREATE TRIGGER IF NOT EXISTS notices_ad AFTER DELETE ON notices BEGIN
                    INSERT INTO notices_fts(
                        notices_fts, rowid, notice_id, title, solicitation_number, notice_type,
                        organization, naics_code, classification_code, attachment_names_text, description
                    )
                    VALUES (
                        'delete', old.rowid, old.notice_id, old.title, old.solicitation_number,
                        old.notice_type, old.organization, old.naics_code, old.classification_code,
                        old.attachment_names_text, old.description
                    );
                END
                """
            )
            conn.execute(
                """
                CREATE TRIGGER IF NOT EXISTS notices_au AFTER UPDATE ON notices BEGIN
                    INSERT INTO notices_fts(
                        notices_fts, rowid, notice_id, title, solicitation_number, notice_type,
                        organization, naics_code, classification_code, attachment_names_text, description
                    )
                    VALUES (
                        'delete', old.rowid, old.notice_id, old.title, old.solicitation_number,
                        old.notice_type, old.organization, old.naics_code, old.classification_code,
                        old.attachment_names_text, old.description
                    );
                    INSERT INTO notices_fts(
                        rowid, notice_id, title, solicitation_number, notice_type, organization,
                        naics_code, classification_code, attachment_names_text, description
                    )
                    VALUES (
                        new.rowid, new.notice_id, new.title, new.solicitation_number, new.notice_type,
                        new.organization, new.naics_code, new.classification_code,
                        new.attachment_names_text, new.description
                    );
                END
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_notices_posted ON notices(posted_date)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_notices_solicitation ON notices(solicitation_number)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_notices_source ON notices(source)")
            conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
            conn.commit()

    def clear(self) -> None:
        with closing(self.connect()) as conn:
            conn.execute("DELETE FROM notices")
            conn.execute("DELETE FROM notices_fts")
            conn.execute("DELETE FROM meta WHERE key != 'schema_version'")
            conn.commit()

    def delete_database(self) -> None:
        for suffix in ("", "-wal", "-shm"):
            path = Path(str(self.db_path) + suffix)
            try:
                path.unlink()
            except FileNotFoundError:
                pass
        self.ensure_schema()

    def rebuild_from_json_cache(self, progress_callback: Optional[Any] = None) -> int:
        self.ensure_schema()
        count = 0
        with closing(self.connect()) as conn:
            conn.execute("DELETE FROM notices")
            conn.execute("DELETE FROM notices_fts")
            for path in sorted(self.cache.notices_dir.glob("*.json")):
                record = self.cache.read_json(path)
                if not isinstance(record, dict):
                    continue
                item = record.get("item")
                if not isinstance(item, dict):
                    continue
                if not normalize_notice_id(item.get("noticeId") or record.get("notice_id")):
                    continue
                self._upsert_item_conn(conn, item, record=record)
                count += 1
                if progress_callback and count % 100 == 0:
                    progress_callback(count)
            conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('last_rebuild_utc', ?)", (utc_now_iso(),))
            conn.commit()
        return count

    def upsert_item(self, item: JsonDict, source: str = "") -> None:
        record = {
            "source": source or item.get("samgovsearchSource") or "runtime",
            "saved_at_utc": utc_now_iso(),
            "item": item,
        }
        with closing(self.connect()) as conn:
            self._upsert_item_conn(conn, item, record=record)
            conn.commit()

    def _upsert_item_conn(self, conn: sqlite3.Connection, item: JsonDict, record: Optional[JsonDict] = None) -> None:
        record = record or {}
        notice_id = normalize_notice_id(item.get("noticeId") or record.get("notice_id"))
        if not notice_id:
            return

        names = attachment_names_from_item(item)
        links = resource_links_from_item(item)
        raw_json = json_dumps(item)
        conn.execute(
            """
            INSERT INTO notices (
                notice_id, title, solicitation_number, notice_type, posted_date,
                response_deadline, active, organization, naics_code, classification_code,
                attachment_count, attachment_total_mb, attachment_names_text,
                attachment_names_json, resource_links_json, description, ui_link,
                source, saved_at_utc, indexed_at_utc, raw_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(notice_id) DO UPDATE SET
                title=excluded.title,
                solicitation_number=excluded.solicitation_number,
                notice_type=excluded.notice_type,
                posted_date=excluded.posted_date,
                response_deadline=excluded.response_deadline,
                active=excluded.active,
                organization=excluded.organization,
                naics_code=excluded.naics_code,
                classification_code=excluded.classification_code,
                attachment_count=excluded.attachment_count,
                attachment_total_mb=excluded.attachment_total_mb,
                attachment_names_text=excluded.attachment_names_text,
                attachment_names_json=excluded.attachment_names_json,
                resource_links_json=excluded.resource_links_json,
                description=excluded.description,
                ui_link=excluded.ui_link,
                source=excluded.source,
                saved_at_utc=excluded.saved_at_utc,
                indexed_at_utc=excluded.indexed_at_utc,
                raw_json=excluded.raw_json
            """,
            (
                notice_id,
                normalize_text(item.get("title")),
                normalize_text(item.get("solicitationNumber")),
                normalize_text(item.get("type")),
                normalize_text(item.get("postedDate")),
                normalize_text(item.get("responseDeadLine")),
                normalize_text(item.get("active")),
                normalize_text(item.get("fullParentPathName")),
                normalize_text(item.get("naicsCode")),
                normalize_text(item.get("classificationCode")),
                attachment_count_from_item(item),
                attachment_total_mb(item),
                " | ".join(names),
                json_dumps(names),
                json_dumps(links),
                normalize_text(item.get("description")),
                normalize_text(item.get("uiLink")),
                source_label_from_record(record, item),
                saved_at_from_record(record) or utc_now_iso(),
                utc_now_iso(),
                raw_json,
            ),
        )

    def search(
        self,
        keywords: Optional[Sequence[str]] = None,
        attachment_pattern: str = "",
        max_results: int = 1000,
        require_attachments: bool = False,
        min_attachment_count: int = 0,
        min_total_attachment_mb: float = 0.0,
    ) -> List[sqlite3.Row]:
        self.ensure_schema()
        keywords = [str(term).strip() for term in (keywords or []) if str(term).strip()]
        attachment_pattern = attachment_pattern.strip()

        clauses: List[str] = []
        params: List[Any] = []

        if keywords:
            keyword_clauses = []
            for term in keywords:
                like = f"%{term}%"
                keyword_clauses.append(
                    "("
                    "notice_id LIKE ? OR title LIKE ? OR solicitation_number LIKE ? OR "
                    "notice_type LIKE ? OR organization LIKE ? OR naics_code LIKE ? OR "
                    "classification_code LIKE ? OR attachment_names_text LIKE ? OR description LIKE ?"
                    ")"
                )
                params.extend([like] * 9)
            clauses.append("(" + " OR ".join(keyword_clauses) + ")")

        if attachment_pattern:
            like_pattern = attachment_pattern
            if "*" in like_pattern or "?" in like_pattern:
                like_pattern = like_pattern.replace("*", "%").replace("?", "_")
            elif "%" not in like_pattern and "_" not in like_pattern:
                like_pattern = f"%{like_pattern}%"
            clauses.append("(attachment_names_text LIKE ? OR resource_links_json LIKE ?)")
            params.extend([like_pattern, like_pattern])

        if require_attachments:
            clauses.append("attachment_count >= ?")
            params.append(max(1, int(min_attachment_count or 1)))
        elif min_attachment_count:
            clauses.append("attachment_count >= ?")
            params.append(int(min_attachment_count))

        if min_total_attachment_mb:
            clauses.append("COALESCE(attachment_total_mb, 0) >= ?")
            params.append(float(min_total_attachment_mb))

        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        sql = (
            "SELECT * FROM notices"
            f"{where} "
            "ORDER BY "
            "CASE WHEN posted_date IS NULL OR posted_date = '' THEN 1 ELSE 0 END, "
            "posted_date DESC, solicitation_number COLLATE NOCASE, title COLLATE NOCASE "
            "LIMIT ?"
        )
        params.append(int(max_results or 1000))

        with closing(self.connect()) as conn:
            return list(conn.execute(sql, params))

    def all_rows(self, limit: int = 1000) -> List[sqlite3.Row]:
        return self.search(max_results=limit)

    def row_to_search_result(self, row: sqlite3.Row, keyword: str = "local cache") -> base.SearchResult:
        links = json_loads_list(row["resource_links_json"])
        names = json_loads_list(row["attachment_names_json"])
        result = base.SearchResult(
            keyword=keyword,
            matched_by="sqlite-index",
            notice_id=row["notice_id"] or "",
            title=row["title"] or "",
            solicitation_number=row["solicitation_number"] or "",
            notice_type=row["notice_type"] or "",
            posted_date=row["posted_date"] or "",
            response_deadline=row["response_deadline"] or "",
            active=row["active"] or "",
            organization=row["organization"] or "",
            naics_code=row["naics_code"] or "",
            classification_code=row["classification_code"] or "",
            attachment_count=int(row["attachment_count"] or 0),
            attachment_total_mb=row["attachment_total_mb"],
            attachment_size_note="from SQLite local index",
            ui_link=row["ui_link"] or (f"https://sam.gov/opp/{row['notice_id']}/view" if row["notice_id"] else ""),
            resource_links=[str(link) for link in links if str(link).strip()],
        )
        setattr(result, "attachment_names", [str(name) for name in names if str(name).strip()])
        setattr(result, "description", row["description"] or "")
        setattr(result, "cache_source", row["source"] or "")
        setattr(result, "cache_saved_at_utc", row["saved_at_utc"] or "")
        return result

    def rows_to_results(self, rows: Iterable[sqlite3.Row], keyword: str = "local cache") -> List[base.SearchResult]:
        return [self.row_to_search_result(row, keyword=keyword) for row in rows]

    def summary(self) -> IndexSummary:
        self.ensure_schema()
        with closing(self.connect()) as conn:
            notice_count = int(conn.execute("SELECT COUNT(*) FROM notices").fetchone()[0])
            attachment_count = int(conn.execute("SELECT COALESCE(SUM(attachment_count), 0) FROM notices").fetchone()[0])
            row = conn.execute("SELECT value FROM meta WHERE key = 'last_rebuild_utc'").fetchone()
            last_rebuild = row[0] if row else ""
        return IndexSummary(
            db_path=self.db_path,
            notice_count=notice_count,
            attachment_count=attachment_count,
            last_rebuild_utc=last_rebuild,
        )

    def export_csv(self, path: Path) -> int:
        rows = self.all_rows(limit=1_000_000)
        fieldnames = [
            "Notice ID", "Title", "Solicitation Number", "Type", "Posted Date", "Response Deadline",
            "Active", "Organization", "NAICS", "PSC", "Attachment Count", "Attachment Total MB",
            "Attachment Names", "SAM Link", "Source", "Saved At UTC",
        ]
        with path.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow({
                    "Notice ID": row["notice_id"],
                    "Title": row["title"],
                    "Solicitation Number": row["solicitation_number"],
                    "Type": row["notice_type"],
                    "Posted Date": row["posted_date"],
                    "Response Deadline": row["response_deadline"],
                    "Active": row["active"],
                    "Organization": row["organization"],
                    "NAICS": row["naics_code"],
                    "PSC": row["classification_code"],
                    "Attachment Count": row["attachment_count"],
                    "Attachment Total MB": row["attachment_total_mb"],
                    "Attachment Names": row["attachment_names_text"],
                    "SAM Link": row["ui_link"],
                    "Source": row["source"],
                    "Saved At UTC": row["saved_at_utc"],
                })
        return len(rows)
