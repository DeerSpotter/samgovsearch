# SAM.gov Search

A small Python Tkinter GUI for batch searching SAM.gov Contract Opportunities with the public SAM.gov Opportunities API.

The app reads your API key from:

```text
EnvironmentVariable=SAM_API_KEY
```

No API key is stored in the app, written to disk, or entered into the GUI.

## Features

- Batch search one keyword, part number, solicitation number, or notice ID per line.
- Auto search mode for mixed batches:
  - title search for normal keywords
  - solicitation number search for values that look like part numbers or solicitation numbers
  - notice ID search for long hexadecimal notice IDs
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

### Windows Command Prompt

```bat
setx SAM_API_KEY "paste_your_sam_api_key_here"
```

Close and reopen Command Prompt after running `setx`.

Then run:

```bat
python samgovsearch.py
```

### Windows PowerShell

For the current PowerShell window only:

```powershell
$env:SAM_API_KEY = "paste_your_sam_api_key_here"
python .\samgovsearch.py
```

For your Windows user profile permanently:

```powershell
[Environment]::SetEnvironmentVariable("SAM_API_KEY", "paste_your_sam_api_key_here", "User")
```

Close and reopen PowerShell after setting it permanently.

## Date behavior

SAM.gov requires a posted date range for the Opportunities API.

The GUI defaults to:

- Posted From: today minus 365 days
- Posted To: today

The SAM.gov API date format is:

```text
MM/DD/YYYY
```

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
