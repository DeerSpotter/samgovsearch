from __future__ import annotations

import fnmatch
from typing import Any, List
import tkinter as tk
from tkinter import messagebox, ttk

import samgovsearch as base
from samgovsearch_pro_initial_match import SamGovSearchProInitialMatchApp


class SamGovSearchProAttachmentFilterLiveApp(SamGovSearchProInitialMatchApp):
    """Final user-facing app with live attachment-name filtering.

    The SQLite Local Index attachment field is intentionally not an advanced
    search parser. It is a live, local, attachment-name-only filter supporting
    plain contains text plus * and ? wildcards. Clearing the field restores the
    currently loaded result set without re-querying SAM.gov or the SQLite index.
    """

    def _add_local_index_section(self, left_panel: ttk.Frame, row: int) -> None:
        frame = ttk.LabelFrame(left_panel, text="SQLite Local Index", padding=8)
        frame.grid(row=row, column=0, sticky="ew", pady=(8, 0))
        frame.columnconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)

        self.attachment_name_filter_var = tk.StringVar(value="")
        ttk.Label(frame, text="Attachment Name Filter").grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Entry(frame, textvariable=self.attachment_name_filter_var).grid(
            row=1, column=0, columnspan=2, sticky="ew", pady=(2, 4)
        )
        self.attachment_name_filter_var.trace_add("write", lambda *_args: self._on_attachment_name_filter_changed())

        ttk.Button(frame, text="Search Cached Results", command=self.search_sqlite_cache).grid(
            row=2, column=0, sticky="ew", padx=(0, 4), pady=(2, 0)
        )
        ttk.Button(frame, text="Rebuild Index", command=self.rebuild_sqlite_index).grid(
            row=2, column=1, sticky="ew", padx=(4, 0), pady=(2, 0)
        )

        self.index_summary_var = tk.StringVar(value="SQLite index not summarized yet.")
        ttk.Label(frame, textvariable=self.index_summary_var, wraplength=330).grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(5, 0)
        )
        ttk.Label(
            frame,
            text=(
                "Attachment Name Filter is local and automatic. It only filters the results currently loaded "
                "in the table and never searches SAM.gov. Clear the box to restore the loaded results. "
                "Syntax here is simple only: plain text, * and ? wildcards. No regex."
            ),
            wraplength=330,
        ).grid(row=4, column=0, columnspan=2, sticky="w", pady=(5, 0))
        ttk.Label(
            frame,
            text=(
                "Search Cached Results uses the SQLite index and the batch keywords above. "
                "The attachment filter is applied visually after results load, so clearing it brings those "
                "loaded results back without running another search."
            ),
            wraplength=330,
        ).grid(row=5, column=0, columnspan=2, sticky="w", pady=(5, 0))

    def _on_attachment_name_filter_changed(self) -> None:
        self._attachment_name_filter_text = self.attachment_name_filter_var.get().strip()
        if hasattr(self, "tree"):
            self._rebuild_result_tree()
            self._set_results_status(prefix="Filtered" if self._any_local_filter_active_safe() else "Ready")

    def _any_local_filter_active_safe(self) -> bool:
        if getattr(self, "_active_result_filter", ""):
            return True
        if getattr(self, "_attachment_name_filter_text", ""):
            return True
        if getattr(self, "_exclude_search_tokens", []):
            return True
        return False

    def _result_matches_attachment_name_filter(self, result: Any) -> bool:
        pattern = getattr(self, "_attachment_name_filter_text", "").strip()
        if not pattern:
            return True

        pattern_folded = pattern.casefold()
        names = [str(name).casefold() for name in self._attachment_names_for_result(result) if str(name).strip()]
        if not names:
            return False

        if "*" in pattern_folded or "?" in pattern_folded:
            return any(fnmatch.fnmatchcase(name, pattern_folded) for name in names)

        return any(pattern_folded in name for name in names)

    def search_sqlite_cache(self) -> None:
        """Search SQLite by batch keywords only, then visually apply the attachment filter.

        Earlier behavior sent the attachment-name filter into the SQLite query. If
        that query returned nothing, the previous result set was replaced and the
        user could not simply clear the filter to get back to the loaded rows.
        """
        if not self.pro_settings.enable_sqlite_index:
            messagebox.showinfo("SQLite Index Disabled", "Turn on SQLite local index in Search Settings first.")
            return

        try:
            max_results = base.parse_int(self.max_results_var.get(), base.DEFAULT_MAX_RESULTS_PER_SEARCH, 1, 100000)
        except Exception:
            max_results = base.DEFAULT_MAX_RESULTS_PER_SEARCH

        keywords = base.split_keywords(self.keyword_text.get("1.0", "end"))

        try:
            if self.pro_settings.rebuild_index_before_cache_search:
                summary = self._sqlite_index.summary()
                if summary.notice_count == 0:
                    self._log("SQLite index is empty; rebuilding from JSON cache before local search.")
                    self._sqlite_index.rebuild_from_json_cache()
            rows = self._sqlite_index.search(
                keywords=keywords,
                attachment_pattern="",
                max_results=max_results,
                require_attachments=bool(self.require_attachments_var.get()),
                min_attachment_count=base.parse_int(self.min_attachment_count_var.get(), 1, 1, 100000) if self.require_attachments_var.get() else 0,
                min_total_attachment_mb=base.parse_float(self.min_total_size_var.get(), 0.0, 0.0) if self.require_attachments_var.get() else 0.0,
            )
        except Exception as exc:
            messagebox.showerror("SQLite Search Failed", str(exc))
            return

        keyword_label = ", ".join(keywords) if keywords else "all cached results"
        self.stop_event.clear()
        self.results.clear()
        self.seen_notice_ids.clear()
        for row_id in self.tree.get_children():
            self.tree.delete(row_id)

        self._attachment_name_filter_text = self.attachment_name_filter_var.get().strip()
        self.results = self._sqlite_index.rows_to_results(rows, keyword=keyword_label)
        self._visible_results = self._display_results()
        self._rebuild_result_tree()
        self.export_button.configure(state="normal" if self.results else "disabled")
        self._log(
            f"SQLite local index search loaded {len(self.results)} result(s) before local attachment filtering. "
            "No SAM.gov request was made."
        )
        self._set_results_status(prefix="Local cache search" if not self._attachment_name_filter_text else "Filtered")
        self._refresh_index_summary_label()


def main() -> None:
    app = SamGovSearchProAttachmentFilterLiveApp()
    app.mainloop()


if __name__ == "__main__":
    main()
