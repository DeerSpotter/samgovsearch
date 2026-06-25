"""SQLite schema and connection for Arrow local datastore."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional


def default_db_path() -> Path:
    return Path.home() / ".arrow" / "arrow.db"


def connect(path: Optional[Path] = None) -> sqlite3.Connection:
    p = path or default_db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), isolation_level=None)  # autocommit; we use explicit BEGIN
    conn.row_factory = sqlite3.Row
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        PRAGMA foreign_keys = ON;

        CREATE TABLE IF NOT EXISTS opportunities (
            notice_id TEXT PRIMARY KEY,
            solicitation_number TEXT,
            title TEXT,
            posted_date TEXT,
            response_deadline TEXT,
            agency_path_name TEXT,
            agency_path_code TEXT,
            notice_type TEXT,
            base_type TEXT,
            archive_date TEXT,
            set_aside_code TEXT,
            set_aside_description TEXT,
            naics_code TEXT,
            classification_code TEXT,
            active INTEGER NOT NULL DEFAULT 1,
            link TEXT,
            description TEXT,
            raw_json TEXT NOT NULL,
            normalized_hash TEXT NOT NULL,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            last_source TEXT NOT NULL,
            sync_status TEXT NOT NULL DEFAULT 'active'
        );

        CREATE INDEX IF NOT EXISTS idx_opportunities_posted ON opportunities(posted_date);
        CREATE INDEX IF NOT EXISTS idx_opportunities_title ON opportunities(title);
        CREATE INDEX IF NOT EXISTS idx_opportunities_last_seen ON opportunities(last_seen_at);
        CREATE INDEX IF NOT EXISTS idx_opportunities_first_seen ON opportunities(first_seen_at);

        CREATE TABLE IF NOT EXISTS opportunity_snapshots (
            snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
            notice_id TEXT NOT NULL,
            sync_run_id INTEGER NOT NULL,
            pulled_at TEXT NOT NULL,
            source_type TEXT NOT NULL,
            raw_json TEXT NOT NULL,
            normalized_hash TEXT NOT NULL,
            FOREIGN KEY (notice_id) REFERENCES opportunities(notice_id)
        );

        CREATE INDEX IF NOT EXISTS idx_snapshots_notice ON opportunity_snapshots(notice_id);
        CREATE INDEX IF NOT EXISTS idx_snapshots_run ON opportunity_snapshots(sync_run_id);

        CREATE TABLE IF NOT EXISTS sync_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_type TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            status TEXT NOT NULL,
            total_seen INTEGER NOT NULL DEFAULT 0,
            new_count INTEGER NOT NULL DEFAULT 0,
            changed_count INTEGER NOT NULL DEFAULT 0,
            missing_count INTEGER NOT NULL DEFAULT 0,
            notes TEXT
        );

        CREATE TABLE IF NOT EXISTS saved_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            notice_id TEXT NOT NULL UNIQUE,
            saved_at TEXT NOT NULL,
            source TEXT,
            notes TEXT,
            FOREIGN KEY (notice_id) REFERENCES opportunities(notice_id)
        );
        """
    )
