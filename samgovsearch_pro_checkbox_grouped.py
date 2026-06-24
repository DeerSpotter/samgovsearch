from __future__ import annotations

from typing import Any, Iterable
import tkinter as tk
from tkinter import ttk

from samgovsearch_pro_initial_match_toggle import SamGovSearchProInitialMatchToggleApp


class SamGovSearchProCheckboxGroupedApp(SamGovSearchProInitialMatchToggleApp):
    """Final launcher target with main checkboxes grouped after filters."""

    def _build_left_panel(self, left_panel: ttk.Frame) -> None:
        super()._build_left_panel(left_panel)
        self._group_search_checkboxes_after_filters(left_panel)

    def _group_search_checkboxes_after_filters(self, left_panel: ttk.Frame) -> None:
        # Hide the scattered checkbox controls created by older UI layers. Their
        # variables and command methods are reused below so behavior is unchanged.
        self._hide_checkbutton_by_text(left_panel, "Search all date ranges")
        self._hide_checkbutton_by_text(left_panel, "Only show opportunities with attachments")
        self._hide_checkbutton_by_text(left_panel, "Search all statuses")
        self._hide_checkbutton_by_text(left_panel, "Ignore cached searches for this run")
        self._hide_checkbutton_by_text(left_panel, "Strictly validate returned results before showing them")

        # Hide explanatory labels tied to the old checkbox locations.
        self._hide_widget_containing_text(left_panel, "Status dropdown is ignored")
        self._hide_widget_containing_text(left_panel, "skips existing query and notice cache hits")
        self._hide_widget_containing_text(left_panel, "Off matches SAM.gov website behavior")

        # Hide old checkbox-only frames so the left panel does not show duplicate
        # sections lower down.
        self._hide_labelframe_by_text(left_panel, "Cache Options")
        self._hide_labelframe_by_text(left_panel, "Initial Result Matching")

        # Move sections that used to sit immediately after the SQLite filter down
        # below the grouped checkboxes.
        self._regrid_labelframe_by_text(left_panel, "Cache / Behavior", row=17)
        self._regrid_labelframe_by_text(left_panel, "Download Options", row=18)

        frame = ttk.LabelFrame(left_panel, text="Search Checkboxes", padding=8)
        frame.grid(row=16, column=0, sticky="ew", pady=(8, 0))
        frame.columnconfigure(0, weight=1)

        ttk.Checkbutton(
            frame,
            text="Search all date ranges",
            variable=self.all_date_ranges_var,
            command=self._toggle_date_controls,
        ).grid(row=0, column=0, sticky="w", pady=(0, 3))

        ttk.Checkbutton(
            frame,
            text="Only show opportunities with attachments",
            variable=self.require_attachments_var,
            command=self._toggle_attachment_controls,
        ).grid(row=1, column=0, sticky="w", pady=3)

        ttk.Checkbutton(
            frame,
            text="Search all statuses",
            variable=self.all_statuses_var,
            command=self._toggle_status_controls,
        ).grid(row=2, column=0, sticky="w", pady=3)

        ttk.Checkbutton(
            frame,
            text="Ignore cached searches for this run",
            variable=self.ignore_cached_searches_var,
        ).grid(row=3, column=0, sticky="w", pady=3)

        ttk.Checkbutton(
            frame,
            text="Strictly validate returned results before showing them",
            variable=self.strict_initial_match_var,
        ).grid(row=4, column=0, sticky="w", pady=(3, 0))

        ttk.Label(
            frame,
            text=(
                "Grouped here so all run-changing toggles are directly below the result filters. "
                "Strict initial matching is off by default so searches behave like SAM.gov unless enabled."
            ),
            wraplength=330,
        ).grid(row=5, column=0, sticky="w", pady=(6, 0))

    def _walk_widgets(self, root: tk.Widget) -> Iterable[tk.Widget]:
        pending = list(root.winfo_children())
        while pending:
            widget = pending.pop(0)
            yield widget
            pending.extend(widget.winfo_children())

    def _widget_text(self, widget: tk.Widget) -> str:
        try:
            return str(widget.cget("text") or "")
        except Exception:
            return ""

    def _hide_checkbutton_by_text(self, root: tk.Widget, text: str) -> None:
        for widget in self._walk_widgets(root):
            if isinstance(widget, ttk.Checkbutton) and self._widget_text(widget) == text:
                try:
                    widget.grid_remove()
                except Exception:
                    pass

    def _hide_widget_containing_text(self, root: tk.Widget, text: str) -> None:
        needle = text.casefold()
        for widget in self._walk_widgets(root):
            value = self._widget_text(widget)
            if value and needle in value.casefold():
                try:
                    widget.grid_remove()
                except Exception:
                    pass

    def _hide_labelframe_by_text(self, root: tk.Widget, text: str) -> None:
        for widget in self._walk_widgets(root):
            if isinstance(widget, ttk.LabelFrame) and self._widget_text(widget) == text:
                try:
                    widget.grid_remove()
                except Exception:
                    pass

    def _regrid_labelframe_by_text(self, root: tk.Widget, text: str, row: int) -> None:
        for widget in self._walk_widgets(root):
            if isinstance(widget, ttk.LabelFrame) and self._widget_text(widget) == text:
                try:
                    widget.grid_configure(row=row, column=0, sticky="ew", pady=(8, 0))
                except Exception:
                    pass


def main() -> None:
    app = SamGovSearchProCheckboxGroupedApp()
    app.mainloop()


if __name__ == "__main__":
    main()
