from __future__ import annotations

import csv
import json
import os
import queue
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple
import tkinter as tk
from tkinter import filedialog, messagebox
from tkinter import ttk


SAM_API_URL = "https://api.sam.gov/opportunities/v2/search"
DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_MAX_RESULTS_PER_SEARCH = 100
DEFAULT_STATUS = "active"
ALL_DATE_RANGES_START = date(2018, 1, 1)
DATE_FORMAT = "%m/%d/%Y"
MAX_POSTED_DATE_WINDOW_DAYS = 365


@dataclass
class SearchSettings:
    keywords: List[str]
    raw_batch_count: int
    duplicate_batch_count: int
    date_windows: List[Tuple[str, str]]
    all_date_ranges: bool
    status: str
    ptype: str
    search_mode: str
    max_results_per_search: int
    require_attachments: bool
    min_attachment_count: int
    min_total_attachment_mb: float
    timeout_seconds: int


@dataclass
class SearchResult:
    keyword: str
    matched_by: str
    notice_id: str
    title: str
    solicitation_number: str
    notice_type: str
    posted_date: str
    response_deadline: str
    active: str
    organization: str
    naics_code: str
    classification_code: str
    attachment_count: int
    attachment_total_mb: Optional[float]
    attachment_size_note: str
    ui_link: str
    resource_links: List[str] = field(default_factory=list)

    def as_csv_row(self) -> Dict[str, Any]:
        return {
            "Keyword": self.keyword,
            "Matched By": self.matched_by,
            "Notice ID": self.notice_id,
            "Title": self.title,
            "Solicitation Number": self.solicitation_number,
            "Type": self.notice_type,
            "Posted Date": self.posted_date,
            "Response Deadline": self.response_deadline,
            "Active": self.active,
            "Organization": self.organization,
            "NAICS": self.naics_code,
            "PSC": self.classification_code,
            "Attachment Count": self.attachment_count,
            "Attachment Total MB": "" if self.attachment_total_mb is None else f"{self.attachment_total_mb:.3f}",
            "Attachment Size Note": self.attachment_size_note,
            "SAM Link": self.ui_link,
            "Resource Links": " | ".join(self.resource_links),
        }


class SamGovClient:
    def __init__(self, api_key: str, timeout_seconds: int) -> None:
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    def search(self, params: Dict[str, Any]) -> Dict[str, Any]:
        merged = dict(params)
        merged["api_key"] = self.api_key
        query = urllib.parse.urlencode(merged, doseq=True)
        url = f"{SAM_API_URL}?{query}"
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "samgovsearch/1.1",
            },
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                payload = response.read().decode("utf-8", errors="replace")
                return json.loads(payload)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"SAM.gov HTTP {exc.code}: {body[:500]}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"SAM.gov connection error: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"SAM.gov returned invalid JSON: {exc}") from exc

    def get_content_length(self, url: str) -> Optional[int]:
        test_urls = [url]
        keyed = append_api_key_if_missing(url, self.api_key)
        if keyed != url:
            test_urls.append(keyed)

        for candidate in test_urls:
            length = self._content_length_head(candidate)
            if length is not None:
                return length

            length = self._content_length_range(candidate)
            if length is not None:
                return length

        return None

    def _content_length_head(self, url: str) -> Optional[int]:
        request = urllib.request.Request(
            url,
            method="HEAD",
            headers={"User-Agent": "samgovsearch/1.1"},
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                value = response.headers.get("Content-Length")
                if value and value.isdigit():
                    return int(value)
        except Exception:
            return None

        return None

    def _content_length_range(self, url: str) -> Optional[int]:
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "samgovsearch/1.1",
                "Range": "bytes=0-0",
            },
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                content_range = response.headers.get("Content-Range")
                if content_range:
                    match = re.search(r"/(\d+)$", content_range)
                    if match:
                        return int(match.group(1))

                value = response.headers.get("Content-Length")
                if value and value.isdigit():
                    # If the server ignored the Range header, this is still usually
                    # the full file size. We do not read the body.
                    return int(value)
        except Exception:
            return None

        return None


def append_api_key_if_missing(url: str, api_key: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if "sam.gov" not in parsed.netloc.lower():
        return url

    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    if any(key.lower() == "api_key" for key, _ in query):
        return url

    query.append(("api_key", api_key))
    return urllib.parse.urlunparse(
        parsed._replace(query=urllib.parse.urlencode(query))
    )


def default_posted_dates() -> Tuple[str, str]:
    today = date.today()
    start = today - timedelta(days=MAX_POSTED_DATE_WINDOW_DAYS)
    return start.strftime(DATE_FORMAT), today.strftime(DATE_FORMAT)


def parse_batch_terms(raw: str) -> Tuple[List[str], int, int]:
    terms: List[str] = []
    for line in raw.replace(",", "\n").splitlines():
        value = line.strip()
        if value:
            terms.append(value)

    seen = set()
    cleaned: List[str] = []
    duplicate_count = 0
    for term in terms:
        # Collapse interior whitespace for dedupe only. Keep the original term for searching.
        key = " ".join(term.lower().split())
        if key in seen:
            duplicate_count += 1
            continue
        cleaned.append(term)
        seen.add(key)

    return cleaned, len(terms), duplicate_count


def split_keywords(raw: str) -> List[str]:
    keywords, _, _ = parse_batch_terms(raw)
    return keywords


def parse_int(value: str, default: int, minimum: int, maximum: int) -> int:
    text = value.strip()
    if not text:
        return default
    number = int(text)
    if number < minimum or number > maximum:
        raise ValueError(f"Value must be between {minimum} and {maximum}.")
    return number


def parse_float(value: str, default: float, minimum: float) -> float:
    text = value.strip()
    if not text:
        return default
    number = float(text)
    if number < minimum:
        raise ValueError(f"Value must be at least {minimum}.")
    return number


def parse_mmddyyyy(value: str, field_name: str) -> date:
    text = value.strip()
    if not text:
        raise ValueError(f"{field_name} is required unless Search all date ranges is checked.")
    try:
        return datetime.strptime(text, DATE_FORMAT).date()
    except ValueError as exc:
        raise ValueError(f"{field_name} must be MM/DD/YYYY.") from exc


def build_all_date_windows(start: date, end: date) -> List[Tuple[str, str]]:
    if end < start:
        raise ValueError("All date range end date is before the start date.")

    windows: List[Tuple[str, str]] = []
    window_start = start
    while window_start <= end:
        window_end = min(window_start + timedelta(days=MAX_POSTED_DATE_WINDOW_DAYS), end)
        windows.append((window_start.strftime(DATE_FORMAT), window_end.strftime(DATE_FORMAT)))
        window_start = window_end + timedelta(days=1)
    return windows


def build_manual_date_window(posted_from: str, posted_to: str) -> List[Tuple[str, str]]:
    start = parse_mmddyyyy(posted_from, "Posted From")
    end = parse_mmddyyyy(posted_to, "Posted To")

    if end < start:
        raise ValueError("Posted To must be the same as or later than Posted From.")

    if (end - start).days > MAX_POSTED_DATE_WINDOW_DAYS:
        raise ValueError(
            "SAM.gov only allows a posted date range of 1 year. "
            "Shorten the date range or check Search all date ranges."
        )

    return [(start.strftime(DATE_FORMAT), end.strftime(DATE_FORMAT))]


def build_search_variants(term: str, mode: str) -> List[Tuple[str, Dict[str, str]]]:
    mode = mode.lower()
    term = term.strip()
    variants: List[Tuple[str, Dict[str, str]]] = []

    if mode == "title":
        return [("title", {"title": term})]
    if mode == "solicitation number":
        return [("solnum", {"solnum": term})]
    if mode == "notice id":
        return [("noticeid", {"noticeid": term})]
    if mode == "title + solicitation number":
        return [
            ("title", {"title": term}),
            ("solnum", {"solnum": term}),
        ]

    # Auto mode: useful for mixed batches with part numbers, solicitation
    # numbers, notice IDs, and normal keywords.
    variants.append(("title", {"title": term}))

    if any(ch.isdigit() for ch in term):
        variants.append(("solnum", {"solnum": term}))

    normalized = re.sub(r"[^A-Fa-f0-9]", "", term)
    if len(normalized) >= 20 and re.fullmatch(r"[A-Fa-f0-9]+", normalized):
        variants.append(("noticeid", {"noticeid": term}))

    return variants


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def extract_resource_links(item: Dict[str, Any]) -> List[str]:
    value = item.get("resourceLinks")
    if not value:
        return []
    if isinstance(value, list):
        return [normalize_text(url) for url in value if normalize_text(url)]
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    return []


def item_to_result(
    keyword: str,
    matched_by: str,
    item: Dict[str, Any],
    attachment_total_mb: Optional[float],
    attachment_size_note: str,
) -> SearchResult:
    return SearchResult(
        keyword=keyword,
        matched_by=matched_by,
        notice_id=normalize_text(item.get("noticeId")),
        title=normalize_text(item.get("title")),
        solicitation_number=normalize_text(item.get("solicitationNumber")),
        notice_type=normalize_text(item.get("type")),
        posted_date=normalize_text(item.get("postedDate")),
        response_deadline=normalize_text(item.get("responseDeadLine")),
        active=normalize_text(item.get("active")),
        organization=normalize_text(
            item.get("fullParentPathName")
            or ".".join(
                part
                for part in [
                    normalize_text(item.get("department")),
                    normalize_text(item.get("subTier")),
                    normalize_text(item.get("office")),
                ]
                if part
            )
        ),
        naics_code=normalize_text(item.get("naicsCode")),
        classification_code=normalize_text(item.get("classificationCode")),
        attachment_count=len(extract_resource_links(item)),
        attachment_total_mb=attachment_total_mb,
        attachment_size_note=attachment_size_note,
        ui_link=normalize_text(item.get("uiLink")),
        resource_links=extract_resource_links(item),
    )


class SamGovSearchApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()

        self.title("SAM.gov Batch Search")
        self.geometry("1360x820")
        self.minsize(1100, 700)

        self.worker_thread: Optional[threading.Thread] = None
        self.stop_event = threading.Event()
        self.queue: "queue.Queue[Tuple[str, Any]]" = queue.Queue()
        self.results: List[SearchResult] = []
        self.seen_notice_ids: set[str] = set()

        self._build_ui()
        self._poll_queue()

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=0)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        left = ttk.Frame(self, padding=10)
        left.grid(row=0, column=0, sticky="nsw")
        left.columnconfigure(0, weight=1)

        right = ttk.Frame(self, padding=(0, 10, 10, 10))
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)

        api_key = os.environ.get("SAM_API_KEY", "").strip()
        key_status = "SAM_API_KEY found" if api_key else "SAM_API_KEY not found"
        self.api_key_label = ttk.Label(left, text=key_status)
        self.api_key_label.grid(row=0, column=0, sticky="w", pady=(0, 8))

        ttk.Label(left, text="Batch keywords, part numbers, solicitation numbers").grid(row=1, column=0, sticky="w")
        self.keyword_text = tk.Text(left, width=42, height=12, wrap="word")
        self.keyword_text.grid(row=2, column=0, sticky="ew", pady=(3, 8))
        self.keyword_text.insert("1.0", "Patriot\nfrequency converter\nK0357NC200461-0001")

        form = ttk.LabelFrame(left, text="SAM.gov Search Options", padding=8)
        form.grid(row=3, column=0, sticky="ew", pady=(0, 8))
        form.columnconfigure(1, weight=1)

        posted_from, posted_to = default_posted_dates()

        ttk.Label(form, text="Posted From").grid(row=0, column=0, sticky="w")
        self.posted_from_var = tk.StringVar(value=posted_from)
        self.posted_from_entry = ttk.Entry(form, textvariable=self.posted_from_var, width=18)
        self.posted_from_entry.grid(row=0, column=1, sticky="ew", padx=(8, 0), pady=2)

        ttk.Label(form, text="Posted To").grid(row=1, column=0, sticky="w")
        self.posted_to_var = tk.StringVar(value=posted_to)
        self.posted_to_entry = ttk.Entry(form, textvariable=self.posted_to_var, width=18)
        self.posted_to_entry.grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=2)

        self.all_date_ranges_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            form,
            text="Search all date ranges",
            variable=self.all_date_ranges_var,
            command=self._toggle_date_controls,
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(2, 6))

        ttk.Label(form, text="Status").grid(row=3, column=0, sticky="w")
        self.status_var = tk.StringVar(value=DEFAULT_STATUS)
        ttk.Combobox(
            form,
            textvariable=self.status_var,
            values=["", "active", "inactive", "archived", "cancelled", "deleted"],
            state="readonly",
            width=18,
        ).grid(row=3, column=1, sticky="ew", padx=(8, 0), pady=2)

        ttk.Label(form, text="Procurement Type").grid(row=4, column=0, sticky="w")
        self.ptype_var = tk.StringVar(value="")
        ttk.Combobox(
            form,
            textvariable=self.ptype_var,
            values=[
                "",
                "o Solicitation",
                "k Combined Synopsis/Solicitation",
                "r Sources Sought",
                "p Presolicitation",
                "s Special Notice",
                "a Award Notice",
                "u Justification",
                "g Sale of Surplus Property",
                "i Intent to Bundle Requirements",
            ],
            state="readonly",
            width=28,
        ).grid(row=4, column=1, sticky="ew", padx=(8, 0), pady=2)

        ttk.Label(form, text="Search Mode").grid(row=5, column=0, sticky="w")
        self.search_mode_var = tk.StringVar(value="Auto")
        ttk.Combobox(
            form,
            textvariable=self.search_mode_var,
            values=[
                "Auto",
                "Title",
                "Solicitation Number",
                "Notice ID",
                "Title + Solicitation Number",
            ],
            state="readonly",
            width=28,
        ).grid(row=5, column=1, sticky="ew", padx=(8, 0), pady=2)

        ttk.Label(form, text="Max Results / Search").grid(row=6, column=0, sticky="w")
        self.max_results_var = tk.StringVar(value=str(DEFAULT_MAX_RESULTS_PER_SEARCH))
        ttk.Entry(form, textvariable=self.max_results_var, width=18).grid(row=6, column=1, sticky="ew", padx=(8, 0), pady=2)

        ttk.Label(form, text="Timeout Seconds").grid(row=7, column=0, sticky="w")
        self.timeout_var = tk.StringVar(value=str(DEFAULT_TIMEOUT_SECONDS))
        ttk.Entry(form, textvariable=self.timeout_var, width=18).grid(row=7, column=1, sticky="ew", padx=(8, 0), pady=2)

        self.require_attachments_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            left,
            text="Only show opportunities with attachments",
            variable=self.require_attachments_var,
            command=self._toggle_attachment_controls,
        ).grid(row=4, column=0, sticky="w", pady=(0, 6))

        self.attachment_frame = ttk.LabelFrame(left, text="Attachment Filters", padding=8)
        self.attachment_frame.columnconfigure(1, weight=1)

        ttk.Label(self.attachment_frame, text="Minimum Attachment Count").grid(row=0, column=0, sticky="w")
        self.min_attachment_count_var = tk.StringVar(value="")
        ttk.Entry(self.attachment_frame, textvariable=self.min_attachment_count_var, width=18).grid(
            row=0, column=1, sticky="ew", padx=(8, 0), pady=2
        )

        ttk.Label(self.attachment_frame, text="Minimum Total Size MB").grid(row=1, column=0, sticky="w")
        self.min_total_size_var = tk.StringVar(value="")
        ttk.Entry(self.attachment_frame, textvariable=self.min_total_size_var, width=18).grid(
            row=1, column=1, sticky="ew", padx=(8, 0), pady=2
        )

        ttk.Label(
            self.attachment_frame,
            text="Defaults when blank: count = 1, size = 0 MB.",
            wraplength=330,
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(4, 0))

        self.button_frame = ttk.Frame(left)
        self.button_frame.grid(row=6, column=0, sticky="ew", pady=(4, 0))
        self.button_frame.columnconfigure(0, weight=1)
        self.button_frame.columnconfigure(1, weight=1)

        self.search_button = ttk.Button(self.button_frame, text="Search", command=self.start_search)
        self.search_button.grid(row=0, column=0, sticky="ew", padx=(0, 4))

        self.stop_button = ttk.Button(self.button_frame, text="Stop", command=self.stop_search, state="disabled")
        self.stop_button.grid(row=0, column=1, sticky="ew", padx=(4, 0))

        self.export_button = ttk.Button(left, text="Export Results to CSV", command=self.export_csv, state="disabled")
        self.export_button.grid(row=7, column=0, sticky="ew", pady=(8, 0))

        ttk.Label(
            left,
            text=(
                "API key is read only from EnvironmentVariable=SAM_API_KEY. "
                "Dates must be MM/DD/YYYY. Search all date ranges searches "
                "01/01/2018 through today in 1-year windows."
            ),
            wraplength=360,
        ).grid(row=8, column=0, sticky="w", pady=(10, 0))

        summary = ttk.Frame(right)
        summary.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        summary.columnconfigure(0, weight=1)

        self.status_var_text = tk.StringVar(value="Ready.")
        ttk.Label(summary, textvariable=self.status_var_text).grid(row=0, column=0, sticky="w")

        self.progress = ttk.Progressbar(summary, mode="indeterminate")
        self.progress.grid(row=1, column=0, sticky="ew", pady=(6, 0))

        columns = [
            "Keyword",
            "Matched By",
            "Posted",
            "Type",
            "Solicitation",
            "Title",
            "Attachments",
            "Size MB",
            "Notice ID",
            "SAM Link",
        ]

        self.tree = ttk.Treeview(right, columns=columns, show="headings", selectmode="browse")
        self.tree.grid(row=1, column=0, sticky="nsew")

        widths = {
            "Keyword": 140,
            "Matched By": 90,
            "Posted": 90,
            "Type": 180,
            "Solicitation": 160,
            "Title": 430,
            "Attachments": 90,
            "Size MB": 90,
            "Notice ID": 240,
            "SAM Link": 260,
        }

        for column in columns:
            self.tree.heading(column, text=column)
            self.tree.column(column, width=widths[column], anchor="w")

        self.tree.bind("<Double-1>", self.open_selected_link)

        yscroll = ttk.Scrollbar(right, orient="vertical", command=self.tree.yview)
        yscroll.grid(row=1, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=yscroll.set)

        xscroll = ttk.Scrollbar(right, orient="horizontal", command=self.tree.xview)
        xscroll.grid(row=2, column=0, sticky="ew")
        self.tree.configure(xscrollcommand=xscroll.set)

        log_frame = ttk.LabelFrame(right, text="Log", padding=6)
        log_frame.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        log_frame.columnconfigure(0, weight=1)

        self.log_text = tk.Text(log_frame, height=7, wrap="word")
        self.log_text.grid(row=0, column=0, sticky="ew")
        self.log_text.configure(state="disabled")

        self._toggle_date_controls()
        self._toggle_attachment_controls()

    def _toggle_date_controls(self) -> None:
        state = "disabled" if self.all_date_ranges_var.get() else "normal"
        self.posted_from_entry.configure(state=state)
        self.posted_to_entry.configure(state=state)

    def _toggle_attachment_controls(self) -> None:
        if self.require_attachments_var.get():
            self.attachment_frame.grid(row=5, column=0, sticky="ew", pady=(0, 8))
        else:
            self.attachment_frame.grid_remove()

    def start_search(self) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            messagebox.showinfo("Search Running", "A search is already running.")
            return

        api_key = os.environ.get("SAM_API_KEY", "").strip()
        if not api_key:
            messagebox.showerror(
                "Missing SAM_API_KEY",
                "EnvironmentVariable=SAM_API_KEY was not found.\n\n"
                "Set SAM_API_KEY, close and reopen the terminal, then run this app again.",
            )
            return

        try:
            settings = self._read_settings()
        except Exception as exc:
            messagebox.showerror("Invalid Input", str(exc))
            return

        self.stop_event.clear()
        self.results.clear()
        self.seen_notice_ids.clear()
        self.export_button.configure(state="disabled")
        for row_id in self.tree.get_children():
            self.tree.delete(row_id)
        self._set_log("")

        self._log(
            f"Starting search for {len(settings.keywords)} unique batch item(s) "
            f"from {settings.raw_batch_count} entered item(s)."
        )
        if settings.duplicate_batch_count:
            self._log(f"Skipped {settings.duplicate_batch_count} duplicate batch item(s) before searching.")
        if settings.all_date_ranges:
            first_from, _ = settings.date_windows[0]
            _, last_to = settings.date_windows[-1]
            self._log(
                f"Search all date ranges enabled: {first_from} to {last_to} "
                f"across {len(settings.date_windows)} one-year window(s)."
            )

        self.search_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.progress.start(10)
        self.status_var_text.set("Searching SAM.gov...")

        self.worker_thread = threading.Thread(
            target=self._search_worker,
            args=(api_key, settings),
            daemon=True,
        )
        self.worker_thread.start()

    def stop_search(self) -> None:
        self.stop_event.set()
        self._log("Stop requested. Finishing current request...")

    def _read_settings(self) -> SearchSettings:
        keywords, raw_count, duplicate_count = parse_batch_terms(self.keyword_text.get("1.0", "end"))
        if not keywords:
            raise ValueError("Enter at least one keyword, part number, solicitation number, or notice ID.")

        max_results = parse_int(
            self.max_results_var.get(),
            DEFAULT_MAX_RESULTS_PER_SEARCH,
            1,
            10000,
        )
        timeout = parse_int(
            self.timeout_var.get(),
            DEFAULT_TIMEOUT_SECONDS,
            5,
            300,
        )

        all_date_ranges = self.all_date_ranges_var.get()
        if all_date_ranges:
            date_windows = build_all_date_windows(ALL_DATE_RANGES_START, date.today())
        else:
            date_windows = build_manual_date_window(
                self.posted_from_var.get(),
                self.posted_to_var.get(),
            )

        require_attachments = self.require_attachments_var.get()
        min_count = 0
        min_size = 0.0
        if require_attachments:
            min_count = parse_int(self.min_attachment_count_var.get(), 1, 1, 10000)
            min_size = parse_float(self.min_total_size_var.get(), 0.0, 0.0)

        return SearchSettings(
            keywords=keywords,
            raw_batch_count=raw_count,
            duplicate_batch_count=duplicate_count,
            date_windows=date_windows,
            all_date_ranges=all_date_ranges,
            status=self.status_var.get().strip(),
            ptype=self._ptype_code(),
            search_mode=self.search_mode_var.get().strip(),
            max_results_per_search=max_results,
            require_attachments=require_attachments,
            min_attachment_count=min_count,
            min_total_attachment_mb=min_size,
            timeout_seconds=timeout,
        )

    def _ptype_code(self) -> str:
        value = self.ptype_var.get().strip()
        if not value:
            return ""
        return value.split(" ", 1)[0]

    def _search_worker(self, api_key: str, settings: SearchSettings) -> None:
        client = SamGovClient(api_key=api_key, timeout_seconds=settings.timeout_seconds)

        try:
            for keyword in settings.keywords:
                if self.stop_event.is_set():
                    break

                variants = build_search_variants(keyword, settings.search_mode)
                self.queue.put(("log", f"Searching {keyword!r} using {', '.join(name for name, _ in variants)}."))

                for matched_by, variant_params in variants:
                    if self.stop_event.is_set():
                        break

                    for item in self._paged_search(client, settings, variant_params):
                        if self.stop_event.is_set():
                            break

                        notice_id = normalize_text(item.get("noticeId"))
                        if notice_id and notice_id in self.seen_notice_ids:
                            continue

                        links = extract_resource_links(item)
                        attachment_count = len(links)

                        if settings.require_attachments and attachment_count < settings.min_attachment_count:
                            continue

                        total_mb: Optional[float] = None
                        size_note = ""
                        if links:
                            total_bytes, unknown_count = self._attachment_total_bytes(client, links, settings)
                            if total_bytes is not None:
                                total_mb = total_bytes / (1024 * 1024)
                            if unknown_count:
                                size_note = f"{unknown_count} unknown size(s)"

                        if settings.require_attachments and settings.min_total_attachment_mb > 0:
                            if total_mb is None:
                                continue
                            if total_mb < settings.min_total_attachment_mb:
                                continue

                        result = item_to_result(
                            keyword=keyword,
                            matched_by=matched_by,
                            item=item,
                            attachment_total_mb=total_mb,
                            attachment_size_note=size_note,
                        )

                        if notice_id:
                            self.seen_notice_ids.add(notice_id)
                        self.queue.put(("result", result))

            self.queue.put(("done", None))
        except Exception as exc:
            self.queue.put(("error", str(exc)))

    def _paged_search(
        self,
        client: SamGovClient,
        settings: SearchSettings,
        variant_params: Dict[str, str],
    ) -> Iterable[Dict[str, Any]]:
        retrieved = 0

        for posted_from, posted_to in settings.date_windows:
            offset = 0
            total_records_for_window: Optional[int] = None

            while retrieved < settings.max_results_per_search:
                if self.stop_event.is_set():
                    return

                page_limit = min(1000, settings.max_results_per_search - retrieved)
                params: Dict[str, Any] = {
                    "postedFrom": posted_from,
                    "postedTo": posted_to,
                    "limit": page_limit,
                    "offset": offset,
                }
                if settings.status:
                    params["status"] = settings.status
                if settings.ptype:
                    params["ptype"] = settings.ptype
                params.update(variant_params)

                data = client.search(params)
                items = data.get("opportunitiesData") or []
                total_records_for_window = int(data.get("totalRecords") or 0)

                if not items:
                    break

                for item in items:
                    retrieved += 1
                    yield item

                    if retrieved >= settings.max_results_per_search:
                        return

                if retrieved >= settings.max_results_per_search:
                    return

                records_seen_for_window = (offset * page_limit) + len(items)
                if records_seen_for_window >= total_records_for_window:
                    break

                offset += 1

    def _attachment_total_bytes(
        self,
        client: SamGovClient,
        links: List[str],
        settings: SearchSettings,
    ) -> Tuple[Optional[int], int]:
        if settings.min_total_attachment_mb <= 0:
            return None, 0

        total = 0
        unknown_count = 0
        for url in links:
            if self.stop_event.is_set():
                break
            length = client.get_content_length(url)
            if length is None:
                unknown_count += 1
                continue
            total += length

        return total, unknown_count

    def _poll_queue(self) -> None:
        try:
            while True:
                event, payload = self.queue.get_nowait()
                if event == "result":
                    self._add_result(payload)
                elif event == "log":
                    self._log(str(payload))
                elif event == "error":
                    self._finish_search()
                    messagebox.showerror("Search Error", str(payload))
                    self._log(f"ERROR: {payload}")
                elif event == "done":
                    self._finish_search()
        except queue.Empty:
            pass

        self.after(100, self._poll_queue)

    def _add_result(self, result: SearchResult) -> None:
        self.results.append(result)
        size_text = "" if result.attachment_total_mb is None else f"{result.attachment_total_mb:.2f}"
        self.tree.insert(
            "",
            "end",
            values=[
                result.keyword,
                result.matched_by,
                result.posted_date,
                result.notice_type,
                result.solicitation_number,
                result.title,
                result.attachment_count,
                size_text,
                result.notice_id,
                result.ui_link,
            ],
        )
        self.status_var_text.set(f"{len(self.results)} result(s) found.")
        if self.results:
            self.export_button.configure(state="normal")

    def _finish_search(self) -> None:
        self.progress.stop()
        self.search_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        if self.stop_event.is_set():
            self.status_var_text.set(f"Stopped. {len(self.results)} result(s) found.")
            self._log(f"Stopped with {len(self.results)} result(s).")
        else:
            self.status_var_text.set(f"Done. {len(self.results)} result(s) found.")
            self._log(f"Done. {len(self.results)} result(s).")

    def _set_log(self, text: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        if text:
            self.log_text.insert("end", text)
        self.log_text.configure(state="disabled")

    def _log(self, text: str) -> None:
        timestamp = time.strftime("%H:%M:%S")
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{timestamp}] {text}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def export_csv(self) -> None:
        if not self.results:
            messagebox.showinfo("No Results", "There are no results to export.")
            return

        path = filedialog.asksaveasfilename(
            title="Save SAM.gov results",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            initialfile=f"samgov_results_{date.today().strftime('%Y%m%d')}.csv",
        )
        if not path:
            return

        fieldnames = list(self.results[0].as_csv_row().keys())
        with open(path, "w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for result in self.results:
                writer.writerow(result.as_csv_row())

        self._log(f"Exported {len(self.results)} result(s) to {path}.")
        messagebox.showinfo("Export Complete", f"Exported {len(self.results)} result(s).")

    def open_selected_link(self, _event: Any = None) -> None:
        selected = self.tree.selection()
        if not selected:
            return
        index = self.tree.index(selected[0])
        if index < 0 or index >= len(self.results):
            return
        link = self.results[index].ui_link
        if link:
            webbrowser.open(link)


def main() -> None:
    app = SamGovSearchApp()
    app.mainloop()


if __name__ == "__main__":
    main()
