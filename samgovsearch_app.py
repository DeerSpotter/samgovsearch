from __future__ import annotations

import mimetypes
import os
from pathlib import Path
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from typing import Any, Dict, List, Optional
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import samgovsearch_unified as unified

SAM_ACCOUNT_DETAILS_URL = "https://sam.gov/profile/details"
SAM_API_DOCS_URL = "https://open.gsa.gov/api/get-opportunities-public-api/"
DOWNLOAD_TIMEOUT_SECONDS = 180
DOWNLOAD_CHUNK_BYTES = 1024 * 1024
WEBSITE_ZIP_TIMEOUT_MS = 90000


class SamGovSearchApp(unified.UnifiedSamGovSearchApp):
    """Final user-facing SAM.gov Search UI.

    Adds user settings for SAM_API_KEY, click-to-sort result columns, and
    selected-row attachment downloads while keeping the unified
    internal/API/hybrid search behavior in one app.
    """

    def _build_ui(self) -> None:
        super()._build_ui()
        self._sort_reverse_by_column: Dict[str, bool] = {}
        self._last_sorted_column = ""
        self._install_sortable_headings()
        self._add_settings_button()
        self._add_download_button()

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

    def _add_download_button(self) -> None:
        left_panel = self.grid_slaves(row=0, column=0)[0]
        download_frame = ttk.LabelFrame(left_panel, text="Attachments", padding=8)
        download_frame.grid(row=13, column=0, sticky="ew", pady=(8, 0))
        download_frame.columnconfigure(0, weight=1)

        self.download_attachments_button = ttk.Button(
            download_frame,
            text="Download Attachments for Selected Result",
            command=self.download_selected_attachments,
        )
        self.download_attachments_button.grid(row=0, column=0, sticky="ew")

        ttk.Label(
            download_frame,
            text=(
                "Select one result row. The app tries SAM.gov's Download All ZIP method first, "
                "then falls back to individual public attachment links."
            ),
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

    def _add_result(self, result: Any) -> None:
        super()._add_result(result)
        self._update_download_button_state()

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
        self._update_download_button_state()

    def _update_download_button_state(self) -> None:
        button = getattr(self, "download_attachments_button", None)
        if button is not None:
            button.configure(state="normal" if self.results else "disabled")

    def _selected_result(self) -> Optional[Any]:
        selected = self.tree.selection()
        if not selected:
            return None
        index = self.tree.index(selected[0])
        if index < 0 or index >= len(self.results):
            return None
        return self.results[index]

    def download_selected_attachments(self) -> None:
        result = self._selected_result()
        if result is None:
            messagebox.showinfo("No Result Selected", "Select one result row before downloading attachments.")
            return

        folder = filedialog.askdirectory(title="Choose folder for SAM.gov attachments")
        if not folder:
            return

        target_folder = Path(folder) / self._safe_folder_name(
            result.solicitation_number or result.notice_id or result.title or "samgov_opportunity"
        )
        target_folder.mkdir(parents=True, exist_ok=True)

        notice_id = str(getattr(result, "notice_id", "") or "").strip()
        links = list(getattr(result, "resource_links", []) or [])
        zip_error = ""

        if notice_id:
            self.status_var_text.set("Trying SAM.gov Download All ZIP method...")
            self.update_idletasks()
            try:
                zip_path = self._download_samgov_website_zip(result, target_folder)
                self._log(f"Downloaded SAM.gov Download All ZIP: {zip_path}")
                try:
                    os.startfile(str(target_folder))  # type: ignore[attr-defined]
                except Exception:
                    pass
                messagebox.showinfo(
                    "Download Complete",
                    "Downloaded the SAM.gov Download All ZIP for the selected result.\n\n"
                    f"File:\n{zip_path}",
                )
                self.status_var_text.set("Downloaded SAM.gov Download All ZIP for selected result.")
                return
            except Exception as exc:
                zip_error = str(exc)
                self._log(f"SAM.gov Download All ZIP method unavailable: {zip_error}")

        if not links:
            detail = (
                "The selected result does not have known individual attachment links."
                if not zip_error else
                "The SAM.gov Download All ZIP method failed and the selected result does not have known individual attachment links."
            )
            if zip_error:
                detail += f"\n\nZIP method error:\n{zip_error}"
            messagebox.showinfo("No Attachments Found", detail)
            return

        attachment_names = self._attachment_names_for_result(result)
        saved_paths: List[Path] = []
        failures: List[str] = []

        self.status_var_text.set(f"Downloading {len(links)} individual attachment(s)...")
        self.update_idletasks()

        for index, url in enumerate(links, start=1):
            name = self._attachment_name_for_index(attachment_names, index, url)
            target_path = self._unique_path(target_folder / self._safe_filename(name))

            try:
                final_path = self._download_attachment_url(
                    url=url,
                    target_path=target_path,
                    referer=getattr(result, "ui_link", "") or "https://sam.gov/",
                )
                saved_paths.append(final_path)
                self._log(f"Downloaded attachment {index}/{len(links)}: {final_path}")
            except Exception as exc:
                message = f"{name}: {exc}"
                failures.append(message)
                self._log(f"Attachment download failed: {message}")

        if saved_paths:
            try:
                os.startfile(str(target_folder))  # type: ignore[attr-defined]
            except Exception:
                pass

        summary = f"Downloaded {len(saved_paths)} of {len(links)} individual attachment(s).\n\nFolder:\n{target_folder}"
        if zip_error:
            summary += f"\n\nSAM.gov ZIP method was tried first but was unavailable:\n{zip_error}"
        if failures:
            summary += "\n\nFailures:\n" + "\n".join(failures[:8])
            if len(failures) > 8:
                summary += f"\n...and {len(failures) - 8} more."
            messagebox.showwarning("Download Complete With Errors", summary)
        else:
            messagebox.showinfo("Download Complete", summary)

        self.status_var_text.set(f"Downloaded {len(saved_paths)} individual attachment(s) for selected result.")

    def _download_samgov_website_zip(self, result: Any, target_folder: Path) -> Path:
        notice_id = str(getattr(result, "notice_id", "") or "").strip()
        if not notice_id:
            raise RuntimeError("No SAM.gov notice ID is available for the selected result.")

        try:
            from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
            from playwright.sync_api import sync_playwright
        except Exception as exc:
            raise RuntimeError(
                "Website ZIP download requires Playwright. Install it with:\n\n"
                "py -3 -m pip install playwright\n"
                "py -3 -m playwright install chromium"
            ) from exc

        ui_link = str(getattr(result, "ui_link", "") or "").strip() or f"https://sam.gov/opp/{notice_id}/view"
        zip_base_name = self._safe_filename(
            f"{getattr(result, 'solicitation_number', '') or notice_id}_samgov_download_all.zip"
        )
        zip_target = self._unique_path(target_folder / zip_base_name)

        user_agent = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(accept_downloads=True, user_agent=user_agent)
            page = context.new_page()
            try:
                page.goto(ui_link, wait_until="domcontentloaded", timeout=WEBSITE_ZIP_TIMEOUT_MS)
                immediate_path = self._click_download_all_attachments(page, PlaywrightTimeoutError, zip_target)
                if immediate_path is not None:
                    return immediate_path
                href = self._wait_for_generated_zip_href(page, PlaywrightTimeoutError)
                return self._download_generated_zip_with_playwright(page, href, zip_target)
            finally:
                context.close()
                browser.close()

    def _click_download_all_attachments(self, page: Any, timeout_error_type: Any, zip_target: Path) -> Optional[Path]:
        selectors = [
            "a:has-text('Download All Attachments/Links')",
            "button:has-text('Download All Attachments/Links')",
            "text=Download All Attachments/Links",
        ]
        last_error: Optional[Exception] = None

        for selector in selectors:
            locator = page.locator(selector).first
            try:
                locator.wait_for(state="visible", timeout=WEBSITE_ZIP_TIMEOUT_MS)
                try:
                    with page.expect_download(timeout=5000) as download_info:
                        locator.click(timeout=20000)
                    download = download_info.value
                    suggested = self._safe_filename(download.suggested_filename or zip_target.name)
                    final_path = self._unique_path(zip_target.with_name(suggested))
                    download.save_as(str(final_path))
                    return final_path
                except timeout_error_type:
                    # SAM.gov normally injects a short-lived S3 ZIP link into the page
                    # instead of starting the download immediately. The click still happened.
                    return None
            except Exception as exc:
                last_error = exc
                continue

        raise RuntimeError(
            "Could not find the SAM.gov 'Download All Attachments/Links' control on the opportunity page. "
            f"Last error: {last_error}"
        )

    def _wait_for_generated_zip_href(self, page: Any, timeout_error_type: Any) -> str:
        selectors = [
            "a[href*='iae-fbo-attachments.s3.amazonaws.com'][href*='.zip']",
            "a[href*='.zip'][href*='X-Amz-Signature']",
            "a[href*='X-Amz-Signature']",
        ]
        last_error: Optional[Exception] = None

        for selector in selectors:
            locator = page.locator(selector).first
            try:
                locator.wait_for(state="attached", timeout=WEBSITE_ZIP_TIMEOUT_MS)
                href = str(locator.get_attribute("href") or "").strip()
                if href:
                    return href
            except Exception as exc:
                last_error = exc
                continue

        # Some SAM.gov renders put the link text near a "Download Link" label.
        try:
            html = page.content()
            match = re.search(r'href="([^"]*X-Amz-Signature[^"]*)"', html)
            if match:
                return match.group(1).replace("&amp;", "&")
        except Exception as exc:
            last_error = exc

        raise RuntimeError(
            "SAM.gov did not generate a Download All ZIP link. "
            "Controlled-only attachments may require signing in on SAM.gov. "
            f"Last error: {last_error}"
        )

    def _download_generated_zip_with_playwright(self, page: Any, href: str, target_path: Path) -> Path:
        # SAM.gov pre-signed ZIP URLs can expire in only a few seconds, so download
        # with the page request context immediately after the link is generated.
        response = page.request.get(href, timeout=DOWNLOAD_TIMEOUT_SECONDS * 1000)
        if not response.ok:
            body = ""
            try:
                body = response.text()[:250]
            except Exception:
                body = ""
            raise RuntimeError(f"Generated SAM.gov ZIP link returned HTTP {response.status}: {body}")

        headers = {str(key).lower(): value for key, value in response.headers.items()}
        header_name = self._filename_from_content_disposition(headers.get("content-disposition", ""))
        final_path = self._unique_path(target_path.with_name(self._safe_filename(header_name))) if header_name else target_path
        final_path.parent.mkdir(parents=True, exist_ok=True)
        final_path.write_bytes(response.body())
        return final_path

    def _attachment_names_for_result(self, result: Any) -> List[str]:
        notice_id = getattr(result, "notice_id", "")
        cached_item = self._cached_notice_item(notice_id) if notice_id else None
        if isinstance(cached_item, dict):
            names = cached_item.get("samgovsearchAttachmentNames")
            if isinstance(names, list):
                return [str(name) for name in names if str(name).strip()]
        return []

    def _attachment_name_for_index(self, attachment_names: List[str], index: int, url: str) -> str:
        if index - 1 < len(attachment_names):
            name = attachment_names[index - 1].strip()
            if name:
                return name

        parsed = urllib.parse.urlparse(url)
        path_name = Path(urllib.parse.unquote(parsed.path)).name
        if path_name and path_name.lower() not in {"download", "files"}:
            return path_name

        return f"attachment_{index:03d}.bin"

    def _download_attachment_url(self, url: str, target_path: Path, referer: str) -> Path:
        api_key = os.environ.get("SAM_API_KEY", "").strip()
        candidates = [url]
        if api_key:
            keyed = unified.base.append_api_key_if_missing(url, api_key)
            if keyed != url:
                candidates.append(keyed)

        last_error: Optional[Exception] = None
        for candidate in candidates:
            try:
                return self._download_candidate_url(candidate, target_path, referer)
            except Exception as exc:
                last_error = exc

        raise RuntimeError(str(last_error) if last_error else "Download failed.")

    def _download_candidate_url(self, url: str, target_path: Path, referer: str) -> Path:
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/octet-stream,*/*",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": referer or "https://sam.gov/",
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            },
        )

        try:
            with urllib.request.urlopen(request, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response:
                final_path = self._maybe_apply_response_filename(target_path, response)
                final_path.parent.mkdir(parents=True, exist_ok=True)
                with open(final_path, "wb") as handle:
                    while True:
                        chunk = response.read(DOWNLOAD_CHUNK_BYTES)
                        if not chunk:
                            break
                        handle.write(chunk)
                return final_path
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {exc.code}: {body[:250]}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Connection error: {exc}") from exc

    def _maybe_apply_response_filename(self, target_path: Path, response: Any) -> Path:
        header_name = self._filename_from_content_disposition(response.headers.get("Content-Disposition", ""))
        if header_name:
            return self._unique_path(target_path.with_name(self._safe_filename(header_name)))

        if target_path.suffix:
            return target_path

        content_type = str(response.headers.get("Content-Type", "")).split(";", 1)[0].strip().lower()
        extension = mimetypes.guess_extension(content_type) if content_type else None
        if extension:
            return self._unique_path(target_path.with_suffix(extension))

        return target_path

    @staticmethod
    def _filename_from_content_disposition(value: str) -> str:
        if not value:
            return ""

        match = re.search(r"filename\*=UTF-8''([^;]+)", value, flags=re.IGNORECASE)
        if match:
            return urllib.parse.unquote(match.group(1).strip().strip('"'))

        match = re.search(r'filename="?([^";]+)"?', value, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip()

        return ""

    @classmethod
    def _safe_folder_name(cls, value: str) -> str:
        return cls._safe_filename(value, max_length=90)

    @staticmethod
    def _safe_filename(value: str, max_length: int = 160) -> str:
        name = str(value or "").strip()
        name = re.sub(r'[:<>"/\\|?*\x00-\x1f]', "_", name)
        name = re.sub(r"\s+", " ", name).strip(" .")
        if not name:
            name = "attachment"

        reserved = {
            "CON", "PRN", "AUX", "NUL",
            "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
            "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
        }
        stem = name.split(".", 1)[0].upper()
        if stem in reserved:
            name = f"_{name}"

        if len(name) > max_length:
            path = Path(name)
            suffix = path.suffix
            stem_text = path.stem[: max(1, max_length - len(suffix) - 1)]
            name = f"{stem_text}{suffix}" if suffix else name[:max_length]

        return name

    @staticmethod
    def _unique_path(path: Path) -> Path:
        if not path.exists():
            return path

        stem = path.stem
        suffix = path.suffix
        parent = path.parent
        counter = 2
        while True:
            candidate = parent / f"{stem} ({counter}){suffix}"
            if not candidate.exists():
                return candidate
            counter += 1


def main() -> None:
    app = SamGovSearchApp()
    app.mainloop()


if __name__ == "__main__":
    main()
