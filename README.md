# SAM.gov Search

A Windows-friendly Python Tkinter GUI for batch searching SAM.gov opportunities.

The app uses **one UI** and **one launcher**:

```text
run_samgovsearch.bat
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
- One desktop UI: `samgovsearch_responsive.py`.
- Responsive layout: the left options panel scrolls and the right results area resizes when the window is not maximized.
- Batch search one keyword, part number, solicitation number, or notice ID per line.
- Duplicate batch entries are removed before searching.
- Search source selector:
  - Website/Internal Search, no key
  - Official API Search
  - Hybrid Search
- Settings button to paste and save `SAM_API_KEY` to the Windows user environment.
- Settings button links to SAM.gov account details and the official SAM.gov API docs.
- Click result column headers to sort ascending or descending.
- Download known public attachments for the selected result row.
- Optional checkbox: search all date ranges.
- Optional checkbox: search all statuses.
- Optional filter: only show opportunities with attachments.
- Optional attachment filters:
  - minimum attachment count
  - minimum total attachment size in MB
- Attachment sizes in internal and hybrid modes come from the SAM.gov internal resources endpoint when available.
- Local cache/index reuses prior responses before spending new requests.
- Export results to CSV.
- Double click a result row to open the SAM.gov opportunity link.

## Requirements

- Python 3.10 or newer recommended.
- Tkinter. This is included with the standard Windows Python installer.
- No third-party Python packages are required for the unified Tkinter app.

## Setup and launch

Double click:

```text
run_samgovsearch.bat
```

The BAT launcher will:

- start from the repo folder automatically
- launch `samgovsearch_responsive.py`
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
python .\samgovsearch_responsive.py
```

For your Windows user profile permanently:

```powershell
[Environment]::SetEnvironmentVariable("SAM_API_KEY", "paste_your_sam_api_key_here", "User")
```

Close and reopen PowerShell after setting it permanently.

## Sorting results

Click any result column header to sort the visible results.

- First click sorts ascending.
- Second click on the same column sorts descending.
- The selected column shows an up or down arrow.

Sorting reorders the internal result list too, so double clicking a sorted row still opens the correct SAM.gov opportunity link.

## Downloading attachments

Select one result row and click:

```text
Download Attachments for Selected Result
```

The app will ask for a folder, create a subfolder using the solicitation number, notice ID, or title, then download every known attachment link for that result.

Website/Internal and Hybrid modes usually provide the best attachment metadata because they call:

```text
https://sam.gov/api/prod/opps/v3/opportunities/{notice_id}/resources
```

That endpoint can expose attachment names, resource IDs, and sizes. Official API mode can still download from `resourceLinks` when those links are present. If `SAM_API_KEY` is set, the downloader will also retry SAM.gov links with the key appended when needed.

Downloaded filenames are sanitized for Windows and duplicate names are automatically numbered.

## Local cache and index

The app stores successful official API responses and internal search results locally so later searches can reuse the same data before spending another request.

The default cache folder is:

```text
%LOCALAPPDATA%\SAMGovSearch\ApiCache
```

The cache stores:

- `queries\` exact query responses keyed by query parameters
- `notices\` one file per SAM.gov notice ID found in results
- `index.jsonl` append-only cache activity log
- `README_DO_NOT_DELETE.txt` marker file

This folder is intentionally placed in user-local app data instead of the Windows temp folder because temp folders are designed to be cleaned or deleted. No user-owned folder can be made truly undeletable, but the app recreates the cache folder if it is missing. If the cache is deleted, only the cached data is lost.

To force a different cache location, set:

```bat
setx SAMGOVSEARCH_CACHE_DIR "C:\Path\To\SamGovSearchCache"
```

By default cached data does not expire. To set a max cache age, set days with:

```bat
setx SAMGOVSEARCH_CACHE_MAX_AGE_DAYS "30"
```

Use `0` or leave it unset to keep cached data indefinitely.
