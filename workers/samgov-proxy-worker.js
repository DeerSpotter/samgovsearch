/**
 * SAM.gov Search no-key proxy for the GitHub Pages tool.
 *
 * This Worker does not use SAM_API_KEY. It relays public SAM.gov website
 * endpoints and auto-indexes successful search/resource responses into Supabase
 * through the Supabase Edge Function index-search-results.
 */

const SAM_ORIGIN = 'https://sam.gov';
const INTERNAL_SEARCH_URL = 'https://sam.gov/api/prod/sgs/v1/search/';
const INTERNAL_DETAILS_URL = 'https://sam.gov/api/prod/opps/v2/opportunities';
const INTERNAL_RESOURCES_URL = 'https://sam.gov/api/prod/opps/v3/opportunities';
const INTERNAL_DOWNLOAD_URL = 'https://sam.gov/api/prod/opps/v3/opportunities/resources/files';
const DEFAULT_INDEX_FUNCTION_URL = 'https://igkjmfjmwatgtubfjcok.supabase.co/functions/v1/index-search-results';

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
  const text = cleanText(value, 64);
  if (!text) return null;
  const iso = text.match(/^(\d{4}-\d{2}-\d{2})/);
  if (iso) return iso[1];
  const us = text.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})/);
  if (us) return `${us[3]}-${String(us[1]).padStart(2, '0')}-${String(us[2]).padStart(2, '0')}`;
  return null;
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

function responseHeaders(request, env, upstream, cacheSeconds) {
  const headers = new Headers(upstream.headers);
  for (const [key, value] of Object.entries(corsHeaders(request, env))) {
    headers.set(key, value);
  }
  headers.set('Cache-Control', upstream.ok ? `public, max-age=${cacheSeconds}` : 'no-store');
  headers.delete('Content-Security-Policy');
  headers.delete('X-Frame-Options');
  return headers;
}

async function relay(request, env, targetUrl, cacheSeconds = 30) {
  const upstream = await fetch(targetUrl.toString(), {
    method: request.method === 'HEAD' ? 'HEAD' : 'GET',
    headers: samHeaders(),
    redirect: 'follow',
  });

  return new Response(upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: responseHeaders(request, env, upstream, cacheSeconds),
  });
}

async function relayJsonAndIndex(request, env, ctx, targetUrl, cacheSeconds, buildIndexJobs) {
  const upstream = await fetch(targetUrl.toString(), {
    method: request.method === 'HEAD' ? 'HEAD' : 'GET',
    headers: samHeaders(),
    redirect: 'follow',
  });

  const text = await upstream.text();
  const headers = responseHeaders(request, env, upstream, cacheSeconds);

  if (upstream.ok && request.method !== 'HEAD') {
    try {
      const data = JSON.parse(text);
      const jobs = buildIndexJobs(data).filter((job) => job.rows && job.rows.length);
      const task = Promise.all(jobs.map((job) => postIndexRows(env, job.kind, job.rows))).catch((error) => {
        console.warn('Indexing failed:', error && error.message ? error.message : String(error));
      });
      if (ctx && typeof ctx.waitUntil === 'function') ctx.waitUntil(task);
    } catch (error) {
      console.warn('Index preparation failed:', error && error.message ? error.message : String(error));
    }
  }

  return new Response(text, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers,
  });
}

function indexFunctionUrl(env) {
  return String(env.INDEX_FUNCTION_URL || DEFAULT_INDEX_FUNCTION_URL).trim();
}

async function postIndexRows(env, kind, rows) {
  if (!Array.isArray(rows) || rows.length === 0) return { ok: true, indexed: 0 };
  const target = indexFunctionUrl(env);
  if (!target) throw new Error('INDEX_FUNCTION_URL is not configured.');
  const response = await fetch(target, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
    body: JSON.stringify({ kind, rows: rows.slice(0, 500) }),
  });
  const body = await response.text();
  if (!response.ok) {
    throw new Error(`Supabase index function failed ${response.status}: ${body.slice(0, 500)}`);
  }
  try {
    return JSON.parse(body);
  } catch {
    return { ok: true, raw: body };
  }
}

function resultsFrom(data) {
  if (data && data._embedded && Array.isArray(data._embedded.results)) return data._embedded.results.filter(Boolean);
  for (const key of ['results', 'opportunitiesData', 'items']) {
    if (Array.isArray(data && data[key])) return data[key].filter(Boolean);
  }
  return [];
}

function getPath(object, path) {
  let current = object;
  for (const part of path) {
    if (!current || typeof current !== 'object') return null;
    current = current[part];
  }
  return current ?? null;
}

function noticeIdFrom(row) {
  return cleanText(row.notice_id || row.noticeId || row.noticeID || row._id || row.id || row.opportunityId, 200);
}

function typeFrom(row) {
  const type = row && row.type;
  if (type && typeof type === 'object') {
    return [type.code, type.value].map((v) => cleanText(v, 120)).filter(Boolean).join(' ') || null;
  }
  return cleanText(row.notice_type || row.noticeType || type, 250);
}

function orgFrom(row) {
  const hierarchy = row.organizationHierarchy || row.organizationHierarchyName;
  if (Array.isArray(hierarchy)) {
    const parts = hierarchy.map((item) => {
      if (item && typeof item === 'object') return cleanText(item.name || item.value, 300);
      return cleanText(item, 300);
    }).filter(Boolean);
    if (parts.length) return parts.join(' > ');
  }
  return cleanText(row.agency || row.organization || row.fullParentPathName || row.organizationName || row.officeName || row.agencyName, 1200);
}

function normalizeOpportunity(row) {
  const noticeId = noticeIdFrom(row);
  if (!noticeId) return null;
  return {
    notice_id: noticeId,
    solicitation_number: cleanText(row.solicitation_number || row.solicitationNumber, 500),
    title: cleanText(row.title || row.notice_title || row.noticeTitle, 1000),
    posted_date: cleanDate(row.posted_date || row.postedDate || row.publishDate),
    response_deadline: cleanText(row.response_deadline || row.responseDeadline || row.responseDate || row.responseDeadLine, 250),
    agency: orgFrom(row),
    notice_type: typeFrom(row),
    naics: cleanText(row.naics || row.naicsCode, 100),
    psc: cleanText(row.psc || row.classificationCode || row.pscCode, 100),
    description: cleanText(row.description || row.descriptionText, 12000),
    sam_url: cleanText(row.sam_url || row.samUrl || row.uiLink || `https://sam.gov/opp/${encodeURIComponent(noticeId)}/view`, 1000),
    source_json: row,
  };
}

function extensionFrom(name) {
  const text = cleanText(name, 1000) || '';
  const clean = text.split('?')[0].split('#')[0].toLowerCase();
  const index = clean.lastIndexOf('.');
  return index >= 0 ? clean.slice(index + 1) : null;
}

function formatGroupFrom(name) {
  const ext = extensionFrom(name);
  if (['zip', '7z', 'rar', 'tar', 'gz', 'tgz', 'bz2'].includes(ext)) return 'Compressed File';
  if (ext === 'pdf') return 'PDF';
  if (['xls', 'xlsx', 'xlsm', 'csv'].includes(ext)) return 'Spreadsheet';
  if (['doc', 'docx', 'rtf'].includes(ext)) return 'Word';
  if (['ppt', 'pptx', 'pps', 'ppsx'].includes(ext)) return 'Presentation';
  if (['dwg', 'dxf', 'dgn', 'stp', 'step', 'igs', 'iges', 'prt', 'asm', 'sldprt', 'sldasm', 'catpart', 'catproduct', 'c4', 'cal', 'tdp', 'mil'].includes(ext)) return 'CAD / Drawing';
  if (['png', 'jpg', 'jpeg', 'gif', 'tif', 'tiff', 'bmp', 'webp'].includes(ext)) return 'Image';
  if (['txt', 'xml', 'json', 'htm', 'html'].includes(ext)) return 'Text';
  return 'Other';
}

function docsFromResources(data, noticeId) {
  const docs = [];
  const lists = getPath(data, ['_embedded', 'opportunityAttachmentList']);
  if (!Array.isArray(lists)) return docs;
  for (const group of lists) {
    const attachments = Array.isArray(group && group.attachments) ? group.attachments : [];
    for (const attachment of attachments) {
      if (!attachment || cleanText(attachment.deletedFlag, 10) === '1') continue;
      const resourceId = cleanText(attachment.resourceId, 200);
      const name = cleanText(attachment.name || attachment.filename, 1000);
      if (!noticeId || !resourceId || !name) continue;
      const size = Number(String(attachment.size ?? '').replace(/,/g, ''));
      docs.push({
        notice_id: noticeId,
        resource_id: resourceId,
        document_name: name,
        extension: extensionFrom(name),
        format_group: formatGroupFrom(name),
        size_bytes: Number.isFinite(size) ? size : null,
        download_url: `${INTERNAL_DOWNLOAD_URL}/${encodeURIComponent(resourceId)}/download`,
        sam_url: `https://sam.gov/opp/${encodeURIComponent(noticeId)}/view`,
        source_json: attachment,
      });
    }
  }
  return docs;
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
  const rows = kind === 'opportunities'
    ? inputRows.map(normalizeOpportunity).filter(Boolean)
    : inputRows;

  try {
    const result = await postIndexRows(env, kind, rows);
    return jsonResponse(request, env, result);
  } catch (error) {
    return errorResponse(request, env, error && error.message ? error.message : String(error), 502);
  }
}

async function handleRequest(request, env, ctx) {
  const url = new URL(request.url);
  const path = url.pathname.replace(/\/+$/, '') || '/';

  if (request.method === 'OPTIONS') {
    return new Response(null, { status: 204, headers: corsHeaders(request, env) });
  }

  if (path === '/' || path === '/health') {
    return jsonResponse(request, env, {
      ok: true,
      name: 'samgovsearch no-api proxy',
      usesApiKey: false,
      supabaseIndexing: true,
      indexingMode: 'supabase-edge-function',
      indexFunctionUrl: indexFunctionUrl(env),
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
    const targetUrl = buildSearchUrl(url);
    return relayJsonAndIndex(request, env, ctx, targetUrl, 20, (data) => {
      const rows = resultsFrom(data).map(normalizeOpportunity).filter(Boolean);
      return [{ kind: 'opportunities', rows }];
    });
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
    return relayJsonAndIndex(request, env, ctx, `${INTERNAL_RESOURCES_URL}/${encodeURIComponent(noticeId)}/resources`, 60, (data) => {
      const rows = docsFromResources(data, noticeId);
      return [{ kind: 'documents', rows }];
    });
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
  async fetch(request, env, ctx) {
    try {
      return await handleRequest(request, env || {}, ctx);
    } catch (error) {
      return errorResponse(request, env || {}, error && error.message ? error.message : String(error), 502);
    }
  },
};
