from __future__ import annotations

import os
import re
import threading
import time
from typing import Any, Dict, Iterable, Optional
import tkinter as tk
from tkinter import messagebox, ttk

import samgovsearch as base

# SAM.gov rejects date windows that are exactly one calendar year apart.
# Keep every generated request safely under that boundary.
base.MAX_POSTED_DATE_WINDOW_DAYS = 364

ALL_DATE_REQUEST_DELAY_SECONDS = 2.0
NORMAL_REQUEST_DELAY_SECONDS = 0.25
ALL_DATE_CONFIRM_REQUEST_THRESHOLD = 12


class SamGovSearchAllStatusApp(base.SamGovSearchApp):
    """Extension layer for all-status and quota-safer all-date searches."""

    def __init__(self) -> None:
        self._last_api_request_at = 0.0
        super().__init__()

    def _build_ui(self) -> None:
        super()._build_ui()

        self.all_statuses_var = tk.BooleanVar(value=False)
        left_panel = self.grid_slaves(row=0, column=0)[0]

        ttk.Checkbutton(
            left_panel,
            text="Search all statuses",
            variable=self.all_statuses_var,
            command=self._toggle_status_controls,
        ).grid(row=9, column=0, sticky="w", pady=(8, 0))

        ttk.Label(
            left_panel,
            text=(
                "When checked, the Status dropdown is ignored and no status filter is sent to SAM.gov. "
                "All-date searches are throttled to reduce 429 quota/rate-limit errors."
            ),
            wraplength=360,
        ).grid(row=10, column=0, sticky="w", pady=(2, 0))

        self._toggle_status_controls()

    def _find_status_combo(self) -> Optional[ttk.Combobox]:
        target_var = str(self.status_var)
        pending = list(self.winfo_children())

        while pending:
            widget = pending.pop(0)
            if isinstance(widget, ttk.Combobox):
                try:
                    if widget.cget("textvariable") == target_var:
                        return widget
                except tk.TclError:
                    pass
            pending.extend(widget.winfo_children())

        return None

    def _toggle_status_controls(self) -> None:
        combo = self._find_status_combo()
        if combo is None:
            return
        combo.configure(state="disabled" if self.all_statuses_var.get() else "readonly")

    def _read_settings(self) -> base.SearchSettings:
        settings = super()._read_settings()
        if self.all_statuses_var.get():
            settings.status = ""
        return settings

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

        estimated_requests = self._estimate_minimum_api_requests(settings)
        if settings.all_date_ranges and estimated_requests >= ALL_DATE_CONFIRM_REQUEST_THRESHOLD:
            proceed = messagebox.askyesno(
                "Large SAM.gov API Search",
                "Search all date ranges can use a lot of SAM.gov API quota.\n\n"
                f"Minimum planned search requests: {estimated_requests}\n"
                f"Date windows: {len(settings.date_windows)}\n"
                f"Unique batch items: {len(settings.keywords)}\n\n"
                "This does not include extra pages when SAM.gov returns more results than one page.\n\n"
                "Continue?",
            )
            if not proceed:
                self.status_var_text.set("Search cancelled before using API quota.")
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
                f"across {len(settings.date_windows)} 364-day window(s)."
            )
            self._log(
                f"Estimated minimum API search requests: {estimated_requests}. "
                f"Delay between all-date API requests: {ALL_DATE_REQUEST_DELAY_SECONDS:g} seconds."
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

    def _estimate_minimum_api_requests(self, settings: base.SearchSettings) -> int:
        variant_count = sum(
            len(base.build_search_variants(keyword, settings.search_mode))
            for keyword in settings.keywords
        )
        return max(1, len(settings.date_windows) * max(1, variant_count))

    def _request_delay_seconds(self, settings: base.SearchSettings) -> float:
        if settings.all_date_ranges:
            return ALL_DATE_REQUEST_DELAY_SECONDS
        return NORMAL_REQUEST_DELAY_SECONDS

    def _wait_before_api_request(self, settings: base.SearchSettings) -> None:
        delay = self._request_delay_seconds(settings)
        if delay <= 0:
            return

        elapsed = time.monotonic() - self._last_api_request_at
        remaining = delay - elapsed
        if remaining > 0:
            self.stop_event.wait(remaining)
        self._last_api_request_at = time.monotonic()

    def _search_sam_gov(
        self,
        client: base.SamGovClient,
        params: Dict[str, Any],
        settings: base.SearchSettings,
    ) -> Dict[str, Any]:
        self._wait_before_api_request(settings)
        if self.stop_event.is_set():
            return {"opportunitiesData": [], "totalRecords": 0}

        try:
            return client.search(params)
        except RuntimeError as exc:
            message = str(exc)
            if "HTTP 429" in message or "throttled" in message.lower() or "quota" in message.lower():
                reset_text = self._extract_next_access_time(message)
                reset_suffix = f"\n\nSAM.gov next access time: {reset_text}" if reset_text else ""
                raise RuntimeError(
                    "SAM.gov quota or rate limit was reached. The search stopped so the app does not keep spending requests."
                    f"{reset_suffix}\n\n"
                    "Reduce the batch size, turn off Search all date ranges, lower broad keyword usage, or wait until the reset time."
                ) from exc
            raise

    def _extract_next_access_time(self, message: str) -> str:
        patterns = [
            r'"nextAccessTime"\s*:\s*"([^"]+)"',
            r"'nextAccessTime'\s*:\s*'([^']+)'",
        ]
        for pattern in patterns:
            match = re.search(pattern, message)
            if match:
                return match.group(1)
        return ""

    def _paged_search(
        self,
        client: base.SamGovClient,
        settings: base.SearchSettings,
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

                data = self._search_sam_gov(client, params, settings)
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


def main() -> None:
    app = SamGovSearchAllStatusApp()
    app.mainloop()


if __name__ == "__main__":
    main()
