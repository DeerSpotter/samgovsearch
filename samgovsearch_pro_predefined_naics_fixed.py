from __future__ import annotations

from typing import Optional
import tkinter as tk
from tkinter import ttk

from samgovsearch_pro_predefined_naics import SamGovSearchProPredefinedNaicsApp


class SamGovSearchProPredefinedNaicsFixedApp(SamGovSearchProPredefinedNaicsApp):
    """Final launcher target with missing label-frame lookup helper restored."""

    def _find_labelframe_by_text(self, root: tk.Widget, text: str) -> Optional[ttk.LabelFrame]:
        for widget in self._walk_widgets(root):
            if isinstance(widget, ttk.LabelFrame) and self._widget_text(widget) == text:
                return widget
        return None


def main() -> None:
    app = SamGovSearchProPredefinedNaicsFixedApp()
    app.mainloop()


if __name__ == "__main__":
    main()
