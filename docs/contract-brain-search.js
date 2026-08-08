(() => {
  'use strict';

  const WORKER = 'https://samgovsearch.spotterdeer.workers.dev';
  const WIDTH_STORE = 'samgovsearch.contractBrain.searchColumnWidths.v1';
  const $ = id => document.getElementById(id);
  const ids = [
    'contractSearchBtn','searchWorkspace','emptyState','notebook','cbTerms','cbPostedFrom','cbPostedTo','cbAllDates','cbStatus','cbType','cbSearchMode','cbNaicsMode','cbMaxResults','cbPageSize','cbDelayMs','cbEnrichResources','cbRequireAttachments','cbMinCount','cbMinMb','cbShowFilter','cbHideFilter','cbAttachmentFilter','cbSearchBtn','cbStopBtn','cbExportBtn','cbClearBtn','cbSearchStatus','cbResultCount','cbRequestCount','cbResultsTable','cbResultsHead','cbResultsBody','cbDetailPanel','cbOpenIdentifier','cbOpenIdentifierBtn'
  ];
  const el = Object.fromEntries(ids.map(id => [id, $(id)]));
  if (!el.searchWorkspace) return;

  const cols = [
    ['keyword','Keyword',110],
    ['matchedBy','Matched By',105],
    ['posted','Posted',105],
    ['title','Opportunity',340],
    ['solicitation','Solicitation',165],
    ['type','Type',170],
    ['agency','Agency',290],
    ['naics','NAICS',90],
    ['psc','PSC',80],
    ['attachmentCount','Att',68],
    ['attachmentTotalMb','MB',82],
    ['source','Source',100],
    ['action','Action',130],
  ];

  function loadWidths() { try { return JSON.parse(localStorage.getItem(WIDTH_STORE) || '{}') || {}; } catch { return {}; } }
  const state = {
    stop:false, requests:0, rows:[], visible:[], seen:new Map(), selected:'',
    sortColumn:'posted', sortReverse:true, widths:loadWidths(), detailSerial:0,
  };

  const text = v => v == null ? '' : String(v).trim();
  const pad = n => String(n).padStart(2,'0');
  const esc = v => text(v).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const fmt = d => `${pad(d.getMonth()+1)}/${pad(d.getDate())}/${d.getFullYear()}`;
  const add = (d,n) => { const x=new Date(d); x.setDate(x.getDate()+n); return x; };
  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
  const isNaics = v => /^\d{2,6}$/.test(text(v));
  const fmtBytes = value => { const n=Number(value); if(!Number.isFinite(n)||n<0)return '—'; const u=['B','KB','MB','GB']; let i=0,x=n; while(x>=1024&&i<u.length-1){x/=1024;i++;} return `${x>=10||i===0?x.toFixed(0):x.toFixed(1)} ${u[i]}`; };

  function status(msg, kind='') { el.cbSearchStatus.textContent=msg; el.cbSearchStatus.className=`cb-search-status ${kind}`.trim(); }
  function counts() { el.cbResultCount.textContent=`${state.visible.length} shown / ${state.rows.length} total`; el.cbRequestCount.textContent=`${state.requests} request${state.requests===1?'':'s'}`; el.cbExportBtn.disabled=!state.visible.length; }
  function parseDate(v,name) { const m=text(v).match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/); if(!m)throw new Error(`${name} must be MM/DD/YYYY.`); const d=new Date(+m[3],+m[1]-1,+m[2]); if(d.getMonth()!==+m[1]-1||d.getDate()!==+m[2])throw new Error(`${name} is invalid.`); return d; }
  function windows() { if(!el.cbAllDates.checked){const a=parseDate(el.cbPostedFrom.value,'Posted From'),b=parseDate(el.cbPostedTo.value,'Posted To');if(b<a)throw new Error('Posted To must be later than Posted From.');if((b-a)/86400000>364)throw new Error('Use All dates for ranges over 364 days.');return[[fmt(a),fmt(b)]];}const out=[],end=new Date();for(let s=new Date(2018,0,1);s<=end;){const e=add(s,364)>end?end:add(s,364);out.push([fmt(s),fmt(e)]);s=add(e,1);}return out; }
  function terms() { const seen=new Set(); return el.cbTerms.value.replace(/,/g,'\n').split(/\r?\n/).map(text).filter(Boolean).filter(v=>{const k=v.toLowerCase().replace(/\s+/g,' ');if(seen.has(k))return false;seen.add(k);return true;}); }

  async function json(path,params={}) { state.requests++; counts(); const u=new URL(WORKER+path); Object.entries(params).forEach(([k,v])=>{if(v!==''&&v!=null)u.searchParams.set(k,v);}); const r=await fetch(u,{headers:{Accept:'application/json'},cache:'no-store'}); const body=await r.text(); if(!r.ok)throw new Error(`${r.status}: ${body.slice(0,240)}`); return body?JSON.parse(body):{}; }
  function results(d) { if(d?._embedded&&Array.isArray(d._embedded.results))return d._embedded.results.filter(Boolean);for(const k of['results','opportunitiesData','items'])if(Array.isArray(d?.[k]))return d[k].filter(Boolean);return[]; }
  function totalFrom(d,fallback) { for(const v of[d?.page?.totalElements,d?.totalRecords,d?.totalElements,d?.total,d?.count]){const n=parseInt(String(v??'').replace(/,/g,''),10);if(Number.isFinite(n))return n;}return fallback; }
  function id(o) { return text(o.noticeId||o.noticeID||o._id||o.id||o.opportunityId); }
  function org(o) { const h=o.organizationHierarchy||o.organizationHierarchyName;if(Array.isArray(h)){const p=h.map(x=>typeof x==='object'?text(x.name||x.value):text(x)).filter(Boolean);if(p.length)return p.join(' > ');}return text(o.fullParentPathName||o.organizationName||o.officeName||o.agencyName); }
  function type(o) { const v=text(o?.type?.value),c=text(o?.type?.code);return v&&c?`${c} ${v}`:v||c||text(o.type); }
  function strip(v) { const d=document.createElement('div');d.innerHTML=text(v);return text(d.textContent||d.innerText||''); }
  function desc(o) { if(Array.isArray(o.descriptions)&&o.descriptions[0]){const d=o.descriptions[0];return strip(typeof d==='object'?(d.content||d.description||''):d);}return strip(o.description||o.descriptionText||''); }

  function normalize(o,term,matchedBy='Search') {
    const notice=id(o);
    return {
      noticeId:notice,title:text(o.title)||'Untitled opportunity',solicitation:text(o.solicitationNumber),posted:text(o.publishDate||o.postedDate).replace(/T.*$/,''),deadline:text(o.responseDate||o.responseDeadLine||o.responseDeadline),agency:org(o),type:type(o),naics:text(o.naicsCode),psc:text(o.classificationCode||o.pscCode),description:desc(o),keyword:term,matchedBy,source:'Live',samUrl:notice?`https://sam.gov/opp/${encodeURIComponent(notice)}/view`:'',attachments:[],attachmentCount:null,attachmentTotalBytes:null,attachmentTotalMb:null,enriched:false,detailsLoaded:false,
    };
  }

  function parseResources(data) {
    const attachments=[]; let totalBytes=0, unknown=0;
    const lists=data?._embedded?.opportunityAttachmentList;
    if(Array.isArray(lists)) for(const group of lists) for(const a of(Array.isArray(group?.attachments)?group.attachments:[])){
      if(!a||text(a.deletedFlag)==='1')continue;
      const resourceId=text(a.resourceId),name=text(a.name||a.filename||'unknown');
      if(!resourceId)continue;
      const size=Number(String(a.size??'').replace(/,/g,''));
      if(Number.isFinite(size))totalBytes+=size;else unknown++;
      attachments.push({resourceId,name,sizeBytes:Number.isFinite(size)?size:null,download:`${WORKER}/download/${encodeURIComponent(resourceId)}`});
    }
    return {attachments,totalBytes,unknown};
  }

  function variants(term) {
    if(el.cbNaicsMode.checked&&isNaics(term))return[{matchedBy:'NAICS',naics:term}];
    const mode=text(el.cbSearchMode.value).toLowerCase();
    if(mode==='notice id')return[{matchedBy:'Notice ID',noticeId:term}];
    if(mode==='solicitation number')return[{matchedBy:'Solicitation',q:term}];
    if(mode==='title + solicitation number')return[{matchedBy:'Title',q:term},{matchedBy:'Solicitation',q:term}];
    if(mode==='title')return[{matchedBy:'Title',q:term}];
    const v=[{matchedBy:'Auto',q:term}];
    const compact=term.replace(/[^A-Fa-f0-9]/g,'');
    if(compact.length>=20&&/^[A-Fa-f0-9]+$/.test(compact))v.push({matchedBy:'Notice ID',noticeId:term});
    return v;
  }

  function mergeRow(old,row) {
    const merged={...old};
    for(const [k,v] of Object.entries(row)) if(v!==''&&v!=null) merged[k]=v;
    if(old.keyword&&row.keyword&&old.keyword!==row.keyword&&!old.keyword.split(' | ').includes(row.keyword))merged.keyword=`${old.keyword} | ${row.keyword}`;
    if(old.matchedBy&&row.matchedBy&&old.matchedBy!==row.matchedBy&&!old.matchedBy.split(' | ').includes(row.matchedBy))merged.matchedBy=`${old.matchedBy} | ${row.matchedBy}`;
    return merged;
  }

  function upsertRow(row) {
    if(!row.noticeId)return row;
    const old=state.seen.get(row.noticeId);
    const merged=old?mergeRow(old,row):row;
    state.seen.set(row.noticeId,merged);
    const i=state.rows.findIndex(x=>x.noticeId===row.noticeId);
    if(i>=0)state.rows[i]=merged;else state.rows.push(merged);
    applyFilters();
    return merged;
  }

  async function enrichResources(row) {
    if(!el.cbEnrichResources.checked||!row.noticeId){row.attachmentCount=0;row.attachmentTotalBytes=0;row.attachmentTotalMb=0;row.enriched=true;upsertRow(row);return row;}
    try {
      const parsed=parseResources(await json(`/resources/${encodeURIComponent(row.noticeId)}`));
      row.attachments=parsed.attachments;row.attachmentCount=parsed.attachments.length;row.attachmentTotalBytes=parsed.totalBytes;row.attachmentTotalMb=parsed.totalBytes/1048576;row.attachmentSizeUnknown=parsed.unknown;row.enriched=true;upsertRow(row);
    } catch(error) {
      row.attachmentCount=0;row.attachmentTotalBytes=0;row.attachmentTotalMb=0;row.enriched=true;row.enrichError=error.message||String(error);upsertRow(row);
    }
    return row;
  }

  function passesAttachmentRules(row) {
    if(!row.enriched&&el.cbEnrichResources.checked)return !el.cbRequireAttachments.checked && !(+el.cbMinCount.value||0) && !(+el.cbMinMb.value||0) && !text(el.cbAttachmentFilter.value);
    const count=Number(row.attachmentCount||0),mb=Number(row.attachmentTotalMb||0),minCount=+el.cbMinCount.value||0,minMb=+el.cbMinMb.value||0;
    if(el.cbRequireAttachments.checked&&count<=0)return false;
    if(minCount&&count<minCount)return false;
    if(minMb&&mb<minMb)return false;
    const af=text(el.cbAttachmentFilter.value);
    if(af){const res=af.split(',').map(x=>wild(text(x))).filter(Boolean);const names=(row.attachments||[]).map(a=>a.name||'');if(!res.every(re=>names.some(n=>re.test(n))))return false;}
    return true;
  }

  function wild(s) { if(!s)return null; return new RegExp(s.replace(/[.+^${}()|[\]\\]/g,'\\$&').replace(/\*/g,'.*').replace(/\?/g,'.'),'i'); }
  function searchable(row) { return [row.keyword,row.matchedBy,row.title,row.solicitation,row.agency,row.type,row.naics,row.psc,row.noticeId,...(row.attachments||[]).map(a=>a.name)].join(' '); }
  function localPass(row) {
    const show=text(el.cbShowFilter.value);if(show){const terms=show.split(/\s+/).filter(Boolean).map(wild);if(!terms.every(re=>re.test(searchable(row))))return false;}
    const hide=text(el.cbHideFilter.value);if(hide){const terms=hide.split(',').map(text).filter(Boolean).map(wild);if(terms.some(re=>re.test(searchable(row))))return false;}
    return passesAttachmentRules(row);
  }

  function sortVisible() {
    const k=state.sortColumn,dir=state.sortReverse?-1:1;
    state.visible.sort((a,b)=>{
      let av=a[k],bv=b[k];
      if(k==='attachmentCount'||k==='attachmentTotalMb'){av=Number(av??-1);bv=Number(bv??-1);return(av-bv)*dir;}
      return String(av||'').localeCompare(String(bv||''),undefined,{numeric:true,sensitivity:'base'})*dir;
    });
  }
  function applyFilters() { state.visible=state.rows.filter(localPass);sortVisible();render(); }

  function colWidth(k) { const w=+state.widths[k]; const def=cols.find(c=>c[0]===k)?.[2]||120; return Number.isFinite(w)&&w>=55?w:def; }
  function saveWidths() { localStorage.setItem(WIDTH_STORE,JSON.stringify(state.widths)); }
  function applyColumnWidth(k,w) { const idx=cols.findIndex(c=>c[0]===k)+1;if(idx<=0)return;document.querySelectorAll(`#cbResultsTable tr > *:nth-child(${idx})`).forEach(cell=>{cell.style.width=`${w}px`;cell.style.minWidth=`${w}px`;cell.style.maxWidth=`${w}px`;}); }
  function startResize(e,k) { e.preventDefault();e.stopPropagation();const startX=e.clientX,startW=colWidth(k),handle=e.currentTarget;handle.classList.add('active');document.body.style.cursor='col-resize';document.body.style.userSelect='none';const move=ev=>{const w=Math.max(55,startW+(ev.clientX-startX));state.widths[k]=w;applyColumnWidth(k,w);};const up=()=>{handle.classList.remove('active');document.body.style.cursor='';document.body.style.userSelect='';saveWidths();document.removeEventListener('mousemove',move);document.removeEventListener('mouseup',up);};document.addEventListener('mousemove',move);document.addEventListener('mouseup',up); }

  function renderHead() {
    el.cbResultsHead.innerHTML=cols.map(([k,label])=>{const w=colWidth(k),arrow=state.sortColumn===k?(state.sortReverse?'▼':'▲'):'';return `<th data-sort="${esc(k)}" style="width:${w}px;min-width:${w}px;max-width:${w}px"><div class="cb-sort-label"><span>${esc(label)}</span><span class="cb-sort-arrow">${arrow}</span></div><span class="cb-resize-handle" data-resize="${esc(k)}"></span></th>`;}).join('');
    el.cbResultsHead.querySelectorAll('th[data-sort]').forEach(th=>th.addEventListener('click',()=>{const k=th.dataset.sort;if(state.sortColumn===k)state.sortReverse=!state.sortReverse;else{state.sortColumn=k;state.sortReverse=false;}applyFilters();}));
    el.cbResultsHead.querySelectorAll('[data-resize]').forEach(h=>h.addEventListener('mousedown',e=>startResize(e,h.dataset.resize)));
  }

  function cell(k,row) {
    if(k==='keyword')return esc(row.keyword||'—');
    if(k==='matchedBy')return esc(row.matchedBy||'—');
    if(k==='posted')return esc(row.posted||'—');
    if(k==='title')return `<button class="cb-title-link" data-open="${esc(row.noticeId)}" title="${esc(row.title)}">${esc(row.title)}</button><div class="cb-row-sub">${esc(row.noticeId)}</div>`;
    if(k==='solicitation')return esc(row.solicitation||'—');
    if(k==='type')return esc(row.type||'—');
    if(k==='agency')return `<span title="${esc(row.agency||'')}">${esc(row.agency||'—')}</span>`;
    if(k==='naics')return esc(row.naics||'—');
    if(k==='psc')return esc(row.psc||'—');
    if(k==='attachmentCount')return row.enriched?`<span class="cb-num">${Number(row.attachmentCount||0).toLocaleString()}</span>`:'<span class="cb-att-pending">…</span>';
    if(k==='attachmentTotalMb')return row.enriched?`<span class="cb-num">${Number(row.attachmentTotalMb||0).toFixed(3)}</span>`:'<span class="cb-att-pending">…</span>';
    if(k==='source')return '<span class="status-pill green">Live</span>';
    if(k==='action')return `<button class="btn btn-accent cb-open-btn" data-open="${esc(row.noticeId)}">Open Notebook →</button>`;
    return '';
  }

  function render() {
    renderHead();
    el.cbResultsBody.innerHTML=state.visible.map(row=>`<tr data-id="${esc(row.noticeId)}" class="${state.selected===row.noticeId?'selected':''}">${cols.map(([k])=>`<td style="width:${colWidth(k)}px;min-width:${colWidth(k)}px;max-width:${colWidth(k)}px">${cell(k,row)}</td>`).join('')}</tr>`).join('')||`<tr><td colspan="${cols.length}" class="empty-mini">${state.rows.length?'No results match the current local filters.':'Run a search to discover contracts.'}</td></tr>`;
    el.cbResultsBody.querySelectorAll('[data-open]').forEach(b=>b.addEventListener('click',e=>{e.stopPropagation();open(b.dataset.open);}));
    el.cbResultsBody.querySelectorAll('tr[data-id]').forEach(tr=>tr.addEventListener('click',()=>select(tr.dataset.id)));
    counts();
  }

  async function select(notice) {
    state.selected=notice;render();let row=state.seen.get(notice);if(!row)return;
    const serial=++state.detailSerial;
    renderDetail(row,true);
    if(!row.detailsLoaded){
      try { const d=await json(`/details/${encodeURIComponent(notice)}`); if(serial!==state.detailSerial)return; const raw=d?.data2&&typeof d.data2==='object'?d.data2:d; row=mergeRow(row,{description:desc(raw)||row.description,deadline:text(raw.responseDeadline||raw.responseDate||raw.responseDeadLine)||row.deadline,detailsLoaded:true});state.seen.set(notice,row);const idx=state.rows.findIndex(x=>x.noticeId===notice);if(idx>=0)state.rows[idx]=row;renderDetail(row,false); }
      catch { if(serial===state.detailSerial){row.detailsLoaded=true;renderDetail(row,false);} }
    }
  }

  function renderDetail(row,loadingDetails=false) {
    const attachments=(row.attachments||[]);
    el.cbDetailPanel.innerHTML=`<div class="card-head"><div><h3>${esc(row.title)}</h3><span class="cb-row-sub">${esc(row.solicitation||row.noticeId)} · ${esc(row.agency||'')}</span></div><button id="cbDetailOpen" class="btn btn-accent">Open Notebook →</button></div><div class="card-body"><div class="cb-detail-grid"><div><span>Posted</span><strong>${esc(row.posted||'—')}</strong></div><div><span>Due</span><strong>${esc(row.deadline||'—')}</strong></div><div><span>Attachments</span><strong>${row.enriched?esc(row.attachmentCount||0):'Loading…'}</strong></div><div><span>Total Size</span><strong>${row.enriched?esc(fmtBytes(row.attachmentTotalBytes||0)):'Loading…'}</strong></div><div><span>NAICS / PSC</span><strong>${esc([row.naics,row.psc].filter(Boolean).join(' / ')||'—')}</strong></div><div><span>Matched By</span><strong>${esc(row.matchedBy||'—')}</strong></div></div><p class="cb-description">${esc(row.description||(loadingDetails?'Loading notice description…':'No description loaded.'))}</p><div class="cb-attachment-list"><h4>Attachments</h4>${attachments.length?attachments.map(a=>`<div class="cb-attachment-row"><a href="${esc(a.download)}" target="_blank" rel="noopener" title="${esc(a.name)}">${esc(a.name)}</a><small>${esc(fmtBytes(a.sizeBytes))}</small></div>`).join(''):'<div class="muted" style="font-size:10px">No public attachments loaded for this result.</div>'}</div><div class="cb-detail-actions"><a href="${esc(row.samUrl)}" target="_blank" rel="noopener">Open SAM.gov ↗</a><span>${row.enrichError?esc(`Attachment lookup: ${row.enrichError}`):'Notebook follows this notice ID'}</span></div></div>`;
    $('cbDetailOpen').onclick=()=>open(row.noticeId);
  }

  async function searchNotice(term,noticeId,matchedBy) {
    const d=await json(`/details/${encodeURIComponent(noticeId)}`);const raw=d?.data2&&typeof d.data2==='object'?d.data2:d;return normalize(raw,term,matchedBy);
  }

  async function searchVariant(term,variant,from,to,max) {
    if(variant.noticeId){const row=await searchNotice(term,variant.noticeId,variant.matchedBy);const stored=upsertRow(row);if(!stored.enriched)await enrichResources(stored);return;}
    const pageSize=Math.max(1,Math.min(100,+el.cbPageSize.value||100));
    const p={index:'opp',page:0,mode:'search',sort:'-modifiedDate',size:Math.min(pageSize,max),postedFrom:from,postedTo:to};
    if(el.cbStatus.value==='active')p.is_active='true';else if(el.cbStatus.value)p.status=el.cbStatus.value;
    if(el.cbType.value)p.opp_type=el.cbType.value;
    if(variant.naics){p.naics=variant.naics;p.naicsCode=variant.naics;}else p.q=variant.q;
    let loaded=0;
    for(let page=0;!state.stop&&loaded<max;page++){
      p.page=page;p.size=Math.min(pageSize,max-loaded);
      const d=await json('/search',p),raw=results(d);if(!raw.length)break;
      for(const o of raw){
        if(state.stop)break;
        loaded++;
        let row=normalize(o,term,variant.matchedBy),stored=upsertRow(row);
        if(!stored.enriched)await enrichResources(stored);
        if(+el.cbDelayMs.value>0)await sleep(+el.cbDelayMs.value);
        if(loaded>=max)break;
      }
      const total=totalFrom(d,raw.length);if((page*pageSize)+raw.length>=total)break;
    }
  }

  async function run() {
    const ts=terms();if(!ts.length){status('Enter at least one search term.','error');return;}
    let ws;try{ws=windows();}catch(e){status(e.message,'error');return;}
    state.stop=false;state.requests=0;state.rows=[];state.visible=[];state.seen=new Map();state.selected='';render();el.cbSearchBtn.disabled=true;el.cbStopBtn.disabled=false;status('Searching live SAM.gov and enriching attachment metadata…','active');
    const max=Math.max(1,Math.min(500,+el.cbMaxResults.value||100));
    try {
      for(const term of ts){for(const variant of variants(term)){for(const[from,to]of ws){if(state.stop)break;await searchVariant(term,variant,from,to,max);}if(state.stop)break;}if(state.stop)break;}
      status(state.stop?'Stopped.':`Search complete. ${state.rows.length} unique opportunities found.`,state.stop?'':'ok');
    } catch(e) { status(`Search failed: ${e.message||e}`,'error'); }
    finally { el.cbSearchBtn.disabled=false;el.cbStopBtn.disabled=true;applyFilters(); }
  }

  function csvVal(v) { const s=text(v).replace(/\r?\n/g,' ');return /[",\n]/.test(s)?`"${s.replace(/"/g,'""')}"`:s; }
  function exportCsv() {
    const head=['Keyword','Matched By','Notice ID','Posted','Title','Solicitation','Type','Agency','NAICS','PSC','Attachment Count','Attachment Total MB','SAM Link','Attachment Names','Attachment Links'];
    const rows=state.visible.map(r=>[r.keyword,r.matchedBy,r.noticeId,r.posted,r.title,r.solicitation,r.type,r.agency,r.naics,r.psc,r.attachmentCount??'',r.attachmentTotalMb==null?'':r.attachmentTotalMb.toFixed(3),r.samUrl,(r.attachments||[]).map(a=>a.name).join(' | '),(r.attachments||[]).map(a=>a.download).join(' | ')]);
    const csv=[head,...rows].map(row=>row.map(csvVal).join(',')).join('\r\n');const url=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download=`contract_brain_search_${new Date().toISOString().slice(0,10)}.csv`;document.body.appendChild(a);a.click();a.remove();URL.revokeObjectURL(url);
  }

  function parseIdentifier(v) { const raw=text(v),m=raw.match(/sam\.gov\/opp\/([^/?#]+)\/view/i);return m?decodeURIComponent(m[1]):raw; }
  function open(notice) { if(!notice)return;location.href=`contract-brain.html?noticeId=${encodeURIComponent(notice)}&view=overview`; }
  function show() { el.searchWorkspace.classList.remove('hidden');el.emptyState?.classList.add('hidden');el.notebook?.classList.add('hidden');document.querySelectorAll('.nav-item').forEach(x=>x.classList.remove('active'));el.contractSearchBtn.classList.add('active');window.history.replaceState(null,'',location.pathname); }
  function clear() { state.stop=true;state.requests=0;state.rows=[];state.visible=[];state.seen=new Map();state.selected='';state.detailSerial++;render();el.cbDetailPanel.innerHTML='<div class="card-body empty-mini">Select a result to inspect its details and attachments before opening the notebook.</div>';status('Ready.'); }

  const today=new Date();el.cbPostedFrom.value=fmt(add(today,-364));el.cbPostedTo.value=fmt(today);
  el.cbAllDates.onchange=()=>{el.cbPostedFrom.disabled=el.cbAllDates.checked;el.cbPostedTo.disabled=el.cbAllDates.checked;};
  el.cbSearchBtn.onclick=run;el.cbStopBtn.onclick=()=>{state.stop=true;status('Stopping after current request…');};el.cbExportBtn.onclick=exportCsv;el.cbClearBtn.onclick=clear;
  [el.cbShowFilter,el.cbHideFilter,el.cbAttachmentFilter,el.cbRequireAttachments,el.cbMinCount,el.cbMinMb].forEach(node=>node?.addEventListener(node.type==='checkbox'?'change':'input',applyFilters));
  el.cbTerms.onkeydown=e=>{if((e.ctrlKey||e.metaKey)&&e.key==='Enter')run();};el.cbOpenIdentifierBtn.onclick=()=>open(parseIdentifier(el.cbOpenIdentifier.value));el.cbOpenIdentifier.onkeydown=e=>{if(e.key==='Enter')open(parseIdentifier(el.cbOpenIdentifier.value));};el.contractSearchBtn.onclick=show;
  const obs=new MutationObserver(()=>{if(el.notebook&&!el.notebook.classList.contains('hidden'))el.searchWorkspace.classList.add('hidden');});if(el.notebook)obs.observe(el.notebook,{attributes:true,attributeFilter:['class']});
  if(new URLSearchParams(location.search).has('noticeId'))el.searchWorkspace.classList.add('hidden');else show();
  render();counts();
})();