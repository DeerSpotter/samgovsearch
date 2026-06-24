# SAM.gov Download All ZIP Capture Userscript

This is a test harness for figuring out the exact browser behavior behind SAM.gov's **Download All Attachments/Links** button.

The userscript is here:

```text
userscripts/samgov-download-zip-capture.user.js
```

## Why this exists

SAM.gov does not show the bulk ZIP URL on the page immediately. The page first shows a **Download All Attachments/Links** button. After clicking it, SAM.gov injects a temporary S3 ZIP link into the page.

The Python app currently falls back to downloading individual public attachments if it cannot capture that ZIP flow. This script lets us test the real browser behavior directly in SAM.gov before hardening the Python implementation.

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

## How to test

1. Open an opportunity page on SAM.gov.
2. Scroll to **Attachments/Links**.
3. Use either:
   - the normal SAM.gov **Download All Attachments/Links** button, or
   - the userscript panel button **Click Download All**.
4. Watch the bottom-right **SAM ZIP Capture** panel.
5. When SAM.gov generates the ZIP link, the panel should show the captured URL.
6. Click **Copy Latest URL** or **Download Latest**.

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

- SAM.gov generated ZIP links are very short lived. Download or copy them immediately.
- Controlled attachments still require normal SAM.gov authorization.
- This script does not bypass SAM.gov sign-in, controlled-access, or authorization rules.
- If SAM.gov does not generate a ZIP link, the panel will stay in waiting mode.
- This is a debugging tool. Once we know which event reliably exposes the ZIP URL, the Python downloader can be updated to use the same method.

## What to send back when testing

Copy the panel status and browser console lines that start with:

```text
[SAM ZIP Capture]
```

Useful test results:

- Whether the panel captured a ZIP URL.
- Which source captured it, such as `mutation added anchor`, `fetch response body`, or `xhr response body`.
- Whether **Click Download All** found and clicked the SAM.gov button.
- Whether **Download Latest** successfully saved the ZIP.
