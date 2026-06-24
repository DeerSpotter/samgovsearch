# SAM.gov Search

A small Python Tkinter GUI for batch searching SAM.gov Contract Opportunities with the public SAM.gov Opportunities API.

The app reads your API key from:

```text
EnvironmentVariable=SAM_API_KEY
```

No API key is stored in the app, written to disk, or entered into the GUI.

## Features

- Batch search one keyword, part number, solicitation number, or notice ID per line.
- Duplicate batch entries are removed before searching.
- Auto search mode for mixed batches:
  - title search for normal keywords
  - solicitation number search for values that look like part numbers or solicitation numbers
  - notice ID search for long hexadecimal notice IDs
- Optional checkbox: search all date ranges.
- Optional checkbox: search all statuses.
- Optional filter: only show opportunities with attachments.
- When attachment filtering is enabled, extra fields appear:
  - minimum attachment count
  - minimum total attachment size in MB
- Blank attachment fields use defaults:
  - minimum attachment count = `1`
  - minimum total attachment size = `0 MB`
- Export results to CSV.
- Double click a result row to open the SAM.gov opportunity link.

## Requirements

- Python 3.10 or newer recommended.
- Tkinter. This is included with the standard Windows Python installer.
- No third-party Python packages are required.

## Setup

### Easiest Windows launch

Double click:

```text
run_samgovsearch.bat
```

The BAT launcher will:

- start from the repo folder automatically
- launch `samgovsearch_all_status.py` when it exists, otherwise fall back to `samgovsearch.py`
- use `py -3` first, then fall back to `python`
- warn you if Python is missing
- warn you if `SAM_API_KEY` is not set
- let you paste a SAM.gov API key for that launch only

### Windows Command Prompt

```bat
setx SAM_API_KEY "paste_your_sam_api_key_here"
```

Close and reopen Command Prompt after running `setx`.

Then run:

```bat
python samgovsearch_all_status.py
```

Or use the launcher:

```bat
run_samgovsearch.bat
```

### Windows PowerShell

For the current PowerShell window only:

```powershell
$env:SAM_API_KEY = "paste_your_sam_api_key_here"
python .\samgovsearch_all_status.py
```

For your Windows user profile permanently:

```powershell
[Environment]::SetEnvironmentVariable("SAM_API_KEY", "paste_your_sam_api_key_here", "User")
```

Close and reopen PowerShell after setting it permanently.

## Date behavior

SAM.gov requires a posted date range for the Opportunities API. The SAM.gov API date format is:

```text
MM/DD/YYYY
```

The GUI launcher defaults to:

- Posted From: today minus 364 days
- Posted To: today

The app intentionally stays below the exact one-calendar-year boundary because SAM.gov can reject a request such as `06/24/2025` through `06/24/2026` with a date range error.

The manual date range must be less than one calendar year. If you need to search wider than one year, check:

```text
Search all date ranges
```

When this is checked, the app disables the Posted From and Posted To fields and searches from:

```text
01/01/2018 through today
```

It does that by splitting the search into 364-day SAM.gov API windows. This avoids invalid no-date requests and avoids the SAM.gov posted date range boundary error.

## Status behavior

The Status dropdown defaults to:

```text
active
```

To include all SAM.gov statuses, check:

```text
Search all statuses
```

When this is checked, the app disables the Status dropdown and does not send the `status` filter to SAM.gov. SAM.gov documents the status parameter as optional and lists these accepted values:

```text
active, inactive, archived, cancelled, deleted
```

## Batch dedupe behavior

Before searching, the app removes duplicate batch entries. Dedupe is case-insensitive and ignores extra interior whitespace for matching.

Example:

```text
Patriot
patriot
PATRIOT
```

Only the first `Patriot` line is searched.

## Search modes

### Auto

Best for mixed pasted batches.

For each line, Auto tries:

- `title`
- `solnum` when the term contains at least one digit
- `noticeid` when the term looks like a long hexadecimal SAM.gov notice ID

### Title

Uses the SAM.gov `title` parameter.

### Solicitation Number

Uses the SAM.gov `solnum` parameter.

### Notice ID

Uses the SAM.gov `noticeid` parameter.

### Title + Solicitation Number

Always searches both title and solicitation number for each line.

## Attachment filtering

When **Only show opportunities with attachments** is checked:

- opportunities with fewer than the minimum attachment count are removed
- if minimum total size is blank or `0`, the app only checks that links exist in `resourceLinks`
- if minimum total size is greater than `0`, the app attempts to read `Content-Length` from each attachment link and compares the total size in MB

Some SAM.gov attachment links may not report a file size. If a minimum size is required and the total known size is below the threshold, the result is filtered out.

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

## API reference

The app uses the public SAM.gov Get Opportunities API v2 endpoint:

```text
https://api.sam.gov/opportunities/v2/search
```

Official documentation:

```text
https://open.gsa.gov/api/get-opportunities-public-api/
```
