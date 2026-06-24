from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

CACHE_SCHEMA_VERSION = 1
CACHE_DIR_ENV = "SAMGOVSEARCH_CACHE_DIR"
CACHE_MAX_AGE_DAYS_ENV = "SAMGOVSEARCH_CACHE_MAX_AGE_DAYS"


JsonDict = Dict[str, Any]
FetchFunction = Callable[[Dict[str, Any]], JsonDict]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def default_cache_root() -> Path:
    override = os.environ.get(CACHE_DIR_ENV, "").strip()
    if override:
        return Path(override).expanduser()

    # Use user-local app data by default instead of the Windows temp folder.
    # Temp folders are designed to be deleted by Windows cleanup tools.
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or tempfile.gettempdir()
    return Path(base) / "SAMGovSearch" / "ApiCache"


def canonicalize_params(params: Dict[str, Any]) -> Dict[str, Any]:
    normalized: Dict[str, Any] = {}
    for key, value in params.items():
        if key.lower() == "api_key":
            continue
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            normalized[key] = [str(item) for item in value]
        else:
            normalized[key] = str(value)
    return {key: normalized[key] for key in sorted(normalized)}


def query_cache_key(params: Dict[str, Any]) -> str:
    canonical = canonicalize_params(params)
    blob = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def safe_filename(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    return cleaned[:160] or "unknown"


def normalize_notice_id(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def get_notice_id_from_params(params: Dict[str, Any]) -> str:
    for key in ("noticeid", "noticeId", "noticeID"):
        value = params.get(key)
        if isinstance(value, (list, tuple)):
            value = value[0] if value else ""
        notice_id = normalize_notice_id(value)
        if notice_id:
            return notice_id
    return ""


def parse_cache_max_age_days() -> Optional[float]:
    raw = os.environ.get(CACHE_MAX_AGE_DAYS_ENV, "").strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    if value <= 0:
        return None
    return value


def parse_iso_datetime(value: str) -> Optional[datetime]:
    text = value.strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


class SamGovApiCache:
    def __init__(self, root: Optional[Path] = None, max_age_days: Optional[float] = None) -> None:
        self.root = root or default_cache_root()
        self.max_age_days = parse_cache_max_age_days() if max_age_days is None else max_age_days
        self.queries_dir = self.root / "queries"
        self.notices_dir = self.root / "notices"
        self.events_path = self.root / "index.jsonl"
        self.ensure_ready()

    @classmethod
    def default(cls) -> "SamGovApiCache":
        return cls()

    def ensure_ready(self) -> None:
        self.queries_dir.mkdir(parents=True, exist_ok=True)
        self.notices_dir.mkdir(parents=True, exist_ok=True)
        readme = self.root / "README_DO_NOT_DELETE.txt"
        if not readme.exists():
            readme.write_text(
                "SAM.gov Search API cache.\n"
                "This folder stores prior API responses so future searches can reuse them and reduce SAM.gov API usage.\n"
                "The app will recreate this folder if deleted, but deleted cache data cannot be reused.\n",
                encoding="utf-8",
            )

    def query_path(self, params: Dict[str, Any]) -> Path:
        return self.queries_dir / f"{query_cache_key(params)}.json"

    def notice_path(self, notice_id: str) -> Path:
        return self.notices_dir / f"{safe_filename(notice_id).lower()}.json"

    def read_json(self, path: Path) -> Optional[JsonDict]:
        try:
            with path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            return data if isinstance(data, dict) else None
        except FileNotFoundError:
            return None
        except Exception:
            return None

    def write_json_atomic(self, path: Path, data: JsonDict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(tmp, path)

    def is_stale(self, saved_at: str) -> bool:
        if self.max_age_days is None:
            return False
        saved = parse_iso_datetime(saved_at)
        if saved is None:
            return True
        age_seconds = (datetime.now(timezone.utc) - saved).total_seconds()
        return age_seconds > (self.max_age_days * 86400)

    def append_event(self, event: JsonDict) -> None:
        try:
            event = dict(event)
            event.setdefault("time_utc", utc_now_iso())
            with self.events_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
        except Exception:
            # Cache telemetry must never break searching.
            return

    def get_query_response(self, params: Dict[str, Any]) -> Optional[JsonDict]:
        record = self.read_json(self.query_path(params))
        if not record:
            return None
        if int(record.get("schema_version") or 0) != CACHE_SCHEMA_VERSION:
            return None
        if self.is_stale(str(record.get("saved_at_utc") or "")):
            return None
        response = record.get("response")
        if isinstance(response, dict):
            self.append_event({"event": "query_cache_hit", "query_key": query_cache_key(params)})
            return response
        return None

    def get_notice_response(self, params: Dict[str, Any]) -> Optional[JsonDict]:
        notice_id = get_notice_id_from_params(params)
        if not notice_id:
            return None

        offset = str(params.get("offset", "0")).strip()
        if offset not in ("", "0"):
            return {"opportunitiesData": [], "totalRecords": 0}

        record = self.read_json(self.notice_path(notice_id))
        if not record:
            return None
        if int(record.get("schema_version") or 0) != CACHE_SCHEMA_VERSION:
            return None
        if self.is_stale(str(record.get("saved_at_utc") or "")):
            return None
        item = record.get("item")
        if not isinstance(item, dict):
            return None

        self.append_event({"event": "notice_cache_hit", "notice_id": notice_id})
        return {
            "opportunitiesData": [item],
            "totalRecords": 1,
            "limit": int(str(params.get("limit", "1") or "1")),
            "offset": 0,
            "samgovsearchCache": {
                "hit": True,
                "type": "notice",
                "noticeId": notice_id,
                "cacheRoot": str(self.root),
            },
        }

    def store_notice_item(self, item: Dict[str, Any], source_label: str = "api") -> None:
        notice_id = normalize_notice_id(item.get("noticeId"))
        if not notice_id:
            return
        record = {
            "schema_version": CACHE_SCHEMA_VERSION,
            "saved_at_utc": utc_now_iso(),
            "source": source_label,
            "notice_id": notice_id,
            "item": item,
        }
        self.write_json_atomic(self.notice_path(notice_id), record)
        self.append_event({"event": "notice_store", "notice_id": notice_id, "source": source_label})

    def store_query_response(self, params: Dict[str, Any], response: Dict[str, Any], source_label: str = "api") -> None:
        canonical = canonicalize_params(params)
        key = query_cache_key(params)
        record = {
            "schema_version": CACHE_SCHEMA_VERSION,
            "saved_at_utc": utc_now_iso(),
            "source": source_label,
            "query_key": key,
            "params": canonical,
            "response": response,
        }
        self.write_json_atomic(self.query_path(params), record)

        items = response.get("opportunitiesData") if isinstance(response, dict) else None
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    self.store_notice_item(item, source_label=source_label)

        self.append_event({
            "event": "query_store",
            "query_key": key,
            "source": source_label,
            "item_count": len(items) if isinstance(items, list) else 0,
        })

    def get_or_fetch_response(
        self,
        params: Dict[str, Any],
        fetch_function: FetchFunction,
        source_label: str = "api",
    ) -> Tuple[JsonDict, str]:
        exact = self.get_query_response(params)
        if exact is not None:
            return exact, "query-cache"

        notice = self.get_notice_response(params)
        if notice is not None:
            return notice, "notice-cache"

        response = fetch_function(params)
        self.store_query_response(params, response, source_label=source_label)
        return response, "network"

    def summary(self) -> Dict[str, Any]:
        query_count = len(list(self.queries_dir.glob("*.json"))) if self.queries_dir.exists() else 0
        notice_count = len(list(self.notices_dir.glob("*.json"))) if self.notices_dir.exists() else 0
        return {
            "cache_root": str(self.root),
            "query_count": query_count,
            "notice_count": notice_count,
            "max_age_days": self.max_age_days,
        }
