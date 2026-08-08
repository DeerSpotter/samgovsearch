# SAM.gov Search

A Windows-friendly Python Tkinter GUI for batch searching SAM.gov opportunities, plus the browser-based **Contract Brain** workspace for living public-contract evidence analysis.

## Contract Brain

The current Contract Brain feature branch adds a browser-native contract notebook at:

```text
docs/contract-brain.html
```

When a notebook opens, Contract Brain can automatically process public attachments in the browser without Python parser installation:

- Web Worker background queue
- Web Crypto SHA-256
- PDF.js native PDF text and geometry
- JSZip DOCX / PPTX / XLSX / ZIP extraction
- Tesseract.js lazy OCR fallback only when a PDF has no native text
- IndexedDB local resume/cache
- Supabase persistent evidence memory through a server-side Edge Function

Manual Refresh still controls when Contract Brain checks SAM.gov for new/changed source inventory. Source parsing itself is automatic for evidence already associated with the open notebook.

The legacy/desktop SAM.gov Search application remains available below.

## Desktop SAM.gov Search

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

For full desktop-search documentation and options, use the existing application controls and source comments. Contract Brain is being developed alongside the desktop search so discovery can flow directly into a persistent notebook and evidence graph.
