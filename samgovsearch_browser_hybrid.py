from __future__ import annotations

import csv
import json
import os
import queue
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtWidgets import QFileDialog, QMessageBox, QPushButton, QTableWidgetItem

from samgovsearch_browser import BrowserResult, SamGovBrowserSearchApp


SAM_API_URL = "https://api.sam.gov/opportunities/v2/search"
DEFAULT_API_TIMEOUT_SECONDS = 30
DEFAULT_API_FALLBACK_DAYS = 364
HYBRID_API_REQUEST_DELAY_SECONDS = 1.5
NOTICE_ID_PATTERN = re.compile(
    r"(?<![A-Fa-f0-9])([A-Fa-f0-9]{32}|[A-Fa-f0-9]{8}-[A-Fa-f0-9]{4}-[A-Fa-f0-9]{4}-[A-Fa-f0-9]{4}-[A-Fa-f0-9]{12})(?![A-Fa-f0-9])"
)
DATE_PATTERNS = [
    re.compile(r"(?:posted|published|date posted|posted date)\D{0,50}(\d{1,2}/\d{1,2}/\d{4})", re.IGNORECASE),
    re.compile(r"(?:posted|published|date posted|posted date)\D{0,50}([A-Z][a-z]{2,8}\s+\d{1,2},\s+\d{4})", re.IGNORECASE),
    re.compile(r"\b(\d{1,2}/\d{1,2}/\d{4})\b"),
    re.compile(r"\b([A-Z][a-z]{2,8}\s+\d{1,2},\s+\d{4})\b"),
]


class SamGovApiClient:
    def __init__(self, api_key: str, timeout_seconds: int = DEFAULT_API_TIMEOUT_SECONDS) -> None:
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    def search(self, params: Dict[str, Any]) -> Dict[str, Any]:
        merged = dict(params)
        merged["api_key"] = self.api_key
        query = urllib.parse.urlencode(merged, doseq=True)
        request = urllib.request.Request(
            f"{SAM_API_URL}?{query}",
            headers={
                "Accept": "application/json",
                "User-Agent": "samgovsearch-browser-hybrid/1.0",
            },
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                body = response.read().decode("utf-8", errors="replace")
                return json.loads(body)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            message = body[:800]
            try:
                parsed = json.loads(body)
                message = str(parsed.get("message") or parsed.get("errorMessage") or parsed)
            except Exception:
                pass
            raise RuntimeError(f"SAM.gov HTTP {exc.code}: {message}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"SAM.gov connection error: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"SAM.gov returned invalid JSON: {exc}") from exc


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def extract_resource_links(item: Dict[str, Any]) -> List[str]:
    value = item.get("resourceLinks")
    if not value:
        return []
    if isinstance(value, list):
        return [normalize_text(url) for url in value if normalize_text(url)]
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    return []


def extract_notice_id(value: str) -> str:
    parsed = urllib.parse.urlparse(value)
    query = urllib.parse.parse_qs(parsed.query)
    for key in ("noticeid", "noticeId", "noticeID"):
        values = query.get(key)
        if values and values[0].strip():
            return values[0].strip()

    path_match = re.search(r"/opp/([^/?#]+)/?", parsed.path, re.IGNORECASE)
    if path_match:
        candidate = path_match.group(1).strip()
        if candidate:
            return candidate

    match = NOTICE_ID_PATTERN.search(value)
    return match.group(1) if match else ""


def parse_date(value: str) -> Optional[date]:
    text = value.strip()
    for fmt in ("%m/%d/%Y", "%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def extract_posted_date(value: str) -> str:
    for pattern in DATE_PATTERNS:
        match = pattern.search(value)
        if not match:
            continue
        parsed = parse_date(match.group(1))
        if parsed:
            return parsed.strftime("%m/%d/%Y")
    return ""


def extract_solicitation_number(value: str) -> str:
    patterns = [
        r"Solicitation\s*(?:Number|No\.?|#)?\s*[:#-]?\s*([A-Z0-9][A-Z0-9._/-]{3,80})",
        r"Sol\s*(?:Number|No\.?|#)?\s*[:#-]?\s*([A-Z0-9][A-Z0-9._/-]{3,80})",
    ]
    for pattern in patterns:
        match = re.search(pattern, value, re.IGNORECASE)
        if match:
            return match.group(1).strip().rstrip(".,;)")
    return ""


def api_date_window_for_result(result: BrowserResult) -> Tuple[str, str, str]:
    posted_date = getattr(result, "posted_date", "")
    posted = parse_date(posted_date) if posted_date else None
    if posted:
        value = posted.strftime("%m/%d/%Y")
        return value, value, "posted date from browser result"

    fallback_to = date.today()
    fallback_from = fallback_to - timedelta(days=DEFAULT_API_FALLBACK_DAYS)
    return (
        fallback_from.strftime("%m/%d/%Y"),
        fallback_to.strftime("%m/%d/%Y"),
        "fallback last 364 days because no posted date was extracted",
    )


def ensure_hybrid_fields(result: BrowserResult) -> None:
    combined = f"{result.url}\n{result.title}\n{result.snippet}"
    if not hasattr(result, "notice_id"):
        result.notice_id = extract_notice_id(combined)
    elif not result.notice_id:
        result.notice_id = extract_notice_id(combined)

    if not hasattr(result, "posted_date"):
        result.posted_date = extract_posted_date(combined)
    elif not result.posted_date:
        result.posted_date = extract_posted_date(combined)

    if not hasattr(result, "solicitation_number"):
        result.solicitation_number = extract_solicitation_number(combined)
    elif not result.solicitation_number:
        result.solicitation_number = extract_solicitation_number(combined)

    if not hasattr(result, "api_attachment_count"):
        result.api_attachment_count = ""
    if not hasattr(result, "api_attachment_status"):
        result.api_attachment_status = "Not enriched"
    if not hasattr(result, "api_resource_links"):
        result.api_resource_links = []


class HybridSamGovBrowserSearchApp(SamGovBrowserSearchApp):
    def __init__(self) -> None:
        self.hybrid_queue: "queue.Queue[Tuple[str, Any]]" = queue.Queue()
        self.hybrid_thread: Optional[threading.Thread] = None
        super().__init__()
        self._install_hybrid_ui()
        self.hybrid_timer = QTimer(self)
        self.hybrid_timer.timeout.connect(self._poll_hybrid_queue)
        self.hybrid_timer.start(200)

    def _install_hybrid_ui(self) -> None:
        self.setWindowTitle("SAM.gov Browser Search + Hybrid API Filter")
        headers = [
            "Keyword",
            "Title",
            "Notice ID",
            "Posted",
            "Attachment Text Hits",
            "API Attachments",
            "URL",
            "Snippet",
        ]
        self.result_table.setColumnCount(len(headers))
        self.result_table.setHorizontalHeaderLabels(headers)
        widths = [120, 280, 230, 95, 145, 130, 330, 430]
        for index, width in enumerate(widths):
            self.result_table.setColumnWidth(index, width)

        left = self.centralWidget().widget(0)
        layout = left.layout()
        self.hybrid_button = QPushButton("Hybrid API Enrich Results")
        self.hybrid_button.setEnabled(False)
        self.hybrid_button.clicked.connect(self.hybrid_api_enrich_results)
        layout.insertWidget(max(0, layout.count() - 1), self.hybrid_button)

        self.status_label.setText(
            "Ready. Browser search uses no API. Hybrid enrichment uses SAM_API_KEY only for extracted visible results."
        )

    def _add_result(self, result: BrowserResult) -> None:
        ensure_hybrid_fields(result)
        self.results.append(result)
        row_index = self.result_table.rowCount()
        self.result_table.insertRow(row_index)
        self._set_table_row(row_index, result)
        self.export_button.setEnabled(bool(self.results))
        self.hybrid_button.setEnabled(bool(self.results))

    def _set_table_row(self, row_index: int, result: BrowserResult) -> None:
        ensure_hybrid_fields(result)
        values = [
            result.keyword,
            result.title,
            result.notice_id,
            result.posted_date,
            str(result.attachment_text_hits),
            result.api_attachment_count or result.api_attachment_status,
            result.url,
            result.snippet,
        ]
        for column, value in enumerate(values):
            item = QTableWidgetItem(value)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.result_table.setItem(row_index, column, item)

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
                "Hybrid enrichment uses the SAM.gov API only for extracted browser results. Set SAM_API_KEY before running this step.",
            )
            return

        for result in self.results:
            ensure_hybrid_fields(result)
        candidates = [
            index for index, result in enumerate(self.results)
            if getattr(result, "api_attachment_status", "Not enriched") in ("", "Not enriched", "No notice ID")
        ]
        if not candidates:
            QMessageBox.information(self, "Nothing to Enrich", "All extracted results already have an API enrichment status.")
            return

        missing_notice = sum(1 for index in candidates if not self.results[index].notice_id)
        message = (
            f"This will use up to {len(candidates)} SAM.gov API request(s), one per extracted browser result when a posted date is available.\n\n"
            f"Results without a notice ID: {missing_notice}. Those will be skipped.\n\n"
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
        client = SamGovApiClient(api_key)
        enriched = 0
        skipped = 0
        try:
            for position, index in enumerate(candidates, start=1):
                result = self.results[index]
                ensure_hybrid_fields(result)
                notice_id = result.notice_id
                if not notice_id:
                    self.hybrid_queue.put(("update", (index, {"api_attachment_status": "No notice ID"})))
                    skipped += 1
                    continue

                posted_from, posted_to, window_note = api_date_window_for_result(result)
                params = {
                    "noticeid": notice_id,
                    "postedFrom": posted_from,
                    "postedTo": posted_to,
                    "limit": 10,
                    "offset": 0,
                }
                self.hybrid_queue.put(("status", f"API enrich {position}/{len(candidates)}: {notice_id} ({window_note})."))
                data = client.search(params)
                items = data.get("opportunitiesData") or []
                if not items:
                    self.hybrid_queue.put(("update", (index, {
                        "notice_id": notice_id,
                        "api_attachment_status": f"No API match using {posted_from} to {posted_to}",
                    })))
                    skipped += 1
                else:
                    item = items[0]
                    links = extract_resource_links(item)
                    update = {
                        "notice_id": normalize_text(item.get("noticeId")) or notice_id,
                        "solicitation_number": normalize_text(item.get("solicitationNumber")) or result.solicitation_number,
                        "posted_date": normalize_text(item.get("postedDate")) or result.posted_date,
                        "api_attachment_count": str(len(links)),
                        "api_attachment_status": "OK" if links else "OK, no attachments returned",
                        "api_resource_links": links,
                    }
                    self.hybrid_queue.put(("update", (index, update)))
                    enriched += 1

                if position < len(candidates):
                    time.sleep(HYBRID_API_REQUEST_DELAY_SECONDS)

            self.hybrid_queue.put(("done", (enriched, skipped)))
        except Exception as exc:
            self.hybrid_queue.put(("error", str(exc)))

    def _poll_hybrid_queue(self) -> None:
        try:
            while True:
                event, payload = self.hybrid_queue.get_nowait()
                if event == "status":
                    self.status_label.setText(str(payload))
                elif event == "update":
                    index, updates = payload
                    self._apply_result_update(index, updates)
                elif event == "done":
                    enriched, skipped = payload
                    self.hybrid_button.setEnabled(bool(self.results))
                    self.status_label.setText(f"Hybrid API enrichment done. Enriched {enriched}; skipped/no match {skipped}.")
                elif event == "error":
                    self.hybrid_button.setEnabled(bool(self.results))
                    QMessageBox.warning(self, "Hybrid API Error", str(payload))
                    self.status_label.setText(f"Hybrid API enrichment stopped: {payload}")
        except queue.Empty:
            pass

    def _apply_result_update(self, index: int, updates: Dict[str, Any]) -> None:
        if index < 0 or index >= len(self.results):
            return
        result = self.results[index]
        for key, value in updates.items():
            setattr(result, key, value)
        self._set_table_row(index, result)

    def clear_results(self) -> None:
        super().clear_results()
        self.hybrid_button.setEnabled(False)

    def export_csv(self) -> None:
        if not self.results:
            QMessageBox.information(self, "No Results", "There are no browser-mode results to export.")
            return

        default_name = f"samgov_browser_hybrid_results_{date.today().strftime('%Y%m%d')}.csv"
        path, _ = QFileDialog.getSaveFileName(self, "Save browser/hybrid results", default_name, "CSV files (*.csv);;All files (*.*)")
        if not path:
            return

        fieldnames = [
            "Keyword",
            "Title",
            "Notice ID",
            "Solicitation Number",
            "Posted Date",
            "URL",
            "Visible Attachment Text Hits",
            "API Attachment Count",
            "API Attachment Status",
            "API Resource Links",
            "Visible Text Snippet",
        ]
        with open(path, "w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for result in self.results:
                ensure_hybrid_fields(result)
                writer.writerow({
                    "Keyword": result.keyword,
                    "Title": result.title,
                    "Notice ID": result.notice_id,
                    "Solicitation Number": result.solicitation_number,
                    "Posted Date": result.posted_date,
                    "URL": result.url,
                    "Visible Attachment Text Hits": str(result.attachment_text_hits),
                    "API Attachment Count": result.api_attachment_count,
                    "API Attachment Status": result.api_attachment_status,
                    "API Resource Links": " | ".join(result.api_resource_links),
                    "Visible Text Snippet": result.snippet,
                })

        QMessageBox.information(self, "Export Complete", f"Exported {len(self.results)} result(s).")
        self.status_label.setText(f"Exported {len(self.results)} result(s) to {path}.")


def main() -> int:
    from PyQt6.QtWidgets import QApplication
    import sys

    app = QApplication(sys.argv)
    window = HybridSamGovBrowserSearchApp()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
