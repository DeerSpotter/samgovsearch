from __future__ import annotations

import fnmatch
from typing import Any
import tkinter as tk
from tkinter import ttk

from samgovsearch_pro_naics_q_filter import SamGovSearchProNaicsQFilterApp


class SamGovSearchProTitleResultFilterApp(SamGovSearchProNaicsQFilterApp):
    """Final launcher target with title-only live result filtering.

    This does not change search behavior. It only changes the Filter Current
    Results box so it filters against the Title column only.
    """

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
                "Filters only the Title column of results already loaded in the table. "
                "Use plain text contains, or * and ? wildcards. Clearing this box restores all current results."
            ),
            wraplength=330,
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(5, 0))

    def _result_matches_filter(self, result: Any, filter_text: str) -> bool:
        pattern = str(filter_text or "").strip()
        if not pattern:
            return True

        title = str(getattr(result, "title", "") or "")
        title_folded = title.casefold()
        pattern_folded = pattern.casefold()

        if "*" in pattern_folded or "?" in pattern_folded:
            return fnmatch.fnmatchcase(title_folded, pattern_folded)

        return pattern_folded in title_folded

    def _set_results_status(self, prefix: str = "Ready") -> None:
        total = len(self.results)
        shown = len(getattr(self, "_visible_results", self.results))
        if getattr(self, "_active_result_filter", ""):
            self.status_var_text.set(
                f"{prefix}. Showing {shown} of {total} result(s) with Title filter: {self._active_result_filter}"
            )
        else:
            self.status_var_text.set(f"{prefix}. {total} result(s) found.")


def main() -> None:
    app = SamGovSearchProTitleResultFilterApp()
    app.mainloop()


if __name__ == "__main__":
    main()
