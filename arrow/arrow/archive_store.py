from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_archive_dir() -> Path:
    """Directory for optional JSON file copies (separate from DB saved_items)."""
    return Path.home() / ".arrow" / "archive"


def _week_folder_name(dt: datetime) -> str:
    # ISO week, e.g. 2026-W15
    iso = dt.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _safe_slug(s: str) -> str:
    keep = []
    for ch in s:
        if ch.isalnum() or ch in ("-", "_"):
            keep.append(ch)
        elif ch.isspace():
            keep.append("_")
    out = "".join(keep).strip("_")
    return out[:80] if out else "item"


@dataclass(frozen=True)
class ArchivedItem:
    archived_at: str
    week: str
    item: Dict[str, Any]
    path: Optional[Path] = None


class ArchiveStore:
    """Optional on-disk JSON copies of notices (week folders). Not the same as DB saved_items."""

    def __init__(self, root_dir: Optional[Path] = None) -> None:
        self.root_dir = root_dir or default_archive_dir()
        self.legacy_jsonl = Path.home() / ".arrow" / "archive.jsonl"

    def append(self, item: Dict[str, Any]) -> None:
        now = datetime.now(timezone.utc)
        week = _week_folder_name(now)
        dest_dir = self.root_dir / week
        dest_dir.mkdir(parents=True, exist_ok=True)

        ident = str(item.get("noticeId") or item.get("solicitationNumber") or "item")
        stamp = now.strftime("%Y%m%dT%H%M%SZ")
        filename = f"{_safe_slug(ident)}_{stamp}.json"
        path = dest_dir / filename

        record = {"archived_at": now.isoformat(), "week": week, "item": item}
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def iter_all(self) -> Iterable[ArchivedItem]:
        out: List[ArchivedItem] = []

        # New format: ~/.arrow/archive/<YYYY-Www>/*.json
        if self.root_dir.exists():
            for week_dir in sorted([p for p in self.root_dir.iterdir() if p.is_dir()]):
                week = week_dir.name
                for p in sorted([x for x in week_dir.iterdir() if x.is_file() and x.suffix == ".json"]):
                    try:
                        rec = json.loads(p.read_text(encoding="utf-8"))
                    except Exception:
                        continue
                    if not isinstance(rec, dict):
                        continue
                    archived_at = rec.get("archived_at")
                    item = rec.get("item")
                    if isinstance(archived_at, str) and isinstance(item, dict):
                        out.append(
                            ArchivedItem(archived_at=archived_at, week=str(rec.get("week") or week), item=item, path=p)
                        )

        # Legacy format: ~/.arrow/archive.jsonl (read-only, kept for continuity)
        if self.legacy_jsonl.exists():
            try:
                raw = self.legacy_jsonl.read_text(encoding="utf-8")
            except Exception:
                raw = ""
            for line in raw.splitlines():
                s = line.strip()
                if not s:
                    continue
                try:
                    rec = json.loads(s)
                except Exception:
                    continue
                if not isinstance(rec, dict):
                    continue
                archived_at = rec.get("archived_at")
                item = rec.get("item")
                if isinstance(archived_at, str) and isinstance(item, dict):
                    out.append(ArchivedItem(archived_at=archived_at, week="legacy", item=item, path=None))

        return out

    def list_newest_first(self, limit: int = 200) -> List[ArchivedItem]:
        items = list(self.iter_all())
        items.sort(key=lambda x: x.archived_at, reverse=True)
        return items[: max(1, limit)]

    def delete(self, archived: ArchivedItem) -> None:
        if not archived.path:
            raise RuntimeError("Cannot delete legacy entries (archive.jsonl has no per-row file).")
        p = Path(archived.path).expanduser().resolve()
        if not p.is_file():
            raise FileNotFoundError(f"Export file missing: {p}")
        p.unlink()

