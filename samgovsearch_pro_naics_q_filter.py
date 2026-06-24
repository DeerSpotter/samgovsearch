from __future__ import annotations

import re
from typing import Any, Iterable, List
import tkinter as tk

import samgovsearch as base
from samgovsearch_pro_naics_validated import SamGovSearchProNaicsValidatedApp


class SamGovSearchProNaicsQFilterApp(SamGovSearchProNaicsValidatedApp):
    """Final launcher target for NAICS-as-query searching.

    Normal behavior is unchanged unless Search predefined NAICS numbers is checked.
    When checked, SAM.gov is searched with the predefined NAICS codes as the actual
    search terms because that matches the website behavior the user confirmed.
    The main batch keyword box then becomes a local text filter on those NAICS
    results. If the batch box is blank, all NAICS-code search results are shown.
    """

    def _read_settings(self) -> base.SearchSettings:
        if not self._use_predefined_naics_enabled():
            return super()._read_settings()

        codes = self._interested_naics_codes()
        if not codes:
            raise ValueError("Search predefined NAICS numbers is checked, but no valid 6 digit NAICS codes were found.")
        self._validate_naics_codes(codes)

        local_terms, raw_count, duplicate_count = base.parse_batch_terms(self.keyword_text.get("1.0", "end"))

        max_results = base.parse_int(self.max_results_var.get(), base.DEFAULT_MAX_RESULTS_PER_SEARCH, 1, 100000)
        timeout = base.parse_int(self.timeout_var.get(), base.DEFAULT_TIMEOUT_SECONDS, 5, 300)

        all_date_ranges = bool(self.all_date_ranges_var.get())
        if all_date_ranges:
            date_windows = base.build_all_date_windows(base.ALL_DATE_RANGES_START, base.date.today())
        else:
            date_windows = base.build_manual_date_window(self.posted_from_var.get(), self.posted_to_var.get())

        status = "" if bool(self.all_statuses_var.get()) else self.status_var.get().strip()
        require_attachments = bool(self.require_attachments_var.get())
        min_count = 0
        min_size = 0.0
        if require_attachments:
            min_count = base.parse_int(self.min_attachment_count_var.get(), 1, 1, 100000)
            min_size = base.parse_float(self.min_total_size_var.get(), 0.0, 0.0)

        settings = base.SearchSettings(
            keywords=codes,
            raw_batch_count=len(codes),
            duplicate_batch_count=0,
            date_windows=date_windows,
            all_date_ranges=all_date_ranges,
            status=status,
            ptype=self._ptype_code(),
            search_mode=self.search_mode_var.get().strip(),
            max_results_per_search=max_results,
            require_attachments=require_attachments,
            min_attachment_count=min_count,
            min_total_attachment_mb=min_size,
            timeout_seconds=timeout,
        )
        setattr(settings, "ignore_cached_searches", bool(getattr(self, "ignore_cached_searches_var", tk.BooleanVar(value=False)).get()))
        setattr(settings, "use_predefined_naics", False)
        setattr(settings, "predefined_naics_codes", codes)
        setattr(settings, "naics_q_search_enabled", True)
        setattr(settings, "naics_q_local_terms", local_terms)
        setattr(settings, "naics_q_local_raw_count", raw_count)
        setattr(settings, "naics_q_local_duplicate_count", duplicate_count)
        return settings

    def start_search(self) -> None:
        if self._use_predefined_naics_enabled():
            try:
                codes = self._interested_naics_codes()
                local_terms = base.split_keywords(self.keyword_text.get("1.0", "end"))
                if local_terms:
                    self._log(
                        "Predefined NAICS search enabled. Searching SAM.gov with NAICS code(s) "
                        f"{', '.join(codes)} and locally filtering results by: {', '.join(local_terms)}."
                    )
                else:
                    self._log(
                        "Predefined NAICS search enabled. Searching SAM.gov with NAICS code(s) "
                        f"{', '.join(codes)}. Batch keyword box is blank, so no local word filter is applied."
                    )
            except Exception:
                # Let the normal validation path show the exact error message.
                pass
        super().start_search()

    def _add_result(self, result: base.SearchResult) -> None:
        if self._use_predefined_naics_enabled():
            terms = base.split_keywords(self.keyword_text.get("1.0", "end"))
            if terms and not self._result_contains_all_local_terms(result, terms):
                skipped = int(getattr(self, "_naics_q_local_skipped", 0)) + 1
                setattr(self, "_naics_q_local_skipped", skipped)
                if skipped in (1, 5, 10) or skipped % 25 == 0:
                    try:
                        self._log(f"NAICS local word filter skipped {skipped} result(s).")
                    except Exception:
                        pass
                return
        super()._add_result(result)

    def _result_contains_all_local_terms(self, result: base.SearchResult, terms: Iterable[str]) -> bool:
        haystack = self._result_search_text(result)
        for term in terms:
            if not self._term_matches_text(term, haystack):
                return False
        return True

    def _result_search_text(self, result: base.SearchResult) -> str:
        values: List[str] = [
            result.title,
            result.solicitation_number,
            result.notice_id,
            result.notice_type,
            result.organization,
            result.naics_code,
            result.classification_code,
            result.response_deadline,
            result.ui_link,
            " ".join(result.resource_links or []),
        ]
        try:
            values.extend(self._attachment_names_for_result(result))
        except Exception:
            pass
        return "\n".join(str(value or "") for value in values).casefold()

    def _term_matches_text(self, term: str, haystack: str) -> bool:
        text = str(term or "").strip().casefold()
        if not text:
            return True

        # Quoted phrase support for convenience, but no regex in this local NAICS mode.
        if len(text) >= 2 and text[0] == text[-1] == '"':
            text = text[1:-1].strip()
            return text in haystack if text else True

        # Space-separated words are treated as AND, matching the user's wording.
        words = [word for word in re.split(r"\s+", text) if word]
        return all(word in haystack for word in words)


def main() -> None:
    app = SamGovSearchProNaicsQFilterApp()
    app.mainloop()


if __name__ == "__main__":
    main()
