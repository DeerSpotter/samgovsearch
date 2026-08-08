# Contract Brain deterministic ingestion

Contract Brain now has a persistent public-evidence memory layer based on the extraction architecture proven in the CONOPS source-coverage work.

## Processing model

```text
SAM.gov resourceId
      |
      v
download public bytes
      |
      v
SHA-256
      |
      +--> same hash + same parser already complete? --> reuse Supabase evidence
      |
      v
native extraction
      |
      +--> PDF has native text --> PyMuPDF blocks with sort=True
      |
      +--> PDF has zero native text --> bounded 200 DPI grayscale Tesseract OCR
      |
      +--> DOCX / PPTX / XLSX / text / bounded one-level ZIP adapters
      |
      v
normalized logical source rows
      |
      v
Supabase evidence memory
```

The extraction layer does **not** automatically turn text into verified systems, interfaces, requirements, or CONOPS claims. It preserves source evidence first so later modules can make reviewable, source-linked relationships.

## Supabase memory objects

The migration `supabase/migrations/202608080112_contract_brain_evidence_memory.sql` adds:

- `source_binaries`
  - notice ID
  - SAM.gov `resourceId`
  - document name
  - SHA-256
  - byte size
  - MIME type
- `extraction_runs`
  - parser version
  - status
  - extraction mode
  - pages
  - row count
  - OCR page count
  - timestamps and error state
- `source_rows`
  - stable source-row ID
  - exact locator
  - page number
  - exact extracted text
  - PDF block geometry when available
- `document_analysis_status`
  - convenient read-only status view used by the Contract Brain Sources screen

Public browser clients have read-only access to these public-evidence objects. Persistent writes require the Supabase service role key and must never be placed in browser JavaScript or committed to Git.

## Install the parser

From the repository root:

```bat
py -3 -m pip install -r requirements-contract-brain-ingest.txt
```

Optional OCR fallback additionally requires the Tesseract executable to be installed and available on `PATH`.

Tesseract is not used for PDFs that already contain a native text layer.

## Configure persistent writes locally

Set the service role key only in the local terminal that will perform ingestion:

### Command Prompt

```bat
set SUPABASE_SERVICE_ROLE_KEY=your_service_role_key_here
```

### PowerShell

```powershell
$env:SUPABASE_SERVICE_ROLE_KEY = "your_service_role_key_here"
```

Do not paste the service role key into the Contract Brain browser UI and do not commit it to the repository.

## Process every indexed attachment for a notice

```bat
py scripts\contract_brain_ingest.py --notice-id NOTICE_ID
```

Example progress:

```text
START         6 attachment(s)
SOURCE        1/6 Statement of Work.pdf
DOWNLOAD      Statement of Work.pdf
HASH          sha256=4b7d...
EXTRACT       PyMuPDF native text blocks; sort=True; OCR not invoked
STORE         stored rows 1-300 of 812
STORE         stored rows 301-600 of 812
STORE         stored rows 601-812 of 812
SOURCE        2/6 Attachment B.xlsx
...
DONE          processed 6 attachment(s)
```

## Analyze-once behavior

On a later run, if the same SAM.gov `resourceId` downloads to the same SHA-256 and the same parser version already completed successfully, the parser reports:

```text
CACHE         unchanged binary already analyzed; reusing Supabase evidence
```

It does not extract or store the document again.

If SAM.gov serves changed bytes for the same `resourceId`, the new SHA-256 creates a new source-binary version and that version is analyzed independently.

If the parser logic changes, increment `PARSER_VERSION` in `contract_brain_pipeline/extractor.py`. Existing evidence remains available while the new parser version can create a new extraction run.

## Process one indexed attachment

```bat
py scripts\contract_brain_ingest.py --resource-id RESOURCE_ID
```

## Force a parser rerun

```bat
py scripts\contract_brain_ingest.py --notice-id NOTICE_ID --force
```

This is intended for development/debugging. Normal Contract Brain operation should rely on hash + parser-version reuse.

## Source screen

After a source has been analyzed, open the notebook and select **Sources**.

The table reads `document_analysis_status` and shows:

- Complete
- Running
- Review required
- Failed
- Not processed
- normalized row count

This makes the persistent memory state visible without rerunning extraction.

## Next integration step

The current deterministic ingestion CLI is intentionally separate from browser JavaScript so privileged Supabase credentials are not exposed.

The next integration should add a trusted local or hosted job service that lets the Contract Brain UI request processing and stream progress while keeping persistence credentials server-side.
