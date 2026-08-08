(() => {
  'use strict';

  const nativeFetch = window.fetch.bind(window);
  const STEP_ORDER = ['indexedOpportunity','indexedDocuments','liveDetails','liveResources','normalize','extract','graph'];
  const LABELS = {
    indexedOpportunity: ['Indexed opportunity', 'Read the saved opportunity record from Supabase.'],
    indexedDocuments: ['Indexed source inventory', 'Read any attachment metadata already indexed for this notice.'],
    liveDetails: ['Live SAM.gov notice', 'Fetch the current public opportunity detail record.'],
    liveResources: ['Live attachment inventory', 'Fetch the current SAM.gov resource list and resource IDs.'],
    normalize: ['Normalize evidence', 'Merge live and indexed fields into one canonical contract record.'],
    extract: ['Extract technical candidates', 'Scan the title, description, and source filenames for candidate technical entities.'],
    graph: ['Build ontology graph', 'Create evidence-linked contract, context, source, and candidate nodes.'],
  };

  let session = null;
  let elapsedTimer = null;

  function text(v) { return v == null ? '' : String(v).trim(); }
  function noticeId() { return text(new URLSearchParams(location.search).get('noticeId')); }
  function isOntologyContext() {
    const params = new URLSearchParams(location.search);
    if (params.get('view') === 'ontology') return true;
    const active = document.querySelector('.nav-item[data-view="ontology"].active');
    if (active) return true;
    const mount = document.getElementById('viewMount');
    return !!(mount && mount.textContent.includes('Building technical ontology'));
  }

  function classify(url) {
    const value = String(url || '');
    if (/\/rest\/v1\/opportunities(?:\?|$)/.test(value)) return 'indexedOpportunity';
    if (/\/rest\/v1\/documents(?:\?|$)/.test(value)) return 'indexedDocuments';
    if (/\/details\//.test(value)) return 'liveDetails';
    if (/\/resources\//.test(value)) return 'liveResources';
    return '';
  }

  function startSession() {
    const id = noticeId();
    if (!id) return null;
    if (session && session.noticeId === id && !session.finished) return session;
    session = {
      noticeId: id,
      startedAt: performance.now(),
      finished: false,
      steps: Object.fromEntries(STEP_ORDER.map(k => [k, { status: 'pending', detail: '' }])),
    };
    ensurePanel();
    startElapsedClock();
    return session;
  }

  function startElapsedClock() {
    clearInterval(elapsedTimer);
    elapsedTimer = setInterval(() => {
      if (!session || session.finished) { clearInterval(elapsedTimer); return; }
      const node = document.getElementById('ontologyProgressElapsed');
      if (node) node.textContent = `${((performance.now() - session.startedAt) / 1000).toFixed(1)}s elapsed`;
    }, 100);
  }

  function statusIcon(status) {
    if (status === 'done') return '✓';
    if (status === 'running') return '●';
    if (status === 'warn') return '!';
    if (status === 'error') return '×';
    return '○';
  }

  function ensureStyles() {
    if (document.getElementById('ontologyProgressStyles')) return;
    const style = document.createElement('style');
    style.id = 'ontologyProgressStyles';
    style.textContent = `
      .ontology-progress{max-width:940px;margin:42px auto 0;border:1px solid var(--line2);border-radius:10px;background:linear-gradient(180deg,#0d1f33,#091827);box-shadow:0 20px 50px rgba(0,0,0,.18);overflow:hidden}
      .ontology-progress-head{padding:15px 17px;border-bottom:1px solid var(--line);display:flex;align-items:flex-start;justify-content:space-between;gap:14px}.ontology-progress-head h3{margin:0;font-size:16px}.ontology-progress-head p{margin:3px 0 0;color:var(--muted);font-size:11px}.ontology-progress-head span{color:#79dff0;font-size:11px;white-space:nowrap}
      .ontology-progress-bar{height:3px;background:#07111e}.ontology-progress-bar>i{display:block;height:100%;width:0;background:linear-gradient(90deg,var(--cyan2),var(--cyan));transition:width .2s ease}
      .ontology-progress-list{padding:7px 17px 12px}.ontology-progress-row{display:grid;grid-template-columns:24px minmax(190px,.75fr) minmax(260px,1.5fr) auto;gap:9px;align-items:center;padding:9px 0;border-bottom:1px solid rgba(32,54,80,.65)}.ontology-progress-row:last-child{border-bottom:0}.ontology-progress-icon{width:20px;height:20px;border-radius:50%;display:grid;place-items:center;border:1px solid #35516b;color:#738ba2;font-size:10px}.ontology-progress-row.running .ontology-progress-icon{border-color:#18c9e5;color:#67e9fa;box-shadow:0 0 12px rgba(22,216,244,.15)}.ontology-progress-row.done .ontology-progress-icon{border-color:#327355;color:#62da93}.ontology-progress-row.warn .ontology-progress-icon{border-color:#77612e;color:#f2c761}.ontology-progress-row.error .ontology-progress-icon{border-color:#7e3940;color:#ff828b}.ontology-progress-name{font-weight:700;font-size:11px}.ontology-progress-desc{color:var(--muted);font-size:10px}.ontology-progress-detail{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;color:#89a1b7;font-size:9px;text-align:right;white-space:nowrap}
      .ontology-progress-note{padding:10px 17px;border-top:1px solid var(--line);background:#081523;color:#7890a7;font-size:10px}.ontology-progress-note strong{color:#9fb6c9}
      @media(max-width:850px){.ontology-progress{margin-top:18px}.ontology-progress-row{grid-template-columns:22px 1fr}.ontology-progress-desc,.ontology-progress-detail{grid-column:2}.ontology-progress-detail{text-align:left}}
    `;
    document.head.appendChild(style);
  }

  function ensurePanel() {
    if (!session || session.finished) return;
    const mount = document.getElementById('viewMount');
    if (!mount || mount.querySelector('#ontologyRoot')) return;
    ensureStyles();
    mount.innerHTML = `
      <section id="ontologyProgress" class="ontology-progress">
        <div class="ontology-progress-head"><div><h3>Building Technical Ontology</h3><p>Watching the actual public-data requests and local graph build for this contract.</p></div><span id="ontologyProgressElapsed">0.0s elapsed</span></div>
        <div class="ontology-progress-bar"><i id="ontologyProgressBar"></i></div>
        <div id="ontologyProgressList" class="ontology-progress-list"></div>
        <div class="ontology-progress-note"><strong>No AI call is happening here.</strong> This stage currently uses SAM.gov + Supabase metadata and local deterministic extraction. Attachment file contents are not parsed yet.</div>
      </section>`;
    renderPanel();
  }

  function renderPanel() {
    if (!session || session.finished) return;
    const list = document.getElementById('ontologyProgressList');
    if (!list) return;
    const completed = STEP_ORDER.filter(k => ['done','warn'].includes(session.steps[k].status)).length;
    const runningBonus = STEP_ORDER.some(k => session.steps[k].status === 'running') ? .35 : 0;
    const pct = Math.min(96, Math.round(((completed + runningBonus) / STEP_ORDER.length) * 100));
    const bar = document.getElementById('ontologyProgressBar');
    if (bar) bar.style.width = `${pct}%`;
    list.innerHTML = STEP_ORDER.map(key => {
      const s = session.steps[key], meta = LABELS[key];
      return `<div class="ontology-progress-row ${s.status}"><div class="ontology-progress-icon">${statusIcon(s.status)}</div><div class="ontology-progress-name">${meta[0]}</div><div class="ontology-progress-desc">${meta[1]}</div><div class="ontology-progress-detail">${s.detail || (s.status === 'pending' ? 'waiting' : s.status)}</div></div>`;
    }).join('');
  }

  function setStep(key, status, detail='') {
    if (!session || !session.steps[key]) return;
    session.steps[key].status = status;
    if (detail) session.steps[key].detail = detail;
    ensurePanel();
    renderPanel();
  }

  function allNetworkSettled() {
    return ['indexedOpportunity','indexedDocuments','liveDetails','liveResources'].every(k => ['done','warn','error'].includes(session.steps[k].status));
  }

  function afterNetwork() {
    if (!session || !allNetworkSettled()) return;
    if (session.steps.normalize.status === 'pending') {
      setStep('normalize','running','merging live + indexed evidence');
      requestAnimationFrame(() => {
        if (!session || session.finished) return;
        setStep('normalize','done','canonical record ready');
        setStep('extract','running','scanning title, description + filenames');
        requestAnimationFrame(() => {
          if (!session || session.finished) return;
          setStep('extract','done','candidate terms ranked locally');
          setStep('graph','running','laying out nodes + evidence edges');
        });
      });
    }
  }

  async function summarizeResponse(key, response) {
    const ms = Math.round(performance.now() - (response.__cbStartedAt || performance.now()));
    try {
      const data = await response.clone().json();
      if (key === 'indexedOpportunity') {
        const n = Array.isArray(data) ? data.length : 0;
        return `${response.status} • ${n} indexed record${n===1?'':'s'}`;
      }
      if (key === 'indexedDocuments') {
        const n = Array.isArray(data) ? data.length : 0;
        return `${response.status} • ${n} indexed source${n===1?'':'s'}`;
      }
      if (key === 'liveResources') {
        const groups = data?._embedded?.opportunityAttachmentList;
        let n = 0;
        if (Array.isArray(groups)) for (const g of groups) n += Array.isArray(g?.attachments) ? g.attachments.filter(a => a && String(a.deletedFlag||'') !== '1').length : 0;
        return `${response.status} • ${n} live attachment${n===1?'':'s'}`;
      }
      return `${response.status} • current notice loaded`;
    } catch {
      return `${response.status}${ms ? ` • ${ms} ms` : ''}`;
    }
  }

  window.fetch = async function(input, init) {
    const url = typeof input === 'string' ? input : input && input.url;
    const key = classify(url);
    const relevant = key && isOntologyContext();
    const started = performance.now();
    if (relevant) {
      startSession();
      setStep(key,'running','request in progress');
    }
    try {
      const response = await nativeFetch(input, init);
      if (relevant && session && !session.finished) {
        response.__cbStartedAt = started;
        const detail = await summarizeResponse(key,response);
        setStep(key,response.ok?'done':'warn',detail);
        afterNetwork();
      }
      return response;
    } catch (error) {
      if (relevant && session && !session.finished) {
        setStep(key,'warn',`fallback path • ${text(error && error.message || error).slice(0,80)}`);
        afterNetwork();
      }
      throw error;
    }
  };

  function finishWhenGraphAppears() {
    const mount = document.getElementById('viewMount');
    if (!mount) return;
    const observer = new MutationObserver(() => {
      const loadingText = mount.textContent || '';
      if (loadingText.includes('Building technical ontology') && !mount.querySelector('#ontologyProgress')) {
        startSession();
        ensurePanel();
      }
      if (mount.querySelector('#ontologyRoot') && session && !session.finished) {
        setStep('graph','done','graph ready');
        session.finished = true;
        clearInterval(elapsedTimer);
      }
    });
    observer.observe(mount,{childList:true,subtree:true});
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded',finishWhenGraphAppears);
  else finishWhenGraphAppears();
})();
