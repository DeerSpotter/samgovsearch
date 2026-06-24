from __future__ import annotations

import os
from typing import Any, Dict
import tkinter as tk
from tkinter import ttk

import samgovsearch_app as final_app
import samgovsearch_unified as unified


class ResponsiveSamGovSearchApp(final_app.SamGovSearchApp):
    """Responsive one-window SAM.gov Search UI.

    This class keeps the existing search, cache, settings, sorting, and download
    behavior, but rebuilds the window with a scrollable options panel and a
    resizable results area so controls are not cut off when the window is not
    maximized.
    """

    def _build_ui(self) -> None:
        self.geometry("1220x760")
        self.minsize(760, 520)

        self._sort_reverse_by_column: Dict[str, bool] = {}
        self._last_sorted_column = ""

        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        paned = ttk.Panedwindow(self, orient="horizontal")
        paned.grid(row=0, column=0, sticky="nsew")

        left_shell = ttk.Frame(paned)
        right = ttk.Frame(paned, padding=(8, 10, 10, 10))
        paned.add(left_shell, weight=0)
        paned.add(right, weight=1)

        left_shell.rowconfigure(0, weight=1)
        left_shell.columnconfigure(0, weight=1)
        left_panel = self._create_scrollable_left_panel(left_shell)
        left_panel.columnconfigure(0, weight=1)

        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)

        self._build_left_panel(left_panel)
        self._build_right_panel(right)

        self._toggle_date_controls()
        self._toggle_attachment_controls()
        self._toggle_status_controls()
        self._toggle_source_controls()
        self._install_sortable_headings()
        self._update_download_button_state()

    def _build_left_panel(self, left_panel: ttk.Frame) -> None:
        api_key = os.environ.get("SAM_API_KEY", "").strip()
        key_status = "SAM_API_KEY found" if api_key else "SAM_API_KEY not found"
        self.api_key_label = ttk.Label(left_panel, text=key_status)
        self.api_key_label.grid(row=0, column=0, sticky="w", pady=(0, 8))

        ttk.Label(left_panel, text="Batch keywords, part numbers, solicitation numbers").grid(
            row=1, column=0, sticky="w"
        )
        self.keyword_text = tk.Text(left_panel, width=36, height=8, wrap="word")
        self.keyword_text.grid(row=2, column=0, sticky="ew", pady=(3, 8))
        self.keyword_text.insert("1.0", "Patriot\nfrequency converter\nK0357NC200461-0001")

        form = ttk.LabelFrame(left_panel, text="SAM.gov Search Options", padding=8)
        form.grid(row=3, column=0, sticky="ew", pady=(0, 8))
        form.columnconfigure(1, weight=1)

        posted_from, posted_to = unified.base.default_posted_dates()

        ttk.Label(form, text="Posted From").grid(row=0, column=0, sticky="w")
        self.posted_from_var = tk.StringVar(value=posted_from)
        self.posted_from_entry = ttk.Entry(form, textvariable=self.posted_from_var, width=18)
        self.posted_from_entry.grid(row=0, column=1, sticky="ew", padx=(8, 0), pady=2)

        ttk.Label(form, text="Posted To").grid(row=1, column=0, sticky="w")
        self.posted_to_var = tk.StringVar(value=posted_to)
        self.posted_to_entry = ttk.Entry(form, textvariable=self.posted_to_var, width=18)
        self.posted_to_entry.grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=2)

        self.all_date_ranges_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            form,
            text="Search all date ranges",
            variable=self.all_date_ranges_var,
            command=self._toggle_date_controls,
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(2, 6))

        ttk.Label(form, text="Status").grid(row=3, column=0, sticky="w")
        self.status_var = tk.StringVar(value=unified.base.DEFAULT_STATUS)
        self.status_combo = ttk.Combobox(
            form,
            textvariable=self.status_var,
            values=["", "active", "inactive", "archived", "cancelled", "deleted"],
            state="readonly",
            width=18,
        )
        self.status_combo.grid(row=3, column=1, sticky="ew", padx=(8, 0), pady=2)

        ttk.Label(form, text="Procurement Type").grid(row=4, column=0, sticky="w")
        self.ptype_var = tk.StringVar(value="")
        ttk.Combobox(
            form,
            textvariable=self.ptype_var,
            values=[
                "",
                "o Solicitation",
                "k Combined Synopsis/Solicitation",
                "r Sources Sought",
                "p Presolicitation",
                "s Special Notice",
                "a Award Notice",
                "u Justification",
                "g Sale of Surplus Property",
                "i Intent to Bundle Requirements",
            ],
            state="readonly",
            width=28,
        ).grid(row=4, column=1, sticky="ew", padx=(8, 0), pady=2)

        ttk.Label(form, text="Search Mode").grid(row=5, column=0, sticky="w")
        self.search_mode_var = tk.StringVar(value="Auto")
        ttk.Combobox(
            form,
            textvariable=self.search_mode_var,
            values=[
                "Auto",
                "Title",
                "Solicitation Number",
                "Notice ID",
                "Title + Solicitation Number",
            ],
            state="readonly",
            width=28,
        ).grid(row=5, column=1, sticky="ew", padx=(8, 0), pady=2)

        ttk.Label(form, text="Max Results / Search").grid(row=6, column=0, sticky="w")
        self.max_results_var = tk.StringVar(value=str(unified.base.DEFAULT_MAX_RESULTS_PER_SEARCH))
        ttk.Entry(form, textvariable=self.max_results_var, width=18).grid(
            row=6, column=1, sticky="ew", padx=(8, 0), pady=2
        )

        ttk.Label(form, text="Timeout Seconds").grid(row=7, column=0, sticky="w")
        self.timeout_var = tk.StringVar(value=str(unified.base.DEFAULT_TIMEOUT_SECONDS))
        ttk.Entry(form, textvariable=self.timeout_var, width=18).grid(
            row=7, column=1, sticky="ew", padx=(8, 0), pady=2
        )

        self.require_attachments_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            left_panel,
            text="Only show opportunities with attachments",
            variable=self.require_attachments_var,
            command=self._toggle_attachment_controls,
        ).grid(row=4, column=0, sticky="w", pady=(0, 6))

        self.attachment_frame = ttk.LabelFrame(left_panel, text="Attachment Filters", padding=8)
        self.attachment_frame.columnconfigure(1, weight=1)

        ttk.Label(self.attachment_frame, text="Minimum Attachment Count").grid(row=0, column=0, sticky="w")
        self.min_attachment_count_var = tk.StringVar(value="")
        ttk.Entry(self.attachment_frame, textvariable=self.min_attachment_count_var, width=18).grid(
            row=0, column=1, sticky="ew", padx=(8, 0), pady=2
        )

        ttk.Label(self.attachment_frame, text="Minimum Total Size MB").grid(row=1, column=0, sticky="w")
        self.min_total_size_var = tk.StringVar(value="")
        ttk.Entry(self.attachment_frame, textvariable=self.min_total_size_var, width=18).grid(
            row=1, column=1, sticky="ew", padx=(8, 0), pady=2
        )

        ttk.Label(
            self.attachment_frame,
            text="Defaults when blank: count = 1, size = 0 MB.",
            wraplength=320,
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(4, 0))

        self.button_frame = ttk.LabelFrame(left_panel, text="Search / Export", padding=8)
        self.button_frame.grid(row=6, column=0, sticky="ew", pady=(4, 0))
        self.button_frame.columnconfigure(0, weight=1)
        self.button_frame.columnconfigure(1, weight=1)

        self.search_button = ttk.Button(self.button_frame, text="Search", command=self.start_search)
        self.search_button.grid(row=0, column=0, sticky="ew", padx=(0, 4))

        self.stop_button = ttk.Button(self.button_frame, text="Stop", command=self.stop_search, state="disabled")
        self.stop_button.grid(row=0, column=1, sticky="ew", padx=(4, 0))

        self.export_button = ttk.Button(
            self.button_frame,
            text="Export Results to CSV",
            command=self.export_csv,
            state="disabled",
        )
        self.export_button.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))

        ttk.Label(
            left_panel,
            text=(
                "Dates must be MM/DD/YYYY. Search all date ranges searches "
                "01/01/2018 through today in 364-day windows."
            ),
            wraplength=340,
        ).grid(row=7, column=0, sticky="w", pady=(8, 0))

        self.all_statuses_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            left_panel,
            text="Search all statuses",
            variable=self.all_statuses_var,
            command=self._toggle_status_controls,
        ).grid(row=8, column=0, sticky="w", pady=(8, 0))

        ttk.Label(
            left_panel,
            text=(
                "When checked, the Status dropdown is ignored and no status filter is sent. "
                "All-date searches are throttled to reduce rate-limit errors."
            ),
            wraplength=340,
        ).grid(row=9, column=0, sticky="w", pady=(2, 0))

        self.search_source_var = tk.StringVar(value=unified.SOURCE_INTERNAL)
        source_frame = ttk.LabelFrame(left_panel, text="Search Source", padding=8)
        source_frame.grid(row=10, column=0, sticky="ew", pady=(8, 0))
        source_frame.columnconfigure(0, weight=1)

        self.search_source_combo = ttk.Combobox(
            source_frame,
            textvariable=self.search_source_var,
            values=[unified.SOURCE_INTERNAL, unified.SOURCE_OFFICIAL, unified.SOURCE_HYBRID],
            state="readonly",
            width=34,
        )
        self.search_source_combo.grid(row=0, column=0, sticky="ew")
        self.search_source_combo.bind("<<ComboboxSelected>>", lambda _event: self._toggle_source_controls())

        self.search_source_note_var = tk.StringVar()
        ttk.Label(source_frame, textvariable=self.search_source_note_var, wraplength=330).grid(
            row=1, column=0, sticky="w", pady=(5, 0)
        )

        self._add_settings_section(left_panel, row=11)
        self._add_download_section(left_panel, row=12)

    def _build_right_panel(self, right: ttk.Frame) -> None:
        summary = ttk.Frame(right)
        summary.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        summary.columnconfigure(0, weight=1)

        self.status_var_text = tk.StringVar(value="Ready.")
        ttk.Label(summary, textvariable=self.status_var_text).grid(row=0, column=0, sticky="w")

        self.progress = ttk.Progressbar(summary, mode="indeterminate")
        self.progress.grid(row=1, column=0, sticky="ew", pady=(6, 0))

        columns = [
            "Keyword",
            "Matched By",
            "Posted",
            "Type",
            "Solicitation",
            "Title",
            "Attachments",
            "Size MB",
            "Notice ID",
            "SAM Link",
        ]

        self.tree = ttk.Treeview(right, columns=columns, show="headings", selectmode="browse")
        self.tree.grid(row=1, column=0, sticky="nsew")

        widths = {
            "Keyword": 120,
            "Matched By": 90,
            "Posted": 90,
            "Type": 165,
            "Solicitation": 140,
            "Title": 380,
            "Attachments": 90,
            "Size MB": 80,
            "Notice ID": 220,
            "SAM Link": 240,
        }

        for column in columns:
            self.tree.heading(column, text=column)
            self.tree.column(column, width=widths[column], minwidth=60, anchor="w", stretch=True)

        self.tree.bind("<Double-1>", self.open_selected_link)
        self.tree.bind("<<TreeviewSelect>>", lambda _event: self._update_download_button_state())

        yscroll = ttk.Scrollbar(right, orient="vertical", command=self.tree.yview)
        yscroll.grid(row=1, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=yscroll.set)

        xscroll = ttk.Scrollbar(right, orient="horizontal", command=self.tree.xview)
        xscroll.grid(row=2, column=0, sticky="ew")
        self.tree.configure(xscrollcommand=xscroll.set)

        log_frame = ttk.LabelFrame(right, text="Log", padding=6)
        log_frame.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        log_frame.columnconfigure(0, weight=1)

        self.log_text = tk.Text(log_frame, height=6, wrap="word")
        self.log_text.grid(row=0, column=0, sticky="ew")
        self.log_text.configure(state="disabled")

    def _create_scrollable_left_panel(self, parent: ttk.Frame) -> ttk.Frame:
        canvas = tk.Canvas(parent, width=390, highlightthickness=0, borderwidth=0)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas, padding=10)

        window_id = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        def update_scroll_region(_event: Any = None) -> None:
            canvas.configure(scrollregion=canvas.bbox("all"))

        def update_inner_width(event: Any) -> None:
            canvas.itemconfigure(window_id, width=event.width)

        inner.bind("<Configure>", update_scroll_region)
        canvas.bind("<Configure>", update_inner_width)
        self._bind_mousewheel_to_canvas(canvas)
        return inner

    def _bind_mousewheel_to_canvas(self, canvas: tk.Canvas) -> None:
        def on_mousewheel(event: Any) -> None:
            if getattr(event, "num", None) == 4:
                canvas.yview_scroll(-3, "units")
            elif getattr(event, "num", None) == 5:
                canvas.yview_scroll(3, "units")
            else:
                delta = int(-1 * (event.delta / 120)) if getattr(event, "delta", 0) else 0
                if delta:
                    canvas.yview_scroll(delta, "units")

        def bind_scroll(_event: Any) -> None:
            canvas.bind_all("<MouseWheel>", on_mousewheel)
            canvas.bind_all("<Button-4>", on_mousewheel)
            canvas.bind_all("<Button-5>", on_mousewheel)

        def unbind_scroll(_event: Any) -> None:
            canvas.unbind_all("<MouseWheel>")
            canvas.unbind_all("<Button-4>")
            canvas.unbind_all("<Button-5>")

        canvas.bind("<Enter>", bind_scroll)
        canvas.bind("<Leave>", unbind_scroll)

    def _add_settings_section(self, left_panel: ttk.Frame, row: int) -> None:
        settings_frame = ttk.LabelFrame(left_panel, text="Settings", padding=8)
        settings_frame.grid(row=row, column=0, sticky="ew", pady=(8, 0))
        settings_frame.columnconfigure(0, weight=1)

        ttk.Button(
            settings_frame,
            text="Settings / SAM_API_KEY",
            command=self.open_settings_dialog,
        ).grid(row=0, column=0, sticky="ew")

        ttk.Label(
            settings_frame,
            text="Paste a SAM.gov API key into the Windows user environment variable.",
            wraplength=330,
        ).grid(row=1, column=0, sticky="w", pady=(5, 0))

    def _add_download_section(self, left_panel: ttk.Frame, row: int) -> None:
        download_frame = ttk.LabelFrame(left_panel, text="Attachments", padding=8)
        download_frame.grid(row=row, column=0, sticky="ew", pady=(8, 0))
        download_frame.columnconfigure(0, weight=1)

        self.download_attachments_button = ttk.Button(
            download_frame,
            text="Download Attachments for Selected Result",
            command=self.download_selected_attachments,
            state="disabled",
        )
        self.download_attachments_button.grid(row=0, column=0, sticky="ew")

        ttk.Label(
            download_frame,
            text=(
                "Select one result row, then download its known public attachments. "
                "Internal and Hybrid modes usually include attachment names and sizes."
            ),
            wraplength=330,
        ).grid(row=1, column=0, sticky="w", pady=(5, 0))


def main() -> None:
    app = ResponsiveSamGovSearchApp()
    app.mainloop()


if __name__ == "__main__":
    main()
