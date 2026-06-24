# SAM.gov Browser Mode

Browser Mode is a second search path for this repo. It renders the public SAM.gov website inside the app instead of starting with the SAM.gov Opportunities API.

Use this when the API quota is in the way or when you want to visually inspect the same page a normal SAM.gov browser search shows.

## Launch

Double click:

```text
run_samgovsearch_browser.bat
```

The BAT launches `samgovsearch_browser_hybrid.py` when present. It falls back to `samgovsearch_browser.py` if the hybrid file is missing.

The first time, install the browser dependencies:

```bat
py -3 -m pip install -r requirements-browser.txt
```

If your machine uses `python` instead of `py -3`, use:

```bat
python -m pip install -r requirements-browser.txt
```

## What it does

- Opens an embedded browser using PyQt6 WebEngine.
- Accepts a batch list of keywords, part numbers, or solicitation numbers.
- Removes duplicate batch entries before searching.
- Generates normal SAM.gov website search URLs for each batch item.
- Lets you step through the batch with **Search First** and **Next Batch Item**.
- Reads the currently visible page content to extract opportunity-like rows.
- Can hide non-matching visible cards on the page.
- Can export extracted visible results to CSV.

## Hybrid API enrichment

The hybrid path is designed to reduce API usage.

Workflow:

1. Use browser mode to search SAM.gov normally.
2. Click **Extract Visible Results**.
3. Review the visible results table.
4. Click **Hybrid API Enrich Results**.

Hybrid enrichment uses `SAM_API_KEY`, but only after browser results are extracted. It attempts one API request per extracted result when a notice ID and posted date are available. That is much cheaper than searching every keyword across every date window through the API.

The enrichment adds these fields to the table and CSV when available:

- Notice ID
- Posted Date
- Solicitation Number
- API Attachment Count
- API Resource Links
- API Attachment Status

If the browser result does not expose a notice ID, that row is skipped. If the browser result does not expose a posted date, the tool uses a safe 364-day fallback window because the SAM.gov Opportunities API requires `postedFrom` and `postedTo`.

## Attachment filtering limitation

Browser Mode can only filter from visible page text. The checkbox:

```text
Only keep results with visible attachment/document text
```

looks for words such as attachment, document, download, resource, and file in the rendered page text. It is not the same as the API mode attachment check, because the API returns structured `resourceLinks` while the public SAM.gov website may not show every attachment detail on the search-result card.

For exact attachment count and attachment link export, use **Hybrid API Enrich Results** after extracting visible browser results.

## Recommended workflow

1. Launch `run_samgovsearch_browser.bat`.
2. Paste the batch list into the left text box.
3. Click **Search First**.
4. Wait for SAM.gov to load.
5. Click **Extract Visible Results**.
6. Click **Next Batch Item** and repeat.
7. Click **Hybrid API Enrich Results** if you need exact API attachment counts and links.
8. Export CSV when done.

## Notes

This mode depends on SAM.gov's rendered page content. If SAM.gov changes the website layout, extraction may need updates. The internal browser still lets you manually search and inspect results even if extraction needs adjustment.
