(() => {
  'use strict';

  const WORKER = 'https://samgovsearch.spotterdeer.workers.dev';
  const SUPABASE_URL = 'https://igkjmfjmwatgtubfjcok.supabase.co';
  const SUPABASE_KEY = 'sb_publishable_O5yiMJQAdYTHJWCvyAQU5g_3jasem35';
  const STORAGE = {
    saved: 'samgovsearch.contractBrain.saved.v1',
    snapshots: 'samgovsearch.contractBrain.snapshots.v1',
    history: 'samgovsearch.contractBrain.history.v1',
  };

  const el = Object.fromEntries([
    'globalSearch','searchResults','lastRefreshTop','liveDot','refreshTopBtn','content','emptyState','noticeInput','openNoticeBtn','notebook','contractTitle','noticeIdButton','agencyChip','typeChip','deadlineChip','saveNotebookBtn','samLink','viewMount','toast','navSourceCount','navChangeCount','savedCount','refreshSideBtn'
  ].map(id => [id, document.getElementById(id)]));

  const state = {
    view: 'overview',
    noticeId: '',
    opportunity: null,
    documents: [],
    indexedDocuments: [],
    currentSnapshot: null,
    currentChanges: [],
    refreshing: false,
    searchTimer: null,
  };

  const text = v => v == null ? '' : String(v).trim();
  const esc = v => text(v).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const loadJson = (key, fallback) => { try { return JSON.parse(localStorage.getItem(key) || '') || fallback; } catch { return fallback; } };
  const saveJson = (key, value) => localStorage.setItem(key, JSON.stringify(value));
  const fmtDateTime = value => { if (!value) return 'Never'; const d = new Date(value); return Number.isNaN(d.getTime()) ? value : d.toLocaleString(); };
  const fmtDate = value => { if (!value) return ''; const d = new Date(value); return Number.isNaN(d.getTime()) ? value : d.toLocaleDateString(); };
  const fmtBytes = value => { const n = Number(value); if (!Number.isFinite(n) || n <= 0) return '—'; const units=['B','KB','MB','GB']; let i=0,x=n; while(x>=1024&&i<units.length-1){x/=1024;i++;} return `${x>=10||i===0?x.toFixed(0):x.toFixed(1)} ${units[i]}`; };
  const nowIso = () => new Date().toISOString();

  function toast(message, error=false) {
    el.toast.textContent = message;
    el.toast.classList.remove('hidden','error');
    if (error) el.toast.classList.add('error');
    clearTimeout(toast._timer);
    toast._timer = setTimeout(() => el.toast.classList.add('hidden'), 4500);
  }

  async function fetchJson(url, options={}) {
    const response = await fetch(url, { headers:{Accept:'application/json', ...(options.headers||{})}, cache:'no-store', ...options });
    const body = await response.text();
    if (!response.ok) throw new Error(`${response.status}: ${body.slice(0,300)}`);
    return body ? JSON.parse(body) : null;
  }

  async function supabase(table, pairs=[]) {
    const url = new URL(`${SUPABASE_URL}/rest/v1/${table}`);
    for (const [key,value] of pairs) if (value !== '' && value != null) url.searchParams.append(key, value);
    return fetchJson(url, { headers:{apikey:SUPABASE_KEY, Authorization:`Bearer ${SUPABASE_KEY}`} });
  }

  function embeddedResult(data) {
    if (!data || typeof data !== 'object') return data || {};
    if (data._embedded) {
      for (const key of ['opportunity','opportunityData','results']) {
        const value = data._embedded[key];
        if (Array.isArray(value) && value[0]) return value[0];
        if (value && typeof value === 'object') return value;
      }
    }
    return data;
  }

  function getPath(object, path) {
    let current = object;
    for (const part of path) { if (!current || typeof current !== 'object') return ''; current = current[part]; }
    return current == null ? '' : current;
  }

  function firstValue(obj, paths) {
    for (const path of paths) {
      const value = Array.isArray(path) ? getPath(obj,path) : obj && obj[path];
      if (text(value)) return value;
    }
    return '';
  }

  function normalizeOpportunity(raw, fallback={}) {
    const row = embeddedResult(raw || {});
    const noticeId = text(firstValue(row,['noticeId','noticeID','_id','id','opportunityId'])) || text(fallback.notice_id || fallback.noticeId);
    let organization = firstValue(row,['fullParentPathName','organizationName','agencyName','officeName']);
    if (!organization && Array.isArray(row.organizationHierarchy)) organization = row.organizationHierarchy.map(x => text(x && (x.name||x.value) || x)).filter(Boolean).join(' > ');
    const typeRaw = row.type;
    const type = typeof typeRaw === 'object' && typeRaw ? [typeRaw.code,typeRaw.value].filter(Boolean).join(' ') : text(firstValue(row,['noticeType','type'])) || text(fallback.notice_type);
    return {
      noticeId,
      title: text(firstValue(row,['title','noticeTitle'])) || text(fallback.title) || 'Untitled opportunity',
      solicitation: text(firstValue(row,['solicitationNumber'])) || text(fallback.solicitation_number),
      posted: text(firstValue(row,['publishDate','postedDate'])) || text(fallback.posted_date),
      deadline: text(firstValue(row,['responseDeadline','responseDate','responseDeadLine'])) || text(fallback.response_deadline),
      agency: text(organization) || text(fallback.agency),
      type,
      naics: text(firstValue(row,['naics','naicsCode'])) || text(fallback.naics),
      psc: text(firstValue(row,['classificationCode','pscCode'])) || text(fallback.psc),
      status: text(firstValue(row,['status','active'])) || '',
      description: text(firstValue(row,['description','descriptionText'])) || text(fallback.description),
      samUrl: text(fallback.sam_url) || (noticeId ? `https://sam.gov/opp/${encodeURIComponent(noticeId)}/view` : ''),
      raw: row,
    };
  }

  function extractDocuments(resources, noticeId) {
    const docs = [];
    const lists = getPath(resources,['_embedded','opportunityAttachmentList']);
    if (Array.isArray(lists)) {
      for (const group of lists) for (const a of (Array.isArray(group && group.attachments) ? group.attachments : [])) {
        if (!a || text(a.deletedFlag) === '1') continue;
        const resourceId = text(a.resourceId);
        const name = text(a.name || a.filename);
        if (!resourceId || !name) continue;
        const size = Number(String(a.size ?? '').replace(/,/g,''));
        docs.push({resourceId,name,sizeBytes:Number.isFinite(size)?size:null,posted:text(a.postedDate||a.createdDate),source:'SAM.gov resource',download:`${WORKER}/download/${encodeURIComponent(resourceId)}`,raw:a});
      }
    }
    return docs;
  }

  function snapshotFor(opportunity, documents) {
    return {
      noticeId: opportunity.noticeId,
      capturedAt: nowIso(),
      metadata: {
        title: opportunity.title,
        solicitation: opportunity.solicitation,
        deadline: opportunity.deadline,
        agency: opportunity.agency,
        type: opportunity.type,
        posted: opportunity.posted,
      },
      documents: documents.map(d => ({resourceId:d.resourceId,name:d.name,sizeBytes:d.sizeBytes||null,posted:d.posted||''})).sort((a,b)=>a.resourceId.localeCompare(b.resourceId)),
    };
  }

  function compareSnapshots(previous, current) {
    if (!previous) return [];
    const changes=[];
    for (const key of ['title','solicitation','deadline','agency','type','posted']) {
      if (text(previous.metadata && previous.metadata[key]) !== text(current.metadata[key])) changes.push({kind:'metadata',status:'changed',label:key,from:text(previous.metadata&&previous.metadata[key]),to:text(current.metadata[key])});
    }
    const oldMap = new Map((previous.documents||[]).map(d=>[d.resourceId,d]));
    const newMap = new Map((current.documents||[]).map(d=>[d.resourceId,d]));
    for (const [id,doc] of newMap) {
      const old = oldMap.get(id);
      if (!old) changes.push({kind:'document',status:'new',resourceId:id,label:doc.name,to:doc});
      else if (old.name !== doc.name || Number(old.sizeBytes||0)!==Number(doc.sizeBytes||0)) changes.push({kind:'document',status:'changed',resourceId:id,label:doc.name,from:old,to:doc});
    }
    for (const [id,doc] of oldMap) if (!newMap.has(id)) changes.push({kind:'document',status:'removed',resourceId:id,label:doc.name,from:doc});
    return changes;
  }

  function savedNotebooks() { return loadJson(STORAGE.saved, []); }
  function snapshots() { return loadJson(STORAGE.snapshots, {}); }
  function changeHistory() { return loadJson(STORAGE.history, {}); }

  function updateSavedCount() { el.savedCount.textContent = String(savedNotebooks().length); }

  function saveCurrentNotebook(silent=false) {
    if (!state.opportunity || !state.noticeId) return;
    const rows = savedNotebooks().filter(x=>x.noticeId!==state.noticeId);
    rows.unshift({noticeId:state.noticeId,title:state.opportunity.title,solicitation:state.opportunity.solicitation,agency:state.opportunity.agency,savedAt:nowIso()});
    saveJson(STORAGE.saved,rows.slice(0,100)); updateSavedCount();
    el.saveNotebookBtn.textContent='★ Saved';
    if (!silent) toast('Notebook saved in this browser.');
  }

  function lastHistoryEntries() {
    const rows=(changeHistory()[state.noticeId]||[]).slice().sort((a,b)=>String(b.detectedAt).localeCompare(String(a.detectedAt)));
    return rows;
  }

  function persistSnapshot(snapshot, changes) {
    const snaps=snapshots(); snaps[state.noticeId]=snapshot; saveJson(STORAGE.snapshots,snaps);
    if (changes.length) {
      const all=changeHistory(); const existing=all[state.noticeId]||[];
      all[state.noticeId]=[{detectedAt:snapshot.capturedAt,changes},...existing].slice(0,80); saveJson(STORAGE.history,all);
    }
  }

  async function fetchContract(noticeId) {
    let indexedOpp=null, indexedDocs=[];
    try { const rows=await supabase('opportunities', [['select','*'],['notice_id',`eq.${noticeId}`],['limit','1']]); indexedOpp=rows&&rows[0]||null; } catch {}
    try { indexedDocs=await supabase('documents', [['select','notice_id,resource_id,document_name,size_bytes,posted_date,download_url,last_seen_at'],['notice_id',`eq.${noticeId}`],['order','document_name.asc']]); } catch {}
    let details=null,resources=null;
    try { details=await fetchJson(`${WORKER}/details/${encodeURIComponent(noticeId)}`); } catch (error) { if (!indexedOpp) throw error; }
    try { resources=await fetchJson(`${WORKER}/resources/${encodeURIComponent(noticeId)}`); } catch {}
    const opportunity=normalizeOpportunity(details,indexedOpp||{notice_id:noticeId});
    let documents=extractDocuments(resources,noticeId);
    if (!documents.length && Array.isArray(indexedDocs)) documents=indexedDocs.map(d=>({resourceId:text(d.resource_id),name:text(d.document_name),sizeBytes:d.size_bytes,posted:text(d.posted_date),source:'Indexed DB',download:text(d.download_url)||`${WORKER}/download/${encodeURIComponent(d.resource_id)}`,raw:d})).filter(d=>d.resourceId&&d.name);
    return {opportunity,documents,indexedDocs};
  }

  async function openNotebook(noticeId, options={}) {
    noticeId=text(noticeId); if(!noticeId){toast('Enter a SAM.gov notice ID.',true);return;}
    setLoading(true);
    try {
      const data=await fetchContract(noticeId);
      state.noticeId=noticeId; state.opportunity=data.opportunity; state.documents=data.documents; state.indexedDocuments=data.indexedDocs||[];
      const snaps=snapshots(); state.currentSnapshot=snaps[noticeId]||null; state.currentChanges=[];
      if (!state.currentSnapshot) { const baseline=snapshotFor(state.opportunity,state.documents); persistSnapshot(baseline,[]); state.currentSnapshot=baseline; }
      const url=new URL(location.href); url.searchParams.set('noticeId',noticeId); window.history.replaceState(null,'',url);
      el.emptyState.classList.add('hidden'); el.notebook.classList.remove('hidden');
      renderHeader(); setView(options.view||state.view||'overview'); saveCurrentNotebook(true); updateTopRefresh();
      toast(`Opened ${state.opportunity.title}`);
    } catch(error){toast(`Could not open notice: ${error.message||error}`,true);} finally{setLoading(false);}
  }

  function setLoading(on) { document.body.classList.toggle('loading',Boolean(on)); el.refreshTopBtn.disabled=on; }

  function renderHeader() {
    const o=state.opportunity;
    el.contractTitle.textContent=o.title||'Untitled opportunity'; el.noticeIdButton.textContent=o.noticeId||state.noticeId;
    el.agencyChip.textContent=o.agency?`Agency · ${o.agency}`:'Agency · —'; el.typeChip.textContent=o.type?`Type · ${o.type}`:'Type · —'; el.deadlineChip.textContent=o.deadline?`Due · ${o.deadline}`:'Due · —';
    el.samLink.href=o.samUrl; el.navSourceCount.textContent=String(state.documents.length); el.navChangeCount.textContent=String(lastHistoryEntries().reduce((n,x)=>n+(x.changes||[]).length,0));
    const saved=savedNotebooks().some(x=>x.noticeId===state.noticeId); el.saveNotebookBtn.textContent=saved?'★ Saved':'☆ Save';
  }

  function updateTopRefresh() {
    const snap=(snapshots()[state.noticeId]||state.currentSnapshot);
    if(snap&&snap.capturedAt){el.lastRefreshTop.textContent=`Last refreshed: ${fmtDateTime(snap.capturedAt)}`;el.liveDot.classList.add('on');} else {el.lastRefreshTop.textContent='Not refreshed';el.liveDot.classList.remove('on');}
  }

  function setView(view) {
    state.view=view;
    document.querySelectorAll('.nav-item[data-view]').forEach(btn=>btn.classList.toggle('active',btn.dataset.view===view));
    if(!state.opportunity && view!=='saved' && view!=='adapters' && view!=='security') return;
    if(view==='overview') renderOverview();
    else if(view==='sources') renderSources();
    else if(view==='changes') renderChanges();
    else if(view==='saved') renderSaved();
    else if(view==='adapters') renderAdapters();
    else if(view==='security') renderSecurity();
    else renderRoadmap(view);
  }

  function metrics() {
    const hist=lastHistoryEntries(), totalChanges=hist.reduce((n,x)=>n+(x.changes||[]).length,0);
    const indexed=state.indexedDocuments.length;
    return [
      ['Sources',state.documents.length,'Public attachments'],
      ['Indexed Docs',indexed,indexed?`${indexed} searchable`:'Index pending'],
      ['Changes',totalChanges,totalChanges?'Since first snapshot':'No detected deltas'],
      ['Status',state.opportunity.status||'Loaded','SAM.gov notebook'],
      ['Posted',state.opportunity.posted?fmtDate(state.opportunity.posted):'—','Opportunity date'],
      ['Refresh','Manual','No background polling'],
    ];
  }

  function renderOverview() {
    const recent=lastHistoryEntries().flatMap(x=>(x.changes||[]).map(c=>({...c,detectedAt:x.detectedAt}))).slice(0,6);
    const desc=state.opportunity.description || 'Description was not available from the public notice response. Open SAM.gov or the Sources view for the original solicitation material.';
    el.viewMount.innerHTML=`
      <div class="metric-grid">${metrics().map(([l,v,d])=>`<div class="metric"><div class="label">${esc(l)}</div><div class="value">${esc(v)}</div><div class="delta">${esc(d)}</div></div>`).join('')}</div>
      <div class="dashboard-grid">
        <section class="card"><div class="card-head"><h2>Mission / Notice Summary</h2><span class="status-pill green">Source grounded</span></div><div class="card-body"><div class="summary-text collapsed">${esc(desc)}</div><div class="kv-list" style="margin-top:14px"><dt>Solicitation</dt><dd>${esc(state.opportunity.solicitation||'—')}</dd><dt>NAICS</dt><dd>${esc(state.opportunity.naics||'—')}</dd><dt>PSC</dt><dd>${esc(state.opportunity.psc||'—')}</dd></div></div></section>
        <section class="card"><div class="card-head"><h2>Recent Changes</h2><span class="card-link" data-jump="changes">View all</span></div><div class="card-body change-list">${recent.length?recent.map(changeHtml).join(''):'<div class="empty-mini">No material changes detected after the saved baseline.</div>'}</div></section>
        <section class="card"><div class="card-head"><h2>Next Best Actions</h2></div><div class="card-body action-list">${actionRows()}</div></section>
      </div>
      <div style="height:12px"></div>
      <section class="card"><div class="card-head"><h2>Contract Brain Build Status</h2><span class="muted">Foundation PR</span></div><div class="card-body"><div class="module-strip">
        <div class="module-box live"><strong>Notebook</strong><span>Persistent local workspace</span></div><div class="module-box live"><strong>Sources</strong><span>Resource-ID attachment inventory</span></div><div class="module-box live"><strong>Manual Refresh</strong><span>Snapshot + change diff</span></div><div class="module-box live"><strong>Change History</strong><span>New / changed / removed evidence</span></div>
        <div class="module-box"><strong>CONOPS</strong><span>Mission extraction next</span></div><div class="module-box"><strong>Requirements</strong><span>Traceability next</span></div><div class="module-box"><strong>Graph</strong><span>Evidence relationships next</span></div><div class="module-box"><strong>AI Ask</strong><span>Cited retrieval after parsing</span></div>
      </div></div></section>`;
    wireJumpLinks();
  }

  function changeHtml(c) {
    const icon=c.status==='new'?'+':c.status==='removed'?'−':'↻';
    const extra=c.kind==='metadata'?`${text(c.from)||'—'} → ${text(c.to)||'—'}`:(c.resourceId||'');
    return `<div class="change-row"><div class="change-icon">${icon}</div><div><strong>${esc(c.label||'Change')}</strong><small>${esc(extra)}</small></div><span class="change-type ${esc(c.status)}">${esc(c.status)}</span></div>`;
  }

  function actionRows() {
    const recent=lastHistoryEntries().flatMap(x=>x.changes||[]), newDocs=recent.filter(c=>c.kind==='document'&&c.status==='new').length;
    const rows=[];
    if(newDocs) rows.push([`Review ${newDocs} new source${newDocs===1?'':'s'}`,'New public attachments detected','sources']);
    rows.push(['Review source inventory',`${state.documents.length} public attachments currently known`,'sources']);
    rows.push(['Refresh before capture review','Only spends requests when you choose to check','changes']);
    rows.push(['Build mission decomposition','Next Contract Brain milestone','mission']);
    return rows.map(([title,sub,view])=>`<div class="action-row clickable" data-jump="${view}"><div class="change-icon">›</div><div><strong>${esc(title)}</strong><small>${esc(sub)}</small></div><span>›</span></div>`).join('');
  }

  function renderSources() {
    el.viewMount.innerHTML=`<div class="view-title-row"><div><h2>Sources</h2><p>Public SAM.gov attachments keyed by durable resource ID.</p></div><div><span class="status-pill green">${state.documents.length} known</span></div></div>
      <div class="source-toolbar"><input id="sourceFilter" class="field" placeholder="Filter documents..."><select id="sourceType" class="select"><option value="">All types</option><option>pdf</option><option>zip</option><option>xlsx</option><option>docx</option></select></div>
      <div class="table-wrap"><table class="data-table"><thead><tr><th>Document</th><th>Resource ID</th><th>Size</th><th>Source</th><th>Action</th></tr></thead><tbody id="sourceBody"></tbody></table></div>`;
    const filter=document.getElementById('sourceFilter'),type=document.getElementById('sourceType');
    const render=()=>{const q=text(filter.value).toLowerCase(),ext=text(type.value);const rows=state.documents.filter(d=>(!q||`${d.name} ${d.resourceId}`.toLowerCase().includes(q))&&(!ext||d.name.toLowerCase().endsWith(`.${ext}`)));document.getElementById('sourceBody').innerHTML=rows.map(d=>`<tr><td><div class="doc-name">${esc(d.name)}</div><div class="doc-meta">${esc(d.posted||'')}</div></td><td class="mono">${esc(d.resourceId)}</td><td class="size">${esc(fmtBytes(d.sizeBytes))}</td><td>${esc(d.source||'SAM.gov')}</td><td><a class="download-link" href="${esc(d.download)}" target="_blank" rel="noopener">Download ↗</a></td></tr>`).join('')||'<tr><td colspan="5" class="muted">No matching sources.</td></tr>';};
    filter.addEventListener('input',render);type.addEventListener('change',render);render();
  }

  function renderChanges() {
    const groups=lastHistoryEntries();
    el.viewMount.innerHTML=`<div class="refresh-banner"><div><h3>Manual Refresh Intelligence</h3><p>Contract Brain checks SAM.gov only when you ask. It compares notice metadata and attachment resource IDs against the previous snapshot.</p></div><button id="refreshViewBtn" class="btn btn-accent">↻ Refresh Now</button></div>
      <div class="view-title-row"><div><h2>Change History</h2><p>${groups.length} refresh event${groups.length===1?'':'s'} with material deltas.</p></div></div>
      ${groups.length?groups.map(g=>`<section class="card" style="margin-bottom:10px"><div class="card-head"><h3>${esc(fmtDateTime(g.detectedAt))}</h3><span class="status-pill amber">${(g.changes||[]).length} change${(g.changes||[]).length===1?'':'s'}</span></div><div class="card-body change-list">${(g.changes||[]).map(changeHtml).join('')}</div></section>`).join(''):'<section class="card"><div class="card-body empty-mini">No changes yet. Your first open established the baseline snapshot.</div></section>'}`;
    document.getElementById('refreshViewBtn').addEventListener('click',refreshCurrent);
  }

  function renderSaved() {
    const rows=savedNotebooks();
    el.notebook.classList.remove('hidden'); el.emptyState.classList.add('hidden');
    el.viewMount.innerHTML=`<div class="view-title-row"><div><h2>Saved Notebooks</h2><p>Saved locally in this browser. Server-side team workspaces are a later milestone.</p></div></div><div class="saved-list">${rows.length?rows.map(r=>`<section class="card saved-card" data-notice="${esc(r.noticeId)}"><h3>${esc(r.title||r.noticeId)}</h3><p>${esc(r.solicitation||r.noticeId)} · ${esc(r.agency||'')}</p><p style="margin-top:6px">Saved ${esc(fmtDateTime(r.savedAt))}</p></section>`).join(''):'<section class="card saved-card"><h3>No saved notebooks</h3><p>Open a contract from search to create one.</p></section>'}</div>`;
    document.querySelectorAll('[data-notice]').forEach(x=>x.addEventListener('click',()=>openNotebook(x.dataset.notice,{view:'overview'})));
  }

  const ROADMAP = {
    mission:['Mission / CONOPS','Extract outcomes, functions, operating modes, constraints, systems, and mission relationships from source documents.',['Source parsing','Mission-function ontology','Evidence-linked CONOPS']],
    requirements:['Requirements','Turn shall-statements and structured requirements into traceable objects linked to source sections.',['Requirement extraction','Status and confidence','Source citation path']],
    components:['Components','Resolve systems, subsystems, hardware, software, and parts referenced across the opportunity.',['Entity resolver','Component hierarchy','Cross-contract reuse']],
    interfaces:['Interfaces','Model data, power, control, mechanical, and logistics interfaces as first-class evidence objects.',['Interface families','ICD evidence','Cross-program matching']],
    nsn:['NSN / Parts','Trace public NSNs, part numbers, nomenclature, and possible substitutes without claiming unsupported matches.',['Public catalog adapters','Candidate scoring','Human verification']],
    manufacturers:['Manufacturers','Rank possible suppliers from public evidence, award lineage, capability alignment, and standards.',['CAGE / vendor evidence','Capability model','Probability rationale']],
    analogs:['Analogs','Find historical contracts that share mission functions, interfaces, specifications, components, and agency lineage.',['Multidimensional scoring','Explainable edges','Evidence matrix']],
    gaps:['Gaps & Risks','Detect unsupported claims, missing interfaces, conflicts, unknown suppliers, and decision-critical uncertainty.',['Gap taxonomy','Conflict engine','Risk prioritization']],
    clarifications:['Clarifications','Convert high-impact unknowns into source-grounded questions that can change the bid decision.',['Question generator','Impact rationale','Review queue']],
    reports:['Reports','Export a capture intelligence package with mission, requirements, sources, analogs, gaps, changes, and citations.',['PDF / XLSX','Decision log','Source appendix']],
  };

  function renderRoadmap(view) {
    const data=ROADMAP[view]||['Module','Planned Contract Brain module.',['Evidence first','Human review','Public data']];
    el.viewMount.innerHTML=`<div class="view-title-row"><div><h2>${esc(data[0])}</h2><p>${esc(data[1])}</p></div><span class="status-pill amber">Planned</span></div><div class="roadmap-grid">${data[2].map((x,i)=>`<section class="card roadmap-card"><h3>${i+1}. ${esc(x)}</h3><p>This foundation PR creates the notebook, sources, refresh snapshots, and persistent navigation this module will build on.</p></section>`).join('')}</div>`;
  }

  function renderAdapters() {
    el.viewMount.innerHTML=`<div class="view-title-row"><div><h2>Source Adapters</h2><p>Current and planned public evidence sources.</p></div></div><div class="roadmap-grid"><section class="card roadmap-card"><h3>SAM.gov</h3><p><span class="status-pill green">Connected</span> Search, notice details, resources, resource-ID download.</p></section><section class="card roadmap-card"><h3>Supabase Index</h3><p><span class="status-pill green">Connected</span> Indexed opportunities and public attachment metadata.</p></section><section class="card roadmap-card"><h3>USAspending / DLA / Specs</h3><p><span class="status-pill amber">Planned</span> Normalize public award, NSN, catalog, and specification evidence.</p></section></div>`;
  }

  function renderSecurity() {
    el.viewMount.innerHTML=`<div class="view-title-row"><div><h2>Public Data Boundary</h2><p>The current Contract Brain demonstrator is intentionally scoped to public sources.</p></div></div><section class="card"><div class="card-body"><div class="kv-list"><dt>PUBLIC</dt><dd><span class="status-pill green">Allowed</span> SAM.gov notices, public attachments, public index records.</dd><dt>USER PRIVATE</dt><dd><span class="status-pill amber">Not implemented</span></dd><dt>PROPRIETARY</dt><dd><span class="status-pill red">Not allowed in public demo</span></dd><dt>CUI</dt><dd><span class="status-pill red">Not allowed</span></dd><dt>CLASSIFIED</dt><dd><span class="status-pill red">Not allowed</span></dd></div></div></section>`;
  }

  async function refreshCurrent() {
    if(!state.noticeId||state.refreshing) return;
    state.refreshing=true; setLoading(true);
    const old=snapshots()[state.noticeId]||state.currentSnapshot;
    try {
      const data=await fetchContract(state.noticeId); const current=snapshotFor(data.opportunity,data.documents); const changes=compareSnapshots(old,current);
      state.opportunity=data.opportunity; state.documents=data.documents; state.indexedDocuments=data.indexedDocs||[]; state.currentSnapshot=current; state.currentChanges=changes; persistSnapshot(current,changes); renderHeader(); updateTopRefresh(); setView(state.view);
      toast(changes.length?`Refresh complete: ${changes.length} material change${changes.length===1?'':'s'} detected.`:'Refresh complete: no material changes detected.');
    } catch(error){toast(`Refresh failed: ${error.message||error}`,true);} finally{state.refreshing=false;setLoading(false);}
  }

  function wireJumpLinks() { document.querySelectorAll('[data-jump]').forEach(x=>x.addEventListener('click',()=>setView(x.dataset.jump))); }

  async function searchIndexed(term) {
    term=text(term); if(term.length<2){el.searchResults.classList.add('hidden');return;}
    try {
      const safe=term.replace(/[,*()]/g,' ').trim();
      const rows=await supabase('opportunities', [['select','notice_id,solicitation_number,title,agency,posted_date,notice_type'],['or',`(title.ilike.*${safe}*,solicitation_number.ilike.*${safe}*,notice_id.ilike.*${safe}*,agency.ilike.*${safe}*)`],['order','posted_date.desc.nullslast'],['limit','12']]);
      el.searchResults.innerHTML=(rows||[]).map(r=>`<button class="search-result" data-notice="${esc(r.notice_id)}"><strong>${esc(r.title||r.solicitation_number||r.notice_id)}</strong><span>${esc(r.solicitation_number||r.notice_id)} · ${esc(r.agency||'')}</span></button>`).join('')||'<div class="empty-mini">No indexed matches.</div>';
      el.searchResults.classList.remove('hidden'); document.querySelectorAll('.search-result[data-notice]').forEach(btn=>btn.addEventListener('click',()=>{el.searchResults.classList.add('hidden');el.globalSearch.value='';openNotebook(btn.dataset.notice,{view:'overview'});}));
    } catch(error){el.searchResults.innerHTML=`<div class="empty-mini error">Search failed: ${esc(error.message||error)}</div>`;el.searchResults.classList.remove('hidden');}
  }

  document.querySelectorAll('.nav-item[data-view]').forEach(btn=>btn.addEventListener('click',()=>{
    const view=btn.dataset.view;
    if(!state.opportunity && !['saved','adapters','security'].includes(view)){toast('Open a contract notebook first.');return;}
    setView(view);
  }));
  el.refreshSideBtn.addEventListener('click',refreshCurrent); el.refreshTopBtn.addEventListener('click',refreshCurrent); el.saveNotebookBtn.addEventListener('click',()=>saveCurrentNotebook(false));
  el.noticeIdButton.addEventListener('click',async()=>{try{await navigator.clipboard.writeText(state.noticeId);toast('Notice ID copied.');}catch{toast(state.noticeId);}});
  el.openNoticeBtn.addEventListener('click',()=>openNotebook(el.noticeInput.value,{view:'overview'})); el.noticeInput.addEventListener('keydown',e=>{if(e.key==='Enter')openNotebook(el.noticeInput.value,{view:'overview'});});
  el.globalSearch.addEventListener('input',()=>{clearTimeout(state.searchTimer);state.searchTimer=setTimeout(()=>searchIndexed(el.globalSearch.value),250);});
  el.globalSearch.addEventListener('keydown',e=>{if(e.key==='Escape')el.searchResults.classList.add('hidden');if(e.key==='Enter'&&text(el.globalSearch.value).length>8)openNotebook(el.globalSearch.value,{view:'overview'});});
  document.addEventListener('click',e=>{if(!e.target.closest('.global-search-wrap'))el.searchResults.classList.add('hidden');});

  updateSavedCount();
  const params=new URLSearchParams(location.search), initial=params.get('noticeId');
  if(initial) openNotebook(initial,{view:params.get('view')||'overview'});
})();