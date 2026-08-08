# contract-brain-browser-ingest

Supabase Edge Function used by Contract Brain's browser-native evidence pipeline.

The browser performs deterministic extraction in a Web Worker and sends normalized row batches to this function. The function keeps the Supabase service-role credential server-side.

For a new source hash, `begin` independently checks that the `resourceId` belongs to the indexed notice and downloads the public source to verify the browser-supplied SHA-256 before creating an extraction run.

Supported actions:

- `begin` — verify source identity/hash and create or reuse an extraction run
- `rows` — accept bounded normalized evidence-row batches for that run
- `complete` — finalize the run status and counts

The function is intentionally limited to public SAM.gov evidence already represented in the `documents` index. It does not promote source rows into verified engineering claims.
