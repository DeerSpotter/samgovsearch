# Contract Brain Architecture

Contract Brain is the next evolution of `samgovsearch`: a persistent, public-data contract notebook that can grow from SAM.gov discovery into source-grounded mission, requirements, component, interface, analog, supplier, and change intelligence.

## Product rule

The notebook is a maintained knowledge object, not a one-time AI report.

The initial implementation intentionally uses **manual refresh**. Nothing polls SAM.gov in the background. A user chooses when to check for changes, and unchanged evidence is not reprocessed.

## Current foundation

The first Contract Brain slice is implemented under `docs/contract-brain.html` with supporting CSS and JavaScript.

It currently provides:

- Contract Brain dark UI shell with fixed left navigation.
- Open an opportunity by SAM.gov notice ID.
- Search the existing public Supabase opportunity index.
- Load notice details from the existing Cloudflare Worker.
- Load attachment metadata from `/resources/{noticeId}`.
- Treat SAM.gov `resourceId` as the stable public attachment identifier.
- Fall back to the existing Supabase document index when live resource metadata is unavailable.
- Save notebooks locally in the browser.
- Save a baseline snapshot locally in the browser.
- Manual refresh only.
- Diff notice metadata and attachment resource IDs against the prior snapshot.
- Classify changes as new, changed, or removed.
- Preserve local change history per notice.
- Direct public attachment download through the existing Worker `/download/{resourceId}` route.
- Explicit public-data boundary.

No LLM call is required by the foundation and no background monitoring is performed.

## Target layers

```text
Contract Brain UI
    |
Intelligence Engine
    |
Knowledge / Evidence Layer
    |
Document Processing Layer
    |
Source Adapters
```

### 1. Source adapters

Normalize public evidence from external sources without coupling source-specific APIs to the UI.

Initial:

- SAM.gov opportunity search
- SAM.gov notice details
- SAM.gov public attachment resources
- Supabase indexed opportunity/document metadata

Planned:

- USAspending award history
- DLA/public NSN and catalog sources where legally/publicly accessible
- Public specifications and standards metadata
- Manufacturer public catalogs

### 2. Document processing

Future document jobs should produce versioned evidence rather than raw filenames only.

Planned pipeline:

```text
download
  -> hash/version
  -> unpack archives
  -> parse
  -> structure/chunk
  -> extract entities/claims
  -> resolve entities
  -> index
```

Supported targets should include PDF, DOCX, XLSX, PPTX, CSV, TXT/XML, ZIP, images, and useful drawing/package metadata.

### 3. Knowledge and evidence layer

Core objects:

- opportunity
- document
- document version
- requirement
- mission function
- system
- subsystem
- component
- interface
- specification / standard
- part / NSN
- manufacturer / organization
- contract / award
- claim
- evidence
- relationship
- gap / conflict
- reviewer decision

Every extracted claim or relationship should point back to evidence and retain state such as:

- proposed
- supported
- verified
- conflicting
- rejected
- superseded
- unknown

### 4. Intelligence engine

Planned capabilities:

- Hybrid lexical + semantic + graph retrieval.
- Requirements traceability.
- Mission / CONOPS decomposition.
- Technical entity resolution.
- Interface intelligence.
- Cross-contract analog scoring.
- Gap and conflict detection.
- Supplier/manufacturer capability scoring.
- Clarification-question generation.
- Cited AI Q&A only after retrieval/provenance is in place.

Scores must remain explainable. A single percentage should never hide its contributing dimensions or evidence.

### 5. Contract Brain UI

The left navigation is the persistent product shell.

Foundation/live:

- Overview
- Sources
- Changes
- Saved Notebooks
- Source Adapters
- Public Data Boundary

Next:

- Mission / CONOPS
- Requirements
- Components
- Interfaces
- Analogs
- Gaps & Risks
- Clarifications

Later:

- NSN / Parts
- Manufacturers
- Reports / capture package
- Collaboration / team workspaces

## Refresh model

Contract Brain uses a staged refresh model to control SAM.gov, storage, embedding, and AI usage.

### Quick/manual refresh

Cheap comparison only:

- notice metadata
- resource IDs
- filenames
- sizes
- dates

### Process changes

Only when new/changed source evidence is found:

- download new/changed files
- parse new versions
- update evidence and entities
- update search index

### Rebuild intelligence

Explicit expensive operation for parser/model/schema upgrades or troubleshooting.

Unchanged documents should never be repeatedly reprocessed.

## Security boundary

The public demonstrator is **PUBLIC data only**.

Do not ingest CUI, classified information, source-selection information, export-controlled nonpublic data, proprietary customer material, or other protected content into the public deployment.

Future private deployments need explicit classification, authorization, storage, model-routing, audit, and retention controls before additional data classes are accepted.

## Next implementation milestone

Build server-side document versioning and parsing so a Contract Notebook can turn attachment metadata into traceable source content. The first useful vertical slice should be:

```text
Open Contract
  -> Public attachments
  -> Version/hash
  -> Parse PDF/DOCX/XLSX/ZIP
  -> Requirements + entities
  -> Evidence provenance
  -> Mission/CONOPS view
  -> Manual refresh
  -> Process only changed evidence
```
