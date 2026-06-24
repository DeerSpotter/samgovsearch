from __future__ import annotations

import os
import subprocess
import sys
import webbrowser
from datetime import date
from typing import Any, Callable, Dict
import tkinter as tk
from tkinter import messagebox, ttk

import samgovsearch_unified as unified

SAM_ACCOUNT_DETAILS_URL = "https://sam.gov/profile/details"
SAM_API_DOCS_URL = "https://open.gsa.gov/api/get-opportunities-public-api/"


class SamGovSearchApp(unified.UnifiedSamGovSearchApp):
    """Final user-facing SAM.gov Search UI.

    Adds user settings for SAM_API_KEY and click-to-sort result columns while
    keeping the unified internal/API/hybrid search behavior in one app.
    """

    def _build_ui(self) -> None:
        super()._build_ui()
        self._sort_reverse_by_column: Dict[str, bool] = {}
        self._last_sorted_column = ""
        self._install_sortable_headings()
        self._add_settings_button()

    def _add_settings_button(self) -> None:
        left_panel = self.grid_slaves(row=0, column=0)[0]
        settings_frame = ttk.LabelFrame(left_panel, text="Settings", padding=8)
        settings_frame.grid(row=12, column=0, sticky="ew", pady=(8, 0))
        settings_frame.columnconfigure(0, weight=1)

        ttk.Button(
            settings_frame,
            text="Settings / SAM_API_KEY",
            command=self.open_settings_dialog,
        ).grid(row=0, column=0, sticky="ew")

        ttk.Label(
            settings_frame,
            text="Use this to paste a SAM.gov API key into the user environment variable.",
            wraplength=360,
        ).grid(row=1, column=0, sticky="w", pady=(5, 0))

    def open_settings_dialog(self) -> None:
        dialog = tk.Toplevel(self)
        dialog.title("SAM.gov Search Settings")
        dialog.transient(self)
        dialog.resizable(False, False)
        dialog.columnconfigure(0, weight=1)

        frame = ttk.Frame(dialog, padding=12)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text="SAM_API_KEY").grid(row=0, column=0, sticky="w", pady=(0, 4))
        key_var = tk.StringVar(value=os.environ.get("SAM_API_KEY", ""))
        key_entry = ttk.Entry(frame, textvariable=key_var, width=56, show="*")
        key_entry.grid(row=0, column=1, sticky="ew", pady=(0, 4))
        key_entry.focus_set()

        show_var = tk.BooleanVar(value=False)

        def toggle_show_key() -> None:
            key_entry.configure(show="" if show_var.get() else "*")

        ttk.Checkbutton(
            frame,
            text="Show key",
            variable=show_var,
            command=toggle_show_key,
        ).grid(row=1, column=1, sticky="w", pady=(0, 8))

        status_var = tk.StringVar(value=self._api_key_status_text())
        ttk.Label(frame, textvariable=status_var, wraplength=480).grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(0, 8)
        )

        help_text = (
            "SAM.gov requires you to generate or view the public API key inside "
            "your signed-in SAM.gov account. The app can save a key you paste here, "
            "but it cannot generate the key for you because SAM.gov requires account "
            "login and password confirmation."
        )
        ttk.Label(frame, text=help_text, wraplength=520).grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(0, 10)
        )

        button_frame = ttk.Frame(frame)
        button_frame.grid(row=4, column=0, columnspan=2, sticky="ew")
        for column in range(4):
            button_frame.columnconfigure(column, weight=1)

        def save_key() -> None:
            key = key_var.get().strip()
            if not key:
                messagebox.showerror("Missing API Key", "Paste a SAM.gov API key before saving.", parent=dialog)
                return

            try:
                self._save_api_key_to_environment(key)
            except Exception as exc:
                messagebox.showerror("Save Failed", str(exc), parent=dialog)
                return

            status_var.set(self._api_key_status_text())
            self._toggle_source_controls()
            messagebox.showinfo(
                "API Key Saved",
                "SAM_API_KEY was saved to the user environment variable and is active in this app now.\n\n"
                "Already-open terminals may not see the updated value until they are reopened.",
                parent=dialog,
            )

        ttk.Button(button_frame, text="Save Key", command=save_key).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ttk.Button(
            button_frame,
            text="Open SAM Account",
            command=lambda: webbrowser.open(SAM_ACCOUNT_DETAILS_URL),
        ).grid(row=0, column=1, sticky="ew", padx=4)
        ttk.Button(
            button_frame,
            text="Open API Docs",
            command=lambda: webbrowser.open(SAM_API_DOCS_URL),
        ).grid(row=0, column=2, sticky="ew", padx=4)
        ttk.Button(button_frame, text="Close", command=dialog.destroy).grid(row=0, column=3, sticky="ew", padx=(4, 0))

        dialog.bind("<Return>", lambda _event: save_key())
        dialog.bind("<Escape>", lambda _event: dialog.destroy())
        dialog.grab_set()

    def _api_key_status_text(self) -> str:
        key = os.environ.get("SAM_API_KEY", "").strip()
        if key:
            return f"SAM_API_KEY is set. Length: {len(key)} character(s)."
        return "SAM_API_KEY is not set. Website/Internal Search still works without it."

    def _save_api_key_to_environment(self, key: str) -> None:
        os.environ["SAM_API_KEY"] = key

        if os.name == "nt":
            completed = subprocess.run(
                ["setx", "SAM_API_KEY", key],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout or "Unknown setx error.").strip()
                raise RuntimeError(f"Could not save SAM_API_KEY using setx.\n\n{detail}")
            return

        raise RuntimeError(
            "SAM_API_KEY was applied to this running app, but automatic persistent environment writes "
            "are currently implemented for Windows only. Add SAM_API_KEY to your shell profile for future launches."
        )

    def _install_sortable_headings(self) -> None:
        if not hasattr(self, "tree"):
            return
        for column in self.tree["columns"]:
            self.tree.heading(
                column,
                text=column,
                command=lambda selected_column=column: self._sort_results_by_column(selected_column),
            )

    def _sort_results_by_column(self, column: str) -> None:
        if not self.results:
            return

        if self._last_sorted_column == column:
            reverse = not self._sort_reverse_by_column.get(column, False)
        else:
            reverse = False

        self._last_sorted_column = column
        self._sort_reverse_by_column[column] = reverse
        self.results.sort(key=lambda result: self._sort_key_for_result(result, column), reverse=reverse)
        self._rebuild_result_tree()
        self._refresh_sort_headings(column, reverse)
        self.status_var_text.set(
            f"Sorted {len(self.results)} result(s) by {column} {'descending' if reverse else 'ascending'}."
        )

    def _refresh_sort_headings(self, active_column: str, reverse: bool) -> None:
        for column in self.tree["columns"]:
            label = column
            if column == active_column:
                label = f"{column} {'▼' if reverse else '▲'}"
            self.tree.heading(
                column,
                text=label,
                command=lambda selected_column=column: self._sort_results_by_column(selected_column),
            )

    def _sort_key_for_result(self, result: Any, column: str) -> Any:
        if column == "Keyword":
            return self._text_key(result.keyword)
        if column == "Matched By":
            return self._text_key(result.matched_by)
        if column == "Posted":
            parsed = unified.parse_date_any(result.posted_date)
            return parsed.toordinal() if parsed is not None else -1
        if column == "Type":
            return self._text_key(result.notice_type)
        if column == "Solicitation":
            return self._text_key(result.solicitation_number)
        if column == "Title":
            return self._text_key(result.title)
        if column == "Attachments":
            return int(result.attachment_count or 0)
        if column == "Size MB":
            return float(result.attachment_total_mb) if result.attachment_total_mb is not None else -1.0
        if column == "Notice ID":
            return self._text_key(result.notice_id)
        if column == "SAM Link":
            return self._text_key(result.ui_link)
        return ""

    @staticmethod
    def _text_key(value: Any) -> str:
        return str(value or "").casefold()

    def _rebuild_result_tree(self) -> None:
        for row_id in self.tree.get_children():
            self.tree.delete(row_id)

        for result in self.results:
            size_text = "" if result.attachment_total_mb is None else f"{result.attachment_total_mb:.2f}"
            self.tree.insert(
                "",
                "end",
                values=[
                    result.keyword,
                    result.matched_by,
                    result.posted_date,
                    result.notice_type,
                    result.solicitation_number,
                    result.title,
                    result.attachment_count,
                    size_text,
                    result.notice_id,
                    result.ui_link,
                ],
            )

        self.export_button.configure(state="normal" if self.results else "disabled")


def main() -> None:
    app = SamGovSearchApp()
    app.mainloop()


if __name__ == "__main__":
    main()
