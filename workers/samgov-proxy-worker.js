/**
 * SAM.gov Search no-key proxy for the GitHub Pages tool.
 *
 * This Worker does not use SAM_API_KEY. It relays public SAM.gov website
 * endpoints and can optionally write indexed search results into Supabase.
 * Supabase writes require Worker secrets, never browser-side service keys.
 */

const SAM_ORIGIN = 'https://sam.gov';
const INTERNAL_SEARCH_URL = 'https://sam.gov/api/prod/sgs/v1/search/';
const INTERNAL_DETAILS_URL = 'https://sam.gov/api/prod/opps/v2/opportunities';
const INTERNAL_RESOURCES_URL = 'https://sam.gov/api/prod/opps/v3/opportunities';
const INTERNAL_DOWNLOAD_URL = 'https://sam.gov/api/prod/opps/v3/opportunities/resources/files';

const SEARCH_ALLOWED_PARAMS = new Set([
  'index',
  'page',
  'mode',
  'sort',
  'size',
  'q',
  'postedFrom',
  'postedTo',
  'is_active',
  'status',
  'opp_type',
  'naics',
  'naicsCode',
  'classificationCode',
  'organization_id',
]);

function corsHeaders(request, env) {
  const requestOrigin = request.headers.get('Origin') || '*';
  const configured = String(env.ALLOWED_ORIGINS || '').trim();
  let allowOrigin = '*';

  if (configured) {
    const allowed = configured.split(',').map((x) => x.trim()).filter(Boolean);
    allowOrigin = allowed.includes(requestOrigin) ? requestOrigin : allowed[0];
  } else if (requestOrigin !== 'null') {
    allowOrigin = requestOrigin;
  }

  return {
    'Access-Control-Allow-Origin': allowOrigin,
    'Access-Control-Allow-Methods': 'GET,HEAD,POST,OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type,Accept,Authorization',
    'Access-Control-Max-Age': '86400',
    'Vary': 'Origin',
  };
}

function jsonResponse(request, env, payload, status = 200) {
  return new Response(JSON.stringify(payload, null, 2), {
    status,
    headers: {
      ...corsHeaders(request, env),
      'Content-Type': 'application/json; charset=utf-8',
      'Cache-Control': 'no-store',
    },
  });
}

function errorResponse(request, env, message, status = 400, extra = {}) {
  return jsonResponse(request, env, { ok: false, error: message, ...extra }, status);
}

function cleanSegment(value) {
  const text = String(value || '').trim();
  if (!text || text.length > 160) return '';
  if (!/^[A-Za-z0-9_.:-]+$/.test(text)) return '';
  return text;
}

function cleanText(value, maxLength = 4000) {
  const text = String(value ?? '').trim();
  if (!text) return null;
  return text.length > maxLength ? text.slice(0, maxLength) : text;
}

function cleanDate(value) {
  const text = cleanText(value, 32);
  if (!text) return null;
  const m = text.match(/^(\d{4}-\d{2}-\d{2})|^(\d{1,2})\/(\d{1,2})\/(\d{4})/);
  if (!m) return null;
  if (m[1]) return m[1];
  return `${m[4]}-${String(m[2]).padStart(2, '0')}-${String(m[3]).padStart(2, '0')}`;
}

function buildSearchUrl(sourceUrl) {
  const target = new URL(INTERNAL_SEARCH_URL);
  for (const [key, value] of sourceUrl.searchParams.entries()) {
    if (SEARCH_ALLOWED_PARAMS.has(key)) {
      target.searchParams.append(key, value);
    }
  }

  if (!target.searchParams.has('index')) target.searchParams.set('index', 'opp');
  if (!target.searchParams.has('mode')) target.searchParams.set('mode', 'search');
  if (!target.searchParams.has('sort')) target.searchParams.set('sort', '-modifiedDate');

  const size = Number(target.searchParams.get('size') || '100');
  if (!Number.isFinite(size) || size < 1 || size > 100) {
    target.searchParams.set('size', '100');
  }

  const page = Number(target.searchParams.get('page') || '0');
  if (!Number.isFinite(page) || page < 0 || page > 1000) {
    target.searchParams.set('page', '0');
  }

  return target;
}

function samHeaders() {
  return {
    'Accept': 'application/hal+json, application/json, */*',
    'Accept-Language': 'en-US,en;q=0.9',
    'Origin': SAM_ORIGIN,
    'Referer': 'https://sam.gov/search/',
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36',
  };
}

async function relay(request, env, targetUrl, cacheSeconds = 30) {
  const upstream = await fetch(targetUrl.toString(), {
    method: request.method === 'HEAD' ? 'HEAD' : 'GET',
    headers: samHeaders(),
    redirect: 'follow',
  });

  const headers = new Headers(upstream.headers);
  for (const [key, value] of Object.entries(corsHeaders(request, env))) {
    headers.set(key, value);
  }
  headers.set('Cache-Control', upstream.ok ? `public, max-age=${cacheSeconds}` : 'no-store');
  headers.delete('Content-Security-Policy');
  headers.delete('X-Frame-Options');

  return new Response(upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers,
  });
}

function supabaseConfig(env) {
  const url = String(env.SUPABASE_URL || '').replace(/\/+$/, '');
  const key = String(env.SUPABASE_SERVICE_ROLE_KEY || env.SUPABASE_SECRET_KEY || '').trim();
  return { url, key, ready: Boolean(url && key) };
}

function normalizeOpportunity(row) {
  const noticeId = cleanText(row.notice_id || row.noticeId || row.noticeID || row.id, 200);
  if (!noticeId) return null;
  return {
    notice_id: noticeId,
    solicitation_number: cleanText(row.solicitation_number || row.solicitationNumber, 500),
    title: cleanText(row.title || row.notice_title || row.noticeTitle, 1000),
    posted_date: cleanDate(row.posted_date || row.postedDate || row.publishDate),
    response_deadline: cleanText(row.response_deadline || row.responseDeadline, 250),
    agency: cleanText(row.agency || row.organization, 1200),
    notice_type: cleanText(row.notice_type || row.noticeType || row.type, 250),
    naics: cleanText(row.naics || row.naicsCode, 100),
    psc: cleanText(row.psc || row.classificationCode, 100),
    description: cleanText(row.description, 12000),
    sam_url: cleanText(row.sam_url || row.samUrl || row.uiLink || `https://sam.gov/opp/${encodeURIComponent(noticeId)}/view`, 1000),
    source_json: row.source_json || row.sourceJson || row,
    last_seen_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };
}

function normalizeDocument(row) {
  const noticeId = cleanText(row.notice_id || row.noticeId, 200);
  const resourceId = cleanText(row.resource_id || row.resourceId, 200);
  const documentName = cleanText(row.document_name || row.documentName || row.name, 1000);
  if (!noticeId || !resourceId || !documentName) return null;
  const extension = cleanText(row.extension || (documentName.includes('.') ? documentName.split('.').pop().toLowerCase() : ''), 32);
  return {
    notice_id: noticeId,
    resource_id: resourceId,
    document_name: documentName,
    extension,
    format_group: cleanText(row.format_group || row.formatGroup || row.format, 100),
    size_bytes: Number.isFinite(Number(row.size_bytes ?? row.sizeBytes)) ? Number(row.size_bytes ?? row.sizeBytes) : null,
    agency: cleanText(row.agency || row.organization, 1200),
    posted_date: cleanDate(row.posted_date || row.postedDate),
    notice_title: cleanText(row.notice_title || row.noticeTitle || row.title, 1000),
    solicitation_number: cleanText(row.solicitation_number || row.solicitationNumber, 500),
    notice_type: cleanText(row.notice_type || row.noticeType || row.source, 250),
    download_url: cleanText(row.download_url || row.downloadUrl || row.downloadLink, 1200),
    sam_url: cleanText(row.sam_url || row.samUrl || row.uiLink || `https://sam.gov/opp/${encodeURIComponent(noticeId)}/view`, 1000),
    source_json: row.source_json || row.sourceJson || row,
    last_seen_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };
}

async function supabaseUpsert(request, env, table, rows, onConflict) {
  const cfg = supabaseConfig(env);
  if (!cfg.ready) {
    return errorResponse(request, env, 'Supabase indexing is not configured on the Worker. Add SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY as Cloudflare Worker secrets/variables.', 501);
  }
  if (!Array.isArray(rows) || !rows.length) {
    return jsonResponse(request, env, { ok: true, indexed: 0, skipped: 0 });
  }

  const payload = rows.slice(0, 500);
  const target = `${cfg.url}/rest/v1/${table}?on_conflict=${encodeURIComponent(onConflict)}`;
  const upstream = await fetch(target, {
    method: 'POST',
    headers: {
      'apikey': cfg.key,
      'Authorization': `Bearer ${cfg.key}`,
      'Content-Type': 'application/json',
      'Prefer': 'resolution=merge-duplicates,return=minimal',
    },
    body: JSON.stringify(payload),
  });
  const text = await upstream.text();
  if (!upstream.ok) {
    return errorResponse(request, env, `Supabase upsert failed: ${text.slice(0, 600)}`, upstream.status);
  }
  return jsonResponse(request, env, { ok: true, indexed: payload.length, skipped: rows.length - payload.length });
}

async function handleIndexRequest(request, env, kind) {
  if (request.method !== 'POST') return errorResponse(request, env, 'Index routes require POST.', 405);
  let body;
  try {
    body = await request.json();
  } catch {
    return errorResponse(request, env, 'Request body must be JSON.', 400);
  }
  const inputRows = Array.isArray(body) ? body : Array.isArray(body.rows) ? body.rows : [];
  if (kind === 'opportunities') {
    const rows = inputRows.map(normalizeOpportunity).filter(Boolean);
    return supabaseUpsert(request, env, 'opportunities', rows, 'notice_id');
  }
  const rows = inputRows.map(normalizeDocument).filter(Boolean);
  return supabaseUpsert(request, env, 'documents', rows, 'notice_id,resource_id');
}

async function handleRequest(request, env) {
  const url = new URL(request.url);
  const path = url.pathname.replace(/\/+$/, '') || '/';

  if (request.method === 'OPTIONS') {
    return new Response(null, { status: 204, headers: corsHeaders(request, env) });
  }

  if (path === '/' || path === '/health') {
    const cfg = supabaseConfig(env);
    return jsonResponse(request, env, {
      ok: true,
      name: 'samgovsearch no-api proxy',
      usesApiKey: false,
      supabaseIndexing: cfg.ready,
      endpoints: ['/search', '/details/{noticeId}', '/resources/{noticeId}', '/download/{resourceId}', '/index/opportunities', '/index/documents'],
    });
  }

  if (path === '/index/opportunities') {
    return handleIndexRequest(request, env, 'opportunities');
  }

  if (path === '/index/documents') {
    return handleIndexRequest(request, env, 'documents');
  }

  if (request.method !== 'GET' && request.method !== 'HEAD') {
    return errorResponse(request, env, 'Only GET, HEAD, POST, and OPTIONS are allowed.', 405);
  }

  if (path === '/search') {
    return relay(request, env, buildSearchUrl(url), 20);
  }

  const detailsMatch = path.match(/^\/details\/([^/]+)$/);
  if (detailsMatch) {
    const noticeId = cleanSegment(decodeURIComponent(detailsMatch[1]));
    if (!noticeId) return errorResponse(request, env, 'Invalid notice ID.', 400);
    return relay(request, env, `${INTERNAL_DETAILS_URL}/${encodeURIComponent(noticeId)}`, 60);
  }

  const resourcesMatch = path.match(/^\/resources\/([^/]+)$/);
  if (resourcesMatch) {
    const noticeId = cleanSegment(decodeURIComponent(resourcesMatch[1]));
    if (!noticeId) return errorResponse(request, env, 'Invalid notice ID.', 400);
    return relay(request, env, `${INTERNAL_RESOURCES_URL}/${encodeURIComponent(noticeId)}/resources`, 60);
  }

  const downloadMatch = path.match(/^\/download\/([^/]+)$/);
  if (downloadMatch) {
    const resourceId = cleanSegment(decodeURIComponent(downloadMatch[1]));
    if (!resourceId) return errorResponse(request, env, 'Invalid resource ID.', 400);
    return relay(request, env, `${INTERNAL_DOWNLOAD_URL}/${encodeURIComponent(resourceId)}/download`, 10);
  }

  return errorResponse(request, env, 'Route not found.', 404, { path });
}

export default {
  async fetch(request, env) {
    try {
      return await handleRequest(request, env || {});
    } catch (error) {
      return errorResponse(request, env || {}, error && error.message ? error.message : String(error), 502);
    }
  },
};
