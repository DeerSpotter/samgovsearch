from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Tuple
import tkinter as tk
from tkinter import messagebox, ttk

import samgovsearch as base
import samgovsearch_unified as unified
from samgovsearch_pro_checkbox_field_states import SamGovSearchProCheckboxFieldStatesApp


DEFAULT_INTERESTED_NAICS_TEXT = """336414 - Guided Missile and Space Vehicle Manufacturing
336415 - Guided Missile and Space Vehicle Propulsion Unit and Propulsion Unit Parts Manufacturing
336419 - Other Guided Missile and Space Vehicle Parts and Auxiliary Equipment Manufacturing"""


class SamGovSearchProPredefinedNaicsApp(SamGovSearchProCheckboxFieldStatesApp):
    """Final launcher target with optional predefined interested NAICS search."""

    def __init__(self) -> None:
        self.use_predefined_naics_var: tk.BooleanVar | None = None
        self.naics_text: tk.Text | None = None
        super().__init__()

    def _build_left_panel(self, left_panel: ttk.Frame) -> None:
        super()._build_left_panel(left_panel)
        self._add_predefined_naics_checkbox_to_top(left_panel)
        self._add_interested_naics_section(left_panel, row=19)

    def _add_predefined_naics_checkbox_to_top(self, left_panel: ttk.Frame) -> None:
        frame = self._find_labelframe_by_text(left_panel, "Search Checkboxes")
        if frame is None:
            return

        self._hide_widget_containing_text(frame, "Grouped here so all run-changing toggles")
        self.use_predefined_naics_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            frame,
            text="Search predefined NAICS numbers",
            variable=self.use_predefined_naics_var,
        ).grid(row=5, column=0, sticky="w", pady=(3, 0))

        ttk.Label(
            frame,
            text=(
                "When checked, the interested NAICS list at the bottom is included in the search. "
                "If the batch keyword box is blank, the app searches those NAICS codes using only the "
                "date/status/source filters. If keywords are entered, the app searches those keywords inside "
                "the predefined NAICS set."
            ),
            wraplength=330,
        ).grid(row=6, column=0, sticky="w", pady=(6, 0))

    def _add_interested_naics_section(self, left_panel: ttk.Frame, row: int) -> None:
        frame = ttk.LabelFrame(left_panel, text="Interested NAICS Numbers", padding=8)
        frame.grid(row=row, column=0, sticky="ew", pady=(8, 0))
        frame.columnconfigure(0, weight=1)

        ttk.Label(
            frame,
            text="One NAICS per line. Descriptions are allowed; the first 6 digit code on each line is used.",
            wraplength=330,
        ).grid(row=0, column=0, sticky="w")

        self.naics_text = tk.Text(frame, width=36, height=5, wrap="word")
        self.naics_text.grid(row=1, column=0, sticky="ew", pady=(4, 4))
        self.naics_text.insert("1.0", DEFAULT_INTERESTED_NAICS_TEXT)

        ttk.Label(
            frame,
            text="Default guided missile / space vehicle NAICS: 336414, 336415, 336419.",
            wraplength=330,
        ).grid(row=2, column=0, sticky="w", pady=(4, 0))

    def _read_settings(self) -> base.SearchSettings:
        if not self._use_predefined_naics_enabled():
            settings = super()._read_settings()
            setattr(settings, "use_predefined_naics", False)
            setattr(settings, "predefined_naics_codes", [])
            return settings

        codes = self._interested_naics_codes()
        if not codes:
            raise ValueError("Search predefined NAICS numbers is checked, but no valid 6 digit NAICS codes were found.")

        keywords, raw_count, duplicate_count = base.parse_batch_terms(self.keyword_text.get("1.0", "end"))
        if not keywords:
            keywords = [""]
            raw_count = 0
            duplicate_count = 0

        max_results = base.parse_int(self.max_results_var.get(), base.DEFAULT_MAX_RESULTS_PER_SEARCH, 1, 100000)
        timeout = base.parse_int(self.timeout_var.get(), base.DEFAULT_TIMEOUT_SECONDS, 5, 300)

        all_date_ranges = bool(self.all_date_ranges_var.get())
        if all_date_ranges:
            date_windows = base.build_all_date_windows(base.ALL_DATE_RANGES_START, base.date.today())
        else:
            date_windows = base.build_manual_date_window(self.posted_from_var.get(), self.posted_to_var.get())

        status = "" if bool(self.all_statuses_var.get()) else self.status_var.get().strip()
        require_attachments = bool(self.require_attachments_var.get())
        min_count = 0
        min_size = 0.0
        if require_attachments:
            min_count = base.parse_int(self.min_attachment_count_var.get(), 1, 1, 100000)
            min_size = base.parse_float(self.min_total_size_var.get(), 0.0, 0.0)

        settings = base.SearchSettings(
            keywords=keywords,
            raw_batch_count=raw_count,
            duplicate_batch_count=duplicate_count,
            date_windows=date_windows,
            all_date_ranges=all_date_ranges,
            status=status,
            ptype=self._ptype_code(),
            search_mode=self.search_mode_var.get().strip(),
            max_results_per_search=max_results,
            require_attachments=require_attachments,
            min_attachment_count=min_count,
            min_total_attachment_mb=min_size,
            timeout_seconds=timeout,
        )
        setattr(settings, "ignore_cached_searches", bool(getattr(self, "ignore_cached_searches_var", tk.BooleanVar(value=False)).get()))
        setattr(settings, "use_predefined_naics", True)
        setattr(settings, "predefined_naics_codes", codes)
        return settings

    def _estimate_minimum_api_requests(self, settings: base.SearchSettings) -> int:
        base_count = super()._estimate_minimum_api_requests(settings)
        codes = getattr(settings, "predefined_naics_codes", []) or []
        if getattr(settings, "use_predefined_naics", False) and codes:
            return max(1, base_count) * len(codes)
        return base_count

    def _use_predefined_naics_enabled(self) -> bool:
        var = getattr(self, "use_predefined_naics_var", None)
        return bool(var.get()) if var is not None else False

    def _interested_naics_codes(self) -> List[str]:
        widget = getattr(self, "naics_text", None)
        raw = widget.get("1.0", "end") if widget is not None else DEFAULT_INTERESTED_NAICS_TEXT
        codes: List[str] = []
        seen = set()
        for line in re.split(r"[\n,;]+", raw):
            match = re.search(r"\b(\d{6})\b", line)
            if not match:
                continue
            code = match.group(1)
            if code not in seen:
                seen.add(code)
                codes.append(code)
        return codes

    def _clean_variant_params(self, variant_params: Dict[str, str]) -> Dict[str, str]:
        return {key: value for key, value in variant_params.items() if str(value or "").strip()}

    def _item_matches_predefined_naics(self, item: Dict[str, Any], settings: base.SearchSettings) -> bool:
        codes = getattr(settings, "predefined_naics_codes", []) or []
        if not codes:
            return True
        values = self._item_naics_values(item)
        if not values:
            return False
        return any(value.startswith(code) or value == code for value in values for code in codes)

    def _item_naics_values(self, item: Dict[str, Any]) -> List[str]:
        values: List[str] = []

        def add(value: Any) -> None:
            if value is None:
                return
            if isinstance(value, dict):
                for nested_key in ("code", "value", "naicsCode"):
                    add(value.get(nested_key))
                return
            if isinstance(value, list):
                for part in value:
                    add(part)
                return
            text = str(value)
            for match in re.finditer(r"\b\d{6}\b", text):
                values.append(match.group(0))

        for key in ("naicsCode", "naics", "ncode", "naicsCodes"):
            add(item.get(key))
        data2 = item.get("data2")
        if isinstance(data2, dict):
            for key in ("naicsCode", "naics", "ncode", "naicsCodes"):
                add(data2.get(key))
        return list(dict.fromkeys(values))

    def _paged_search(self, client: base.SamGovClient, settings: base.SearchSettings, variant_params: Dict[str, str]) -> Iterable[Dict[str, Any]]:
        if not getattr(settings, "use_predefined_naics", False):
            yield from super()._paged_search(client, settings, variant_params)
            return

        codes = getattr(settings, "predefined_naics_codes", []) or []
        clean_variant_params = self._clean_variant_params(variant_params)
        for code in codes:
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
                        "ncode": code,
                    }
                    if settings.status:
                        params["status"] = settings.status
                    if settings.ptype:
                        params["ptype"] = settings.ptype
                    params.update(clean_variant_params)

                    data = client.search(params)
                    items = data.get("opportunitiesData") or []
                    total_records_for_window = int(data.get("totalRecords") or 0)
                    if not items:
                        break
                    for item in items:
                        retrieved += 1
                        if self._item_matches_predefined_naics(item, settings):
                            yield item
                        if retrieved >= settings.max_results_per_search:
                            return
                    records_seen_for_window = (offset * page_limit) + len(items)
                    if total_records_for_window is not None and records_seen_for_window >= total_records_for_window:
                        break
                    offset += 1

    def _internal_paged_search(
        self,
        client: unified.InternalSamGovClient,
        settings: base.SearchSettings,
        keyword: str,
        matched_by: str,
        variant_params: Dict[str, str],
    ) -> Iterable[Tuple[unified.JsonDict, Tuple[str, str]]]:
        if not getattr(settings, "use_predefined_naics", False):
            yield from super()._internal_paged_search(client, settings, keyword, matched_by, variant_params)
            return

        query_text = (variant_params.get("title") or variant_params.get("solnum") or keyword or "").strip()
        codes = getattr(settings, "predefined_naics_codes", []) or []
        for code in codes:
            retrieved = 0
            for posted_from, posted_to in settings.date_windows:
                page = 0
                total_for_window: Optional[int] = None
                while retrieved < settings.max_results_per_search:
                    if self.stop_event.is_set():
                        return
                    page_size = min(100, settings.max_results_per_search - retrieved)
                    params: Dict[str, Any] = {
                        "__source": "internal-search-naics",
                        "index": "opp",
                        "page": page,
                        "mode": "search",
                        "sort": "-modifiedDate",
                        "size": page_size,
                        "postedFrom": posted_from,
                        "postedTo": posted_to,
                        "naics": code,
                    }
                    if query_text:
                        params["q"] = query_text
                    if settings.status == "active":
                        params["is_active"] = "true"
                    elif settings.status:
                        params["status"] = settings.status
                    if settings.ptype:
                        params["opp_type"] = settings.ptype

                    data = self._internal_search_cached(client, params)
                    raw_items = unified.internal_search_results(data)
                    total_for_window = unified.internal_total_records(data, fallback=len(raw_items))
                    if not raw_items:
                        break
                    for raw_item in raw_items:
                        retrieved += 1
                        normalized = unified.normalize_internal_item(raw_item)
                        if self._item_matches_predefined_naics(normalized, settings):
                            yield normalized, (posted_from, posted_to)
                        if retrieved >= settings.max_results_per_search:
                            return
                    records_seen = (page * page_size) + len(raw_items)
                    if total_for_window is not None and records_seen >= total_for_window:
                        break
                    page += 1

    def start_search(self) -> None:
        super().start_search()


def main() -> None:
    app = SamGovSearchProPredefinedNaicsApp()
    app.mainloop()


if __name__ == "__main__":
    main()
