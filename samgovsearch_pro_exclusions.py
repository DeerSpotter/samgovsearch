from __future__ import annotations

import fnmatch
from typing import Any, List
import tkinter as tk
from tkinter import ttk

from samgovsearch_pro_final import SamGovSearchProFinalApp


class SamGovSearchProExclusionsApp(SamGovSearchProFinalApp):
    """Final user-facing app with exclusion keywords for local result filtering."""

    def __init__(self) -> None:
        self._exclude_keyword_terms: List[str] = []
        super().__init__()

    def _build_ui(self) -> None:
        super()._build_ui()
        self._remove_prefilled_sample_number()

    def _remove_prefilled_sample_number(self) -> None:
        widget = getattr(self, "keyword_text", None)
        if widget is None:
            return
        try:
            current = widget.get("1.0", "end").strip()
            lines = [
                line.strip()
                for line in current.splitlines()
                if line.strip() and line.strip().casefold() != "k0357nc200461-0001"
            ]
            if lines != current.splitlines():
                widget.delete("1.0", "end")
                widget.insert("1.0", "\n".join(lines) or "Patriot\nfrequency converter")
        except Exception:
            return

    def _add_result_filter_section(self, left_panel: ttk.Frame, row: int) -> None:
        filter_frame = ttk.LabelFrame(left_panel, text="Filter Current Results", padding=8)
        filter_frame.grid(row=row, column=0, sticky="ew", pady=(8, 0))
        filter_frame.columnconfigure(0, weight=1)

        self.result_filter_var = tk.StringVar(value="")
        ttk.Label(filter_frame, text="Show results containing").grid(row=0, column=0, columnspan=2, sticky="w")
        entry = ttk.Entry(filter_frame, textvariable=self.result_filter_var)
        entry.grid(row=1, column=0, sticky="ew", padx=(0, 4), pady=(2, 4))
        ttk.Button(filter_frame, text="Clear", command=self._clear_result_filter).grid(
            row=1, column=1, sticky="ew", pady=(2, 4)
        )
        self.result_filter_var.trace_add("write", lambda *_args: self._apply_result_filter())

        self.exclude_keywords_var = tk.StringVar(value="")
        ttk.Label(filter_frame, text="Hide results containing any of these comma-separated keywords").grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(4, 0)
        )
        exclude_entry = ttk.Entry(filter_frame, textvariable=self.exclude_keywords_var)
        exclude_entry.grid(row=3, column=0, sticky="ew", padx=(0, 4), pady=(2, 4))
        ttk.Button(filter_frame, text="Clear", command=self._clear_exclude_keywords).grid(
            row=3, column=1, sticky="ew", pady=(2, 4)
        )
        self.exclude_keywords_var.trace_add("write", lambda *_args: self._on_exclude_keywords_changed())

        ttk.Label(
            filter_frame,
            text=(
                "Both fields filter only the currently loaded table. They never run another SAM.gov search. "
                "Show filter supports text, * and ? wildcards. Hide filter is comma separated, for example: "
                "amendment, award, cancelled."
            ),
            wraplength=330,
        ).grid(row=4, column=0, columnspan=2, sticky="w", pady=(5, 0))

    def _clear_exclude_keywords(self) -> None:
        if hasattr(self, "exclude_keywords_var"):
            self.exclude_keywords_var.set("")
        else:
            self._exclude_keyword_terms = []
            self._rebuild_result_tree()

    def _on_exclude_keywords_changed(self) -> None:
        self._exclude_keyword_terms = self._parse_exclude_keywords(
            getattr(self, "exclude_keywords_var", tk.StringVar(value="")).get()
        )
        if hasattr(self, "tree"):
            self._rebuild_result_tree()
            self._set_results_status(prefix="Filtered" if self._any_local_filter_active() else "Ready")

    @staticmethod
    def _parse_exclude_keywords(raw: str) -> List[str]:
        terms: List[str] = []
        seen = set()
        for value in raw.replace("\n", ",").split(","):
            term = value.strip().casefold()
            if term and term not in seen:
                terms.append(term)
                seen.add(term)
        return terms

    def _any_local_filter_active(self) -> bool:
        return bool(
            getattr(self, "_active_result_filter", "")
            or getattr(self, "_attachment_name_filter_text", "")
            or getattr(self, "_exclude_keyword_terms", [])
        )

    def _display_results(self) -> List[Any]:
        if not self._any_local_filter_active():
            return list(self.results)
        return [
            result
            for result in self.results
            if self._result_matches_filter(result, getattr(self, "_active_result_filter", ""))
        ]

    def _result_matches_filter(self, result: Any, filter_text: str) -> bool:
        if not super()._result_matches_filter(result, filter_text):
            return False
        return not self._result_matches_exclude_keywords(result)

    def _result_matches_exclude_keywords(self, result: Any) -> bool:
        terms = getattr(self, "_exclude_keyword_terms", [])
        if not terms:
            return False

        values = self._result_filter_values(result)
        values_folded = [value.casefold() for value in values if value]
        haystack = " | ".join(values_folded)

        for term in terms:
            if "*" in term or "?" in term:
                if any(fnmatch.fnmatchcase(value, term) for value in values_folded):
                    return True
                if fnmatch.fnmatchcase(haystack, term):
                    return True
            elif term in haystack:
                return True

        return False

    def _result_filter_values(self, result: Any) -> List[str]:
        values: List[str] = []
        try:
            row = result.as_csv_row() if hasattr(result, "as_csv_row") else {}
            values.extend(str(value or "") for value in row.values())
        except Exception:
            pass

        try:
            values.extend(self._attachment_names_for_result(result))
        except Exception:
            pass

        try:
            record = self._cache_record_for_notice(getattr(result, "notice_id", ""))
            item = record.get("item") if isinstance(record, dict) else {}
            if isinstance(item, dict):
                values.append(str(item.get("description") or ""))
                values.append(str(item.get("solicitationNumber") or ""))
                values.append(str(item.get("fullParentPathName") or ""))
        except Exception:
            pass

        return values

    def _set_results_status(self, prefix: str = "Ready") -> None:
        total = len(self.results)
        shown = len(getattr(self, "_visible_results", self.results))
        filters = []
        if getattr(self, "_active_result_filter", ""):
            filters.append(f"show: {self._active_result_filter}")
        if getattr(self, "_attachment_name_filter_text", ""):
            filters.append(f"attachment: {self._attachment_name_filter_text}")
        if getattr(self, "_exclude_keyword_terms", []):
            filters.append("hide: " + ", ".join(self._exclude_keyword_terms))

        if filters:
            self.status_var_text.set(f"{prefix}. Showing {shown} of {total} result(s) for " + "; ".join(filters))
        else:
            self.status_var_text.set(f"{prefix}. {total} result(s) found.")


def main() -> None:
    app = SamGovSearchProExclusionsApp()
    app.mainloop()


if __name__ == "__main__":
    main()
