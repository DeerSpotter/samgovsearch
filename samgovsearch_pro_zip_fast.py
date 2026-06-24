from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

from samgovsearch_app import WEBSITE_ZIP_TIMEOUT_MS
from samgovsearch_pro_search_help import SamGovSearchProSearchHelpApp


class SamGovSearchProZipFastApp(SamGovSearchProSearchHelpApp):
    """Final user-facing app with faster SAM.gov Download All ZIP handling.

    SAM.gov pre-signed S3 ZIP links can expire in only a few seconds. The base
    downloader waited briefly to see whether the click produced a browser
    download. This wrapper skips that delay, clicks the SAM.gov control, waits
    only for the injected ZIP href, and immediately streams the ZIP through the
    Playwright page request context.
    """

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
                locator.click(timeout=20000)
                self._log(
                    "Clicked SAM.gov Download All Attachments/Links. "
                    "Waiting for the short-lived ZIP URL and downloading it immediately."
                )
                return None
            except Exception as exc:
                last_error = exc
                continue

        raise RuntimeError(
            "Could not find the SAM.gov 'Download All Attachments/Links' control on the opportunity page. "
            f"Last error: {last_error}"
        )

    def _wait_for_generated_zip_href(self, page: Any, timeout_error_type: Any) -> str:
        script = """
        () => {
            const anchors = Array.from(document.querySelectorAll('a[href]'));
            for (const anchor of anchors) {
                const href = anchor.href || anchor.getAttribute('href') || '';
                if (href.includes('X-Amz-Signature') || href.includes('iae-fbo-attachments.s3.amazonaws.com')) {
                    return href;
                }
            }
            const html = document.documentElement ? document.documentElement.innerHTML : '';
            const match = html.match(/href=[\"']([^\"']*X-Amz-Signature[^\"']*)[\"']/i);
            return match ? match[1].replace(/&amp;/g, '&') : '';
        }
        """
        try:
            handle = page.wait_for_function(script, timeout=WEBSITE_ZIP_TIMEOUT_MS, polling=100)
            href = str(handle.json_value() or "").strip()
            if href:
                self._log("Captured SAM.gov short-lived ZIP URL. Starting immediate download.")
                return href.replace("&amp;", "&")
        except Exception as exc:
            last_error = exc
        else:
            last_error = None

        try:
            html = page.content()
            match = re.search(r'href=["\\']([^"\\']*X-Amz-Signature[^"\\']*)["\\']', html)
            if match:
                self._log("Captured SAM.gov ZIP URL from page HTML. Starting immediate download.")
                return match.group(1).replace("&amp;", "&")
        except Exception as exc:
            last_error = exc

        raise RuntimeError(
            "SAM.gov did not generate a Download All ZIP link. "
            "Controlled-only attachments may require signing in on SAM.gov. "
            f"Last error: {last_error}"
        )

    def _download_generated_zip_with_playwright(self, page: Any, href: str, target_path: Path) -> Path:
        try:
            return super()._download_generated_zip_with_playwright(page, href, target_path)
        except Exception as exc:
            message = str(exc)
            if "Request has expired" in message or "AccessDenied" in message or "X-Amz-Expires" in message:
                raise RuntimeError(
                    "SAM.gov generated the ZIP URL, but the S3 request expired before it could be saved. "
                    "These links may only last about 9 seconds. Try again with Playwright installed and avoid pausing "
                    "at any save prompt."
                ) from exc
            raise


def main() -> None:
    app = SamGovSearchProZipFastApp()
    app.mainloop()


if __name__ == "__main__":
    main()
