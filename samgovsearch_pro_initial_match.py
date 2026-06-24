from __future__ import annotations

from typing import Any, List

from samgovsearch_pro_download_folder import SamGovSearchProDownloadFolderApp


class SamGovSearchProInitialMatchApp(SamGovSearchProDownloadFolderApp):
    def __init__(self) -> None:
        self._initial_match_skipped_count = 0
        super().__init__()

    def start_search(self) -> None:
        self._initial_match_skipped_count = 0
        super().start_search()

    def _add_result(self, result: Any) -> None:
        if not self._result_matches_initial_batch_keyword(result):
            self._initial_match_skipped_count += 1
            if self._initial_match_skipped_count in {1, 5, 10} or self._initial_match_skipped_count % 25 == 0:
                self._log(
                    "Initial match filter skipped "
                    f"{self._initial_match_skipped_count} broad result(s) that did not match the entered keyword syntax."
                )
            self._set_results_status(prefix="Searching")
            return

        super()._add_result(result)

    def _finish_search(self) -> None:
        super()._finish_search()
        if self._initial_match_skipped_count:
            self._log(
                "Initial match filter removed "
                f"{self._initial_match_skipped_count} broad result(s)."
            )
            current = self.status_var_text.get()
            self.status_var_text.set(
                f"{current} Initial filter skipped {self._initial_match_skipped_count} broad result(s)."
            )

    def _result_matches_initial_batch_keyword(self, result: Any) -> bool:
        keyword = str(getattr(result, "keyword", "") or "").strip()
        if not keyword:
            return True

        tokens = self._parse_show_filter(keyword)
        if not tokens:
            return True

        try:
            values: List[str] = self._result_filter_values(result)
        except Exception:
            row = result.as_csv_row() if hasattr(result, "as_csv_row") else {}
            values = [str(value or "") for value in row.values()]

        haystack = " | ".join(value for value in values if value)
        if not haystack.strip():
            return True

        return all(self._token_matches(token, values, haystack) for token in tokens)


def main() -> None:
    app = SamGovSearchProInitialMatchApp()
    app.mainloop()


if __name__ == "__main__":
    main()
