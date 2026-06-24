from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Optional

import samgovsearch as base

# SAM.gov rejects date windows that are exactly one calendar year apart.
# Keep every generated request safely under that boundary.
base.MAX_POSTED_DATE_WINDOW_DAYS = 364


class SamGovSearchAllStatusApp(base.SamGovSearchApp):
    """Small extension layer that adds an all-status checkbox to the base GUI."""

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
            text="When checked, the Status dropdown is ignored and no status filter is sent to SAM.gov.",
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


def main() -> None:
    app = SamGovSearchAllStatusApp()
    app.mainloop()


if __name__ == "__main__":
    main()
