# SAM.gov Search

A Windows-friendly Python Tkinter GUI for batch searching SAM.gov opportunities.

The app uses **one UI** and **one launcher**:

```text
run_samgovsearch.bat
```

The launcher opens:

```text
samgovsearch_pro_download_folder.py
```

Inside the UI, choose the search source:

1. **Website/Internal Search - no API key**
2. **Official API Search - uses SAM_API_KEY**
3. **Hybrid - internal search + official API enrich**

## Why there are three modes

### Website/Internal Search - no API key

This mode uses the same SAM.gov website/internal endpoints used by the `sam-gov-scraper` project:

```text
https://sam.gov/api/prod/sgs/v1/search/
https://sam.gov/api/prod/opps/v2/opportunities/{notice_id}
https://sam.gov/api/prod/opps/v3/opportunities/{notice_id}/resources
```

It does not require `SAM_API_KEY`.

It is best for broad discovery when you do not want to spend official SAM.gov API quota.

Because these are website/internal endpoints, they are not as stable as the official public API. If SAM.gov changes its frontend API, this mode may need maintenance.

### Official API Search - uses SAM_API_KEY

This mode uses the official SAM.gov Opportunities API:

```text
https://api.sam.gov/opportunities/v2/search
```

It requires:

```text
EnvironmentVariable=SAM_API_KEY
```

It is best for structured official API results, but it can hit SAM.gov quota limits.

### Hybrid - internal search + official API enrich

This mode searches broadly with the no-key website/internal endpoint first. After results are found, it checks the local cache and then uses the official API only for per-result enrichment when `SAM_API_KEY` is available.

This reduces official API usage because it avoids using the official API for broad search sweeps.

If `SAM_API_KEY` is not set, Hybrid mode can still run as internal-only enrichment.

## Features

- One launcher: `run_samgovsearch.bat`.
- One desktop UI: `samgovsearch_pro_download_folder.py`.
- Responsive layout: the left options panel scrolls and the right results area resizes when the window is not maximized.
- Batch search one keyword, part number, solicitation number, or notice ID per line.
- Duplicate batch entries are removed before searching.
- Default prefilled keywords are only `Patriot` and `frequency converter`.
- Search source selector:
  - Website/Internal Search, no key
  - Official API Search
  - Hybrid Search
- Settings button to paste and save `SAM_API_KEY` to the Windows user environment.
- Settings button links to SAM.gov account details and the official SAM.gov API docs.
- Search within the currently loaded results without running another SAM.gov search.
- Hide/exclude loaded results by comma-separated keywords without running another SAM.gov search.
- Search within results supports simple text matching plus `*` and `?` wildcards.
- Attachment name filtering for loaded results and cached SQLite searches.
- SQLite local index for fast local searching of previously cached SAM.gov results.
- Cache manager for cache folder, SQLite rebuild, CSV export, and cache cleanup.
- Selected result enrichment/details panel with attachment names, cache source, links, and description when available.
- Tunable retry/rate-limit settings.
- Optional checkbox: ignore cached searches for the current run while still writing fresh successful responses back to cache.
- Click result column headers to sort ascending or descending.
- Download attachments for the selected result row.
  - Downloads go directly to the default Downloads folder or a saved custom folder.
  - No folder picker is shown during the download flow, so short-lived SAM.gov ZIP links are not wasted waiting for user input.
  - Tries SAM.gov's website-style **Download All Attachments/Links** ZIP method first.
  - Falls back to individual public attachment downloads when the ZIP method is unavailable.
- Optional checkbox: search all date ranges.
- Optional checkbox: search all statuses.
- Optional filter: only show opportunities with attachments.
- Optional attachment filters:
  - minimum attachment count
  - minimum total attachment size in MB
- Attachment sizes in internal and hybrid modes come from the SAM.gov internal resources endpoint when available.
- Local cache/index reuses prior responses before spending new requests.
- Export displayed results to CSV.
- Double click a displayed result row to open the correct SAM.gov opportunity link.

## Requirements

- Python 3.10 or newer recommended.
- Tkinter. This is included with the standard Windows Python installer.
- SQLite. This is included with standard Python.
- No third-party Python packages are required for searching, sorting, caching, SQLite indexing, CSV export, result filtering, exclusion filtering, or individual attachment downloads.
- Optional for the SAM.gov website-style ZIP download method: Playwright.

Install the optional ZIP download dependency with:

```bat
py -3 -m pip install -r requirements-website-download.txt
py -3 -m playwright install chromium
```

The app still launches without Playwright. If Playwright is missing, the download button will skip the website ZIP method and fall back to individual attachment links when available.

## Setup and launch

Double click:

```text
run_samgovsearch.bat
```

The BAT launcher will:

- start from the repo folder automatically
- launch `samgovsearch_pro_download_folder.py`
- use `py -3` first, then fall back to `python`
- warn you if Python is missing
- allow no-key searching in Website/Internal mode
- let you add `SAM_API_KEY` from Settings inside the app

## Responsive window behavior

The current launcher opens the responsive UI. It is designed to work when the window is not maximized:

- The left search/settings panel has its own vertical scrollbar.
- The results table expands and shrinks with the window.
- The results table keeps horizontal and vertical scrollbars for wide result data.
- The split between options and results can be adjusted by dragging the divider.
- The minimum window size is reduced so controls remain reachable on smaller screens.

## SAM_API_KEY setup from the app

You only need `SAM_API_KEY` for Official API mode or Hybrid official enrichment.

In the app:

1. Click **Settings / SAM_API_KEY**.
2. Paste the SAM.gov API key.
3. Click **Save Key**.

On Windows, the app runs:

```bat
setx SAM_API_KEY "your_key"
```

It also applies the key to the currently running app immediately. Already-open terminals may not see the new value until they are reopened.

The settings window also includes:

- **Open SAM Account** - opens the SAM.gov account details page where users can generate or view their key after signing in.
- **Open API Docs** - opens the official SAM.gov Opportunities API documentation.

SAM.gov requires the API key to be generated or viewed inside the signed-in account flow, including password confirmation, so the app cannot generate the key automatically.

## Manual SAM_API_KEY setup

### Windows Command Prompt

```bat
setx SAM_API_KEY "paste_your_sam_api_key_here"
```

Close and reopen Command Prompt after running `setx`.

### Windows PowerShell

For the current PowerShell window only:

```powershell
$env:SAM_API_KEY = "paste_your_sam_api_key_here"
python .\samgovsearch_pro_download_folder.py
```

For your Windows user profile permanently:

```powershell
[Environment]::SetEnvironmentVariable("SAM_API_KEY", "paste_your_sam_api_key_here", "User")
```

Close and reopen PowerShell after setting it permanently.

## SQLite local index

The pro UI stores a local SQLite index beside the existing JSON cache:

```text
%LOCALAPPDATA%\SAMGovSearch\ApiCache\samgov_index.sqlite
```

The JSON cache is still the canonical cache. The SQLite database is a fast searchable index built from cached notice JSON files.

Use the **SQLite Local Index** section for:

- **Search Cached Results**: searches local indexed notices only. It does not call SAM.gov.
- **Rebuild Index**: rebuilds SQLite from the JSON notice cache.
- **Attachment Name Filter**: filters by attachment names, such as `drawing`, `parts list`, `*.xlsx`, or `*CDRL*`.

Cached-result search checks title, solicitation number, notice ID, type, organization, NAICS, PSC, attachment names, and description where cached.

## Search and hide within loaded results

Use **Filter Current Results** after a search finishes or while results are still loading.

There are two local result fields:

- **Show results containing**: only displays loaded results that match the typed text or wildcard.
- **Hide results containing any of these comma-separated keywords**: hides loaded results if any exclude keyword is contained in the result data.

These fields are local only:

- They do not call SAM.gov again.
- They do not spend official API quota.
- They do not re-run the internal website search.
- Clearing either field restores the currently loaded rows that are not hidden by another local filter.

The show filter checks the same data exported to CSV, including keyword, title, solicitation number, notice ID, type, posted date, organization, NAICS, PSC, SAM link, and resource links.

The hide filter checks the row data, attachment names, cached description, solicitation number, and agency path when available.

Show examples:

```text
raytheon
```

```text
*patriot*spares*
```

```text
W31P4Q*
```

Hide examples:

```text
amendment, award, cancelled
```

```text
sources sought, draft
```

When filtered, CSV export exports the displayed result rows, not the hidden rows.

## Attachment name filtering

Use **Attachment Name Filter** in the SQLite Local Index section.

It applies to loaded results and cached SQLite searches. It checks cached attachment names and resource links.

Examples:

```text
drawing
```

```text
*parts list*
```

```text
*.xlsx
```

Clearing the attachment name filter restores the currently loaded result set without re-searching SAM.gov.

## Selected result enrichment view

The bottom details panel updates when you select a result row.

It shows available details such as:

- title
- solicitation number
- notice ID
- type
- posted date
- response deadline
- organization
- NAICS / PSC
- attachment count and total size
- attachment names
- resource links
- cache source and cache file
- description when cached

This panel is read-only and does not call SAM.gov by itself.

## Cache manager

Click **Cache Manager** to manage local cache files.

It shows:

- JSON cache root
- number of cached query responses
- number of cached notice records
- SQLite index path
- number of indexed notices
- number of indexed attachment references
- last SQLite rebuild time

Actions:

- **Open Folder**
- **Rebuild Index**
- **Export Index CSV**
- **Clear Query Cache**
- **Clear SQLite Index**

Clearing the SQLite index does not delete the JSON notice cache. Rebuild Index can recreate SQLite from the JSON notice cache.

## Search behavior settings

Click **Search Settings** to adjust:

- Enable SQLite local index
- Automatically index new results as they arrive
- Rebuild index automatically if empty before local cache search
- Retry transient timeout/server/network errors
- Retry attempts
- Retry backoff seconds
- Normal Official API delay seconds
- All-date Official API delay seconds
- Website/Internal delay seconds
- Hybrid Official Enrich delay seconds

Quota/rate-limit errors are not retried because retrying those usually wastes requests. The app stops or falls back to cached/internal data when SAM.gov returns quota or rate-limit errors.

Settings are saved beside the cache:

```text
%LOCALAPPDATA%\SAMGovSearch\ApiCache\samgovsearch_settings.json
```

## Download folder options

Attachment downloads no longer ask for a folder during the download attempt. By default, the app saves to:

```text
%USERPROFILE%\Downloads
```

To change this before downloading:

1. Click **Download Folder Options**.
2. Choose a custom folder with **Browse**, or leave the field blank to use Downloads.
3. Click **Save**.

The download setting is saved beside the cache:

```text
%LOCALAPPDATA%\SAMGovSearch\ApiCache\samgovsearch_download_settings.json
```

This matters because SAM.gov generated ZIP links can expire in only a few seconds. Avoiding a folder picker helps the app download the ZIP immediately after the URL appears.

## Sorting results

Click any result column header to sort the loaded results.

- First click sorts ascending.
- Second click on the same column sorts descending.
- The selected column shows an up or down arrow.

Sorting reorders the internal result list too, so double clicking a sorted and filtered row still opens the correct SAM.gov opportunity link.

## Downloading attachments

Select one result row and click:

```text
Download Attachments for Selected Result
```

The app immediately creates a subfolder under the configured download root using the solicitation number, notice ID, or title. It does not prompt for a folder at download time.

The preferred method is the same user-visible flow SAM.gov uses:

1. Open the selected SAM.gov opportunity page in a headless Chromium session.
2. Click **Download All Attachments/Links**.
3. Wait for SAM.gov to generate the short-lived ZIP download link.
4. Download that ZIP immediately into the configured download folder.

This method requires the optional Playwright dependency:

```bat
py -3 -m pip install -r requirements-website-download.txt
py -3 -m playwright install chromium
```

If Playwright is not installed, if SAM.gov does not generate a ZIP link, or if the selected result cannot be opened by notice ID, the app falls back to downloading individual known public attachment links.

Website/Internal and Hybrid modes usually provide the best individual attachment metadata because they call:

```text
https://sam.gov/api/prod/opps/v3/opportunities/{notice_id}/resources
```

That endpoint can expose attachment names, resource IDs, and sizes. Official API mode can still download from `resourceLinks` when those links are present. If `SAM_API_KEY` is set, the individual downloader will also retry SAM.gov links with the key appended when needed.

Controlled attachments still require normal SAM.gov authorization. The app does not bypass SAM.gov sign-in or controlled-access rules.
