(() => {
  'use strict';

  const WORKER = 'https://samgovsearch.spotterdeer.workers.dev';
  let timer = null;
  const text = value => value == null ? '' : String(value).trim();
  const esc = value => text(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

  function injectStyles() {
    if (document.getElementById('cbManualEvidenceStyles')) return;
    const style = document.createElement('style');
    style.id = 'cbManualEvidenceStyles';
    style.textContent = `
      .cb-manual-banner{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:14px;align-items:center;margin:0 0 12px;padding:13px 15px;border:1px solid #38617f;border-radius:8px;background:linear-gradient(180deg,rgba(12,35,55,.94),rgba(8,25,40,.94))}
      .cb-manual-banner h3{margin:0 0 3px;font-size:14px}.cb-manual-banner p{margin:0;color:var(--muted);font-size:11px;line-height:1.45}.cb-manual-banner strong{color:#8ff0ff}.cb-manual-tag{display:inline-flex;align-items:center;gap:6px;border:1px solid #725d2a;background:rgba(176,127,29,.12);color:#f1c665;border-radius:999px;padding:5px 9px;font-size:10px;font-weight:800;white-space:nowrap}
      .cb-manual-result{margin:0 0 12px;padding:11px 13px;border:1px solid var(--line);border-radius:8px;background:#081726;font-size:11px}.cb-manual-result.hidden{display:none}.cb-manual-result.good{border-color:#287650}.cb-manual-result.bad{border-color:#7f3941}.cb-manual-result h4{margin:0 0 7px;font-size:12px}.cb-manual-result-grid{display:grid;grid-template-columns:130px minmax(0,1fr);gap:4px 10px}.cb-manual-result-grid span:nth-child(odd){color:var(--muted)}.cb-manual-result code{word-break:break-all;color:#bfeff6}
      .cb-source-actions{display:flex;gap:6px;align-items:center;flex-wrap:wrap}.cb-source-actions .btn{padding:6px 8px;font-size:10px;white-space:nowrap}.cb-source-test-status{display:block;margin-top:5px;color:var(--muted);font-size:9px}.cb-source-test-status.good{color:var(--green)}.cb-source-test-status.bad{color:#ff8b93}
      .cb-no-source-note{margin:0 0 12px;padding:16px;border:1px solid #68552d;border-radius:8px;background:rgba(104,85,45,.09);color:#e8c56a}.cb-no-source-note strong{display:block;color:#ffd476;margin-bottom:4px}
      @media(max-width:800px){.cb-manual-banner{grid-template-columns:1fr}.cb-manual-result-grid{grid-template-columns:1fr}}
    `;
    document.head.appendChild(style);
  }

  function ensureTopMode() {
    const footer = document.querySelector('.sidebar-footer span');
    if (footer) footer.textContent = 'Manual evidence mode';
    const actions = document.querySelector('.top-actions');
    if (actions && !document.getElementById('cbManualEvidenceTop')) {
      const button = document.createElement('button');
      button.id = 'cbManualEvidenceTop';
      button.className = 'btn btn-secondary';
      button.textContent = 'Evidence: Manual';
      button.title = 'Automatic attachment parsing is disabled while download behavior is being verified.';
      button.addEventListener('click', () => {
        const sourceNav = document.querySelector('.nav-item[data-view="sources"]');
        if (sourceNav) sourceNav.click();
      });
      actions.insertBefore(button, actions.querySelector('#refreshTopBtn'));
    }
  }

  function sourceContext() {
    const mount = document.getElementById('viewMount');
    if (!mount) return null;
    const heading = [...mount.querySelectorAll('h2')].find(h => h.textContent.trim() === 'Sources');
    if (!heading) return null;
    const table = mount.querySelector('.data-table');
    return { mount, heading, table };
  }

  function rowsWithResources(table) {
    if (!table) return [];
    return [...table.querySelectorAll('tbody tr')].filter(row => {
      if (row.children.length < 2) return false;
      const rid = text(row.children[1]?.textContent);
      return /^[A-Za-z0-9_.:-]{8,160}$/.test(rid);
    });
  }

  function ensureBanner(ctx, rows) {
    let banner = ctx.mount.querySelector('#cbManualEvidenceBanner');
    if (!banner) {
      banner = document.createElement('section');
      banner.id = 'cbManualEvidenceBanner';
      banner.className = 'cb-manual-banner';
      const anchor = ctx.table?.closest('.table-wrap') || ctx.table;
      if (anchor) anchor.parentNode.insertBefore(banner, anchor);
      else ctx.mount.prepend(banner);
    }
    banner.innerHTML = `<div><h3>Manual Attachment Verification</h3><p><strong>Automatic parsing is OFF.</strong> Nothing here starts PDF.js, OCR, hashing, IndexedDB extraction, or Supabase evidence writes. Test one SAM.gov resource at a time before we re-enable analysis.</p></div><span class="cb-manual-tag">${rows.length} public source${rows.length === 1 ? '' : 's'} detected</span>`;

    let result = ctx.mount.querySelector('#cbManualEvidenceResult');
    if (!result) {
      result = document.createElement('section');
      result.id = 'cbManualEvidenceResult';
      result.className = 'cb-manual-result hidden';
      banner.insertAdjacentElement('afterend', result);
    }
    return result;
  }

  function showNoSources(ctx) {
    let note = ctx.mount.querySelector('#cbNoSourceNote');
    if (!note) {
      note = document.createElement('div');
      note.id = 'cbNoSourceNote';
      note.className = 'cb-no-source-note';
      const anchor = ctx.table?.closest('.table-wrap') || ctx.table;
      if (anchor) anchor.parentNode.insertBefore(note, anchor);
      else ctx.mount.appendChild(note);
    }
    note.innerHTML = '<strong>No public attachments were returned for this opportunity.</strong>There is nothing to download or parse. Contract Brain will remain idle. Later analysis can still use the opportunity metadata, but the attachment pipeline should not run.';
  }

  function removeNoSources(ctx) {
    ctx.mount.querySelector('#cbNoSourceNote')?.remove();
  }

  function downloadUrl(resourceId) {
    return `${WORKER}/download/${encodeURIComponent(resourceId)}`;
  }

  function headerValue(response, name) {
    try { return response.headers.get(name) || ''; } catch { return ''; }
  }

  function expectedSize(row) {
    return text(row.children[2]?.textContent) || '—';
  }

  async function probe(row, button) {
    const resourceId = text(row.children[1]?.textContent);
    const name = text(row.querySelector('.doc-name')?.textContent) || resourceId;
    const status = row.querySelector('[data-cb-test-status]');
    const result = document.getElementById('cbManualEvidenceResult');
    if (!resourceId || !result) return;

    button.disabled = true;
    if (status) { status.className = 'cb-source-test-status'; status.textContent = 'Checking response headers…'; }
    result.className = 'cb-manual-result';
    result.innerHTML = `<h4>${esc(name)}</h4><div class="muted">Sending a HEAD request through the same Worker download route. No attachment body is being loaded into JavaScript.</div>`;

    const started = performance.now();
    try {
      const response = await fetch(downloadUrl(resourceId), { method: 'HEAD', cache: 'no-store', headers: { Accept: '*/*' } });
      const elapsed = Math.round(performance.now() - started);
      const type = headerValue(response, 'content-type') || 'not exposed';
      const length = headerValue(response, 'content-length') || 'not exposed';
      const disposition = headerValue(response, 'content-disposition') || 'not exposed to browser';
      const ok = response.ok;
      result.className = `cb-manual-result ${ok ? 'good' : 'bad'}`;
      result.innerHTML = `<h4>${ok ? '✓ Download route responded' : '× Download route failed'} — ${esc(name)}</h4><div class="cb-manual-result-grid"><span>HTTP</span><span>${esc(response.status)} ${esc(response.statusText)}</span><span>Resource ID</span><code>${esc(resourceId)}</code><span>Expected SAM size</span><span>${esc(expectedSize(row))}</span><span>Response length</span><span>${esc(length)}</span><span>Content type</span><span>${esc(type)}</span><span>Content disposition</span><span>${esc(disposition)}</span><span>Round trip</span><span>${elapsed} ms</span><span>Next step</span><span>${ok ? 'Click “Download exact file” to let the browser stream the body directly. Contract Brain will not parse it.' : 'Do not analyze this source. The raw download path must be fixed first.'}</span></div>`;
      if (status) { status.className = `cb-source-test-status ${ok ? 'good' : 'bad'}`; status.textContent = ok ? `HEAD ${response.status} • ready to stream` : `HEAD ${response.status} • failed`; }
    } catch (error) {
      result.className = 'cb-manual-result bad';
      result.innerHTML = `<h4>× Download probe failed — ${esc(name)}</h4><div class="cb-manual-result-grid"><span>Resource ID</span><code>${esc(resourceId)}</code><span>Error</span><span>${esc(error?.message || error)}</span><span>Meaning</span><span>No parser was involved. This failure is strictly in the browser → Worker → SAM.gov download path.</span></div>`;
      if (status) { status.className = 'cb-source-test-status bad'; status.textContent = 'Probe failed'; }
    } finally {
      button.disabled = false;
    }
  }

  function decorateRow(row) {
    if (row.dataset.cbManualDownload === '1') return;
    const resourceId = text(row.children[1]?.textContent);
    if (!resourceId) return;
    const name = text(row.querySelector('.doc-name')?.textContent) || resourceId;
    const action = row.lastElementChild;
    if (!action) return;
    row.dataset.cbManualDownload = '1';
    action.innerHTML = '';
    const wrap = document.createElement('div');
    wrap.className = 'cb-source-actions';

    const test = document.createElement('button');
    test.type = 'button';
    test.className = 'btn btn-secondary';
    test.textContent = 'Test Download';
    test.title = 'Checks the download route with HEAD. Does not load the file body or start analysis.';
    test.addEventListener('click', event => { event.preventDefault(); event.stopPropagation(); probe(row, test); });

    const download = document.createElement('a');
    download.className = 'btn btn-accent';
    download.href = downloadUrl(resourceId);
    download.target = '_blank';
    download.rel = 'noopener';
    download.textContent = 'Download exact file ↗';
    download.title = `Stream SAM.gov resource ${resourceId} directly through the Worker. No parsing.`;

    wrap.append(test, download);
    const status = document.createElement('small');
    status.dataset.cbTestStatus = '1';
    status.className = 'cb-source-test-status';
    status.textContent = name.toLowerCase().endsWith('.zip') ? 'ZIP will be downloaded as the complete archive.' : 'Not tested yet.';
    action.append(wrap, status);
  }

  function decorateSources() {
    injectStyles();
    ensureTopMode();
    const ctx = sourceContext();
    if (!ctx) return;
    const rows = rowsWithResources(ctx.table);
    ensureBanner(ctx, rows);
    if (!rows.length) {
      showNoSources(ctx);
      return;
    }
    removeNoSources(ctx);
    rows.forEach(decorateRow);
  }

  function schedule() {
    clearTimeout(timer);
    timer = setTimeout(decorateSources, 80);
  }

  function init() {
    injectStyles();
    ensureTopMode();
    const mount = document.getElementById('viewMount');
    if (mount) new MutationObserver(schedule).observe(mount, { childList: true, subtree: true });
    window.addEventListener('popstate', schedule);
    schedule();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, { once: true });
  else init();
})();
