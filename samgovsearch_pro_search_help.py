from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass
from typing import Any, List, Optional
import tkinter as tk
from tkinter import ttk

from samgovsearch_pro_exclusions import SamGovSearchProExclusionsApp


@dataclass
class SearchToken:
    raw: str
    kind: str
    regex: Optional[re.Pattern[str]] = None

    @property
    def display(self) -> str:
        if self.kind == "regex":
            return f"regex:{self.raw}"
        if self.kind == "wildcard":
            return f"wildcard:{self.raw}"
        if self.kind == "exact":
            return f'"{self.raw}"'
        return self.raw


class HoverTip:
    """Small tooltip for Tkinter/ttk widgets."""

    def __init__(self, widget: tk.Widget, text: str, wraplength: int = 420) -> None:
        self.widget = widget
        self.text = text
        self.wraplength = wraplength
        self.tip_window: Optional[tk.Toplevel] = None
        widget.bind("<Enter>", self.show)
        widget.bind("<Leave>", self.hide)
        widget.bind("<ButtonPress>", self.hide)

    def show(self, _event: Any = None) -> None:
        if self.tip_window is not None:
            return
        x = self.widget.winfo_rootx() + 18
        y = self.widget.winfo_rooty() + 18
        window = tk.Toplevel(self.widget)
        window.wm_overrideredirect(True)
        window.wm_geometry(f"+{x}+{y}")
        label = ttk.Label(
            window,
            text=self.text,
            justify="left",
            padding=(8, 6),
            relief="solid",
            borderwidth=1,
            wraplength=self.wraplength,
        )
        label.pack()
        self.tip_window = window

    def hide(self, _event: Any = None) -> None:
        if self.tip_window is not None:
            self.tip_window.destroy()
            self.tip_window = None


class SamGovSearchProSearchHelpApp(SamGovSearchProExclusionsApp):
    """User-facing app with advanced local filter syntax and hover help."""

    FILTER_HELP_TEXT = (
        "Local filter syntax. These filters only search results already loaded in the table.\n\n"
        "plain text: patriot\n"
        "  Contains match, case insensitive.\n\n"
        "quoted phrase: \"patriot missile\"\n"
        "  Exact phrase match, including spaces.\n\n"
        "wildcards: W31P4Q* or *frequency?converter*\n"
        "  * matches any text, ? matches one character.\n\n"
        "regex: re:\\bPatriot\\b or /Patriot.*Spares/\n"
        "  Regular expression match, case insensitive.\n\n"
        "Show filter: space separated terms are AND logic.\n"
        "Hide filter: comma separated terms are OR logic, any match hides the row."
    )

    def __init__(self) -> None:
        self._exclude_search_tokens: List[SearchToken] = []
        self._show_search_tokens: List[SearchToken] = []
        super().__init__()

    def _add_result_filter_section(self, left_panel: ttk.Frame, row: int) -> None:
        filter_frame = ttk.LabelFrame(left_panel, text="Filter Current Results", padding=8)
        filter_frame.grid(row=row, column=0, sticky="ew", pady=(8, 0))
        filter_frame.columnconfigure(0, weight=1)

        self.result_filter_var = tk.StringVar(value="")
        show_label_row = ttk.Frame(filter_frame)
        show_label_row.grid(row=0, column=0, columnspan=2, sticky="ew")
        show_label_row.columnconfigure(0, weight=1)
        ttk.Label(show_label_row, text="Show results containing").grid(row=0, column=0, sticky="w")
        show_help = ttk.Label(show_label_row, text="?", width=2, anchor="center", cursor="question_arrow")
        show_help.grid(row=0, column=1, sticky="e")
        HoverTip(show_help, self.FILTER_HELP_TEXT)

        entry = ttk.Entry(filter_frame, textvariable=self.result_filter_var)
        entry.grid(row=1, column=0, sticky="ew", padx=(0, 4), pady=(2, 4))
        ttk.Button(filter_frame, text="Clear", command=self._clear_result_filter).grid(
            row=1, column=1, sticky="ew", pady=(2, 4)
        )
        self.result_filter_var.trace_add("write", lambda *_args: self._apply_result_filter())

        self.exclude_keywords_var = tk.StringVar(value="")
        hide_label_row = ttk.Frame(filter_frame)
        hide_label_row.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        hide_label_row.columnconfigure(0, weight=1)
        ttk.Label(hide_label_row, text="Hide results containing any of these comma-separated terms").grid(
            row=0, column=0, sticky="w"
        )
        hide_help = ttk.Label(hide_label_row, text="?", width=2, anchor="center", cursor="question_arrow")
        hide_help.grid(row=0, column=1, sticky="e")
        HoverTip(hide_help, self.FILTER_HELP_TEXT)

        exclude_entry = ttk.Entry(filter_frame, textvariable=self.exclude_keywords_var)
        exclude_entry.grid(row=3, column=0, sticky="ew", padx=(0, 4), pady=(2, 4))
        ttk.Button(filter_frame, text="Clear", command=self._clear_exclude_keywords).grid(
            row=3, column=1, sticky="ew", pady=(2, 4)
        )
        self.exclude_keywords_var.trace_add("write", lambda *_args: self._on_exclude_keywords_changed())

        ttk.Label(
            filter_frame,
            text=(
                "Local only. Use normal text, quoted exact phrases, * and ? wildcards, "
                "or regex with re:pattern or /pattern/. Hover over ? for examples."
            ),
            wraplength=330,
        ).grid(row=4, column=0, columnspan=2, sticky="w", pady=(5, 0))

    def _apply_result_filter(self) -> None:
        if not hasattr(self, "tree"):
            return
        self._active_result_filter = getattr(self, "result_filter_var", tk.StringVar(value="")).get().strip()
        self._show_search_tokens = self._parse_show_filter(self._active_result_filter)
        self._rebuild_result_tree()
        self._set_results_status(prefix="Filtered" if self._any_local_filter_active() else "Ready")

    def _on_exclude_keywords_changed(self) -> None:
        raw = getattr(self, "exclude_keywords_var", tk.StringVar(value="")).get()
        self._exclude_search_tokens = self._parse_hide_filter(raw)
        self._exclude_keyword_terms = [token.display.casefold() for token in self._exclude_search_tokens]
        if hasattr(self, "tree"):
            self._rebuild_result_tree()
            self._set_results_status(prefix="Filtered" if self._any_local_filter_active() else "Ready")

    def _clear_result_filter(self) -> None:
        self._show_search_tokens = []
        super()._clear_result_filter()

    def _clear_exclude_keywords(self) -> None:
        self._exclude_search_tokens = []
        super()._clear_exclude_keywords()

    def _result_matches_filter(self, result: Any, filter_text: str) -> bool:
        if not self._result_matches_show_tokens(result, filter_text):
            return False
        return not self._result_matches_exclude_keywords(result)

    def _result_matches_show_tokens(self, result: Any, filter_text: str) -> bool:
        if not filter_text.strip():
            return True
        tokens = self._show_search_tokens or self._parse_show_filter(filter_text)
        if not tokens:
            return True
        values = self._result_filter_values(result)
        haystack = " | ".join(value for value in values if value)
        return all(self._token_matches(token, values, haystack) for token in tokens)

    def _result_matches_exclude_keywords(self, result: Any) -> bool:
        tokens = getattr(self, "_exclude_search_tokens", [])
        if not tokens:
            return False
        values = self._result_filter_values(result)
        haystack = " | ".join(value for value in values if value)
        return any(self._token_matches(token, values, haystack) for token in tokens)

    def _set_results_status(self, prefix: str = "Ready") -> None:
        total = len(self.results)
        shown = len(getattr(self, "_visible_results", self.results))
        filters = []
        if getattr(self, "_active_result_filter", ""):
            show_label = " ".join(token.display for token in getattr(self, "_show_search_tokens", []))
            filters.append(f"show: {show_label or self._active_result_filter}")
        if getattr(self, "_attachment_name_filter_text", ""):
            filters.append(f"attachment: {self._attachment_name_filter_text}")
        if getattr(self, "_exclude_search_tokens", []):
            filters.append("hide: " + ", ".join(token.display for token in self._exclude_search_tokens))

        if filters:
            self.status_var_text.set(f"{prefix}. Showing {shown} of {total} result(s) for " + "; ".join(filters))
        else:
            self.status_var_text.set(f"{prefix}. {total} result(s) found.")

    @classmethod
    def _parse_show_filter(cls, raw: str) -> List[SearchToken]:
        return cls._dedupe_tokens(cls._parse_space_terms(raw))

    @classmethod
    def _parse_hide_filter(cls, raw: str) -> List[SearchToken]:
        tokens: List[SearchToken] = []
        for part in cls._split_commas_respecting_quotes(raw):
            tokens.extend(cls._parse_space_terms(part, comma_mode=True))
        return cls._dedupe_tokens(tokens)

    @classmethod
    def _parse_space_terms(cls, raw: str, comma_mode: bool = False) -> List[SearchToken]:
        tokens: List[SearchToken] = []
        i = 0
        length = len(raw)
        while i < length:
            while i < length and (raw[i].isspace() or (raw[i] == "," and not comma_mode)):
                i += 1
            if i >= length:
                break

            if raw[i] in {'"', "'"}:
                quote = raw[i]
                i += 1
                start = i
                while i < length and raw[i] != quote:
                    i += 1
                value = raw[start:i].strip()
                if i < length and raw[i] == quote:
                    i += 1
                if value:
                    tokens.append(cls._build_token(value, forced_kind="exact"))
                continue

            if raw[i] == "/":
                i += 1
                start = i
                escaped = False
                while i < length:
                    char = raw[i]
                    if char == "/" and not escaped:
                        break
                    escaped = char == "\\" and not escaped
                    if char != "\\":
                        escaped = False
                    i += 1
                value = raw[start:i].strip()
                if i < length and raw[i] == "/":
                    i += 1
                if value:
                    tokens.append(cls._build_token(value, forced_kind="regex"))
                continue

            start = i
            while i < length and not raw[i].isspace() and raw[i] != ",":
                i += 1
            value = raw[start:i].strip()
            if value:
                tokens.append(cls._build_token(value))

        return [token for token in tokens if token.raw]

    @staticmethod
    def _split_commas_respecting_quotes(raw: str) -> List[str]:
        parts: List[str] = []
        current: List[str] = []
        quote: Optional[str] = None
        slash_regex = False
        escaped = False
        for char in raw.replace("\n", ","):
            if slash_regex:
                current.append(char)
                if char == "/" and not escaped:
                    slash_regex = False
                escaped = char == "\\" and not escaped
                if char != "\\":
                    escaped = False
                continue
            if quote:
                current.append(char)
                if char == quote:
                    quote = None
                continue
            if char in {'"', "'"}:
                quote = char
                current.append(char)
                continue
            if char == "/":
                slash_regex = True
                current.append(char)
                continue
            if char == ",":
                parts.append("".join(current).strip())
                current = []
                continue
            current.append(char)
        parts.append("".join(current).strip())
        return parts

    @classmethod
    def _build_token(cls, raw: str, forced_kind: Optional[str] = None) -> SearchToken:
        value = raw.strip()
        kind = forced_kind or "plain"
        regex_obj: Optional[re.Pattern[str]] = None

        if forced_kind is None:
            lowered = value.casefold()
            if lowered.startswith("regex:"):
                value = value[6:].strip()
                kind = "regex"
            elif lowered.startswith("re:"):
                value = value[3:].strip()
                kind = "regex"
            elif "*" in value or "?" in value:
                kind = "wildcard"

        if kind == "regex":
            try:
                regex_obj = re.compile(value, re.IGNORECASE)
            except re.error:
                # Bad regex should not break the GUI. Fall back to plain text.
                kind = "plain"
                regex_obj = None

        return SearchToken(raw=value, kind=kind, regex=regex_obj)

    @staticmethod
    def _dedupe_tokens(tokens: List[SearchToken]) -> List[SearchToken]:
        cleaned: List[SearchToken] = []
        seen = set()
        for token in tokens:
            key = (token.kind, token.raw.casefold())
            if token.raw and key not in seen:
                cleaned.append(token)
                seen.add(key)
        return cleaned

    @staticmethod
    def _token_matches(token: SearchToken, values: List[str], haystack: str) -> bool:
        haystack_folded = haystack.casefold()
        raw_folded = token.raw.casefold()

        if token.kind == "regex" and token.regex is not None:
            return bool(token.regex.search(haystack))

        if token.kind == "wildcard":
            pattern = raw_folded
            return any(
                fnmatch.fnmatchcase(str(value or "").casefold(), pattern)
                for value in values
            ) or fnmatch.fnmatchcase(haystack_folded, pattern)

        # Plain and quoted exact phrase terms both use contains matching. Quoted
        # phrases stay together, so "patriot missile" is matched as that exact
        # phrase instead of as two independent words.
        return raw_folded in haystack_folded


def main() -> None:
    app = SamGovSearchProSearchHelpApp()
    app.mainloop()


if __name__ == "__main__":
    main()
