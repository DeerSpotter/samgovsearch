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

        values = self._initial_match_values(result)
        haystack = " | ".join(value for value in values if value)
        if not haystack.strip():
            # Do not hide sparse API records just because the local cache has not
            # enriched them yet. The user can still apply local filters afterward.
            return True

        return all(self._token_matches(token, values, haystack) for token in tokens)

    def _initial_match_values(self, result: Any) -> List[str]:
        """Return only SAM.gov-provided text for initial search validation.

        Do not use _result_filter_values here. That method intentionally includes
        the app's local Keyword column so local filters can search/export table
        metadata. For initial validation, including the Keyword column causes every
        result to match the user's entered search term, even when the opportunity
        itself does not contain that term.
        """
        values: List[str] = []

        for attr in [
            "title",
            "solicitation_number",
            "notice_id",
            "notice_type",
            "posted_date",
            "response_deadline",
            "active",
            "organization",
            "naics_code",
            "classification_code",
            "ui_link",
        ]:
            value = getattr(result, attr, "")
            if value:
                values.append(str(value))

        for link in list(getattr(result, "resource_links", []) or []):
            if link:
                values.append(str(link))

        try:
            values.extend(self._attachment_names_for_result(result))
        except Exception:
            pass

        try:
            record = self._cache_record_for_notice(getattr(result, "notice_id", ""))
            item = record.get("item") if isinstance(record, dict) else {}
            if isinstance(item, dict):
                for key in [
                    "title",
                    "description",
                    "solicitationNumber",
                    "noticeId",
                    "type",
                    "fullParentPathName",
                    "department",
                    "subTier",
                    "office",
                    "naicsCode",
                    "classificationCode",
                ]:
                    value = item.get(key)
                    if value:
                        values.append(str(value))

                resource_links = item.get("resourceLinks")
                if isinstance(resource_links, list):
                    values.extend(str(link) for link in resource_links if link)
                elif isinstance(resource_links, str) and resource_links.strip():
                    values.append(resource_links.strip())
        except Exception:
            pass

        return values


def main() -> None:
    app = SamGovSearchProInitialMatchApp()
    app.mainloop()


if __name__ == "__main__":
    main()
