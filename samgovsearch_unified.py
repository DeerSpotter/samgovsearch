from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple
import tkinter as tk
from tkinter import messagebox, ttk

import samgovsearch as base
import samgovsearch_all_status as all_status
import samgovsearch_cached as cached
from samgov_api_cache import SamGovApiCache

# SAM.gov rejects windows that land exactly one calendar year apart.
base.MAX_POSTED_DATE_WINDOW_DAYS = 364

INTERNAL_SEARCH_URL = "https://sam.gov/api/prod/sgs/v1/search/"
INTERNAL_DETAILS_URL = "https://sam.gov/api/prod/opps/v2/opportunities"
INTERNAL_RESOURCES_URL = "https://sam.gov/api/prod/opps/v3/opportunities"
INTERNAL_DOWNLOAD_URL = "https://sam.gov/api/prod/opps/v3/opportunities/resources/files"

SOURCE_INTERNAL = "Website/Internal Search - no API key"
SOURCE_OFFICIAL = "Official API Search - uses SAM_API_KEY"
SOURCE_HYBRID = "Hybrid - internal search + official API enrich"

INTERNAL_REQUEST_DELAY_SECONDS = 0.35
HYBRID_OFFICIAL_DELAY_SECONDS = 0.35


JsonDict = Dict[str, Any]


def safe_get(obj: Any, *keys: str, default: Any = "") -> Any:
    current = obj
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
    return default if current is None else current


def parse_date_any(value: Any) -> Optional[date]:
    text = base.normalize_text(value)
    if not text:
        return None

    text = text.replace("Z", "+00:00")
    formats = [
        "%m/%d/%Y",
        "%Y-%m-%d",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue

    if "T" in text:
        try:
            return datetime.fromisoformat(text).date()
        except ValueError:
            return None

    return None


def format_date_for_sam(value: Any) -> str:
    parsed = parse_date_any(value)
    if parsed is None:
        return base.normalize_text(value)
    return parsed.strftime(base.DATE_FORMAT)


def strip_html(value: Any) -> str:
    text = base.normalize_text(value)
    if not text:
        return ""
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def first_description(opp: JsonDict) -> str:
    descriptions = opp.get("descriptions")
    if isinstance(descriptions, list) and descriptions:
        first = descriptions[0]
        if isinstance(first, dict):
            return strip_html(first.get("content") or first.get("description") or "")
        return strip_html(first)
    return strip_html(opp.get("description") or opp.get("descriptionText") or "")


def organization_name_from_hierarchy(opp: JsonDict) -> str:
    hierarchy = opp.get("organizationHierarchy") or opp.get("organizationHierarchyName")
    if isinstance(hierarchy, list):
        names = []
        for part in hierarchy:
            if isinstance(part, dict):
                name = base.normalize_text(part.get("name") or part.get("value"))
                if name:
                    names.append(name)
            else:
                text = base.normalize_text(part)
                if text:
                    names.append(text)
        if names:
            return " > ".join(names)
    return base.normalize_text(
        opp.get("fullParentPathName")
        or opp.get("organizationName")
        or opp.get("officeName")
        or opp.get("agencyName")
    )


def internal_type_value(opp: JsonDict) -> str:
    value = safe_get(opp, "type", "value", default="")
    code = safe_get(opp, "type", "code", default="")
    if value and code:
        return f"{code} {value}"
    if value:
        return base.normalize_text(value)
    if code:
        return base.normalize_text(code)
    return base.normalize_text(opp.get("type"))


def internal_notice_id(opp: JsonDict) -> str:
    return base.normalize_text(
        opp.get("noticeId")
        or opp.get("noticeID")
        or opp.get("_id")
        or opp.get("id")
        or opp.get("opportunityId")
    )


def parse_int_like(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    text = base.normalize_text(value).replace(",", "")
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def normalize_internal_item(
    opp: JsonDict,
    attachments: Optional[JsonDict] = None,
    details: Optional[JsonDict] = None,
) -> JsonDict:
    data2 = safe_get(details or {}, "data2", default={})
    if not isinstance(data2, dict):
        data2 = {}

    notice_id = internal_notice_id(opp) or internal_notice_id(data2)
    posted_date = (
        format_date_for_sam(opp.get("publishDate"))
        or format_date_for_sam(opp.get("postedDate"))
        or format_date_for_sam(data2.get("postedDate"))
    )
    response_deadline = (
        format_date_for_sam(opp.get("responseDate"))
        or format_date_for_sam(opp.get("responseDeadLine"))
        or format_date_for_sam(data2.get("responseDeadLine"))
    )

    naics_code = base.normalize_text(opp.get("naicsCode"))
    naics_list = data2.get("naics")
    if not naics_code and isinstance(naics_list, list) and naics_list:
        first = naics_list[0]
        if isinstance(first, dict):
            codes = first.get("code")
            if isinstance(codes, list) and codes:
                naics_code = base.normalize_text(codes[0])
            else:
                naics_code = base.normalize_text(codes)

    psc = base.normalize_text(
        opp.get("classificationCode")
        or opp.get("pscCode")
        or data2.get("classificationCode")
    )

    attachments = attachments or {}
    links = attachments.get("resourceLinks") if isinstance(attachments, dict) else []
    if not isinstance(links, list):
        links = []

    item: JsonDict = {
        "noticeId": notice_id,
        "title": base.normalize_text(opp.get("title") or data2.get("title")),
        "solicitationNumber": base.normalize_text(opp.get("solicitationNumber") or data2.get("solicitationNumber")),
        "type": internal_type_value(opp) or internal_type_value(data2),
        "postedDate": posted_date,
        "responseDeadLine": response_deadline,
        "active": base.normalize_text(opp.get("isActive") if "isActive" in opp else data2.get("active")),
        "fullParentPathName": organization_name_from_hierarchy(opp) or organization_name_from_hierarchy(data2),
        "naicsCode": naics_code,
        "classificationCode": psc,
        "uiLink": f"https://sam.gov/opp/{notice_id}/view" if notice_id else "",
        "resourceLinks": links,
        "samgovsearchInternal": True,
        "samgovsearchInternalResourcesChecked": bool(attachments.get("checked")) if isinstance(attachments, dict) else False,
        "samgovsearchAttachmentTotalBytes": attachments.get("totalBytes") if isinstance(attachments, dict) else None,
        "samgovsearchAttachmentUnknownCount": attachments.get("unknownCount") if isinstance(attachments, dict) else 0,
        "samgovsearchAttachmentNonPublicCount": attachments.get("nonPublicCount") if isinstance(attachments, dict) else 0,
        "samgovsearchAttachmentNames": attachments.get("names") if isinstance(attachments, dict) else [],
        "description": first_description(opp) or first_description(data2),
    }

    # Preserve useful original payload fragments without breaking CSV export.
    item["samgovsearchSource"] = "internal-website"
    return item


def merge_items(primary: JsonDict, secondary: JsonDict) -> JsonDict:
    """Merge two SAM-like item dictionaries, preserving attachment metadata when possible."""
    merged = dict(primary)
    for key, value in secondary.items():
        if value in (None, "", [], {}):
            continue
        merged[key] = value

    # Keep internal attachment metadata and links when the official item does not improve them.
    for key in (
        "resourceLinks",
        "samgovsearchAttachmentTotalBytes",
        "samgovsearchAttachmentUnknownCount",
        "samgovsearchAttachmentNonPublicCount",
        "samgovsearchAttachmentNames",
        "samgovsearchInternalResourcesChecked",
    ):
        if key in primary and primary.get(key) not in (None, "", [], {}):
            merged[key] = primary[key]

    return merged


class InternalSamGovClient:
    """Small stdlib client for the SAM.gov website/internal endpoints used by sam-gov-scraper."""

    def __init__(self, timeout_seconds: int) -> None:
        self.timeout_seconds = timeout_seconds

    def get_json(self, url: str, params: Optional[Dict[str, Any]] = None) -> JsonDict:
        query = urllib.parse.urlencode(params or {}, doseq=True)
        full_url = f"{url}?{query}" if query else url
        request = urllib.request.Request(
            full_url,
            headers={
                "Accept": "application/hal+json, application/json",
                "Accept-Language": "en-US,en;q=0.9",
                "Origin": "https://sam.gov",
                "Referer": "https://sam.gov/search/",
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                payload = response.read().decode("utf-8", errors="replace")
                data = json.loads(payload)
                return data if isinstance(data, dict) else {}
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"SAM.gov internal HTTP {exc.code}: {body[:500]}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"SAM.gov internal connection error: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"SAM.gov internal endpoint returned invalid JSON: {exc}") from exc

    def search_raw(self, params: Dict[str, Any]) -> JsonDict:
        return self.get_json(INTERNAL_SEARCH_URL, params)

    def details_raw(self, notice_id: str) -> JsonDict:
        return self.get_json(f"{INTERNAL_DETAILS_URL}/{urllib.parse.quote(notice_id)}")

    def resources_raw(self, notice_id: str) -> JsonDict:
        return self.get_json(f"{INTERNAL_RESOURCES_URL}/{urllib.parse.quote(notice_id)}/resources")


def internal_search_results(data: JsonDict) -> List[JsonDict]:
    embedded = data.get("_embedded")
    if isinstance(embedded, dict):
        results = embedded.get("results")
        if isinstance(results, list):
            return [item for item in results if isinstance(item, dict)]

    for key in ("results", "opportunitiesData", "items"):
        value = data.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]

    return []


def internal_total_records(data: JsonDict, fallback: int) -> int:
    page = data.get("page")
    if isinstance(page, dict):
        total = parse_int_like(page.get("totalElements"))
        if total is not None:
            return total

    for key in ("totalRecords", "totalElements", "total", "count"):
        total = parse_int_like(data.get(key))
        if total is not None:
            return total

    return fallback


def parse_internal_resources(data: JsonDict) -> JsonDict:
    links: List[str] = []
    names: List[str] = []
    total_bytes = 0
    unknown_count = 0
    non_public_count = 0

    embedded = data.get("_embedded")
    attachment_lists = []
    if isinstance(embedded, dict):
        value = embedded.get("opportunityAttachmentList")
        if isinstance(value, list):
            attachment_lists = value

    for attachment_list in attachment_lists:
        if not isinstance(attachment_list, dict):
            continue
        attachments = attachment_list.get("attachments") or []
        if not isinstance(attachments, list):
            continue

        for attachment in attachments:
            if not isinstance(attachment, dict):
                continue
            if base.normalize_text(attachment.get("deletedFlag")) == "1":
                continue

            resource_id = base.normalize_text(attachment.get("resourceId"))
            if not resource_id:
                continue

            name = base.normalize_text(attachment.get("name") or attachment.get("filename") or "unknown")
            access_level = base.normalize_text(attachment.get("accessLevel") or "public").lower()
            if access_level and access_level != "public":
                non_public_count += 1

            url = f"{INTERNAL_DOWNLOAD_URL}/{urllib.parse.quote(resource_id)}/download"
            links.append(url)
            names.append(name)

            size = parse_int_like(attachment.get("size"))
            if size is None:
                unknown_count += 1
            else:
                total_bytes += size

    return {
        "checked": True,
        "resourceLinks": links,
        "names": names,
        "totalBytes": total_bytes,
        "unknownCount": unknown_count,
        "nonPublicCount": non_public_count,
    }


class UnifiedSamGovSearchApp(cached.CachedSamGovSearchApp):
    """One UI for internal website search, official API search, and hybrid enrichment."""

    def _build_ui(self) -> None:
        super()._build_ui()

        self.search_source_var = tk.StringVar(value=SOURCE_INTERNAL)
        left_panel = self.grid_slaves(row=0, column=0)[0]

        source_frame = ttk.LabelFrame(left_panel, text="Search Source", padding=8)
        source_frame.grid(row=11, column=0, sticky="ew", pady=(8, 0))
        source_frame.columnconfigure(0, weight=1)

        self.search_source_combo = ttk.Combobox(
            source_frame,
            textvariable=self.search_source_var,
            values=[SOURCE_INTERNAL, SOURCE_OFFICIAL, SOURCE_HYBRID],
            state="readonly",
            width=38,
        )
        self.search_source_combo.grid(row=0, column=0, sticky="ew")
        self.search_source_combo.bind("<<ComboboxSelected>>", lambda _event: self._toggle_source_controls())

        self.search_source_note_var = tk.StringVar()
        ttk.Label(source_frame, textvariable=self.search_source_note_var, wraplength=360).grid(
            row=1, column=0, sticky="w", pady=(5, 0)
        )

        self._toggle_source_controls()

    def _toggle_source_controls(self) -> None:
        source = self.search_source_var.get()
        api_key = os.environ.get("SAM_API_KEY", "").strip()

        if source == SOURCE_INTERNAL:
            self.search_source_note_var.set(
                "Uses SAM.gov website/internal endpoints from sam-gov-scraper. No SAM_API_KEY required."
            )
        elif source == SOURCE_HYBRID:
            self.search_source_note_var.set(
                "Broad search uses website/internal endpoints. Official API enrichment is used only after results are found and cached first."
            )
        else:
            self.search_source_note_var.set(
                "Uses the official SAM.gov Opportunities API and requires EnvironmentVariable=SAM_API_KEY."
            )

        if hasattr(self, "api_key_label"):
            if api_key:
                self.api_key_label.configure(text="SAM_API_KEY found")
            elif source == SOURCE_OFFICIAL:
                self.api_key_label.configure(text="SAM_API_KEY not found - required for Official API mode")
            elif source == SOURCE_HYBRID:
                self.api_key_label.configure(text="SAM_API_KEY not found - hybrid will use internal-only data")
            else:
                self.api_key_label.configure(text="SAM_API_KEY not required for current source")

    def start_search(self) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            messagebox.showinfo("Search Running", "A search is already running.")
            return

        self._toggle_source_controls()
        source = self.search_source_var.get()
        api_key = os.environ.get("SAM_API_KEY", "").strip()

        if source == SOURCE_OFFICIAL and not api_key:
            messagebox.showerror(
                "Missing SAM_API_KEY",
                "Official API mode requires EnvironmentVariable=SAM_API_KEY.\n\n"
                "Switch Search Source to Website/Internal Search for no-key searching, "
                "or set SAM_API_KEY and restart the launcher.",
            )
            return

        if source == SOURCE_HYBRID and not api_key:
            proceed = messagebox.askyesno(
                "SAM_API_KEY Not Found",
                "Hybrid mode can still run the broad website/internal search without a key, "
                "but it cannot perform official API enrichment.\n\n"
                "Continue with internal-only enrichment?",
            )
            if not proceed:
                return

        try:
            settings = self._read_settings()
        except Exception as exc:
            messagebox.showerror("Invalid Input", str(exc))
            return

        estimated_requests = self._estimate_minimum_api_requests(settings)
        if settings.all_date_ranges and estimated_requests >= all_status.ALL_DATE_CONFIRM_REQUEST_THRESHOLD:
            request_name = "official API" if source == SOURCE_OFFICIAL else "website/internal"
            proceed = messagebox.askyesno(
                "Large SAM.gov Search",
                "Search all date ranges can make many SAM.gov requests.\n\n"
                f"Minimum planned {request_name} search requests: {estimated_requests}\n"
                f"Date windows: {len(settings.date_windows)}\n"
                f"Unique batch items: {len(settings.keywords)}\n\n"
                "This does not include extra result pages or per-result attachment enrichment.\n\n"
                "Continue?",
            )
            if not proceed:
                self.status_var_text.set("Search cancelled before sending requests.")
                return

        self.stop_event.clear()
        self.results.clear()
        self.seen_notice_ids.clear()
        self.export_button.configure(state="disabled")
        for row_id in self.tree.get_children():
            self.tree.delete(row_id)
        self._set_log("")

        self._log(
            f"Starting {source} for {len(settings.keywords)} unique batch item(s) "
            f"from {settings.raw_batch_count} entered item(s)."
        )
        if settings.duplicate_batch_count:
            self._log(f"Skipped {settings.duplicate_batch_count} duplicate batch item(s) before searching.")
        if settings.all_date_ranges:
            first_from, _ = settings.date_windows[0]
            _, last_to = settings.date_windows[-1]
            self._log(
                f"Search all date ranges enabled: {first_from} to {last_to} "
                f"across {len(settings.date_windows)} 364-day window(s)."
            )

        if source in (SOURCE_OFFICIAL, SOURCE_HYBRID):
            summary = self._api_cache.summary()
            self._log(
                "Cache folder: "
                f"{summary['cache_root']} "
                f"({summary['query_count']} cached querie(s), {summary['notice_count']} cached notice(s))."
            )

        self.search_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.progress.start(10)
        self.status_var_text.set("Searching SAM.gov...")

        self.worker_thread = threading.Thread(
            target=self._unified_search_worker,
            args=(api_key, settings, source),
            daemon=True,
        )
        self.worker_thread.start()

    def _unified_search_worker(self, api_key: str, settings: base.SearchSettings, source: str) -> None:
        if source == SOURCE_OFFICIAL:
            super()._search_worker(api_key, settings)
            return

        try:
            self._internal_search_worker(api_key, settings, source == SOURCE_HYBRID)
            self.queue.put(("done", None))
        except Exception as exc:
            self.queue.put(("error", str(exc)))

    def _sleep_between_internal_requests(self) -> None:
        if INTERNAL_REQUEST_DELAY_SECONDS <= 0:
            return
        self.stop_event.wait(INTERNAL_REQUEST_DELAY_SECONDS)

    def _internal_search_worker(self, api_key: str, settings: base.SearchSettings, hybrid: bool) -> None:
        internal_client = InternalSamGovClient(timeout_seconds=settings.timeout_seconds)
        official_client = base.SamGovClient(api_key, settings.timeout_seconds) if api_key and hybrid else None

        for keyword in settings.keywords:
            if self.stop_event.is_set():
                break

            variants = base.build_search_variants(keyword, settings.search_mode)
            self.queue.put(("log", f"Searching {keyword!r} using internal website search."))

            for matched_by, variant_params in variants:
                if self.stop_event.is_set():
                    break

                if "noticeid" in variant_params:
                    items_with_windows = self._internal_notice_lookup(
                        internal_client,
                        variant_params["noticeid"],
                        settings,
                    )
                else:
                    items_with_windows = self._internal_paged_search(
                        internal_client,
                        settings,
                        keyword,
                        matched_by,
                        variant_params,
                    )

                for item, date_window in items_with_windows:
                    if self.stop_event.is_set():
                        break

                    notice_id = base.normalize_text(item.get("noticeId"))
                    if notice_id and notice_id in self.seen_notice_ids:
                        continue

                    enriched = self._enrich_internal_item(internal_client, item)
                    if hybrid and official_client is not None:
                        enriched = self._official_enrich_after_internal(
                            official_client,
                            enriched,
                            date_window,
                            settings,
                        )

                    links = base.extract_resource_links(enriched)
                    attachment_count = len(links)
                    if settings.require_attachments and attachment_count < settings.min_attachment_count:
                        continue

                    total_mb = self._attachment_mb_from_internal_item(enriched)
                    size_note = self._attachment_note_from_internal_item(enriched)

                    if settings.require_attachments and settings.min_total_attachment_mb > 0:
                        if total_mb is None or total_mb < settings.min_total_attachment_mb:
                            continue

                    result = base.item_to_result(
                        keyword=keyword,
                        matched_by="internal" if not hybrid else "hybrid",
                        item=enriched,
                        attachment_total_mb=total_mb,
                        attachment_size_note=size_note,
                    )

                    if notice_id:
                        self.seen_notice_ids.add(notice_id)
                    self._api_cache.store_notice_item(enriched, source_label="internal-hybrid" if hybrid else "internal-search")
                    self.queue.put(("result", result))

    def _internal_notice_lookup(
        self,
        client: InternalSamGovClient,
        notice_id: str,
        settings: base.SearchSettings,
    ) -> Iterable[Tuple[JsonDict, Tuple[str, str]]]:
        cached_item = self._cached_notice_item(notice_id)
        if cached_item is not None:
            self.queue.put(("log", f"Cache hit for notice {notice_id}; no internal detail request spent."))
            yield cached_item, self._best_date_window_for_item(cached_item, settings)
            return

        self._sleep_between_internal_requests()
        details = client.details_raw(notice_id)
        data2 = safe_get(details, "data2", default={})
        base_item = normalize_internal_item(data2 if isinstance(data2, dict) else {}, details=details)
        if not base_item.get("noticeId"):
            base_item["noticeId"] = notice_id
            base_item["uiLink"] = f"https://sam.gov/opp/{notice_id}/view"
        yield base_item, self._best_date_window_for_item(base_item, settings)

    def _internal_paged_search(
        self,
        client: InternalSamGovClient,
        settings: base.SearchSettings,
        keyword: str,
        matched_by: str,
        variant_params: Dict[str, str],
    ) -> Iterable[Tuple[JsonDict, Tuple[str, str]]]:
        query_text = variant_params.get("title") or variant_params.get("solnum") or keyword
        retrieved = 0

        for posted_from, posted_to in settings.date_windows:
            page = 0
            total_for_window: Optional[int] = None

            while retrieved < settings.max_results_per_search:
                if self.stop_event.is_set():
                    return

                page_size = min(100, settings.max_results_per_search - retrieved)
                params: Dict[str, Any] = {
                    "__source": "internal-search",
                    "index": "opp",
                    "page": page,
                    "mode": "search",
                    "sort": "-modifiedDate",
                    "size": page_size,
                    "q": query_text,
                    "postedFrom": posted_from,
                    "postedTo": posted_to,
                }

                if settings.status == "active":
                    params["is_active"] = "true"
                elif settings.status:
                    # Best-effort. The public website API is not documented like the official API.
                    params["status"] = settings.status

                if settings.ptype:
                    params["opp_type"] = settings.ptype

                data = self._internal_search_cached(client, params)
                raw_items = internal_search_results(data)
                total_for_window = internal_total_records(data, fallback=len(raw_items))

                if not raw_items:
                    break

                for raw_item in raw_items:
                    retrieved += 1
                    yield normalize_internal_item(raw_item), (posted_from, posted_to)

                    if retrieved >= settings.max_results_per_search:
                        return

                records_seen = (page * page_size) + len(raw_items)
                if total_for_window is not None and records_seen >= total_for_window:
                    break

                page += 1

    def _internal_search_cached(self, client: InternalSamGovClient, params: Dict[str, Any]) -> JsonDict:
        cached_response = self._api_cache.get_query_response(params)
        if cached_response is not None:
            self.queue.put(("log", "Internal cache hit: exact website query reused."))
            return cached_response

        self._sleep_between_internal_requests()
        network_params = {key: value for key, value in params.items() if not key.startswith("__")}
        data = client.search_raw(network_params)
        self._api_cache.store_query_response(params, data, source_label="internal-search-query")
        return data

    def _cached_notice_item(self, notice_id: str) -> Optional[JsonDict]:
        if not notice_id:
            return None
        record = self._api_cache.read_json(self._api_cache.notice_path(notice_id))
        if not record:
            return None
        if self._api_cache.is_stale(str(record.get("saved_at_utc") or "")):
            return None
        item = record.get("item")
        return item if isinstance(item, dict) else None

    def _enrich_internal_item(self, client: InternalSamGovClient, item: JsonDict) -> JsonDict:
        notice_id = base.normalize_text(item.get("noticeId"))
        if not notice_id:
            return item

        cached_item = self._cached_notice_item(notice_id)
        if cached_item and cached_item.get("samgovsearchInternalResourcesChecked"):
            return merge_items(cached_item, item)

        resources: JsonDict = {}
        details: JsonDict = {}

        try:
            self._sleep_between_internal_requests()
            resources = client.resources_raw(notice_id)
        except Exception as exc:
            self.queue.put(("log", f"Attachment metadata lookup failed for {notice_id}: {exc}"))

        try:
            self._sleep_between_internal_requests()
            details = client.details_raw(notice_id)
        except Exception:
            details = {}

        attachments = parse_internal_resources(resources) if resources else {
            "checked": True,
            "resourceLinks": [],
            "names": [],
            "totalBytes": 0,
            "unknownCount": 0,
            "nonPublicCount": 0,
        }

        enriched = normalize_internal_item(item, attachments=attachments, details=details)
        self._api_cache.store_notice_item(enriched, source_label="internal-search")
        return enriched

    def _official_enrich_after_internal(
        self,
        official_client: base.SamGovClient,
        item: JsonDict,
        date_window: Tuple[str, str],
        settings: base.SearchSettings,
    ) -> JsonDict:
        notice_id = base.normalize_text(item.get("noticeId"))
        if not notice_id:
            return item

        cached_official = self._cached_official_notice_item(notice_id)
        if cached_official is not None:
            self.queue.put(("log", f"Official API cache hit for {notice_id}; no API request spent."))
            return merge_items(item, cached_official)

        posted_from, posted_to = self._official_notice_date_window(item, date_window)
        params: Dict[str, Any] = {
            "noticeid": notice_id,
            "postedFrom": posted_from,
            "postedTo": posted_to,
            "limit": 1,
            "offset": 0,
        }

        try:
            self._wait_before_api_request(settings)
            self.stop_event.wait(HYBRID_OFFICIAL_DELAY_SECONDS)
            if self.stop_event.is_set():
                return item
            data = official_client.search(params)
            self._api_cache.store_query_response(params, data, source_label="api-hybrid-enrich")
            official_items = data.get("opportunitiesData") if isinstance(data, dict) else None
            if isinstance(official_items, list) and official_items:
                official_item = official_items[0]
                if isinstance(official_item, dict):
                    self.queue.put(("log", f"Hybrid official API enriched {notice_id}."))
                    return merge_items(item, official_item)
        except Exception as exc:
            message = str(exc)
            if "HTTP 429" in message or "quota" in message.lower() or "throttl" in message.lower():
                self.queue.put(("log", f"Official API enrichment stopped by quota/rate limit for {notice_id}. Continuing with internal data."))
            else:
                self.queue.put(("log", f"Official API enrichment failed for {notice_id}: {exc}"))

        return item

    def _cached_official_notice_item(self, notice_id: str) -> Optional[JsonDict]:
        record = self._api_cache.read_json(self._api_cache.notice_path(notice_id))
        if not record:
            return None
        if self._api_cache.is_stale(str(record.get("saved_at_utc") or "")):
            return None

        source = base.normalize_text(record.get("source")).lower()
        if not (source.startswith("api") or "official" in source):
            return None

        item = record.get("item")
        return item if isinstance(item, dict) else None

    def _best_date_window_for_item(self, item: JsonDict, settings: base.SearchSettings) -> Tuple[str, str]:
        posted = parse_date_any(item.get("postedDate") or item.get("publishDate"))
        if posted is not None:
            day = posted.strftime(base.DATE_FORMAT)
            return day, day
        if settings.date_windows:
            return settings.date_windows[0]
        today = date.today().strftime(base.DATE_FORMAT)
        return today, today

    def _official_notice_date_window(self, item: JsonDict, fallback_window: Tuple[str, str]) -> Tuple[str, str]:
        posted = parse_date_any(item.get("postedDate") or item.get("publishDate"))
        if posted is not None:
            day = posted.strftime(base.DATE_FORMAT)
            return day, day
        return fallback_window

    def _attachment_mb_from_internal_item(self, item: JsonDict) -> Optional[float]:
        total = parse_int_like(item.get("samgovsearchAttachmentTotalBytes"))
        if total is None:
            return None
        return total / (1024 * 1024)

    def _attachment_note_from_internal_item(self, item: JsonDict) -> str:
        notes = []
        unknown = parse_int_like(item.get("samgovsearchAttachmentUnknownCount")) or 0
        non_public = parse_int_like(item.get("samgovsearchAttachmentNonPublicCount")) or 0
        if unknown:
            notes.append(f"{unknown} unknown size(s)")
        if non_public:
            notes.append(f"{non_public} non-public attachment(s)")
        if item.get("samgovsearchInternalResourcesChecked"):
            notes.append("size from internal resources endpoint")
        return "; ".join(notes)


def main() -> None:
    app = UnifiedSamGovSearchApp()
    app.mainloop()


if __name__ == "__main__":
    main()
