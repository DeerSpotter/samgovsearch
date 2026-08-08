const PARSER_VERSION = 'contract-brain-browser/0.1.0';
const WORKER_BASE = 'https://samgovsearch.spotterdeer.workers.dev';
const PDFJS_URL = 'https://cdn.jsdelivr.net/npm/pdfjs-dist@4.10.38/legacy/build/pdf.mjs';
const PDFJS_WORKER_URL = 'https://cdn.jsdelivr.net/npm/pdfjs-dist@4.10.38/legacy/build/pdf.worker.mjs';
const JSZIP_URL = 'https://cdn.jsdelivr.net/npm/jszip@3.10.1/+esm';
const TESSERACT_URL = 'https://cdn.jsdelivr.net/npm/tesseract.js@5.1.1/+esm';
const MAX_ARCHIVE_MEMBERS = 200;
const MAX_ARCHIVE_MEMBER_BYTES = 100 * 1024 * 1024;
const MAX_TEXT_BYTES = 32 * 1024 * 1024;
const ROW_BATCH = 250;
const TEXT_EXTS = new Set(['txt','csv','tsv','md','json','xml','html','htm','yaml','yml','rtf','log','ini','cfg','conf']);
const SUPPORTED = new Set(['pdf','docx','pptx','xlsx','zip', ...TEXT_EXTS]);

let pdfjs = null;
let JSZipCtor = null;
let tesseractModule = null;
const cancelled = new Set();

function send(type, payload = {}) { self.postMessage({ type, ...payload }); }
function clean(value) { return String(value ?? '').replace(/\u0000/g, '').replace(/\s+/g, ' ').trim(); }
function ext(name) { const m = String(name || '').toLowerCase().match(/\.([a-z0-9]+)$/); return m ? m[1] : ''; }
function pct(done, total) { return total > 0 ? Math.max(0, Math.min(100, Math.round(done * 100 / total))) : 0; }
function cancelledJob(id) { return cancelled.has(id); }

function xmlDecode(value) {
  return String(value || '')
    .replace(/&#x([0-9a-f]+);/gi, (_, h) => String.fromCodePoint(parseInt(h, 16)))
    .replace(/&#(\d+);/g, (_, d) => String.fromCodePoint(parseInt(d, 10)))
    .replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"')
    .replace(/&apos;/g, "'").replace(/&amp;/g, '&');
}

function xmlTexts(xml, tagPattern = '(?:w:t|a:t|t)') {
  const out = [];
  const re = new RegExp(`<${tagPattern}(?:\\s[^>]*)?>([\\s\\S]*?)<\\/${tagPattern}>`, 'gi');
  let m;
  while ((m = re.exec(xml))) {
    const value = clean(xmlDecode(m[1].replace(/<[^>]+>/g, '')));
    if (value) out.push(value);
  }
  return out;
}

async function sha256Hex(buffer) {
  const digest = await crypto.subtle.digest('SHA-256', buffer);
  return [...new Uint8Array(digest)].map(v => v.toString(16).padStart(2, '0')).join('');
}

async function ensurePdf(jobId) {
  if (pdfjs) return pdfjs;
  send('engine', { jobId, engine: 'PDF engine', status: 'loading', detail: 'Loading PDF.js' });
  pdfjs = await import(PDFJS_URL);
  if (pdfjs.GlobalWorkerOptions) pdfjs.GlobalWorkerOptions.workerSrc = PDFJS_WORKER_URL;
  send('engine', { jobId, engine: 'PDF engine', status: 'ready', detail: 'PDF.js ready' });
  return pdfjs;
}

async function ensureZip(jobId) {
  if (JSZipCtor) return JSZipCtor;
  send('engine', { jobId, engine: 'Office / ZIP engine', status: 'loading', detail: 'Loading JSZip' });
  const mod = await import(JSZIP_URL);
  JSZipCtor = mod.default || mod.JSZip || mod;
  send('engine', { jobId, engine: 'Office / ZIP engine', status: 'ready', detail: 'JSZip ready' });
  return JSZipCtor;
}

async function ensureOcr(jobId) {
  if (tesseractModule) return tesseractModule;
  send('engine', { jobId, engine: 'OCR engine', status: 'loading', detail: 'Loading Tesseract.js only because native PDF text was empty' });
  tesseractModule = await import(TESSERACT_URL);
  send('engine', { jobId, engine: 'OCR engine', status: 'ready', detail: 'Tesseract.js ready' });
  return tesseractModule;
}

async function download(job) {
  const url = `${WORKER_BASE}/download/${encodeURIComponent(job.resourceId)}`;
  send('progress', { jobId: job.jobId, stage: 'DOWNLOAD', status: 'running', detail: job.name, progress: 0 });
  const response = await fetch(url, { cache: 'no-store' });
  if (!response.ok) throw new Error(`download failed ${response.status}: ${(await response.text()).slice(0, 180)}`);
  const total = Number(response.headers.get('content-length') || 0);
  const mime = response.headers.get('content-type') || '';
  if (!response.body || !response.body.getReader) {
    const buffer = await response.arrayBuffer();
    send('progress', { jobId: job.jobId, stage: 'DOWNLOAD', status: 'complete', detail: `${buffer.byteLength.toLocaleString()} bytes`, progress: 100 });
    return { buffer, mime };
  }
  const reader = response.body.getReader();
  const chunks = [];
  let received = 0;
  for (;;) {
    if (cancelledJob(job.jobId)) throw new Error('cancelled');
    const { done, value } = await reader.read();
    if (done) break;
    chunks.push(value);
    received += value.byteLength;
    send('progress', { jobId: job.jobId, stage: 'DOWNLOAD', status: 'running', detail: `${received.toLocaleString()}${total ? ` / ${total.toLocaleString()}` : ''} bytes`, progress: total ? pct(received, total) : null });
  }
  const merged = new Uint8Array(received);
  let offset = 0;
  for (const chunk of chunks) { merged.set(chunk, offset); offset += chunk.byteLength; }
  send('progress', { jobId: job.jobId, stage: 'DOWNLOAD', status: 'complete', detail: `${received.toLocaleString()} bytes`, progress: 100 });
  return { buffer: merged.buffer, mime };
}

function normalizeRow(row, index, memberPath = '') {
  return {
    locator: clean(row.locator),
    exact_text: clean(row.exact_text ?? row.text),
    row_type: clean(row.row_type || 'text'),
    page_number: Number.isFinite(Number(row.page_number)) ? Number(row.page_number) : null,
    geometry: row.geometry || null,
    sort_index: Number.isFinite(Number(row.sort_index)) ? Number(row.sort_index) : index,
    member_path: memberPath || row.member_path || '',
  };
}

function emitRows(jobId, rows, memberPath = '') {
  const normalized = rows.map((row, i) => normalizeRow(row, i + 1, memberPath)).filter(row => row.locator && row.exact_text);
  for (let i = 0; i < normalized.length; i += ROW_BATCH) {
    send('rows', { jobId, rows: normalized.slice(i, i + ROW_BATCH) });
  }
  return normalized.length;
}

async function extractPdf(job, buffer) {
  const lib = await ensurePdf(job.jobId);
  send('progress', { jobId: job.jobId, stage: 'EXTRACT', status: 'running', detail: 'Reading native PDF text', progress: 0 });
  const task = lib.getDocument({ data: new Uint8Array(buffer) });
  const doc = await task.promise;
  let rowCount = 0;
  let order = 0;
  const nativeRows = [];
  for (let pageNo = 1; pageNo <= doc.numPages; pageNo++) {
    if (cancelledJob(job.jobId)) throw new Error('cancelled');
    const page = await doc.getPage(pageNo);
    const textContent = await page.getTextContent();
    let itemNo = 0;
    for (const item of textContent.items || []) {
      const value = clean(item.str);
      if (!value) continue;
      itemNo += 1;
      order += 1;
      const t = Array.isArray(item.transform) ? item.transform : [];
      nativeRows.push({
        locator: `page ${pageNo} item ${itemNo}`,
        exact_text: value,
        row_type: 'pdf_native',
        page_number: pageNo,
        geometry: t.length >= 6 ? { x: Number(t[4]) || 0, y: Number(t[5]) || 0, width: Number(item.width) || 0, height: Number(item.height) || 0 } : null,
        sort_index: order,
      });
      if (nativeRows.length >= ROW_BATCH) { rowCount += emitRows(job.jobId, nativeRows.splice(0)); }
    }
    send('progress', { jobId: job.jobId, stage: 'EXTRACT', status: 'running', detail: `Native text page ${pageNo}/${doc.numPages}`, progress: pct(pageNo, doc.numPages) });
  }
  if (nativeRows.length) rowCount += emitRows(job.jobId, nativeRows);
  if (rowCount > 0) {
    try { await doc.destroy(); } catch {}
    return { status: 'complete', mode: 'PDF.js native text items; OCR not invoked', pageCount: doc.numPages, ocrPageCount: 0, rowCount };
  }

  send('progress', { jobId: job.jobId, stage: 'OCR', status: 'running', detail: 'No native text found; starting bounded OCR fallback', progress: 0 });
  const tesseract = await ensureOcr(job.jobId);
  const ocrWorker = await tesseract.createWorker('eng');
  let ocrRows = 0;
  order = 0;
  try {
    for (let pageNo = 1; pageNo <= doc.numPages; pageNo++) {
      if (cancelledJob(job.jobId)) throw new Error('cancelled');
      const page = await doc.getPage(pageNo);
      const viewport = page.getViewport({ scale: 200 / 72 });
      const canvas = new OffscreenCanvas(Math.max(1, Math.ceil(viewport.width)), Math.max(1, Math.ceil(viewport.height)));
      const context = canvas.getContext('2d', { alpha: false });
      await page.render({ canvasContext: context, viewport }).promise;
      const blob = await canvas.convertToBlob({ type: 'image/png' });
      const result = await ocrWorker.recognize(blob);
      const rows = [];
      let lineNo = 0;
      for (const raw of String(result?.data?.text || '').split(/\r?\n/)) {
        const value = clean(raw);
        if (!value) continue;
        lineNo += 1; order += 1;
        rows.push({ locator: `page ${pageNo} OCR line ${lineNo}`, exact_text: value, row_type: 'pdf_ocr', page_number: pageNo, geometry: null, sort_index: order });
      }
      ocrRows += emitRows(job.jobId, rows);
      send('progress', { jobId: job.jobId, stage: 'OCR', status: 'running', detail: `OCR page ${pageNo}/${doc.numPages}`, progress: pct(pageNo, doc.numPages) });
    }
  } finally {
    try { await ocrWorker.terminate(); } catch {}
    try { await doc.destroy(); } catch {}
  }
  if (!ocrRows) return { status: 'review_required', mode: 'PDF.js returned zero native text and browser OCR returned zero text', pageCount: doc.numPages, ocrPageCount: doc.numPages, rowCount: 0 };
  return { status: 'complete', mode: 'PDF.js zero-native-text gate -> 200 DPI browser render -> Tesseract.js eng OCR', pageCount: doc.numPages, ocrPageCount: doc.numPages, rowCount: ocrRows };
}

async function extractDocx(job, buffer, memberPath = '') {
  const Zip = await ensureZip(job.jobId);
  const zip = await Zip.loadAsync(buffer);
  const file = zip.file('word/document.xml');
  if (!file) throw new Error('DOCX word/document.xml not found');
  const xml = await file.async('text');
  const rows = [];
  let order = 0;
  let paragraph = 0;
  for (const m of xml.matchAll(/<w:p(?:\s[^>]*)?>([\s\S]*?)<\/w:p>/gi)) {
    const parts = xmlTexts(m[1], 'w:t');
    const value = clean(parts.join(' '));
    paragraph += 1;
    if (!value) continue;
    order += 1;
    rows.push({ locator: `paragraph ${paragraph}`, exact_text: value, row_type: 'docx_paragraph', page_number: null, geometry: null, sort_index: order });
  }
  const count = emitRows(job.jobId, rows, memberPath);
  return { status: count ? 'complete' : 'review_required', mode: 'Browser OOXML DOCX paragraph extraction', pageCount: null, ocrPageCount: 0, rowCount: count };
}

async function extractPptx(job, buffer, memberPath = '') {
  const Zip = await ensureZip(job.jobId);
  const zip = await Zip.loadAsync(buffer);
  const slides = Object.keys(zip.files).filter(name => /^ppt\/slides\/slide\d+\.xml$/i.test(name)).sort((a,b) => Number(a.match(/slide(\d+)/i)?.[1] || 0) - Number(b.match(/slide(\d+)/i)?.[1] || 0));
  let order = 0, count = 0;
  for (let s = 0; s < slides.length; s++) {
    const slideNo = Number(slides[s].match(/slide(\d+)/i)?.[1] || s + 1);
    const xml = await zip.file(slides[s]).async('text');
    const texts = xmlTexts(xml, 'a:t');
    const rows = texts.map((value, i) => ({ locator: `slide ${slideNo} text ${i + 1}`, exact_text: value, row_type: 'pptx_text', page_number: slideNo, geometry: null, sort_index: ++order }));
    count += emitRows(job.jobId, rows, memberPath);
    send('progress', { jobId: job.jobId, stage: 'EXTRACT', status: 'running', detail: `Slide ${s + 1}/${slides.length}`, progress: pct(s + 1, slides.length) });
  }
  return { status: count ? 'complete' : 'review_required', mode: 'Browser OOXML PPTX text-run extraction', pageCount: slides.length || null, ocrPageCount: 0, rowCount: count };
}

async function extractXlsx(job, buffer, memberPath = '') {
  const Zip = await ensureZip(job.jobId);
  const zip = await Zip.loadAsync(buffer);
  let shared = [];
  const sharedFile = zip.file('xl/sharedStrings.xml');
  if (sharedFile) {
    const xml = await sharedFile.async('text');
    shared = [...xml.matchAll(/<si(?:\s[^>]*)?>([\s\S]*?)<\/si>/gi)].map(m => clean(xmlTexts(m[1], 't').join(' ')));
  }
  const sheets = Object.keys(zip.files).filter(name => /^xl\/worksheets\/sheet\d+\.xml$/i.test(name)).sort((a,b) => Number(a.match(/sheet(\d+)/i)?.[1] || 0) - Number(b.match(/sheet(\d+)/i)?.[1] || 0));
  let count = 0, order = 0;
  for (let s = 0; s < sheets.length; s++) {
    const sheetNo = Number(sheets[s].match(/sheet(\d+)/i)?.[1] || s + 1);
    const xml = await zip.file(sheets[s]).async('text');
    const rows = [];
    for (const rowMatch of xml.matchAll(/<row([^>]*)>([\s\S]*?)<\/row>/gi)) {
      const rowNum = Number(rowMatch[1].match(/\br="(\d+)"/)?.[1] || 0) || rows.length + 1;
      const parts = [];
      for (const cell of rowMatch[2].matchAll(/<c([^>]*)>([\s\S]*?)<\/c>/gi)) {
        const attrs = cell[1]; const inner = cell[2];
        const ref = attrs.match(/\br="([A-Z]+\d+)"/i)?.[1] || `C${parts.length + 1}`;
        const type = attrs.match(/\bt="([^"]+)"/)?.[1] || '';
        let value = '';
        if (type === 'inlineStr') value = clean(xmlTexts(inner, 't').join(' '));
        else {
          const raw = inner.match(/<v(?:\s[^>]*)?>([\s\S]*?)<\/v>/i)?.[1];
          if (raw != null) value = type === 's' ? clean(shared[Number(raw)] ?? raw) : clean(xmlDecode(raw));
        }
        if (value) parts.push(`${ref}=${value}`);
      }
      if (parts.length) rows.push({ locator: `sheet ${sheetNo} row ${rowNum}`, exact_text: parts.join(' | '), row_type: 'xlsx_row', page_number: null, geometry: null, sort_index: ++order });
    }
    count += emitRows(job.jobId, rows, memberPath);
    send('progress', { jobId: job.jobId, stage: 'EXTRACT', status: 'running', detail: `Sheet ${s + 1}/${sheets.length}`, progress: pct(s + 1, sheets.length) });
  }
  return { status: count ? 'complete' : 'review_required', mode: 'Browser OOXML XLSX sparse-row extraction', pageCount: null, ocrPageCount: 0, rowCount: count };
}

function extractText(job, buffer, suffix, memberPath = '') {
  if (buffer.byteLength > MAX_TEXT_BYTES) throw new Error(`text source exceeds ${MAX_TEXT_BYTES.toLocaleString()} byte limit`);
  const value = new TextDecoder('utf-8', { fatal: false }).decode(buffer);
  let order = 0;
  const rows = [];
  for (const [i, raw] of value.split(/\r?\n/).entries()) {
    const line = clean(raw); if (!line) continue;
    rows.push({ locator: `line ${i + 1}`, exact_text: line, row_type: `text_${suffix || 'plain'}`, page_number: null, geometry: null, sort_index: ++order });
  }
  const count = emitRows(job.jobId, rows, memberPath);
  return { status: count ? 'complete' : 'review_required', mode: `Browser text extraction (${suffix || 'plain'})`, pageCount: null, ocrPageCount: 0, rowCount: count };
}

async function extractZip(job, buffer) {
  const Zip = await ensureZip(job.jobId);
  const zip = await Zip.loadAsync(buffer);
  const members = Object.keys(zip.files).filter(name => !zip.files[name].dir).slice(0, MAX_ARCHIVE_MEMBERS);
  let total = 0, processed = 0, review = 0;
  for (const name of members) {
    if (cancelledJob(job.jobId)) throw new Error('cancelled');
    const suffix = ext(name);
    if (!SUPPORTED.has(suffix) || suffix === 'zip') { review += 1; continue; }
    const member = await zip.file(name).async('arraybuffer');
    if (member.byteLength > MAX_ARCHIVE_MEMBER_BYTES) { review += 1; continue; }
    const result = await extractByType(job, name, member, name, false);
    total += result.rowCount || 0;
    processed += 1;
    send('progress', { jobId: job.jobId, stage: 'EXTRACT', status: 'running', detail: `Archive member ${processed}/${members.length}: ${name}`, progress: pct(processed, members.length) });
  }
  return { status: total ? 'complete' : 'review_required', mode: `Browser bounded ZIP extraction; ${processed} supported members; ${review} skipped/review members`, pageCount: null, ocrPageCount: 0, rowCount: total };
}

async function extractByType(job, name, buffer, memberPath = '', allowArchive = true) {
  const suffix = ext(name);
  if (suffix === 'pdf') return extractPdf(job, buffer);
  if (suffix === 'docx') return extractDocx(job, buffer, memberPath);
  if (suffix === 'pptx') return extractPptx(job, buffer, memberPath);
  if (suffix === 'xlsx') return extractXlsx(job, buffer, memberPath);
  if (suffix === 'zip' && allowArchive) return extractZip(job, buffer);
  if (TEXT_EXTS.has(suffix)) return extractText(job, buffer, suffix, memberPath);
  return { status: 'review_required', mode: `Unsupported browser source type .${suffix || 'unknown'}`, pageCount: null, ocrPageCount: 0, rowCount: 0 };
}

async function processJob(job) {
  const started = Date.now();
  try {
    send('progress', { jobId: job.jobId, stage: 'QUEUE', status: 'complete', detail: 'Background worker started', progress: 100 });
    const downloaded = await download(job);
    if (cancelledJob(job.jobId)) throw new Error('cancelled');
    send('progress', { jobId: job.jobId, stage: 'HASH', status: 'running', detail: 'Computing SHA-256', progress: null });
    const sha256 = await sha256Hex(downloaded.buffer);
    send('source', { jobId: job.jobId, source: { noticeId: job.noticeId, resourceId: job.resourceId, name: job.name, sha256, sizeBytes: downloaded.buffer.byteLength, mimeType: downloaded.mime, parserVersion: PARSER_VERSION } });
    send('progress', { jobId: job.jobId, stage: 'HASH', status: 'complete', detail: `${sha256.slice(0, 16)}…`, progress: 100 });
    const result = await extractByType(job, job.name, downloaded.buffer);
    send('progress', { jobId: job.jobId, stage: 'EXTRACT', status: result.status === 'complete' ? 'complete' : 'review', detail: `${(result.rowCount || 0).toLocaleString()} logical rows`, progress: 100 });
    send('done', { jobId: job.jobId, result: { ...result, parserVersion: PARSER_VERSION, elapsedMs: Date.now() - started } });
  } catch (error) {
    const message = error?.message || String(error);
    send('failed', { jobId: job.jobId, error: message, cancelled: message === 'cancelled' });
  } finally {
    cancelled.delete(job.jobId);
  }
}

self.onmessage = event => {
  const data = event.data || {};
  if (data.type === 'cancel' && data.jobId) { cancelled.add(data.jobId); return; }
  if (data.type === 'process' && data.job) processJob(data.job);
};

send('ready', { parserVersion: PARSER_VERSION });
