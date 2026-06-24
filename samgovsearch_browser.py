from __future__ import annotations

import csv
import json
import re
import sys
import urllib.parse
from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, List

from PyQt6.QtCore import QUrl, Qt
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from PyQt6.QtWebEngineWidgets import QWebEngineView


SAM_SEARCH_HOME = "https://sam.gov/search/?index=opp"
DEFAULT_BATCH = "Patriot\nfrequency converter\nK0357NC200461-0001"
ATTACHMENT_TEXT_PATTERN = re.compile(
    r"\b(attachment|attachments|resource|resources|document|documents|download|downloads|file|files)\b",
    re.IGNORECASE,
)


@dataclass
class BrowserResult:
    keyword: str
    title: str
    url: str
    attachment_text_hits: int
    snippet: str

    def as_csv_row(self) -> Dict[str, str]:
        return {
            "Keyword": self.keyword,
            "Title": self.title,
            "URL": self.url,
            "Visible Attachment Text Hits": str(self.attachment_text_hits),
            "Visible Text Snippet": self.snippet,
        }


def split_and_dedupe_batch(raw: str) -> List[str]:
    candidates: List[str] = []
    for line in raw.replace(",", "\n").splitlines():
        value = line.strip()
        if value:
            candidates.append(value)

    seen = set()
    cleaned: List[str] = []
    for candidate in candidates:
        key = re.sub(r"\s+", " ", candidate).casefold()
        if key in seen:
            continue
        cleaned.append(candidate)
        seen.add(key)
    return cleaned


def parse_min_count(value: str) -> int:
    text = value.strip()
    if not text:
        return 1
    number = int(text)
    if number < 1:
        raise ValueError("Minimum attachment count must be 1 or higher.")
    return number


def make_sam_search_url(keyword: str) -> str:
    # SAM.gov is a JavaScript application. This URL preloads the normal website
    # search page with the same visible search box state a user would enter.
    params = {
        "index": "opp",
        "page": "1",
        "pageSize": "25",
        "sort": "-modifiedDate",
        "sfm[simpleSearch][keywordRadio]": "ALL",
        "sfm[simpleSearch][keywordEditorTextarea]": keyword,
    }
    return "https://sam.gov/search/?" + urllib.parse.urlencode(params)


def first_non_empty_line(text: str) -> str:
    for line in text.splitlines():
        value = re.sub(r"\s+", " ", line).strip()
        if value:
            return value
    return ""


class SamGovBrowserSearchApp(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("SAM.gov Browser Search")
        self.resize(1500, 900)

        self.batch_terms: List[str] = []
        self.current_batch_index = -1
        self.results: List[BrowserResult] = []
        self.seen_result_keys = set()

        self._build_ui()
        self.browser.setUrl(QUrl(SAM_SEARCH_HOME))

    def _build_ui(self) -> None:
        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.setCentralWidget(main_splitter)

        left = QWidget()
        left_layout = QVBoxLayout(left)

        left_layout.addWidget(QLabel("Batch keywords, part numbers, solicitation numbers"))
        self.batch_input = QTextEdit()
        self.batch_input.setPlainText(DEFAULT_BATCH)
        self.batch_input.setMinimumHeight(145)
        left_layout.addWidget(self.batch_input)

        self.require_attachments_checkbox = QCheckBox("Only keep results with visible attachment/document text")
        self.require_attachments_checkbox.setChecked(False)
        self.require_attachments_checkbox.stateChanged.connect(self._toggle_attachment_controls)
        left_layout.addWidget(self.require_attachments_checkbox)

        attachment_form = QWidget()
        self.attachment_form = attachment_form
        form_layout = QFormLayout(attachment_form)
        self.min_attachment_count = QLineEdit()
        self.min_attachment_count.setPlaceholderText("Default 1")
        form_layout.addRow("Minimum visible text hits", self.min_attachment_count)
        left_layout.addWidget(attachment_form)

        self.text_filter = QLineEdit()
        self.text_filter.setPlaceholderText("Optional visible text filter, comma or newline separated")
        left_layout.addWidget(QLabel("Extra page/result text filter"))
        left_layout.addWidget(self.text_filter)

        info = QLabel(
            "Browser mode does not use SAM_API_KEY. It renders SAM.gov and filters visible page elements. "
            "It is useful for avoiding API quota, but it is less exact than the API because SAM.gov can change page markup."
        )
        info.setWordWrap(True)
        left_layout.addWidget(info)

        button_row_1 = QHBoxLayout()
        self.search_first_button = QPushButton("Search First")
        self.search_first_button.clicked.connect(self.search_first)
        button_row_1.addWidget(self.search_first_button)

        self.search_next_button = QPushButton("Next Batch Item")
        self.search_next_button.clicked.connect(self.search_next)
        button_row_1.addWidget(self.search_next_button)
        left_layout.addLayout(button_row_1)

        button_row_2 = QHBoxLayout()
        self.extract_button = QPushButton("Extract Visible Results")
        self.extract_button.clicked.connect(self.extract_visible_results)
        button_row_2.addWidget(self.extract_button)

        self.hide_button = QPushButton("Hide Non-Matching Cards")
        self.hide_button.clicked.connect(self.hide_non_matching_cards)
        button_row_2.addWidget(self.hide_button)
        left_layout.addLayout(button_row_2)

        button_row_3 = QHBoxLayout()
        self.export_button = QPushButton("Export CSV")
        self.export_button.clicked.connect(self.export_csv)
        self.export_button.setEnabled(False)
        button_row_3.addWidget(self.export_button)

        self.clear_button = QPushButton("Clear Results")
        self.clear_button.clicked.connect(self.clear_results)
        button_row_3.addWidget(self.clear_button)
        left_layout.addLayout(button_row_3)

        self.status_label = QLabel("Ready.")
        self.status_label.setWordWrap(True)
        left_layout.addWidget(self.status_label)

        self.result_table = QTableWidget(0, 5)
        self.result_table.setHorizontalHeaderLabels([
            "Keyword",
            "Title",
            "Attachment Text Hits",
            "URL",
            "Snippet",
        ])
        self.result_table.setColumnWidth(0, 120)
        self.result_table.setColumnWidth(1, 300)
        self.result_table.setColumnWidth(2, 145)
        self.result_table.setColumnWidth(3, 360)
        self.result_table.setColumnWidth(4, 430)
        self.result_table.itemDoubleClicked.connect(self.open_result_from_table)
        left_layout.addWidget(self.result_table, stretch=1)

        main_splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)

        nav_row = QHBoxLayout()
        back_action = QAction("Back", self)
        back_action.triggered.connect(self.browser_back)
        forward_action = QAction("Forward", self)
        forward_action.triggered.connect(self.browser_forward)
        reload_action = QAction("Reload", self)
        reload_action.triggered.connect(self.browser_reload)
        self.addAction(back_action)
        self.addAction(forward_action)
        self.addAction(reload_action)

        back_button = QPushButton("Back")
        back_button.clicked.connect(self.browser_back)
        nav_row.addWidget(back_button)

        forward_button = QPushButton("Forward")
        forward_button.clicked.connect(self.browser_forward)
        nav_row.addWidget(forward_button)

        reload_button = QPushButton("Reload")
        reload_button.clicked.connect(self.browser_reload)
        nav_row.addWidget(reload_button)

        self.url_bar = QLineEdit()
        self.url_bar.returnPressed.connect(self.navigate_to_url_bar)
        nav_row.addWidget(self.url_bar, stretch=1)

        go_button = QPushButton("Go")
        go_button.clicked.connect(self.navigate_to_url_bar)
        nav_row.addWidget(go_button)
        right_layout.addLayout(nav_row)

        self.browser = QWebEngineView()
        self.browser.urlChanged.connect(self._on_url_changed)
        self.browser.loadFinished.connect(self._on_load_finished)
        right_layout.addWidget(self.browser, stretch=1)

        main_splitter.addWidget(right)
        main_splitter.setSizes([520, 980])

        self._toggle_attachment_controls()

    def _toggle_attachment_controls(self) -> None:
        self.attachment_form.setVisible(self.require_attachments_checkbox.isChecked())

    def browser_back(self) -> None:
        self.browser.back()

    def browser_forward(self) -> None:
        self.browser.forward()

    def browser_reload(self) -> None:
        self.browser.reload()

    def navigate_to_url_bar(self) -> None:
        text = self.url_bar.text().strip()
        if not text:
            return
        if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", text):
            text = "https://" + text
        self.browser.setUrl(QUrl(text))

    def _on_url_changed(self, url: QUrl) -> None:
        self.url_bar.setText(url.toString())

    def _on_load_finished(self, ok: bool) -> None:
        if ok:
            keyword = self.current_keyword()
            if keyword:
                self.status_label.setText(f"Loaded SAM.gov page for: {keyword}")
            else:
                self.status_label.setText("Loaded page.")
        else:
            self.status_label.setText("Page load failed.")

    def current_keyword(self) -> str:
        if 0 <= self.current_batch_index < len(self.batch_terms):
            return self.batch_terms[self.current_batch_index]
        return ""

    def _load_batch_terms(self) -> bool:
        self.batch_terms = split_and_dedupe_batch(self.batch_input.toPlainText())
        if not self.batch_terms:
            QMessageBox.warning(self, "No Batch Items", "Enter at least one search term.")
            return False
        return True

    def search_first(self) -> None:
        if not self._load_batch_terms():
            return
        self.current_batch_index = 0
        self._navigate_to_current_batch_item()

    def search_next(self) -> None:
        if not self.batch_terms:
            if not self._load_batch_terms():
                return
            self.current_batch_index = 0
        else:
            self.current_batch_index += 1
            if self.current_batch_index >= len(self.batch_terms):
                self.current_batch_index = len(self.batch_terms) - 1
                QMessageBox.information(self, "Batch Complete", "No more batch items.")
                return
        self._navigate_to_current_batch_item()

    def _navigate_to_current_batch_item(self) -> None:
        keyword = self.current_keyword()
        if not keyword:
            return
        url = make_sam_search_url(keyword)
        self.status_label.setText(f"Loading SAM.gov browser search for: {keyword}")
        self.browser.setUrl(QUrl(url))

    def _required_text_terms(self) -> List[str]:
        raw = self.text_filter.text().replace(",", "\n")
        return [line.strip().casefold() for line in raw.splitlines() if line.strip()]

    def _min_attachment_hits(self) -> int:
        if not self.require_attachments_checkbox.isChecked():
            return 0
        return parse_min_count(self.min_attachment_count.text())

    def extract_visible_results(self) -> None:
        try:
            min_attachment_hits = self._min_attachment_hits()
        except Exception as exc:
            QMessageBox.warning(self, "Invalid Attachment Filter", str(exc))
            return

        self.status_label.setText("Extracting visible SAM.gov page elements...")
        self.browser.page().runJavaScript(self._extract_results_js(), lambda rows: self._handle_extracted_rows(rows, min_attachment_hits))

    def _handle_extracted_rows(self, rows: Any, min_attachment_hits: int) -> None:
        if not isinstance(rows, list):
            QMessageBox.warning(self, "Extract Failed", "The page did not return extractable results.")
            self.status_label.setText("Extract failed.")
            return

        keyword = self.current_keyword() or "manual page"
        required_terms = self._required_text_terms()
        added = 0
        skipped = 0

        for row in rows:
            if not isinstance(row, dict):
                continue
            title = str(row.get("title") or "").strip()
            url = str(row.get("url") or "").strip()
            text = str(row.get("text") or "").strip()
            if not text and not title:
                continue

            attachment_hits = len(ATTACHMENT_TEXT_PATTERN.findall(text + " " + title + " " + url))
            if min_attachment_hits and attachment_hits < min_attachment_hits:
                skipped += 1
                continue

            text_fold = text.casefold()
            if required_terms and not all(term in text_fold for term in required_terms):
                skipped += 1
                continue

            if not title:
                title = first_non_empty_line(text) or "SAM.gov result"
            snippet = re.sub(r"\s+", " ", text).strip()[:1000]
            result_key = (url or title + snippet[:100]).casefold()
            if result_key in self.seen_result_keys:
                continue
            self.seen_result_keys.add(result_key)

            result = BrowserResult(
                keyword=keyword,
                title=title[:300],
                url=url,
                attachment_text_hits=attachment_hits,
                snippet=snippet,
            )
            self._add_result(result)
            added += 1

        self.status_label.setText(f"Extracted {added} new visible result(s). Skipped {skipped} non-matching element(s).")

    def _add_result(self, result: BrowserResult) -> None:
        self.results.append(result)
        row_index = self.result_table.rowCount()
        self.result_table.insertRow(row_index)
        values = [
            result.keyword,
            result.title,
            str(result.attachment_text_hits),
            result.url,
            result.snippet,
        ]
        for column, value in enumerate(values):
            item = QTableWidgetItem(value)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.result_table.setItem(row_index, column, item)
        self.export_button.setEnabled(bool(self.results))

    def hide_non_matching_cards(self) -> None:
        try:
            min_attachment_hits = self._min_attachment_hits()
        except Exception as exc:
            QMessageBox.warning(self, "Invalid Attachment Filter", str(exc))
            return

        criteria = {
            "minAttachmentHits": min_attachment_hits,
            "terms": self._required_text_terms(),
        }
        self.browser.page().runJavaScript(self._hide_non_matching_js(criteria), self._handle_hide_result)

    def _handle_hide_result(self, value: Any) -> None:
        if isinstance(value, dict):
            hidden = value.get("hidden", 0)
            kept = value.get("kept", 0)
            self.status_label.setText(f"Page filter applied. Kept {kept} visible block(s), hid {hidden} block(s). Reload page to undo hiding.")
        else:
            self.status_label.setText("Page filter applied. Reload page to undo hiding.")

    def clear_results(self) -> None:
        self.results.clear()
        self.seen_result_keys.clear()
        self.result_table.setRowCount(0)
        self.export_button.setEnabled(False)
        self.status_label.setText("Results cleared.")

    def export_csv(self) -> None:
        if not self.results:
            QMessageBox.information(self, "No Results", "There are no browser-mode results to export.")
            return

        default_name = f"samgov_browser_results_{date.today().strftime('%Y%m%d')}.csv"
        path, _ = QFileDialog.getSaveFileName(self, "Save browser-mode results", default_name, "CSV files (*.csv);;All files (*.*)")
        if not path:
            return

        fieldnames = list(self.results[0].as_csv_row().keys())
        with open(path, "w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for result in self.results:
                writer.writerow(result.as_csv_row())

        QMessageBox.information(self, "Export Complete", f"Exported {len(self.results)} result(s).")
        self.status_label.setText(f"Exported {len(self.results)} result(s) to {path}.")

    def open_result_from_table(self, item: QTableWidgetItem) -> None:
        row = item.row()
        if row < 0 or row >= len(self.results):
            return
        url = self.results[row].url
        if url:
            self.browser.setUrl(QUrl(url))

    def _extract_results_js(self) -> str:
        return r"""
(() => {
  function cleanText(value) {
    return (value || '').replace(/\s+/g, ' ').trim();
  }
  function visible(el) {
    if (!el) return false;
    const style = window.getComputedStyle(el);
    if (!style || style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
    const rect = el.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  }
  function hrefLooksUseful(href) {
    return /\/opp\/|noticeId|opportunity|solicitation|sam\.gov/i.test(href || '');
  }
  function textLooksUseful(text) {
    return /(solicitation|sources sought|presolicitation|combined synopsis|special notice|award notice|posted|response date|notice id|set-aside|attachments?|documents?|download)/i.test(text || '');
  }
  function nearestUsefulBlock(anchor) {
    const selectors = [
      'article', 'li', '[data-testid]', '[id*="result" i]', '[class*="result" i]',
      '[class*="card" i]', '[class*="opportunity" i]', '.grid-row', '.usa-card', 'section', 'div'
    ];
    for (const selector of selectors) {
      const block = anchor.closest(selector);
      if (!block || !visible(block)) continue;
      const text = cleanText(block.innerText || block.textContent || '');
      if (text.length >= 40 && text.length <= 5000) return block;
    }
    return anchor.parentElement || anchor;
  }

  const rows = [];
  const seen = new Set();
  const anchors = Array.from(document.querySelectorAll('a[href]')).filter(visible);

  for (const anchor of anchors) {
    const href = anchor.href || '';
    const anchorText = cleanText(anchor.innerText || anchor.textContent || '');
    const block = nearestUsefulBlock(anchor);
    const text = cleanText(block.innerText || block.textContent || anchorText);
    if (text.length < 20) continue;
    if (!hrefLooksUseful(href) && !textLooksUseful(text)) continue;

    const key = (href || anchorText + text.slice(0, 150)).toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);

    rows.push({
      title: anchorText || text.slice(0, 140),
      url: href,
      text: text.slice(0, 2500)
    });
  }

  if (rows.length === 0) {
    const blocks = Array.from(document.querySelectorAll('article, li, [data-testid], [id*="result" i], [class*="result" i], [class*="card" i], [class*="opportunity" i], section'));
    for (const block of blocks) {
      if (!visible(block)) continue;
      const text = cleanText(block.innerText || block.textContent || '');
      if (text.length < 40 || !textLooksUseful(text)) continue;
      const link = block.querySelector('a[href]');
      const href = link ? link.href : '';
      const title = link ? cleanText(link.innerText || link.textContent || '') : text.slice(0, 140);
      const key = (href || title + text.slice(0, 150)).toLowerCase();
      if (seen.has(key)) continue;
      seen.add(key);
      rows.push({ title, url: href, text: text.slice(0, 2500) });
    }
  }

  return rows;
})();
"""

    def _hide_non_matching_js(self, criteria: Dict[str, Any]) -> str:
        criteria_json = json.dumps(criteria)
        return f"""
(() => {{
  const criteria = {criteria_json};
  const attachmentRegex = /\\b(attachment|attachments|resource|resources|document|documents|download|downloads|file|files)\\b/ig;
  function cleanText(value) {{ return (value || '').replace(/\\s+/g, ' ').trim(); }}
  function visible(el) {{
    if (!el) return false;
    const style = window.getComputedStyle(el);
    if (!style || style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
    const rect = el.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  }}
  function matches(text) {{
    const lower = text.toLowerCase();
    for (const term of (criteria.terms || [])) {{
      if (!lower.includes(String(term).toLowerCase())) return false;
    }}
    const hits = (text.match(attachmentRegex) || []).length;
    if ((criteria.minAttachmentHits || 0) > 0 && hits < criteria.minAttachmentHits) return false;
    return true;
  }}

  const selectors = 'article, li, [data-testid], [id*="result" i], [class*="result" i], [class*="card" i], [class*="opportunity" i], section';
  const blocks = Array.from(document.querySelectorAll(selectors));
  let hidden = 0;
  let kept = 0;
  for (const block of blocks) {{
    if (!visible(block)) continue;
    const text = cleanText(block.innerText || block.textContent || '');
    if (text.length < 30) continue;
    if (matches(text)) {{
      block.style.outline = '3px solid #2e7d32';
      kept += 1;
    }} else {{
      block.dataset.samgovsearchHidden = 'true';
      block.style.display = 'none';
      hidden += 1;
    }}
  }}
  return {{hidden, kept}};
}})();
"""


def main() -> int:
    app = QApplication(sys.argv)
    window = SamGovBrowserSearchApp()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
