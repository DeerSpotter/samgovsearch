from __future__ import annotations

import csv
import fnmatch
from datetime import date
from typing import Any, Dict, List, Optional
import webbrowser
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import samgovsearch as base
import samgovsearch_all_status as all_status
import samgovsearch_responsive as responsive
import samgovsearch_unified as unified


class SamGovSearchFilterCacheApp(responsive.ResponsiveSamGovSearchApp):
    """Single UI wrapper adding displayed-result filtering and cache bypass.

    Result filtering is local only. It never starts a new SAM.gov request and it
    restores the full result set as soon as the filter box is cleared.
    """

    def __init__(self) -> None:
        self._visible_results: List[Any] = []
        self._active_result_filter = ""
        self._ignore_cached_searches_current = False
        self._ignore_cache_log_emitted = False
        super().__init__()

    def _build_left_panel(self, left_panel: ttk.Frame) -> None:
        super()._build_left_panel(left_panel)
        self._add_result_filter_section(left_panel, row=13)
        self._add_cache_options_section(left_panel, row=14)

    def _add_result_filter_section(self, left_panel: ttk.Frame, row: int) -> None:
        filter_frame = ttk.LabelFrame(left_panel, text="Filter Current Results", padding=8)
        filter_frame.grid(row=row, column=0, sticky="ew", pady=(8, 0))
        filter_frame.columnconfigure(0, weight=1)

        self.result_filter_var = tk.StringVar(value="")
        entry = ttk.Entry(filter_frame, textvariable=self.result_filter_var)
        entry.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ttk.Button(filter_frame, text="Clear", command=self._clear_result_filter).grid(row=0, column=1, sticky="ew")

        self.result_filter_var.trace_add("write", lambda *_args: self._apply_result_filter())

        ttk.Label(
            filter_frame,
            text=(
                "Filters only the results already loaded in the table. Use * and ? wildcards. "
                "Clearing this box restores all current results without re-searching SAM.gov."
            ),
            wraplength=330,
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(5, 0))

    def _add_cache_options_section(self, left_panel: ttk.Frame, row: int) -> None:
        cache_frame = ttk.LabelFrame(left_panel, text="Cache Options", padding=8)
        cache_frame.grid(row=row, column=0, sticky="ew", pady=(8, 0))
        cache_frame.columnconfigure(0, weight=1)

        self.ignore_cached_searches_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            cache_frame,
            text="Ignore cached searches for this run",
            variable=self.ignore_cached_searches_var,
        ).grid(row=0, column=0, sticky="w")

        ttk.Label(
            cache_frame,
            text=(
                "When checked, the app skips existing query and notice cache hits and asks SAM.gov again. "
                "Fresh successful responses are still written back into the cache."
            ),
            wraplength=330,
        ).grid(row=1, column=0, sticky="w", pady=(5, 0))

    def _read_settings(self) -> base.SearchSettings:
        settings = super()._read_settings()
        ignore_cache = bool(getattr(self, "ignore_cached_searches_var", tk.BooleanVar(value=False)).get())
        setattr(settings, "ignore_cached_searches", ignore_cache)
        self._ignore_cached_searches_current = ignore_cache
        self._ignore_cache_log_emitted = False
        return settings

    def _ignore_cache_enabled(self, settings: Optional[Any] = None) -> bool:
        if settings is not None and hasattr(settings, "ignore_cached_searches"):
            return bool(getattr(settings, "ignore_cached_searches"))
        return bool(self._ignore_cached_searches_current)

    def _log_ignore_cache_once(self) -> None:
        if self._ignore_cache_log_emitted:
            return
        self._ignore_cache_log_emitted = True
        self.queue.put((
            "log",
            "Ignore cached searches is enabled: cache reads are skipped for this run, but fresh results will still be stored.",
        ))

    def _search_sam_gov(
        self,
        client: base.SamGovClient,
        params: Dict[str, Any],
        settings: base.SearchSettings,
    ) -> Dict[str, Any]:
        if not self._ignore_cache_enabled(settings):
            return super()._search_sam_gov(client, params, settings)

        self._log_cache_path_once()
        self._log_ignore_cache_once()
        data = all_status.SamGovSearchAllStatusApp._search_sam_gov(self, client, params, settings)
        self._api_cache.store_query_response(params, data, source_label="api-search-refresh")
        item_count = len(data.get("opportunitiesData") or []) if isinstance(data, dict) else 0
        self.queue.put(("log", f"API cache refreshed from network response with {item_count} item(s)."))
        return data

    def _internal_search_cached(self, client: unified.InternalSamGovClient, params: Dict[str, Any]) -> unified.JsonDict:
        if not self._ignore_cache_enabled():
            return super()._internal_search_cached(client, params)

        self._log_ignore_cache_once()
        self._sleep_between_internal_requests()
        network_params = {key: value for key, value in params.items() if not key.startswith("__")}
        data = client.search_raw(network_params)
        self._api_cache.store_query_response(params, data, source_label="internal-search-refresh")
        self.queue.put(("log", "Internal cache refreshed from website/internal network response."))
        return data

    def _cached_notice_item(self, notice_id: str) -> Optional[unified.JsonDict]:
        if self._ignore_cache_enabled():
            return None
        return super()._cached_notice_item(notice_id)

    def _cached_official_notice_item(self, notice_id: str) -> Optional[unified.JsonDict]:
        if self._ignore_cache_enabled():
            return None
        return super()._cached_official_notice_item(notice_id)

    def _clear_result_filter(self) -> None:
        if hasattr(self, "result_filter_var"):
            self.result_filter_var.set("")
        else:
            self._active_result_filter = ""
            self._rebuild_result_tree()

    def _apply_result_filter(self) -> None:
        if not hasattr(self, "tree"):
            return
        self._active_result_filter = getattr(self, "result_filter_var", tk.StringVar(value="")).get().strip()
        self._rebuild_result_tree()
        self._set_results_status(prefix="Filtered" if self._active_result_filter else "Ready")

    def _display_results(self) -> List[Any]:
        if not self._active_result_filter:
            return list(self.results)
        return [result for result in self.results if self._result_matches_filter(result, self._active_result_filter)]

    def _result_matches_filter(self, result: Any, filter_text: str) -> bool:
        pattern = filter_text.strip()
        if not pattern:
            return True

        row = result.as_csv_row() if hasattr(result, "as_csv_row") else {}
        haystack = " | ".join(str(value or "") for value in row.values())
        haystack_folded = haystack.casefold()
        pattern_folded = pattern.casefold()

        if "*" in pattern_folded or "?" in pattern_folded:
            return fnmatch.fnmatchcase(haystack_folded, pattern_folded)

        return pattern_folded in haystack_folded

    def _result_row_values(self, result: Any) -> List[Any]:
        size_text = "" if result.attachment_total_mb is None else f"{result.attachment_total_mb:.2f}"
        return [
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
        ]

    def _insert_result_row(self, result: Any) -> None:
        self.tree.insert("", "end", values=self._result_row_values(result))

    def _add_result(self, result: Any) -> None:
        self.results.append(result)
        if self._result_matches_filter(result, self._active_result_filter):
            self._visible_results.append(result)
            self._insert_result_row(result)
        self.export_button.configure(state="normal" if self.results else "disabled")
        self._update_download_button_state()
        self._set_results_status(prefix="Searching")

    def _rebuild_result_tree(self) -> None:
        for row_id in self.tree.get_children():
            self.tree.delete(row_id)

        self._visible_results = self._display_results()
        for result in self._visible_results:
            self._insert_result_row(result)

        self.export_button.configure(state="normal" if self.results else "disabled")
        self._update_download_button_state()

    def _set_results_status(self, prefix: str = "Ready") -> None:
        total = len(self.results)
        shown = len(getattr(self, "_visible_results", self.results))
        if self._active_result_filter:
            self.status_var_text.set(f"{prefix}. Showing {shown} of {total} result(s) for filter: {self._active_result_filter}")
        else:
            self.status_var_text.set(f"{prefix}. {total} result(s) found.")

    def _finish_search(self) -> None:
        super()._finish_search()
        self._visible_results = self._display_results()
        self._set_results_status(prefix="Stopped" if self.stop_event.is_set() else "Done")

    def _sort_results_by_column(self, column: str) -> None:
        if not self.results:
            return

        if self._last_sorted_column == column:
            reverse = not self._sort_reverse_by_column.get(column, False)
        else:
            reverse = False

        self._last_sorted_column = column
        self._sort_reverse_by_column[column] = reverse
        self.results.sort(key=lambda result: self._sort_key_for_result(result, column), reverse=reverse)
        self._rebuild_result_tree()
        self._refresh_sort_headings(column, reverse)
        shown = len(self._visible_results)
        total = len(self.results)
        if self._active_result_filter:
            self.status_var_text.set(
                f"Sorted visible results by {column} {'descending' if reverse else 'ascending'}: {shown} of {total} shown."
            )
        else:
            self.status_var_text.set(
                f"Sorted {total} result(s) by {column} {'descending' if reverse else 'ascending'}."
            )

    def _update_download_button_state(self) -> None:
        button = getattr(self, "download_attachments_button", None)
        if button is not None:
            has_displayed_rows = bool(getattr(self, "_visible_results", []))
            button.configure(state="normal" if has_displayed_rows else "disabled")

    def _selected_result(self) -> Optional[Any]:
        selected = self.tree.selection()
        if not selected:
            return None
        index = self.tree.index(selected[0])
        visible = getattr(self, "_visible_results", self.results)
        if index < 0 or index >= len(visible):
            return None
        return visible[index]

    def open_selected_link(self, _event: Any = None) -> None:
        result = self._selected_result()
        if result is None:
            return
        link = str(getattr(result, "ui_link", "") or "").strip()
        if link:
            webbrowser.open(link)

    def export_csv(self) -> None:
        rows = getattr(self, "_visible_results", self.results)
        if not rows:
            messagebox.showinfo("No Results", "There are no displayed results to export.")
            return

        path = filedialog.asksaveasfilename(
            title="Save SAM.gov displayed results",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            initialfile=f"samgov_results_{date.today().strftime('%Y%m%d')}.csv",
        )
        if not path:
            return

        fieldnames = list(rows[0].as_csv_row().keys())
        with open(path, "w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for result in rows:
                writer.writerow(result.as_csv_row())

        if self._active_result_filter:
            self._log(f"Exported {len(rows)} displayed result(s) from {len(self.results)} total result(s) to {path}.")
            messagebox.showinfo("Export Complete", f"Exported {len(rows)} displayed result(s).")
        else:
            self._log(f"Exported {len(rows)} result(s) to {path}.")
            messagebox.showinfo("Export Complete", f"Exported {len(rows)} result(s).")


def main() -> None:
    app = SamGovSearchFilterCacheApp()
    app.mainloop()


if __name__ == "__main__":
    main()
