# Contract Brain deterministic ingestion

Contract Brain now has a persistent public-evidence memory layer based on the extraction architecture proven in the CONOPS source-coverage work.

The **primary user path is browser-native and automatic**. The Python extractor remains as a development/fallback path, not a normal-user dependency.

## Normal browser workflow

```text
Open Contract Notebook
        |
        v
check live SAM.gov source inventory
        |
        v
check Supabase evidence memory
        |
        +--> already complete? --> reuse stored evidence immediately
        |
        v
queue missing source in browser
        |
        v
Web Worker downloads public attachment
        |
        v
SHA-256 with Web Crypto
        |
        v
native browser extraction
        |
        +--> PDF native text --> PDF.js text items + page geometry
        |
        +--> zero-native-text PDF --> lazy Tesseract.js OCR fallback
        |
        +--> DOCX / PPTX / XLSX / ZIP --> JSZip + deterministic OOXML extraction
        |
        +--> text-family source --> browser text decoder
        |
        v
IndexedDB local evidence cache
        |
        v
Supabase Edge Function verifies source SHA-256
        |
        v
normalized logical source rows -> Supabase
```

There is no `pip install` step for normal browser use. Browser document engines are loaded only when required and are cached by `contract-brain-sw.js` for later sessions.

OCR is **not** downloaded or executed for a PDF that already exposes native text.

## Automatic background behavior

Opening a Contract Notebook automatically starts the evidence queue for sources that are not already complete in Supabase.

The **Evidence** control in the top bar opens a live Background Evidence panel showing:

- total sources
- ready sources
- queued/running sources
- review/failure count
- current document
- current pipeline stage
- PDF engine status
- Office/ZIP engine status
- OCR engine status
- recent activity

The extraction itself runs in `contract-brain-browser-worker.js`, so the main Contract Brain UI remains usable while source processing continues.

If the browser is closed before processing finishes, completed local source rows remain in IndexedDB. The next time the notebook opens, Contract Brain attempts to sync those local rows before re-extracting the source.

## Browser dependency model

Normal users do not install parser packages.

Contract Brain loads these browser engines on demand:

- PDF.js for native PDF text and geometry
- JSZip for ZIP and OOXML containers
- Tesseract.js only for zero-native-text PDF fallback
- Web Crypto for SHA-256
- IndexedDB for local processing state and resumable evidence
- Web Workers for non-blocking extraction

The service worker caches application and dependency assets after they are requested.

## Supabase persistence

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
  - logical row count
  - OCR page count
  - timestamps and error state
- `source_rows`
  - stable source-row ID
  - exact locator
  - page number
  - exact extracted text
  - PDF geometry when available
- `document_analysis_status`
  - read-only status view used by the Contract Brain Sources screen

The deployed Supabase Edge Function `contract-brain-browser-ingest` performs persistence. It uses the Supabase service role only inside the Edge Function environment. The browser never receives that credential.

Before accepting a new source-binary hash, the Edge Function verifies that the `resourceId` belongs to the indexed notice and independently downloads the public attachment to confirm the SHA-256 supplied by the browser.

Browser-extracted source rows remain deterministic evidence records. They are not automatically promoted into verified systems, interfaces, requirements, or CONOPS claims.

## Analyze-once behavior

A completed source is identified by:

```text
SAM.gov resourceId
+
SHA-256
+
parser version
```

If Supabase already contains a successful extraction, Contract Brain does not parse that source again.

If the same source was completed locally but cloud synchronization was interrupted, Contract Brain reuses the IndexedDB rows and retries synchronization rather than rereading the source.

If SAM.gov serves changed bytes, a different SHA-256 produces a new source-binary version.

## Browser parser version

The browser worker currently identifies itself as:

```text
contract-brain-browser/0.1.0
```

Parser upgrades should increment this version so old extracted evidence remains traceable while a newer extraction can be generated intentionally.

## Source screen

The Contract Brain **Sources** screen reads `document_analysis_status` and shows:

- Complete
- Running
- Review required
- Failed
- Not processed
- normalized row count

After a browser extraction is synchronized, the Sources screen refreshes from Supabase without requiring a page reload.

## Python fallback / development extractor

The original deterministic Python extractor remains available for development, regression comparison, and server-side fallback:

```bat
py -3 -m pip install -r requirements-contract-brain-ingest.txt
set SUPABASE_SERVICE_ROLE_KEY=your_service_role_key_here
py scripts\contract_brain_ingest.py --notice-id NOTICE_ID
```

Its extraction philosophy remains the same: SHA first, native extraction first, OCR only when needed, exact locators, normalized evidence, and parser-version reuse.

The service role key must never be placed in browser JavaScript or committed to Git.
