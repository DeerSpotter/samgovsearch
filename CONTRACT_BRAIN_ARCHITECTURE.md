# Contract Brain Architecture

Contract Brain turns SAM.gov discovery into a living public-contract notebook whose source evidence can be searched, traced, related, and incrementally refreshed.

## User flow

```text
Opportunity Search
      |
      v
Select opportunity
      |
      v
Contract Notebook
      |
      +--> Overview
      +--> Sources
      +--> Technical Ontology
      +--> Mission / CONOPS
      +--> Requirements
      +--> Components
      +--> Interfaces
      +--> Analogs
      +--> NSN / Parts
      +--> Manufacturers
      +--> Gaps / Risks
      +--> Clarifications
      +--> Changes
      +--> Reports
```

## Browser-native evidence architecture

Normal Contract Brain operation does not require Python, pip, or a locally installed parser service.

```text
Contract Brain browser
      |
      +--> SAM.gov search / source inventory
      |
      +--> Supabase evidence status
      |
      +--> Web Worker background queue
                |
                +--> Web Crypto SHA-256
                +--> PDF.js native text + geometry
                +--> Tesseract.js OCR only when native PDF text is empty
                +--> JSZip OOXML extraction for DOCX/PPTX/XLSX/ZIP
                +--> text-family extraction
                |
                v
             IndexedDB
                |
                v
      Supabase Edge Function
                |
                +--> independently verifies indexed resourceId + SHA-256
                +--> persists source binary / run / source rows
                v
            Supabase memory
```

The UI stays responsive while extraction runs because document work is performed inside a Web Worker.

## Dependency behavior

Browser engines are loaded lazily and cached:

- PDF.js loads only when a PDF requires extraction.
- JSZip loads only for Office Open XML or ZIP sources.
- Tesseract.js loads only when a PDF has no native text layer.
- Web Crypto and IndexedDB are browser-native.
- `contract-brain-sw.js` caches application and parser assets after first use.

There is no normal-user dependency installation step.

## Persistent evidence model

### source_binaries

One row per unique SAM.gov source binary:

```text
resourceId + SHA-256
```

Stores notice ID, resource ID, name, SHA-256, byte size, MIME type, source URL, and first/last seen times.

### extraction_runs

One processing record per source binary and parser version.

Tracks parser version, status, extraction mode, page count, logical row count, OCR page count, timestamps, and error/review state.

### source_rows

Normalized exact evidence rows storing the stable source row ID, source binary, extraction run, page number, exact locator, row type, exact extracted text, deterministic sort order, and geometry where available.

Full source text is stored once here rather than repeated on every future relationship.

## Analyze-once rule

Contract Brain uses:

```text
resourceId
+
SHA-256
+
parser version
```

as the reusable extraction identity.

If that identity is already complete in Supabase, opening the notebook does not parse it again.

If local extraction completed but synchronization was interrupted, IndexedDB preserves the source rows and the next browser session retries synchronization instead of rereading the source.

If the bytes change, the SHA-256 changes and a new source version is processed.

## Automatic background queue

Opening a notebook automatically:

1. loads the live SAM.gov public source inventory;
2. checks Supabase `document_analysis_status`;
3. marks completed sources as cached;
4. queues only missing sources;
5. processes them one at a time in the browser worker;
6. persists local evidence to IndexedDB as it is produced;
7. streams source rows to the Supabase ingestion function;
8. refreshes the Sources status view when synchronization completes.

The top-bar **Evidence** control opens a live activity panel so background processing is visible rather than a black box.

## Source integrity boundary

The browser computes SHA-256 over the exact bytes it analyzes.

Before a new binary is accepted into persistent memory, the Supabase Edge Function verifies that the `resourceId` exists in the indexed notice, the browser-supplied notice ID matches the indexed document, the public source can be downloaded, and the independently downloaded bytes produce the same SHA-256.

The service-role credential exists only inside the Edge Function environment and is never shipped to browser JavaScript.

## Evidence versus knowledge

Deterministic extraction does not automatically make an engineering claim true.

```text
source bytes
   -> exact rows
   -> candidate entities / requirements / relationships
   -> evidence links
   -> review / confidence state
   -> Contract Brain knowledge graph
```

Technical entities, requirements, interfaces, component relationships, analogs, and CONOPS relationships must keep backlinks to the exact evidence rows that support them.

## Technical Ontology

The current ontology is an early deterministic layer. It can use the notice record and source inventory immediately, then progressively improve as normalized `source_rows` become available.

Future ontology stages should read persisted evidence rather than rereading source files.

## Manual Refresh versus automatic processing

These are different operations.

**Automatic evidence processing** starts when a notebook opens, processes sources already known to that notebook, does not continuously poll SAM.gov, and makes no LLM calls.

**Manual Refresh** explicitly checks SAM.gov for notice/source changes, compares the new source inventory with the previous snapshot, and adds only new or changed evidence to the background processing queue.

This keeps SAM.gov request usage bounded while still making document processing automatic.

## Future semantic layers

Once the normalized evidence corpus is populated, the next layers should be built in this order:

```text
source_rows
    |
    +--> requirement candidates
    +--> entities / systems / components
    +--> interfaces / standards / identifiers
    +--> claims + evidence provenance
    +--> mission / CONOPS graph
    +--> analog contract relationships
    +--> NSN / part / manufacturer enrichment
    +--> gaps / clarifications
    +--> reports and cited AI assistance
```

Any future LLM stage should operate on retrieved evidence rows and cited relationships rather than repeatedly sending whole attachments for analysis.

## Python fallback

`contract_brain_pipeline/extractor.py` and `scripts/contract_brain_ingest.py` remain available for development, regression comparison, or future server-side processing. They are no longer the required normal-user path.
