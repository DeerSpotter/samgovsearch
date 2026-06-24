from __future__ import annotations

from typing import Any, Iterable
import tkinter as tk
from tkinter import ttk

import samgovsearch as base
from samgovsearch_pro_checkbox_grouped import SamGovSearchProCheckboxGroupedApp


class SamGovSearchProCheckboxFieldStatesApp(SamGovSearchProCheckboxGroupedApp):
    """Final launcher target with checkbox-affected fields blanked and disabled.

    When a checkbox overrides a field, the field is visibly blank and greyed out
    so the UI matches what the search code will actually send.
    """

    def __init__(self) -> None:
        self._manual_posted_from_cache = ""
        self._manual_posted_to_cache = ""
        self._manual_status_cache = ""
        super().__init__()

    def _toggle_date_controls(self) -> None:
        checked = bool(getattr(self, "all_date_ranges_var", tk.BooleanVar(value=False)).get())
        from_entry = getattr(self, "posted_from_entry", None)
        to_entry = getattr(self, "posted_to_entry", None)
        from_var = getattr(self, "posted_from_var", None)
        to_var = getattr(self, "posted_to_var", None)

        if checked:
            if from_var is not None and str(from_var.get()).strip():
                self._manual_posted_from_cache = from_var.get()
            if to_var is not None and str(to_var.get()).strip():
                self._manual_posted_to_cache = to_var.get()
            if from_var is not None:
                from_var.set("")
            if to_var is not None:
                to_var.set("")
            self._configure_widget_state(from_entry, "disabled")
            self._configure_widget_state(to_entry, "disabled")
            return

        default_from, default_to = base.default_posted_dates()
        if from_var is not None and not str(from_var.get()).strip():
            from_var.set(self._manual_posted_from_cache or default_from)
        if to_var is not None and not str(to_var.get()).strip():
            to_var.set(self._manual_posted_to_cache or default_to)
        self._configure_widget_state(from_entry, "normal")
        self._configure_widget_state(to_entry, "normal")

    def _toggle_status_controls(self) -> None:
        checked = bool(getattr(self, "all_statuses_var", tk.BooleanVar(value=False)).get())
        combo = getattr(self, "status_combo", None)
        status_var = getattr(self, "status_var", None)

        if checked:
            if status_var is not None and str(status_var.get()).strip():
                self._manual_status_cache = status_var.get()
            if status_var is not None:
                status_var.set("")
            self._configure_widget_state(combo, "disabled")
            return

        if status_var is not None and not str(status_var.get()).strip():
            status_var.set(self._manual_status_cache or base.DEFAULT_STATUS)
        self._configure_widget_state(combo, "readonly")

    def _toggle_attachment_controls(self) -> None:
        checked = bool(getattr(self, "require_attachments_var", tk.BooleanVar(value=False)).get())
        frame = getattr(self, "attachment_frame", None)
        if frame is None:
            return

        # Keep the affected fields visible so users can see why they are inactive.
        try:
            frame.grid(row=5, column=0, sticky="ew", pady=(0, 8))
        except Exception:
            pass

        state = "normal" if checked else "disabled"
        if not checked:
            min_count_var = getattr(self, "min_attachment_count_var", None)
            min_size_var = getattr(self, "min_total_size_var", None)
            if min_count_var is not None:
                min_count_var.set("")
            if min_size_var is not None:
                min_size_var.set("")

        for widget in self._walk_widgets(frame):
            if isinstance(widget, ttk.Entry):
                self._configure_widget_state(widget, state)

    def _configure_widget_state(self, widget: Any, state: str) -> None:
        if widget is None:
            return
        try:
            widget.configure(state=state)
        except Exception:
            pass

    def _walk_widgets(self, root: tk.Widget) -> Iterable[tk.Widget]:
        pending = list(root.winfo_children())
        while pending:
            widget = pending.pop(0)
            yield widget
            pending.extend(widget.winfo_children())


def main() -> None:
    app = SamGovSearchProCheckboxFieldStatesApp()
    app.mainloop()


if __name__ == "__main__":
    main()
