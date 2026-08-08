(() => {
  'use strict';

  const SUPABASE_URL = 'https://igkjmfjmwatgtubfjcok.supabase.co';
  const SUPABASE_KEY = 'sb_publishable_O5yiMJQAdYTHJWCvyAQU5g_3jasem35';
  let timer = null;
  let serial = 0;

  const esc = value => String(value == null ? '' : value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

  function noticeId() {
    return new URLSearchParams(location.search).get('noticeId') || '';
  }

  async function loadStatus(id) {
    const url = new URL(`${SUPABASE_URL}/rest/v1/document_analysis_status`);
    url.searchParams.set('select', 'resource_id,sha256,extraction_status,extraction_mode,page_count,logical_row_count,ocr_page_count,parser_version,completed_at');
    url.searchParams.set('notice_id', `eq.${id}`);
    const response = await fetch(url, {
      headers: { apikey: SUPABASE_KEY, Authorization: `Bearer ${SUPABASE_KEY}`, Accept: 'application/json' },
      cache: 'no-store',
    });
    if (!response.ok) throw new Error(`${response.status}: ${(await response.text()).slice(0,240)}`);
    return response.json();
  }

  function badge(status) {
    if (status === 'complete') return '<span class="status-pill green">Complete</span>';
    if (status === 'running') return '<span class="status-pill">Running</span>';
    if (status === 'review_required') return '<span class="status-pill amber">Review required</span>';
    if (status === 'failed') return '<span class="status-pill red">Failed</span>';
    return '<span class="muted">Not processed</span>';
  }

  function ensureColumns(table) {
    const headRow = table.querySelector('thead tr');
    if (!headRow || headRow.querySelector('[data-cb-analysis-head]')) return;
    const action = headRow.lastElementChild;
    for (const label of ['Analysis', 'Rows']) {
      const th = document.createElement('th');
      th.dataset.cbAnalysisHead = '1';
      th.textContent = label;
      headRow.insertBefore(th, action);
    }
  }

  function ensureRowCells(row) {
    if (row.querySelector('[data-cb-analysis-status]')) return;
    const action = row.lastElementChild;
    const status = document.createElement('td');
    status.dataset.cbAnalysisStatus = '1';
    status.innerHTML = '<span class="muted">Checking…</span>';
    const count = document.createElement('td');
    count.dataset.cbAnalysisRows = '1';
    count.className = 'size';
    count.textContent = '—';
    row.insertBefore(status, action);
    row.insertBefore(count, action);
  }

  function apply(table, records) {
    const byResource = new Map((records || []).map(row => [String(row.resource_id || ''), row]));
    let analyzed = 0;
    const bodyRows = [...table.querySelectorAll('tbody tr')];
    for (const row of bodyRows) {
      if (row.children.length < 5) continue;
      ensureRowCells(row);
      const resourceId = (row.children[1]?.textContent || '').trim();
      const record = byResource.get(resourceId);
      const statusCell = row.querySelector('[data-cb-analysis-status]');
      const rowsCell = row.querySelector('[data-cb-analysis-rows]');
      if (!statusCell || !rowsCell) continue;
      if (!record || !record.extraction_status) {
        statusCell.innerHTML = badge('');
        statusCell.title = 'This source has not been persisted into Contract Brain evidence memory yet.';
        rowsCell.textContent = '—';
        continue;
      }
      analyzed += record.extraction_status === 'complete' ? 1 : 0;
      statusCell.innerHTML = badge(record.extraction_status);
      statusCell.title = [record.extraction_mode, record.parser_version, record.completed_at ? `Completed ${record.completed_at}` : ''].filter(Boolean).join('\n');
      rowsCell.textContent = Number(record.logical_row_count || 0).toLocaleString();
      rowsCell.title = `${record.page_count || '—'} pages; ${record.ocr_page_count || 0} OCR pages`;
    }

    const titleRow = document.querySelector('#viewMount .view-title-row');
    if (titleRow && !titleRow.querySelector('[data-cb-memory-summary]')) {
      const summary = document.createElement('span');
      summary.dataset.cbMemorySummary = '1';
      summary.className = 'status-pill green';
      summary.textContent = `${analyzed}/${bodyRows.length} analyzed`;
      const target = titleRow.lastElementChild || titleRow;
      target.appendChild(summary);
    } else if (titleRow) {
      const summary = titleRow.querySelector('[data-cb-memory-summary]');
      if (summary) summary.textContent = `${analyzed}/${bodyRows.length} analyzed`;
    }
  }

  async function refresh() {
    const id = noticeId();
    const mount = document.getElementById('viewMount');
    if (!id || !mount) return;
    const heading = [...mount.querySelectorAll('h2')].find(h => h.textContent.trim() === 'Sources');
    const table = heading ? mount.querySelector('.data-table') : null;
    if (!table) return;
    ensureColumns(table);
    [...table.querySelectorAll('tbody tr')].forEach(ensureRowCells);
    const mySerial = ++serial;
    try {
      const records = await loadStatus(id);
      if (mySerial !== serial) return;
      apply(table, records);
    } catch (error) {
      if (mySerial !== serial) return;
      for (const cell of table.querySelectorAll('[data-cb-analysis-status]')) {
        cell.innerHTML = '<span class="status-pill red">Status unavailable</span>';
        cell.title = error.message || String(error);
      }
    }
  }

  function schedule() {
    clearTimeout(timer);
    timer = setTimeout(refresh, 80);
  }

  const mount = document.getElementById('viewMount');
  if (mount) new MutationObserver(schedule).observe(mount, { childList: true, subtree: true });
  window.addEventListener('popstate', schedule);
  window.addEventListener('contractbrain:evidence-updated', schedule);
  schedule();
})();

(() => {
  if (document.querySelector('script[data-cb-browser-pipeline]')) return;
  const script = document.createElement('script');
  script.src = 'contract-brain-browser-pipeline.js';
  script.defer = true;
  script.dataset.cbBrowserPipeline = '1';
  document.head.appendChild(script);
})();
