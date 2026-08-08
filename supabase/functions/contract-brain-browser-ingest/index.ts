type AnyRow = Record<string, unknown>;

const CORS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET,POST,OPTIONS',
  'Access-Control-Allow-Headers': 'authorization,x-client-info,apikey,content-type',
  'Access-Control-Max-Age': '86400',
};
const WORKER = 'https://samgovsearch.spotterdeer.workers.dev';
const MAX_BATCH_ROWS = 250;
const MAX_TEXT_PER_ROW = 20000;
const MAX_BATCH_TEXT = 2500000;

function json(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { ...CORS, 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' },
  });
}

function text(value: unknown, max = 4000): string {
  const s = String(value ?? '').trim();
  return s.length > max ? s.slice(0, max) : s;
}

function base() {
  const url = Deno.env.get('SUPABASE_URL');
  const key = Deno.env.get('SUPABASE_SERVICE_ROLE_KEY');
  if (!url || !key) throw new Error('Supabase service environment is unavailable');
  return { url: url.replace(/\/+$/, ''), key };
}

async function rest(method: string, path: string, body?: unknown, prefer = 'return=representation') {
  const { url, key } = base();
  const response = await fetch(`${url}/rest/v1/${path}`, {
    method,
    headers: {
      apikey: key,
      Authorization: `Bearer ${key}`,
      Accept: 'application/json',
      'Content-Type': 'application/json',
      Prefer: prefer,
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const raw = await response.text();
  if (!response.ok) throw new Error(`${method} ${path} failed ${response.status}: ${raw.slice(0, 800)}`);
  return raw ? JSON.parse(raw) : null;
}

async function sha256Hex(value: Uint8Array | string): Promise<string> {
  const bytes = typeof value === 'string' ? new TextEncoder().encode(value) : value;
  const digest = await crypto.subtle.digest('SHA-256', bytes);
  return [...new Uint8Array(digest)].map(v => v.toString(16).padStart(2, '0')).join('');
}

async function verifySource(noticeId: string, resourceId: string, expectedSha: string) {
  const docs = await rest(
    'GET',
    `documents?select=notice_id,resource_id,document_name,download_url,size_bytes&notice_id=eq.${encodeURIComponent(noticeId)}&resource_id=eq.${encodeURIComponent(resourceId)}&limit=1`,
  );
  const doc = Array.isArray(docs) ? docs[0] : null;
  if (!doc) throw new Error('resource_id is not indexed for this notice');

  const candidates = [doc.download_url, `${WORKER}/download/${encodeURIComponent(resourceId)}`].filter(Boolean);
  let lastError = '';
  for (const target of candidates) {
    try {
      const response = await fetch(target, { headers: { Accept: '*/*' } });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const bytes = new Uint8Array(await response.arrayBuffer());
      const actual = await sha256Hex(bytes);
      if (actual !== expectedSha) {
        throw new Error(`source SHA-256 changed during processing; expected ${expectedSha.slice(0,16)}…, got ${actual.slice(0,16)}…`);
      }
      return { doc, sizeBytes: bytes.byteLength, mimeType: response.headers.get('content-type') || null };
    } catch (error) {
      lastError = error instanceof Error ? error.message : String(error);
    }
  }
  throw new Error(`source verification download failed: ${lastError || 'no usable source URL'}`);
}

async function begin(payload: AnyRow) {
  const noticeId = text(payload.notice_id ?? payload.noticeId, 200);
  const resourceId = text(payload.resource_id ?? payload.resourceId, 200);
  const sha256 = text(payload.sha256, 64).toLowerCase();
  const parserVersion = text(payload.parser_version ?? payload.parserVersion, 200);
  const documentName = text(payload.document_name ?? payload.documentName ?? payload.name, 1000);
  if (!noticeId || !resourceId || !/^[a-f0-9]{64}$/.test(sha256) || !parserVersion || !documentName) {
    return json({ ok:false, error:'notice_id, resource_id, document_name, parser_version, and 64-char sha256 are required' }, 400);
  }

  const existingBinaries = await rest(
    'GET',
    `source_binaries?select=id,sha256&resource_id=eq.${encodeURIComponent(resourceId)}&sha256=eq.${sha256}&limit=1`,
  );
  const existingBinary = Array.isArray(existingBinaries) ? existingBinaries[0] : null;
  if (existingBinary?.id) {
    const completed = await rest(
      'GET',
      `extraction_runs?select=id,status,logical_row_count,extraction_mode,parser_version&source_binary_id=eq.${existingBinary.id}&parser_version=eq.${encodeURIComponent(parserVersion)}&status=eq.complete&limit=1`,
    );
    if (Array.isArray(completed) && completed[0]) {
      return json({ ok:true, cached:true, source_binary_id:existingBinary.id, run_id:completed[0].id, existing:completed[0] });
    }
  }

  const verified = await verifySource(noticeId, resourceId, sha256);
  const binaries = await rest(
    'POST',
    'source_binaries?on_conflict=resource_id,sha256',
    {
      notice_id: noticeId,
      resource_id: resourceId,
      document_name: documentName,
      sha256,
      size_bytes: verified.sizeBytes,
      mime_type: text(payload.mime_type ?? payload.mimeType, 250) || verified.mimeType,
      source_url: verified.doc.download_url || `${WORKER}/download/${encodeURIComponent(resourceId)}`,
      last_seen_at: new Date().toISOString(),
    },
    'resolution=merge-duplicates,return=representation',
  );
  const binary = Array.isArray(binaries) ? binaries[0] : null;
  if (!binary?.id) throw new Error('source binary upsert returned no id');

  const running = await rest(
    'GET',
    `extraction_runs?select=id,status&source_binary_id=eq.${binary.id}&parser_version=eq.${encodeURIComponent(parserVersion)}&status=eq.running&order=started_at.desc&limit=1`,
  );
  if (Array.isArray(running) && running[0]) {
    return json({ ok:true, cached:false, reused:true, source_binary_id:binary.id, run_id:running[0].id });
  }

  const runs = await rest('POST', 'extraction_runs', {
    source_binary_id: binary.id,
    parser_version: parserVersion,
    status:'running',
    extraction_mode:'browser-native pending',
  });
  const run = Array.isArray(runs) ? runs[0] : null;
  if (!run?.id) throw new Error('extraction run insert returned no id');
  return json({ ok:true, cached:false, source_binary_id:binary.id, run_id:run.id });
}

async function rowId(parserVersion: string, sourceSha: string, row: AnyRow) {
  const material = JSON.stringify([
    parserVersion,
    sourceSha,
    text(row.member_path ?? row.memberPath, 1200),
    text(row.locator, 2000),
    text(row.row_type ?? row.rowType, 200),
    text(row.exact_text ?? row.text, MAX_TEXT_PER_ROW),
  ]);
  return sha256Hex(material);
}

async function rows(payload: AnyRow) {
  const runId = text(payload.run_id ?? payload.runId, 100);
  const input = Array.isArray(payload.rows) ? payload.rows as AnyRow[] : [];
  if (!runId || !input.length || input.length > MAX_BATCH_ROWS) {
    return json({ ok:false, error:`run_id and 1-${MAX_BATCH_ROWS} rows are required` }, 400);
  }
  const runs = await rest('GET', `extraction_runs?select=id,source_binary_id,parser_version,status&id=eq.${encodeURIComponent(runId)}&limit=1`);
  const run = Array.isArray(runs) ? runs[0] : null;
  if (!run || run.status !== 'running') return json({ ok:false, error:'running extraction run not found' }, 409);
  const binaries = await rest('GET', `source_binaries?select=id,sha256&id=eq.${run.source_binary_id}&limit=1`);
  const binary = Array.isArray(binaries) ? binaries[0] : null;
  if (!binary) throw new Error('source binary not found for run');

  let totalText = 0;
  const normalized = [];
  for (let i = 0; i < input.length; i++) {
    const item = input[i];
    const locator = text(item.locator, 2000);
    const exactText = text(item.exact_text ?? item.text, MAX_TEXT_PER_ROW);
    const rowType = text(item.row_type ?? item.rowType, 200);
    if (!locator || !exactText || !rowType) continue;
    totalText += exactText.length;
    if (totalText > MAX_BATCH_TEXT) return json({ ok:false, error:'batch text limit exceeded' }, 413);
    normalized.push({
      source_binary_id: run.source_binary_id,
      extraction_run_id: run.id,
      source_row_id: await rowId(run.parser_version, binary.sha256, item),
      page_number: Number.isFinite(Number(item.page_number)) ? Number(item.page_number) : null,
      locator,
      row_type: rowType,
      exact_text: exactText,
      sort_index: Number.isFinite(Number(item.sort_index)) ? Number(item.sort_index) : i + 1,
      geometry: item.geometry && typeof item.geometry === 'object' ? item.geometry : null,
    });
  }
  if (normalized.length) {
    await rest('POST', 'source_rows?on_conflict=source_row_id', normalized, 'resolution=ignore-duplicates,return=minimal');
  }
  return json({ ok:true, accepted:normalized.length });
}

async function complete(payload: AnyRow) {
  const runId = text(payload.run_id ?? payload.runId, 100);
  const statusRaw = text(payload.status, 50);
  const status = ['complete','review_required','failed'].includes(statusRaw) ? statusRaw : 'failed';
  if (!runId) return json({ ok:false, error:'run_id is required' }, 400);
  const body = {
    status,
    extraction_mode: text(payload.extraction_mode ?? payload.extractionMode, 1000) || 'browser-native',
    page_count: Number.isFinite(Number(payload.page_count)) ? Number(payload.page_count) : null,
    logical_row_count: Math.max(0, Number(payload.logical_row_count ?? payload.logicalRowCount) || 0),
    ocr_page_count: Math.max(0, Number(payload.ocr_page_count ?? payload.ocrPageCount) || 0),
    completed_at: new Date().toISOString(),
    error_text: text(payload.error_text ?? payload.error, 4000) || null,
  };
  await rest('PATCH', `extraction_runs?id=eq.${encodeURIComponent(runId)}&status=eq.running`, body, 'return=minimal');
  return json({ ok:true, run_id:runId, status });
}

Deno.serve(async (req: Request) => {
  if (req.method === 'OPTIONS') return new Response(null, { status:204, headers:CORS });
  if (req.method === 'GET') {
    return json({
      ok:true,
      name:'contract-brain-browser-ingest',
      actions:['begin','rows','complete'],
      mode:'browser extraction + server hash verification',
    });
  }
  if (req.method !== 'POST') return json({ ok:false, error:'POST required' }, 405);
  try {
    const payload = await req.json() as AnyRow;
    const action = text(payload.action, 32);
    if (action === 'begin') return await begin(payload);
    if (action === 'rows') return await rows(payload);
    if (action === 'complete') return await complete(payload);
    return json({ ok:false, error:'action must be begin, rows, or complete' }, 400);
  } catch (error) {
    return json({ ok:false, error:error instanceof Error ? error.message : String(error) }, 500);
  }
});
