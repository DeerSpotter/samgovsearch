# SAM.gov Download All ZIP Capture Userscript

This is a test harness for figuring out the exact browser behavior behind SAM.gov's **Download All Attachments/Links** button.

The userscript is here:

```text
userscripts/samgov-download-zip-capture.user.js
```

## Why this exists

SAM.gov does not show the bulk ZIP URL on the page immediately. The page first shows a **Download All Attachments/Links** button. After clicking it, SAM.gov injects a temporary S3 ZIP link into the page.

Testing showed that the generated S3 link can expire almost immediately. One observed link had:

```text
X-Amz-Expires=9
```

That means copy and paste is usually too slow. The script now has an **Instant Download All ZIP** mode that arms capture, clicks SAM.gov's button, catches the generated S3 ZIP URL, and starts the browser download immediately.

## Install

1. Install Tampermonkey in your browser.
2. Open Tampermonkey Dashboard.
3. Create a new script.
4. Paste the contents of:

```text
userscripts/samgov-download-zip-capture.user.js
```

5. Save it.
6. Open a SAM.gov opportunity page.

The script runs on:

```text
https://sam.gov/opp/*/view*
https://sam.gov/opp/*
```

## How to test the fast ZIP capture

1. Open an opportunity page on SAM.gov.
2. Scroll to **Attachments/Links**.
3. In the bottom-right **SAM ZIP Capture** panel, click:

```text
Instant Download All ZIP
```

4. The script will:
   - arm instant mode
   - click SAM.gov's **Download All Attachments/Links** button
   - capture the first generated S3 ZIP URL
   - immediately start the download with `GM_download`

Use **Copy Latest URL** only for debugging. Copied URLs may already be expired by the time they are pasted into a new tab.

## Other buttons

- **Instant Download All ZIP**: best test. Clicks SAM.gov and downloads the generated ZIP immediately.
- **Click Only**: clicks SAM.gov's button but does not auto download unless the URL is captured and you manually press download.
- **Fast Download Latest**: immediately downloads the most recently captured URL without a save prompt.
- **Copy Latest URL**: copies the latest URL, but it may expire in seconds.
- **Clear**: clears captured URLs and download state.

## What the script captures

The script watches several places where the short-lived ZIP URL might appear:

- DOM mutations after SAM.gov injects the **Download Link / click here** anchor
- anchor `href` attributes
- `fetch()` request and response URLs
- `fetch()` text/json/html response bodies
- `XMLHttpRequest` request and response URLs
- `XMLHttpRequest` text/json/html response bodies

It looks for ZIP or signed AWS URLs like:

```text
https://iae-fbo-attachments.s3.amazonaws.com/...zip?...X-Amz-Algorithm=AWS4-HMAC-SHA256...
```

## Important limitations

- SAM.gov generated ZIP links can expire in about 9 seconds.
- Do not rely on copied ZIP links except for debugging.
- Controlled attachments still require normal SAM.gov authorization.
- This script does not bypass SAM.gov sign-in, controlled-access, or authorization rules.
- If SAM.gov does not generate a ZIP link, the panel will stay in waiting mode.
- This is a debugging tool. The Python app now mirrors the same idea by clicking the SAM.gov button and downloading immediately through Playwright.

## What to send back when testing

Copy the panel status and browser console lines that start with:

```text
[SAM ZIP Capture]
```

Useful test results:

- Whether **Instant Download All ZIP** saved the ZIP.
- Which source captured the ZIP URL, such as `mutation added anchor`, `fetch response body`, or `xhr response body`.
- Whether **Click Only** found and clicked the SAM.gov button.
- Whether **Fast Download Latest** succeeds if pressed immediately after capture.
