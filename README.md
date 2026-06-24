# SAM.gov Search

A Windows-friendly Python Tkinter GUI for batch searching SAM.gov opportunities.

The app now uses **one UI** and **one launcher**:

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
- One desktop UI: `samgovsearch_unified.py`.
- Batch search one keyword, part number, solicitation number, or notice ID per line.
- Duplicate batch entries are removed before searching.
- Search source selector:
  - Website/Internal Search, no key
  - Official API Search
  - Hybrid Search
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
- launch `samgovsearch_unified.py`
- use `py -3` first, then fall back to `python`
- warn you if Python is missing
- allow no-key searching in Website/Internal mode
- show a warning if `SAM_API_KEY` is not set because Official API mode and Hybrid official enrichment need it

## Optional SAM_API_KEY setup

You only need this for Official API mode or Hybrid official enrichment.

### Windows Command Prompt

```bat
setx SAM_API_KEY "paste_your_sam_api_key_here"
```

Close and reopen Command Prompt after running `setx`.

### Windows PowerShell

For the current PowerShell window only:

```powershell
$env:SAM_API_KEY = "paste_your_sam_api_key_here"
python .\samgovsearch_unified.py
```

For your Windows user profile permanently:

```powershell
[Environment]::SetEnvironmentVariable("SAM_API_KEY", "paste_your_sam_api_key_here", "User")
```

Close and reopen PowerShell after setting it permanently.

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
setx SAMGOVSEARCH_CACHE_DIR "C:\\Path\\To\\SamGovSearchCache"
```

By default cached data does not expire. To set a max cache age, set days with:

```bat
setx SAMGOVSEARCH_CACHE_MAX_AGE_DAYS "30"
```

Use `0` or leave it unset to keep cached data indefinitely.

## Date behavior

The GUI defaults to:

- Posted From: today minus 364 days
- Posted To: today

The app intentionally stays below the exact one-calendar-year boundary because SAM.gov can reject a request such as `06/24/2025` through `06/24/2026` with a date range error.

To search wider than one year, check:

```text
Search all date ranges
```

When this is checked, the app disables the Posted From and Posted To fields and searches from:

```text
01/01/2018 through today
```

It splits the run into 364-day windows.

## Status behavior

The Status dropdown defaults to:

```text
active
```

To include all statuses, check:

```text
Search all statuses
```

When checked, the app disables the Status dropdown. In Official API mode it omits the `status` filter. In Website/Internal mode it omits the website/internal active filter.

## Attachment filtering

When **Only show opportunities with attachments** is checked:

- opportunities with fewer than the minimum attachment count are removed
- blank minimum attachment count defaults to `1`
- blank minimum total size defaults to `0 MB`
- if minimum total size is greater than `0`, the app compares the known total attachment size in MB

In Website/Internal and Hybrid modes, attachment metadata comes from:

```text
https://sam.gov/api/prod/opps/v3/opportunities/{notice_id}/resources
```

This is useful because the resources endpoint can expose attachment names, resource IDs, and sizes.

## Batch dedupe behavior

Before searching, the app removes duplicate batch entries. Dedupe is case-insensitive and ignores extra interior whitespace for matching.

Example:

```text
Patriot
patriot
PATRIOT
```

Only the first `Patriot` line is searched.

## Output columns

The CSV export includes:

- keyword
- matched search field
- notice ID
- title
- solicitation number
- type
- posted date
- response deadline
- active flag
- organization
- NAICS
- PSC
- attachment count
- attachment total MB
- attachment size note
- SAM link
- resource links

## Notes

The Website/Internal Search mode is based on the endpoint structure used by `DeerSpotter/sam-gov-scraper`. It avoids official API quota for broad discovery, but it is not an officially documented public API contract. Keep Official API mode available as the stable fallback.
