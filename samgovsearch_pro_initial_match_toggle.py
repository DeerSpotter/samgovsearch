from __future__ import annotations

from typing import Any
import tkinter as tk
from tkinter import ttk

from samgovsearch_pro_attachment_filter_live import SamGovSearchProAttachmentFilterLiveApp
from samgovsearch_pro_initial_match import SamGovSearchProInitialMatchApp


class SamGovSearchProInitialMatchToggleApp(SamGovSearchProAttachmentFilterLiveApp):
    """Final launcher target with optional strict initial matching.

    SAM.gov website/internal search is intentionally broad. Strict local initial
    validation is useful when the user really wants exact phrase, wildcard, or
    regex enforcement before rows appear, but it can hide legitimate SAM.gov
    website results. Therefore it is controlled by a checkbox and defaults off.
    """

    def __init__(self) -> None:
        self.strict_initial_match_var: tk.BooleanVar | None = None
        self._strict_initial_match_current = False
        self._strict_initial_match_log_emitted = False
        super().__init__()

    def _build_left_panel(self, left_panel: ttk.Frame) -> None:
        super()._build_left_panel(left_panel)
        self._add_initial_match_section(left_panel, row=19)

    def _add_initial_match_section(self, left_panel: ttk.Frame, row: int) -> None:
        frame = ttk.LabelFrame(left_panel, text="Initial Result Matching", padding=8)
        frame.grid(row=row, column=0, sticky="ew", pady=(8, 0))
        frame.columnconfigure(0, weight=1)

        self.strict_initial_match_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            frame,
            text="Strictly validate returned results before showing them",
            variable=self.strict_initial_match_var,
        ).grid(row=0, column=0, sticky="w")

        ttk.Label(
            frame,
            text=(
                "Off matches SAM.gov website behavior and shows broad returned results immediately. "
                "On enforces the batch keyword syntax locally before rows are shown. Use On for exact quoted "
                "phrases, wildcards, or regex when you want the table to reject broad SAM.gov matches."
            ),
            wraplength=330,
        ).grid(row=1, column=0, sticky="w", pady=(5, 0))

    def start_search(self) -> None:
        var = getattr(self, "strict_initial_match_var", None)
        self._strict_initial_match_current = bool(var.get()) if var is not None else False
        self._strict_initial_match_log_emitted = False
        super().start_search()

    def _strict_initial_matching_enabled(self) -> bool:
        return bool(getattr(self, "_strict_initial_match_current", False))

    def _add_result(self, result: Any) -> None:
        if self._strict_initial_matching_enabled():
            super()._add_result(result)
            return

        if not self._strict_initial_match_log_emitted:
            self._strict_initial_match_log_emitted = True
            try:
                self._log("Initial strict match validation is off. Showing SAM.gov broad returned results.")
            except Exception:
                pass

        # Skip only SamGovSearchProInitialMatchApp._add_result. Continue with
        # the rest of the app's normal result-add pipeline: filtering, indexing,
        # enrichment, download button updates, etc.
        super(SamGovSearchProInitialMatchApp, self)._add_result(result)


def main() -> None:
    app = SamGovSearchProInitialMatchToggleApp()
    app.mainloop()


if __name__ == "__main__":
    main()
