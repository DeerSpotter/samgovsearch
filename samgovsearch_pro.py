from __future__ import annotations

import fnmatch
import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import samgovsearch as base
import samgovsearch_all_status as all_status
import samgovsearch_filter_cache as filter_cache
import samgovsearch_unified as unified
from samgov_api_cache import SamGovApiCache
from samgov_sqlite_index import SamGovSQLiteIndex


@dataclass
class ProAppSettings:
    enable_sqlite_index: bool = True
    auto_index_new_results: bool = True
    rebuild_index_before_cache_search: bool = True
    retry_transient_errors: bool = True
    retry_attempts: int = 2
    retry_backoff_seconds: float = 1.5
    normal_api_delay_seconds: float = 0.25
    all_date_api_delay_seconds: float = 2.0
    internal_delay_seconds: float = 0.35
    hybrid_official_delay_seconds: float = 0.35

    @classmethod
    def load(cls, path: Path) -> "ProAppSettings":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return cls()
        if not isinstance(data, dict):
            return cls()

        defaults = cls()
        values: Dict[str, Any] = {}
        for field_name, default_value in asdict(defaults).items():
            value = data.get(field_name, default_value)
            try:
                if isinstance(default_value, bool):
                    values[field_name] = bool(value)
                elif isinstance(default_value, int):
                    values[field_name] = max(0, int(value))
                elif isinstance(default_value, float):
                    values[field_name] = max(0.0, float(value))
                else:
                    values[field_name] = value
            except Exception:
                values[field_name] = default_value
        return cls(**values)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2, sort_keys=True), encoding="utf-8")


class SamGovSearchProApp(filter_cache.SamGovSearchFilterCacheApp):
    """Production-oriented wrapper with SQLite local index, cache search,
    attachment-name filtering, enrichment panel, cache manager, and tunable
    retry/rate-limit behavior.
    """

    def __init__(self) -> None:
        self._bootstrap_cache = SamGovApiCache.default()
        self._settings_path = self._bootstrap_cache.root / "samgovsearch_settings.json"
        self.pro_settings = ProAppSettings.load(self._settings_path)
        self._sqlite_index = SamGovSQLiteIndex(self._bootstrap_cache)
        self._details_text: Optional[tk.Text] = None
        self._attachment_name_filter_text = ""
        super().__init__()
        self._apply_behavior_settings()
        self._refresh_index_summary_label()

    def _build_ui(self) -> None:
        super()._build_ui()
        self._add_enrichment_view()
        if hasattr(self, "tree"):
            self.tree.bind("<<TreeviewSelect>>", lambda _event: self._update_enrichment_view(), add="+")
        self._update_enrichment_view()

    def _build_left_panel(self, left_panel: ttk.Frame) -> None:
        super()._build_left_panel(left_panel)
        self._add_local_index_section(left_panel, row=15)
        self._add_cache_manager_section(left_panel, row=16)

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
                "Search Cached Results uses only the local SQLite index. It does not call SAM.gov. "
                "Attachment filter supports text, * and ? wildcards."
            ),
            wraplength=330,
        ).grid(row=4, column=0, columnspan=2, sticky="w", pady=(5, 0))

    def _add_cache_manager_section(self, left_panel: ttk.Frame, row: int) -> None:
        frame = ttk.LabelFrame(left_panel, text="Cache / Behavior", padding=8)
        frame.grid(row=row, column=0, sticky="ew", pady=(8, 0))
        frame.columnconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)

        ttk.Button(frame, text="Cache Manager", command=self.open_cache_manager_dialog).grid(
            row=0, column=0, sticky="ew", padx=(0, 4)
        )
        ttk.Button(frame, text="Search Settings", command=self.open_behavior_settings_dialog).grid(
            row=0, column=1, sticky="ew", padx=(4, 0)
        )
        ttk.Label(
            frame,
            text="Manage JSON cache, SQLite index, and retry/rate-limit settings.",
            wraplength=330,
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(5, 0))

    def _add_enrichment_view(self) -> None:
        if not hasattr(self, "tree"):
            return
        right = self.tree.master
        right.rowconfigure(4, weight=0)

        details_frame = ttk.LabelFrame(right, text="Selected Result Details / Enrichment", padding=6)
        details_frame.grid(row=4, column=0, sticky="ew", pady=(8, 0))
        details_frame.columnconfigure(0, weight=1)

        text = tk.Text(details_frame, height=9, wrap="word")
        text.grid(row=0, column=0, sticky="ew")
        text.configure(state="disabled")
        yscroll = ttk.Scrollbar(details_frame, orient="vertical", command=text.yview)
        yscroll.grid(row=0, column=1, sticky="ns")
        text.configure(yscrollcommand=yscroll.set)
        self._details_text = text

    def _set_details_text(self, text: str) -> None:
        widget = self._details_text
        if widget is None:
            return
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        if text:
            widget.insert("end", text)
        widget.configure(state="disabled")

    def _update_enrichment_view(self) -> None:
        result = self._selected_result() if hasattr(self, "_selected_result") else None
        if result is None:
            self._set_details_text("Select a result row to see enrichment details, attachment names, cache source, and description.")
            return

        record = self._cache_record_for_notice(getattr(result, "notice_id", ""))
        item = record.get("item") if isinstance(record, dict) and isinstance(record.get("item"), dict) else {}
        names = self._attachment_names_for_result(result)
        links = list(getattr(result, "resource_links", []) or [])
        description = (
            getattr(result, "description", "")
            or (item.get("description") if isinstance(item, dict) else "")
            or ""
        )
        total_mb = getattr(result, "attachment_total_mb", None)
        total_mb_text = "" if total_mb is None else f"{total_mb:.3f}"

        lines = [
            f"Title: {getattr(result, 'title', '')}",
            f"Solicitation: {getattr(result, 'solicitation_number', '')}",
            f"Notice ID: {getattr(result, 'notice_id', '')}",
            f"Type: {getattr(result, 'notice_type', '')}",
            f"Posted: {getattr(result, 'posted_date', '')}",
            f"Response Deadline: {getattr(result, 'response_deadline', '')}",
            f"Active: {getattr(result, 'active', '')}",
            f"Organization: {getattr(result, 'organization', '')}",
            f"NAICS: {getattr(result, 'naics_code', '')}",
            f"PSC: {getattr(result, 'classification_code', '')}",
            f"Attachments: {getattr(result, 'attachment_count', 0)}",
            f"Attachment Total MB: {total_mb_text}",
            f"Attachment Note: {getattr(result, 'attachment_size_note', '')}",
        ]

        if record:
            lines.extend([
                f"Cache Source: {record.get('source', '')}",
                f"Cache Saved UTC: {record.get('saved_at_utc', '')}",
                f"Cache File: {self._api_cache.notice_path(getattr(result, 'notice_id', ''))}",
            ])
        else:
            lines.append("Cache Source: not found in JSON notice cache")

        if names:
            lines.append("")
            lines.append("Attachment Names:")
            for index, name in enumerate(names[:80], start=1):
                lines.append(f"  {index}. {name}")
            if len(names) > 80:
                lines.append(f"  ...and {len(names) - 80} more attachment name(s).")

        if links:
            lines.append("")
            lines.append("Resource Links:")
            for index, link in enumerate(links[:30], start=1):
                lines.append(f"  {index}. {link}")
            if len(links) > 30:
                lines.append(f"  ...and {len(links) - 30} more link(s).")

        if description:
            lines.append("")
            lines.append("Description:")
            lines.append(str(description)[:5000])

        self._set_details_text("\n".join(lines))

    def _cache_record_for_notice(self, notice_id: Any) -> Dict[str, Any]:
        notice = str(notice_id or "").strip()
        if not notice:
            return {}
        record = self._api_cache.read_json(self._api_cache.notice_path(notice))
        return record if isinstance(record, dict) else {}

    def _on_attachment_name_filter_changed(self) -> None:
        self._attachment_name_filter_text = self.attachment_name_filter_var.get().strip()
        if hasattr(self, "tree"):
            self._rebuild_result_tree()
            self._set_results_status(prefix="Filtered" if (self._active_result_filter or self._attachment_name_filter_text) else "Ready")

    def _result_matches_filter(self, result: Any, filter_text: str) -> bool:
        if not super()._result_matches_filter(result, filter_text):
            return False
        return self._result_matches_attachment_name_filter(result)

    def _result_matches_attachment_name_filter(self, result: Any) -> bool:
        pattern = getattr(self, "_attachment_name_filter_text", "").strip()
        if not pattern:
            return True

        values: List[str] = []
        values.extend(self._attachment_names_for_result(result))
        values.extend(str(link) for link in (getattr(result, "resource_links", []) or []))
        haystack = " | ".join(value for value in values if value).casefold()
        if not haystack:
            return False

        pattern_folded = pattern.casefold()
        if "*" in pattern_folded or "?" in pattern_folded:
            return fnmatch.fnmatchcase(haystack, pattern_folded)
        return pattern_folded in haystack

    def _attachment_names_for_result(self, result: Any) -> List[str]:
        direct = getattr(result, "attachment_names", None)
        if isinstance(direct, list):
            names = [str(name) for name in direct if str(name).strip()]
            if names:
                return names
        return super()._attachment_names_for_result(result)

    def _set_results_status(self, prefix: str = "Ready") -> None:
        total = len(self.results)
        shown = len(getattr(self, "_visible_results", self.results))
        filters = []
        if getattr(self, "_active_result_filter", ""):
            filters.append(f"result filter: {self._active_result_filter}")
        if getattr(self, "_attachment_name_filter_text", ""):
            filters.append(f"attachment filter: {self._attachment_name_filter_text}")
        if filters:
            self.status_var_text.set(f"{prefix}. Showing {shown} of {total} result(s) for " + "; ".join(filters))
        else:
            self.status_var_text.set(f"{prefix}. {total} result(s) found.")

    def _add_result(self, result: Any) -> None:
        super()._add_result(result)
        self._index_result_if_enabled(result)
        self._update_enrichment_view()

    def _rebuild_result_tree(self) -> None:
        super()._rebuild_result_tree()
        self._update_enrichment_view()

    def _finish_search(self) -> None:
        super()._finish_search()
        self._refresh_index_summary_label()

    def _index_result_if_enabled(self, result: Any) -> None:
        if not self.pro_settings.enable_sqlite_index or not self.pro_settings.auto_index_new_results:
            return
        try:
            item = self._item_for_result_indexing(result)
            if item:
                self._sqlite_index.upsert_item(item, source=getattr(result, "matched_by", "") or "runtime-result")
        except Exception as exc:
            self._log(f"SQLite index update skipped for {getattr(result, 'notice_id', '')}: {exc}")

    def _item_for_result_indexing(self, result: Any) -> Dict[str, Any]:
        record = self._cache_record_for_notice(getattr(result, "notice_id", ""))
        item = record.get("item") if isinstance(record, dict) else None
        if isinstance(item, dict):
            return item

        names = getattr(result, "attachment_names", [])
        if not isinstance(names, list):
            names = []
        total_mb = getattr(result, "attachment_total_mb", None)
        total_bytes = None if total_mb is None else int(float(total_mb) * 1024 * 1024)
        return {
            "noticeId": getattr(result, "notice_id", ""),
            "title": getattr(result, "title", ""),
            "solicitationNumber": getattr(result, "solicitation_number", ""),
            "type": getattr(result, "notice_type", ""),
            "postedDate": getattr(result, "posted_date", ""),
            "responseDeadLine": getattr(result, "response_deadline", ""),
            "active": getattr(result, "active", ""),
            "fullParentPathName": getattr(result, "organization", ""),
            "naicsCode": getattr(result, "naics_code", ""),
            "classificationCode": getattr(result, "classification_code", ""),
            "uiLink": getattr(result, "ui_link", ""),
            "resourceLinks": list(getattr(result, "resource_links", []) or []),
            "samgovsearchAttachmentNames": names,
            "samgovsearchAttachmentTotalBytes": total_bytes,
            "description": getattr(result, "description", ""),
        }

    def search_sqlite_cache(self) -> None:
        if not self.pro_settings.enable_sqlite_index:
            messagebox.showinfo("SQLite Index Disabled", "Turn on SQLite local index in Search Settings first.")
            return

        try:
            max_results = base.parse_int(self.max_results_var.get(), base.DEFAULT_MAX_RESULTS_PER_SEARCH, 1, 100000)
        except Exception:
            max_results = base.DEFAULT_MAX_RESULTS_PER_SEARCH

        keywords = base.split_keywords(self.keyword_text.get("1.0", "end"))
        attachment_pattern = self.attachment_name_filter_var.get().strip()

        try:
            if self.pro_settings.rebuild_index_before_cache_search:
                summary = self._sqlite_index.summary()
                if summary.notice_count == 0:
                    self._log("SQLite index is empty; rebuilding from JSON cache before local search.")
                    self._sqlite_index.rebuild_from_json_cache()
            rows = self._sqlite_index.search(
                keywords=keywords,
                attachment_pattern=attachment_pattern,
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

        self.results = self._sqlite_index.rows_to_results(rows, keyword=keyword_label)
        self._visible_results = self._display_results()
        self._rebuild_result_tree()
        self.export_button.configure(state="normal" if self.results else "disabled")
        self._log(
            f"SQLite local index search returned {len(self.results)} result(s). "
            "No SAM.gov request was made."
        )
        self._set_results_status(prefix="Local cache search")
        self._refresh_index_summary_label()

    def rebuild_sqlite_index(self) -> None:
        if not self.pro_settings.enable_sqlite_index:
            messagebox.showinfo("SQLite Index Disabled", "Turn on SQLite local index in Search Settings first.")
            return
        try:
            self.status_var_text.set("Rebuilding SQLite index from JSON cache...")
            self.update_idletasks()
            count = self._sqlite_index.rebuild_from_json_cache(
                progress_callback=lambda value: self._log(f"Indexed {value} cached notice(s)...")
            )
        except Exception as exc:
            messagebox.showerror("Index Rebuild Failed", str(exc))
            return

        self._refresh_index_summary_label()
        self._log(f"SQLite index rebuilt from JSON cache with {count} notice(s).")
        messagebox.showinfo("Index Rebuilt", f"Indexed {count} cached notice(s).")

    def _refresh_index_summary_label(self) -> None:
        label = getattr(self, "index_summary_var", None)
        if label is None:
            return
        try:
            summary = self._sqlite_index.summary()
            label.set(
                f"Indexed notices: {summary.notice_count}; attachments: {summary.attachment_count}; "
                f"DB: {summary.db_path}"
            )
        except Exception as exc:
            label.set(f"SQLite index summary unavailable: {exc}")

    def open_cache_manager_dialog(self) -> None:
        dialog = tk.Toplevel(self)
        dialog.title("SAM.gov Cache Manager")
        dialog.transient(self)
        dialog.geometry("720x520")
        dialog.columnconfigure(0, weight=1)
        dialog.rowconfigure(1, weight=1)

        summary_var = tk.StringVar(value="")
        ttk.Label(dialog, textvariable=summary_var, padding=10, wraplength=680).grid(row=0, column=0, sticky="ew")

        text = tk.Text(dialog, height=16, wrap="word")
        text.grid(row=1, column=0, sticky="nsew", padx=10)
        text.configure(state="disabled")

        buttons = ttk.Frame(dialog, padding=10)
        buttons.grid(row=2, column=0, sticky="ew")
        for column in range(5):
            buttons.columnconfigure(column, weight=1)

        def set_text(value: str) -> None:
            text.configure(state="normal")
            text.delete("1.0", "end")
            text.insert("end", value)
            text.configure(state="disabled")

        def refresh() -> None:
            api_summary = self._api_cache.summary()
            index_summary = self._sqlite_index.summary()
            summary_var.set(
                f"JSON cache: {api_summary['query_count']} query file(s), {api_summary['notice_count']} notice file(s). "
                f"SQLite: {index_summary.notice_count} indexed notice(s), {index_summary.attachment_count} attachment reference(s)."
            )
            set_text(
                "Cache Root:\n"
                f"{api_summary['cache_root']}\n\n"
                "SQLite Index:\n"
                f"{index_summary.db_path}\n\n"
                f"Last Index Rebuild UTC: {index_summary.last_rebuild_utc or 'never recorded'}\n"
                f"Max Cache Age Days: {api_summary.get('max_age_days') or 'no expiry'}\n\n"
                "Query cache stores exact SAM.gov/internal search responses.\n"
                "Notice cache stores per-opportunity JSON records.\n"
                "SQLite index is rebuilt from notice cache and is used for fast local searches."
            )

        def open_folder() -> None:
            try:
                os.startfile(str(self._api_cache.root))  # type: ignore[attr-defined]
            except Exception as exc:
                messagebox.showerror("Open Folder Failed", str(exc), parent=dialog)

        def rebuild() -> None:
            try:
                count = self._sqlite_index.rebuild_from_json_cache()
                self._log(f"SQLite index rebuilt from cache manager with {count} notice(s).")
                refresh()
                self._refresh_index_summary_label()
                messagebox.showinfo("Index Rebuilt", f"Indexed {count} cached notice(s).", parent=dialog)
            except Exception as exc:
                messagebox.showerror("Index Rebuild Failed", str(exc), parent=dialog)

        def export_index() -> None:
            path = filedialog.asksaveasfilename(
                title="Export SQLite index",
                defaultextension=".csv",
                filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
                initialfile="samgov_sqlite_index.csv",
                parent=dialog,
            )
            if not path:
                return
            try:
                count = self._sqlite_index.export_csv(Path(path))
                messagebox.showinfo("Export Complete", f"Exported {count} indexed notice(s).", parent=dialog)
            except Exception as exc:
                messagebox.showerror("Export Failed", str(exc), parent=dialog)

        def clear_query_cache() -> None:
            if not messagebox.askyesno("Clear Query Cache", "Delete cached exact query response JSON files?", parent=dialog):
                return
            for path in self._api_cache.queries_dir.glob("*.json"):
                try:
                    path.unlink()
                except Exception:
                    pass
            self._log("Cleared query cache files.")
            refresh()

        def clear_sqlite() -> None:
            if not messagebox.askyesno("Clear SQLite Index", "Clear the SQLite local index database? JSON cache files are not deleted.", parent=dialog):
                return
            try:
                self._sqlite_index.delete_database()
                self._log("Cleared SQLite local index.")
                refresh()
                self._refresh_index_summary_label()
            except Exception as exc:
                messagebox.showerror("Clear SQLite Failed", str(exc), parent=dialog)

        ttk.Button(buttons, text="Refresh", command=refresh).grid(row=0, column=0, sticky="ew", padx=3)
        ttk.Button(buttons, text="Open Folder", command=open_folder).grid(row=0, column=1, sticky="ew", padx=3)
        ttk.Button(buttons, text="Rebuild Index", command=rebuild).grid(row=0, column=2, sticky="ew", padx=3)
        ttk.Button(buttons, text="Export Index CSV", command=export_index).grid(row=0, column=3, sticky="ew", padx=3)
        ttk.Button(buttons, text="Close", command=dialog.destroy).grid(row=0, column=4, sticky="ew", padx=3)
        ttk.Button(buttons, text="Clear Query Cache", command=clear_query_cache).grid(row=1, column=0, columnspan=2, sticky="ew", padx=3, pady=(8, 0))
        ttk.Button(buttons, text="Clear SQLite Index", command=clear_sqlite).grid(row=1, column=2, columnspan=2, sticky="ew", padx=3, pady=(8, 0))

        refresh()
        dialog.grab_set()

    def open_behavior_settings_dialog(self) -> None:
        dialog = tk.Toplevel(self)
        dialog.title("Search Behavior Settings")
        dialog.transient(self)
        dialog.resizable(False, False)

        frame = ttk.Frame(dialog, padding=12)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.columnconfigure(1, weight=1)

        bool_vars: Dict[str, tk.BooleanVar] = {
            "enable_sqlite_index": tk.BooleanVar(value=self.pro_settings.enable_sqlite_index),
            "auto_index_new_results": tk.BooleanVar(value=self.pro_settings.auto_index_new_results),
            "rebuild_index_before_cache_search": tk.BooleanVar(value=self.pro_settings.rebuild_index_before_cache_search),
            "retry_transient_errors": tk.BooleanVar(value=self.pro_settings.retry_transient_errors),
        }
        number_vars: Dict[str, tk.StringVar] = {
            "retry_attempts": tk.StringVar(value=str(self.pro_settings.retry_attempts)),
            "retry_backoff_seconds": tk.StringVar(value=str(self.pro_settings.retry_backoff_seconds)),
            "normal_api_delay_seconds": tk.StringVar(value=str(self.pro_settings.normal_api_delay_seconds)),
            "all_date_api_delay_seconds": tk.StringVar(value=str(self.pro_settings.all_date_api_delay_seconds)),
            "internal_delay_seconds": tk.StringVar(value=str(self.pro_settings.internal_delay_seconds)),
            "hybrid_official_delay_seconds": tk.StringVar(value=str(self.pro_settings.hybrid_official_delay_seconds)),
        }

        row = 0
        checks = [
            ("enable_sqlite_index", "Enable SQLite local index"),
            ("auto_index_new_results", "Automatically index new results as they arrive"),
            ("rebuild_index_before_cache_search", "Rebuild index automatically if empty before local cache search"),
            ("retry_transient_errors", "Retry transient timeout/server/network errors"),
        ]
        for key, text in checks:
            ttk.Checkbutton(frame, text=text, variable=bool_vars[key]).grid(row=row, column=0, columnspan=2, sticky="w", pady=2)
            row += 1

        entries = [
            ("retry_attempts", "Retry Attempts"),
            ("retry_backoff_seconds", "Retry Backoff Seconds"),
            ("normal_api_delay_seconds", "Normal Official API Delay Seconds"),
            ("all_date_api_delay_seconds", "All-Date Official API Delay Seconds"),
            ("internal_delay_seconds", "Website/Internal Delay Seconds"),
            ("hybrid_official_delay_seconds", "Hybrid Official Enrich Delay Seconds"),
        ]
        for key, label in entries:
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=2)
            ttk.Entry(frame, textvariable=number_vars[key], width=16).grid(row=row, column=1, sticky="ew", padx=(8, 0), pady=2)
            row += 1

        ttk.Label(
            frame,
            text=(
                "Settings are saved beside the cache and applied immediately. "
                "Quota/rate-limit errors are not retried; the app stops or falls back to cached/internal data."
            ),
            wraplength=520,
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(8, 8))
        row += 1

        buttons = ttk.Frame(frame)
        buttons.grid(row=row, column=0, columnspan=2, sticky="ew")
        buttons.columnconfigure(0, weight=1)
        buttons.columnconfigure(1, weight=1)

        def save() -> None:
            try:
                updated = ProAppSettings(
                    enable_sqlite_index=bool_vars["enable_sqlite_index"].get(),
                    auto_index_new_results=bool_vars["auto_index_new_results"].get(),
                    rebuild_index_before_cache_search=bool_vars["rebuild_index_before_cache_search"].get(),
                    retry_transient_errors=bool_vars["retry_transient_errors"].get(),
                    retry_attempts=max(0, int(number_vars["retry_attempts"].get())),
                    retry_backoff_seconds=max(0.0, float(number_vars["retry_backoff_seconds"].get())),
                    normal_api_delay_seconds=max(0.0, float(number_vars["normal_api_delay_seconds"].get())),
                    all_date_api_delay_seconds=max(0.0, float(number_vars["all_date_api_delay_seconds"].get())),
                    internal_delay_seconds=max(0.0, float(number_vars["internal_delay_seconds"].get())),
                    hybrid_official_delay_seconds=max(0.0, float(number_vars["hybrid_official_delay_seconds"].get())),
                )
            except Exception as exc:
                messagebox.showerror("Invalid Settings", str(exc), parent=dialog)
                return

            self.pro_settings = updated
            self.pro_settings.save(self._settings_path)
            self._apply_behavior_settings()
            self._refresh_index_summary_label()
            messagebox.showinfo("Settings Saved", "Search behavior settings were saved and applied.", parent=dialog)

        ttk.Button(buttons, text="Save", command=save).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ttk.Button(buttons, text="Close", command=dialog.destroy).grid(row=0, column=1, sticky="ew", padx=(4, 0))

        dialog.bind("<Return>", lambda _event: save())
        dialog.bind("<Escape>", lambda _event: dialog.destroy())
        dialog.grab_set()

    def _apply_behavior_settings(self) -> None:
        all_status.NORMAL_REQUEST_DELAY_SECONDS = self.pro_settings.normal_api_delay_seconds
        all_status.ALL_DATE_REQUEST_DELAY_SECONDS = self.pro_settings.all_date_api_delay_seconds
        unified.INTERNAL_REQUEST_DELAY_SECONDS = self.pro_settings.internal_delay_seconds
        unified.HYBRID_OFFICIAL_DELAY_SECONDS = self.pro_settings.hybrid_official_delay_seconds
        self._log(
            "Search behavior applied: "
            f"API delay={self.pro_settings.normal_api_delay_seconds:g}s, "
            f"all-date delay={self.pro_settings.all_date_api_delay_seconds:g}s, "
            f"internal delay={self.pro_settings.internal_delay_seconds:g}s, "
            f"retries={self.pro_settings.retry_attempts}."
        )

    def start_search(self) -> None:
        self._apply_behavior_settings()
        super().start_search()

    def _call_with_retries(self, label: str, func: Callable[[], Any]) -> Any:
        attempts = max(1, int(self.pro_settings.retry_attempts) + 1)
        delay = max(0.0, float(self.pro_settings.retry_backoff_seconds))
        last_error: Optional[Exception] = None

        for attempt in range(1, attempts + 1):
            if self.stop_event.is_set():
                return func()
            try:
                return func()
            except Exception as exc:
                last_error = exc
                if not self.pro_settings.retry_transient_errors or not self._is_retryable_error(exc) or attempt >= attempts:
                    raise
                self.queue.put((
                    "log",
                    f"{label} failed with a transient error. Retry {attempt}/{attempts - 1} in {delay:g}s: {exc}",
                ))
                self.stop_event.wait(delay)
                delay = delay * 2 if delay > 0 else 0

        if last_error:
            raise last_error
        return func()

    @staticmethod
    def _is_retryable_error(exc: Exception) -> bool:
        message = str(exc).lower()
        if "http 429" in message or "quota" in message or "rate limit" in message or "nextaccesstime" in message:
            return False
        retry_tokens = [
            "timed out",
            "timeout",
            "temporarily",
            "connection reset",
            "connection aborted",
            "remote end closed",
            "http 500",
            "http 502",
            "http 503",
            "http 504",
            "bad gateway",
            "service unavailable",
            "gateway timeout",
        ]
        return any(token in message for token in retry_tokens)

    def _search_sam_gov(
        self,
        client: base.SamGovClient,
        params: Dict[str, Any],
        settings: base.SearchSettings,
    ) -> Dict[str, Any]:
        return self._call_with_retries(
            "Official API search",
            lambda: super(SamGovSearchProApp, self)._search_sam_gov(client, params, settings),
        )

    def _internal_search_cached(self, client: unified.InternalSamGovClient, params: Dict[str, Any]) -> unified.JsonDict:
        return self._call_with_retries(
            "Website/internal search",
            lambda: super(SamGovSearchProApp, self)._internal_search_cached(client, params),
        )


def main() -> None:
    app = SamGovSearchProApp()
    app.mainloop()


if __name__ == "__main__":
    main()
