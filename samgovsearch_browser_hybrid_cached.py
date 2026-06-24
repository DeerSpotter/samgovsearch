from __future__ import annotations

import os
import threading
import time
from typing import List

from PyQt6.QtWidgets import QMessageBox

import samgovsearch_browser_hybrid as hybrid
from samgov_api_cache import SamGovApiCache


class CachedHybridSamGovBrowserSearchApp(hybrid.HybridSamGovBrowserSearchApp):
    """Browser + hybrid API enrichment with local query and notice caching enabled."""

    def __init__(self) -> None:
        self._api_cache = SamGovApiCache.default()
        super().__init__()
        summary = self._api_cache.summary()
        self.status_label.setText(
            "Ready. Browser search uses no API. Hybrid enrichment reuses local API cache first. "
            f"Cache: {summary['query_count']} querie(s), {summary['notice_count']} notice(s)."
        )

    def hybrid_api_enrich_results(self) -> None:
        if not self.results:
            QMessageBox.information(self, "No Results", "Extract visible browser results before hybrid enrichment.")
            return
        if self.hybrid_thread and self.hybrid_thread.is_alive():
            QMessageBox.information(self, "Hybrid Enrichment Running", "Hybrid API enrichment is already running.")
            return

        api_key = os.environ.get("SAM_API_KEY", "").strip()
        if not api_key:
            QMessageBox.warning(
                self,
                "Missing SAM_API_KEY",
                "Hybrid enrichment uses cached API results first, then SAM.gov API only for uncached extracted results. "
                "Set SAM_API_KEY before running this step.",
            )
            return

        for result in self.results:
            hybrid.ensure_hybrid_fields(result)
        candidates = [
            index for index, result in enumerate(self.results)
            if getattr(result, "api_attachment_status", "Not enriched") in ("", "Not enriched", "No notice ID")
        ]
        if not candidates:
            QMessageBox.information(self, "Nothing to Enrich", "All extracted results already have an API enrichment status.")
            return

        missing_notice = sum(1 for index in candidates if not self.results[index].notice_id)
        cached_notice = sum(
            1 for index in candidates
            if self.results[index].notice_id and self._api_cache.get_notice_response({"noticeid": self.results[index].notice_id, "offset": 0, "limit": 1}) is not None
        )
        possible_network = max(0, len(candidates) - missing_notice - cached_notice)
        message = (
            "Hybrid enrichment will use the local API cache before calling SAM.gov.\n\n"
            f"Candidate row(s): {len(candidates)}\n"
            f"Already in local notice cache: {cached_notice}\n"
            f"Results without notice ID, skipped: {missing_notice}\n"
            f"Possible SAM.gov API request(s): {possible_network}\n\n"
            "Continue?"
        )
        if QMessageBox.question(self, "Hybrid API Enrich", message) != QMessageBox.StandardButton.Yes:
            return

        self.hybrid_button.setEnabled(False)
        self.status_label.setText(f"Hybrid API enrichment started for {len(candidates)} result(s)...")
        self.hybrid_thread = threading.Thread(
            target=self._hybrid_api_worker,
            args=(api_key, candidates),
            daemon=True,
        )
        self.hybrid_thread.start()

    def _hybrid_api_worker(self, api_key: str, candidates: List[int]) -> None:
        client = hybrid.SamGovApiClient(api_key)
        enriched = 0
        skipped = 0
        cache_hits = 0
        network_calls = 0
        try:
            for position, index in enumerate(candidates, start=1):
                result = self.results[index]
                hybrid.ensure_hybrid_fields(result)
                notice_id = result.notice_id
                if not notice_id:
                    self.hybrid_queue.put(("update", (index, {"api_attachment_status": "No notice ID"})))
                    skipped += 1
                    continue

                posted_from, posted_to, window_note = hybrid.api_date_window_for_result(result)
                params = {
                    "noticeid": notice_id,
                    "postedFrom": posted_from,
                    "postedTo": posted_to,
                    "limit": 10,
                    "offset": 0,
                }

                self.hybrid_queue.put(("status", f"Hybrid enrich {position}/{len(candidates)}: {notice_id} ({window_note})."))
                data, cache_status = self._api_cache.get_or_fetch_response(
                    params,
                    client.search,
                    source_label="browser-hybrid",
                )
                if cache_status == "network":
                    network_calls += 1
                else:
                    cache_hits += 1

                items = data.get("opportunitiesData") or []
                if not items:
                    self.hybrid_queue.put(("update", (index, {
                        "notice_id": notice_id,
                        "api_attachment_status": f"No API match using {posted_from} to {posted_to}",
                    })))
                    skipped += 1
                else:
                    item = items[0]
                    links = hybrid.extract_resource_links(item)
                    status = "OK" if links else "OK, no attachments returned"
                    if cache_status != "network":
                        status = f"{status} ({cache_status})"
                    update = {
                        "notice_id": hybrid.normalize_text(item.get("noticeId")) or notice_id,
                        "solicitation_number": hybrid.normalize_text(item.get("solicitationNumber")) or result.solicitation_number,
                        "posted_date": hybrid.normalize_text(item.get("postedDate")) or result.posted_date,
                        "api_attachment_count": str(len(links)),
                        "api_attachment_status": status,
                        "api_resource_links": links,
                    }
                    self.hybrid_queue.put(("update", (index, update)))
                    enriched += 1

                if cache_status == "network" and position < len(candidates):
                    time.sleep(hybrid.HYBRID_API_REQUEST_DELAY_SECONDS)

            self.hybrid_queue.put(("done", (enriched, skipped)))
            self.hybrid_queue.put(("status", f"Hybrid enrichment done. Cache hits {cache_hits}; SAM.gov API calls {network_calls}."))
        except Exception as exc:
            self.hybrid_queue.put(("error", str(exc)))


def main() -> int:
    from PyQt6.QtWidgets import QApplication
    import sys

    app = QApplication(sys.argv)
    window = CachedHybridSamGovBrowserSearchApp()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
