(() => {
  'use strict';

  const WORKER = 'https://samgovsearch.spotterdeer.workers.dev';
  const SUPABASE_URL = 'https://igkjmfjmwatgtubfjcok.supabase.co';
  const SUPABASE_KEY = 'sb_publishable_O5yiMJQAdYTHJWCvyAQU5g_3jasem35';
  const REVIEW_KEY = 'samgovsearch.contractBrain.ontologyReviews.v1';
  const text = v => v == null ? '' : String(v).trim();
  const esc = v => text(v).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const strip = v => { const d=document.createElement('div'); d.innerHTML=text(v); return text(d.textContent||d.innerText||''); };
  const fmtBytes = value => { const n=Number(value); if(!Number.isFinite(n)||n<=0)return '—'; const u=['B','KB','MB','GB'];let i=0,x=n;while(x>=1024&&i<u.length-1){x/=1024;i++;}return `${x>=10||i===0?x.toFixed(0):x.toFixed(1)} ${u[i]}`; };
  const load = (k,f={}) => { try{return JSON.parse(localStorage.getItem(k)||'')||f}catch{return f} };
  const save = (k,v) => localStorage.setItem(k,JSON.stringify(v));

  let renderSerial = 0;
  let current = { noticeId:'', opportunity:null, documents:[], nodes:[], edges:[], selected:'contract', filter:'', type:'all' };

  function injectStyles(){
    if(document.getElementById('cbOntologyStyles')) return;
    const style=document.createElement('style');
    style.id='cbOntologyStyles';
    style.textContent=`
      .ontology-shell{display:grid;gap:12px}.ontology-toolbar{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}.ontology-toolbar h2{margin:0;font-size:22px}.ontology-toolbar p{margin:3px 0 0;color:var(--muted)}.ontology-toolbar-actions{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.ontology-toolbar .field,.ontology-toolbar .select{min-width:170px}
      .ontology-layout{display:grid;grid-template-columns:minmax(0,1fr) 330px;gap:12px;align-items:start}.ontology-graph-card{overflow:hidden}.ontology-graph-head{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:12px 14px;border-bottom:1px solid var(--line)}.ontology-legend{display:flex;gap:12px;flex-wrap:wrap;color:var(--muted);font-size:10px}.ontology-legend span{display:inline-flex;align-items:center;gap:5px}.ontology-legend i{width:8px;height:8px;border-radius:50%;display:inline-block}.ontology-legend .contract{background:var(--cyan)}.ontology-legend .context{background:#8aa9c7}.ontology-legend .source{background:#45d483}.ontology-legend .candidate{background:#f3b83f}
      .ontology-stage{height:650px;position:relative;overflow:auto;background:radial-gradient(circle at 45% 48%,rgba(18,107,130,.16),transparent 24rem),linear-gradient(180deg,#071522,#06111d)}.ontology-stage::before{content:'';position:absolute;inset:0;background-image:linear-gradient(rgba(91,132,163,.06) 1px,transparent 1px),linear-gradient(90deg,rgba(91,132,163,.06) 1px,transparent 1px);background-size:34px 34px;pointer-events:none}.ontology-edges{position:absolute;inset:0;width:100%;height:100%;overflow:visible;pointer-events:none}.ontology-edge{stroke:#254863;stroke-width:1.2;opacity:.82}.ontology-edge.candidate{stroke:#6b5b2b}.ontology-edge.source{stroke:#245c48}.ontology-edge-label{fill:#63809a;font-size:8px;letter-spacing:.04em;text-transform:uppercase}
      .ontology-node{position:absolute;transform:translate(-50%,-50%);min-width:128px;max-width:190px;border:1px solid #28445d;border-radius:8px;background:linear-gradient(180deg,#0d2136,#091827);color:#dce9f5;padding:9px 10px;text-align:left;cursor:pointer;box-shadow:0 8px 22px rgba(0,0,0,.22);z-index:2}.ontology-node:hover,.ontology-node.selected{border-color:#28cfe8;box-shadow:0 0 0 2px rgba(22,216,244,.09),0 10px 26px rgba(0,0,0,.28)}.ontology-node .node-kind{display:block;font-size:8px;font-weight:800;letter-spacing:.12em;text-transform:uppercase;color:#6f8ba5}.ontology-node strong{display:block;font-size:11px;line-height:1.25;margin-top:3px;overflow:hidden;text-overflow:ellipsis}.ontology-node small{display:block;color:#7f96ab;font-size:9px;margin-top:3px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.ontology-node.contract{min-width:190px;border-color:#0ca6c7;background:linear-gradient(180deg,#0e3445,#0a2030)}.ontology-node.contract .node-kind{color:#69e8fa}.ontology-node.source{border-color:#28604c}.ontology-node.source .node-kind{color:#6cdb9b}.ontology-node.candidate{border-color:#68552d}.ontology-node.candidate .node-kind{color:#f7c667}.ontology-node.accepted{box-shadow:inset 3px 0 0 var(--green)}.ontology-node.ignored{opacity:.45}.ontology-node.dimmed{opacity:.12;pointer-events:none}
      .ontology-inspector{position:sticky;top:78px;overflow:hidden}.ontology-inspector .card-head{align-items:flex-start}.ontology-inspector-title{font-size:15px;margin:0}.ontology-inspector-type{font-size:9px;color:#6f8ba5;text-transform:uppercase;letter-spacing:.12em}.ontology-inspector .kv-list{grid-template-columns:105px 1fr}.ontology-evidence{margin-top:12px;border-top:1px solid var(--line);padding-top:11px}.ontology-evidence h4{margin:0 0 7px;font-size:11px}.ontology-evidence p{margin:0;color:#aebfd0;font-size:11px;white-space:pre-wrap}.ontology-actions{display:flex;gap:7px;flex-wrap:wrap;margin-top:12px}.ontology-actions .btn{font-size:10px;padding:7px 9px}.ontology-status-note{margin-top:10px;padding:9px;border:1px solid #33445a;border-radius:6px;background:#081624;color:#96aabd;font-size:10px}.ontology-status-note.warn{border-color:#68552d;color:#e9c76d;background:rgba(104,85,45,.11)}
      .ontology-foot{display:grid;grid-template-columns:repeat(4,1fr);gap:9px}.ontology-stat{border:1px solid var(--line);border-radius:7px;background:#091827;padding:10px 11px}.ontology-stat span{display:block;color:var(--muted);font-size:9px;text-transform:uppercase;letter-spacing:.08em}.ontology-stat strong{display:block;font-size:19px;margin-top:3px}.ontology-stat small{display:block;color:#71879c;font-size:9px;margin-top:2px}
      @media(max-width:1200px){.ontology-layout{grid-template-columns:1fr}.ontology-inspector{position:static}.ontology-stage{height:600px}.ontology-foot{grid-template-columns:1fr 1fr}}@media(max-width:760px){.ontology-stage{height:720px}.ontology-foot{grid-template-columns:1fr}.ontology-toolbar-actions{width:100%}.ontology-toolbar .field,.ontology-toolbar .select{min-width:0;flex:1}}
    `;
    document.head.appendChild(style);
  }

  function ensureNav(){
    if(document.querySelector('.nav-item[data-view="ontology"]')) return;
    const overview=document.querySelector('.nav-item[data-view="overview"]');
    if(!overview) return;
    const btn=document.createElement('button');
    btn.className='nav-item';
    btn.dataset.view='ontology';
    btn.innerHTML='◈ <span>Technical Ontology</span><b id="ontologyNodeCount">0</b>';
    overview.parentNode.insertBefore(btn,overview);
    btn.addEventListener('click',e=>{e.preventDefault();e.stopPropagation();setUrlView('ontology');markActive('ontology');renderOntology(true);});
  }

  function setUrlView(view){ const url=new URL(location.href); if(current.noticeId||url.searchParams.get('noticeId')) url.searchParams.set('view',view); window.history.replaceState(null,'',url); }
  function markActive(view){document.querySelectorAll('.nav-item').forEach(x=>x.classList.remove('active'));const x=document.querySelector(`.nav-item[data-view="${view}"]`);if(x)x.classList.add('active');}
  function noticeFromUrl(){return text(new URLSearchParams(location.search).get('noticeId'));}

  async function fetchJson(url,options={}){const r=await fetch(url,{headers:{Accept:'application/json',...(options.headers||{})},cache:'no-store',...options});const body=await r.text();if(!r.ok)throw new Error(`${r.status}: ${body.slice(0,220)}`);return body?JSON.parse(body):null;}
  async function supabase(table,pairs=[]){const u=new URL(`${SUPABASE_URL}/rest/v1/${table}`);for(const[k,v]of pairs)if(v!==''&&v!=null)u.searchParams.append(k,v);return fetchJson(u,{headers:{apikey:SUPABASE_KEY,Authorization:`Bearer ${SUPABASE_KEY}`}});}
  function unwrap(raw){if(!raw||typeof raw!=='object')return{};if(raw.data2&&typeof raw.data2==='object')return raw.data2;if(raw._embedded){for(const k of['opportunity','opportunityData','results']){const v=raw._embedded[k];if(Array.isArray(v)&&v[0])return v[0];if(v&&typeof v==='object')return v;}}return raw;}
  function val(row,...keys){for(const k of keys){const v=row&&row[k];if(text(v))return v;}return'';}
  function org(row,fallback){const h=row.organizationHierarchy||row.organizationHierarchyName;if(Array.isArray(h)){const p=h.map(x=>typeof x==='object'?text(x.name||x.value):text(x)).filter(Boolean);if(p.length)return p.join(' > ');}return text(val(row,'fullParentPathName','organizationName','officeName','agencyName'))||text(fallback&&fallback.agency);}
  function noticeType(row,fallback){const t=row.type;if(t&&typeof t==='object')return [t.code,t.value].map(text).filter(Boolean).join(' ');return text(val(row,'noticeType','type'))||text(fallback&&fallback.notice_type);}
  function description(row,fallback){if(Array.isArray(row.descriptions)&&row.descriptions[0]){const d=row.descriptions[0];return strip(typeof d==='object'?(d.content||d.description||''):d);}return strip(val(row,'description','descriptionText'))||text(fallback&&fallback.description);}
  function normalizeOpportunity(raw,fallback,noticeId){const row=unwrap(raw);return{noticeId:text(val(row,'noticeId','noticeID','_id','id','opportunityId'))||text(fallback&&fallback.notice_id)||noticeId,title:text(val(row,'title','noticeTitle'))||text(fallback&&fallback.title)||'Untitled opportunity',solicitation:text(val(row,'solicitationNumber'))||text(fallback&&fallback.solicitation_number),posted:text(val(row,'publishDate','postedDate'))||text(fallback&&fallback.posted_date),deadline:text(val(row,'responseDeadline','responseDate','responseDeadLine'))||text(fallback&&fallback.response_deadline),agency:org(row,fallback),type:noticeType(row,fallback),naics:text(val(row,'naics','naicsCode'))||text(fallback&&fallback.naics),psc:text(val(row,'classificationCode','pscCode'))||text(fallback&&fallback.psc),description:description(row,fallback),samUrl:text(fallback&&fallback.sam_url)||`https://sam.gov/opp/${encodeURIComponent(noticeId)}/view`};}
  function docsFromResources(raw){const out=[];const lists=raw&&raw._embedded&&raw._embedded.opportunityAttachmentList;if(!Array.isArray(lists))return out;for(const g of lists)for(const a of(Array.isArray(g&&g.attachments)?g.attachments:[])){if(!a||text(a.deletedFlag)==='1')continue;const resourceId=text(a.resourceId),name=text(a.name||a.filename);if(!resourceId||!name)continue;const size=Number(String(a.size??'').replace(/,/g,''));out.push({resourceId,name,sizeBytes:Number.isFinite(size)?size:null,posted:text(a.postedDate||a.createdDate),download:`${WORKER}/download/${encodeURIComponent(resourceId)}`});}return out;}

  async function loadContract(noticeId){
    const [idxOpp,idxDocs,details,resources]=await Promise.allSettled([
      supabase('opportunities',[['select','*'],['notice_id',`eq.${noticeId}`],['limit','1']]),
      supabase('documents',[['select','notice_id,resource_id,document_name,size_bytes,posted_date,download_url'],['notice_id',`eq.${noticeId}`],['order','document_name.asc']]),
      fetchJson(`${WORKER}/details/${encodeURIComponent(noticeId)}`),
      fetchJson(`${WORKER}/resources/${encodeURIComponent(noticeId)}`)
    ]);
    const fallback=idxOpp.status==='fulfilled'&&idxOpp.value&&idxOpp.value[0]?idxOpp.value[0]:null;
    const opportunity=normalizeOpportunity(details.status==='fulfilled'?details.value:null,fallback,noticeId);
    let documents=resources.status==='fulfilled'?docsFromResources(resources.value):[];
    if(!documents.length&&idxDocs.status==='fulfilled'&&Array.isArray(idxDocs.value))documents=idxDocs.value.map(d=>({resourceId:text(d.resource_id),name:text(d.document_name),sizeBytes:d.size_bytes,posted:text(d.posted_date),download:text(d.download_url)||`${WORKER}/download/${encodeURIComponent(d.resource_id)}`})).filter(d=>d.resourceId&&d.name);
    return{opportunity,documents};
  }

  const STOP=new Set('THE AND FOR WITH FROM THIS THAT INTO WILL SHALL MUST MAY ARE WAS WERE HAS HAVE HAD NOT ALL ANY CAN USE USED USING SYSTEM SYSTEMS CONTRACT CONTRACTOR SOLICITATION NOTICE AWARD SOURCES SOUGHT REQUIREMENT REQUIREMENTS ATTACHMENT DOCUMENT DOCUMENTS FILE PDF ZIP DOC DOCX XLS XLSX AMENDMENT STATEMENT WORK SCOPE GOVERNMENT FEDERAL UNITED STATES DEPARTMENT AGENCY'.split(' '));
  function extractCandidates(op,docs){
    const buckets=new Map();
    const add=(term,where)=>{term=text(term).replace(/^[-_./]+|[-_./]+$/g,'');if(term.length<3||term.length>42)return;const up=term.toUpperCase();if(STOP.has(up)||/^\d+$/.test(up))return;const key=up.replace(/\s+/g,' ');const row=buckets.get(key)||{label:term,count:0,evidence:new Set()};row.count++;row.evidence.add(where);if(term.length>row.label.length)row.label=term;buckets.set(key,row);};
    const sources=[['title',op.title],['description',(op.description||'').slice(0,7000)],...docs.slice(0,40).map(d=>[`source:${d.resourceId}`,d.name])];
    for(const[where,raw]of sources){const s=text(raw);for(const m of s.matchAll(/\b[A-Z]{2,}(?:[-\/][A-Z0-9]{2,})*\b/g))add(m[0],where);for(const m of s.matchAll(/\b[A-Za-z]{1,8}[-\/]?[A-Za-z0-9]*\d[A-Za-z0-9-\/]*\b/g))add(m[0],where);for(const token of s.replace(/[_.,;:()\[\]{}]/g,' ').split(/\s+/)){const clean=token.replace(/[^A-Za-z0-9+\-\/]/g,'');if(clean.length>=6&&/^[A-Za-z][A-Za-z0-9+\-\/]+$/.test(clean)&&!STOP.has(clean.toUpperCase()))add(clean,where);}}
    return[...buckets.values()].sort((a,b)=>(b.evidence.size-a.evidence.size)||(b.count-a.count)||a.label.localeCompare(b.label)).slice(0,14).map((x,i)=>({...x,id:`candidate-${i+1}`,evidence:[...x.evidence]}));
  }

  function buildGraph(op,docs){
    const nodes=[{id:'contract',kind:'contract',label:op.title||op.noticeId,sub:op.solicitation||op.noticeId,status:'source-grounded',evidence:'SAM.gov opportunity record',x:43,y:48}];
    const edges=[]; const left=[];
    if(op.solicitation)left.push({id:'solicitation',kind:'context',label:op.solicitation,sub:'Solicitation / PIID',field:'Solicitation'});
    if(op.agency)left.push({id:'agency',kind:'context',label:op.agency,sub:'Issuing organization',field:'Agency'});
    if(op.type)left.push({id:'notice-type',kind:'context',label:op.type,sub:'Notice type',field:'Type'});
    if(op.naics)left.push({id:'naics',kind:'context',label:op.naics,sub:'NAICS classification',field:'NAICS'});
    if(op.psc)left.push({id:'psc',kind:'context',label:op.psc,sub:'PSC classification',field:'PSC'});
    if(op.deadline)left.push({id:'deadline',kind:'context',label:op.deadline,sub:'Response deadline',field:'Deadline'});
    left.forEach((n,i)=>{n.x=15;n.y=12+(i*(76/Math.max(1,left.length-1)));nodes.push(n);edges.push({from:'contract',to:n.id,label:n.id==='agency'?'ISSUED BY':n.id==='solicitation'?'IDENTIFIED BY':'DESCRIBED BY',kind:'context'});});
    const shownDocs=docs.slice(0,9);
    shownDocs.forEach((d,i)=>{const n={id:`source-${i}`,kind:'source',label:d.name,sub:d.resourceId,resourceId:d.resourceId,download:d.download,sizeBytes:d.sizeBytes,x:69,y:9+(i*(82/Math.max(1,shownDocs.length-1)))};nodes.push(n);edges.push({from:'contract',to:n.id,label:'HAS SOURCE',kind:'source'});});
    if(docs.length>shownDocs.length){const n={id:'source-more',kind:'source',label:`+${docs.length-shownDocs.length} more sources`,sub:'Open Sources for full inventory',x:69,y:94};nodes.push(n);edges.push({from:'contract',to:n.id,label:'HAS SOURCE',kind:'source'});}
    const candidates=extractCandidates(op,docs);
    candidates.slice(0,10).forEach((c,i)=>{const n={...c,kind:'candidate',sub:`${c.evidence.length} evidence location${c.evidence.length===1?'':'s'}`,x:91,y:8+(i*(84/Math.max(1,Math.min(10,candidates.length)-1)))};nodes.push(n);let sourceEdge=null;const sourceEvidence=c.evidence.find(x=>x.startsWith('source:'));if(sourceEvidence){const rid=sourceEvidence.slice(7);const idx=shownDocs.findIndex(d=>d.resourceId===rid);if(idx>=0)sourceEdge=`source-${idx}`;}edges.push({from:sourceEdge||'contract',to:n.id,label:'MENTIONS',kind:'candidate'});});
    return{nodes,edges,candidates};
  }

  function reviewsFor(noticeId){const all=load(REVIEW_KEY,{});return all[noticeId]||{};}
  function setReview(nodeId,status){const all=load(REVIEW_KEY,{});all[current.noticeId]=all[current.noticeId]||{};if(status)all[current.noticeId][nodeId]={status,at:new Date().toISOString()};else delete all[current.noticeId][nodeId];save(REVIEW_KEY,all);renderGraph();renderInspector(nodeId);}
  function nodeVisible(n){if(n.id==='contract')return true;if(current.type!=='all'&&n.kind!==current.type)return false;const q=current.filter.toLowerCase();return !q||`${n.label} ${n.sub||''} ${n.kind}`.toLowerCase().includes(q);}

  function renderGraph(){
    const stage=document.getElementById('ontologyStage'); if(!stage)return;
    const reviews=reviewsFor(current.noticeId); const visible=new Set(current.nodes.filter(nodeVisible).map(n=>n.id));visible.add('contract');
    const edgeHtml=current.edges.map(e=>{const a=current.nodes.find(n=>n.id===e.from),b=current.nodes.find(n=>n.id===e.to);if(!a||!b||!visible.has(a.id)||!visible.has(b.id))return'';const mx=(a.x+b.x)/2,my=(a.y+b.y)/2;return`<line class="ontology-edge ${esc(e.kind||'')}" x1="${a.x}%" y1="${a.y}%" x2="${b.x}%" y2="${b.y}%"></line><text class="ontology-edge-label" x="${mx}%" y="${my}%">${esc(e.label)}</text>`;}).join('');
    const nodeHtml=current.nodes.map(n=>{const review=reviews[n.id]&&reviews[n.id].status;const dim=!visible.has(n.id);return`<button class="ontology-node ${esc(n.kind)} ${current.selected===n.id?'selected':''} ${review?esc(review):''} ${dim?'dimmed':''}" data-node="${esc(n.id)}" style="left:${n.x}%;top:${n.y}%"><span class="node-kind">${esc(n.kind==='candidate'?'Candidate technical term':n.kind)}</span><strong>${esc(n.label)}</strong><small>${esc(n.sub||'')}</small></button>`;}).join('');
    stage.innerHTML=`<svg class="ontology-edges" viewBox="0 0 1000 650" preserveAspectRatio="none">${edgeHtml}</svg>${nodeHtml}`;
    stage.querySelectorAll('[data-node]').forEach(btn=>btn.addEventListener('click',()=>{current.selected=btn.dataset.node;renderGraph();renderInspector(current.selected);}));
    const count=document.getElementById('ontologyNodeCount');if(count)count.textContent=String(current.nodes.length);
  }

  function evidenceText(n){if(n.kind==='contract')return 'Direct SAM.gov opportunity record.';if(n.kind==='context')return `Direct SAM.gov metadata field${n.field?`: ${n.field}`:''}.`;if(n.kind==='source')return n.resourceId?`SAM.gov attachment resource ID: ${n.resourceId}`:'Source inventory summary.';if(n.kind==='candidate'){const list=(n.evidence||[]).map(x=>x==='title'?'Opportunity title':x==='description'?'Opportunity description':x.startsWith('source:')?`Attachment ${x.slice(7)}`:x);return `Rule extracted candidate. Mentioned in ${list.join(', ')||'public evidence'}. This is not yet a verified component or system entity.`;}return 'Public evidence.';}
  function renderInspector(nodeId){
    const mount=document.getElementById('ontologyInspector');if(!mount)return;const n=current.nodes.find(x=>x.id===nodeId)||current.nodes[0];if(!n)return;current.selected=n.id;const review=reviewsFor(current.noticeId)[n.id];const related=current.edges.filter(e=>e.from===n.id||e.to===n.id);const isCandidate=n.kind==='candidate';
    mount.innerHTML=`<div class="card-head"><div><div class="ontology-inspector-type">${esc(isCandidate?'Candidate technical entity':n.kind)}</div><h3 class="ontology-inspector-title">${esc(n.label)}</h3></div><span class="status-pill ${isCandidate?'amber':'green'}">${isCandidate?'Needs review':'Source grounded'}</span></div><div class="card-body"><div class="kv-list"><dt>Node ID</dt><dd class="mono">${esc(n.id)}</dd><dt>Class</dt><dd>${esc(n.kind)}</dd><dt>Relationships</dt><dd>${related.length}</dd>${n.sizeBytes!=null?`<dt>Size</dt><dd>${esc(fmtBytes(n.sizeBytes))}</dd>`:''}${review?`<dt>Review</dt><dd>${esc(review.status)} · ${esc(new Date(review.at).toLocaleString())}</dd>`:''}</div><div class="ontology-evidence"><h4>Evidence / provenance</h4><p>${esc(evidenceText(n))}</p></div>${isCandidate?`<div class="ontology-status-note warn">Candidate terms are surfaced by deterministic text rules only. They must not be treated as verified systems, components, interfaces, or requirements until evidence is reviewed.</div>`:`<div class="ontology-status-note">This node comes directly from the public opportunity record or public attachment inventory.</div>`}<div class="ontology-actions">${n.download?`<a class="btn btn-secondary" href="${esc(n.download)}" target="_blank" rel="noopener">Open source ↗</a>`:''}${n.kind==='contract'?`<a class="btn btn-secondary" href="${esc(current.opportunity.samUrl)}" target="_blank" rel="noopener">Open SAM.gov ↗</a>`:''}${isCandidate?`<button class="btn btn-accent" data-review="accepted">✓ Accept candidate</button><button class="btn btn-secondary" data-review="ignored">Ignore</button><button class="btn btn-secondary" data-review="">Clear review</button>`:''}</div></div>`;
    mount.querySelectorAll('[data-review]').forEach(b=>b.addEventListener('click',()=>setReview(n.id,b.dataset.review)));
  }

  function renderShell(){
    const mount=document.getElementById('viewMount');if(!mount)return;
    const g=buildGraph(current.opportunity,current.documents);current.nodes=g.nodes;current.edges=g.edges;if(!current.nodes.some(n=>n.id===current.selected))current.selected='contract';
    mount.innerHTML=`<div id="ontologyRoot" class="ontology-shell"><div class="ontology-toolbar"><div><div class="eyebrow">TECHNICAL KNOWLEDGE MODEL</div><h2>Technical Ontology</h2><p>Source grounded contract context, public evidence, and candidate technical entities in one relationship view.</p></div><div class="ontology-toolbar-actions"><input id="ontologyFilter" class="field" placeholder="Filter nodes..."><select id="ontologyType" class="select"><option value="all">All node classes</option><option value="context">Contract context</option><option value="source">Sources</option><option value="candidate">Candidate technical terms</option></select></div></div><div class="ontology-layout"><section class="card ontology-graph-card"><div class="ontology-graph-head"><strong>Relationship Graph</strong><div class="ontology-legend"><span><i class="contract"></i>Contract</span><span><i class="context"></i>Context</span><span><i class="source"></i>Source evidence</span><span><i class="candidate"></i>Candidate term</span></div></div><div id="ontologyStage" class="ontology-stage"></div></section><aside id="ontologyInspector" class="card ontology-inspector"></aside></div><div class="ontology-foot"><div class="ontology-stat"><span>Graph nodes</span><strong>${g.nodes.length}</strong><small>Current ontology view</small></div><div class="ontology-stat"><span>Public sources</span><strong>${current.documents.length}</strong><small>Attachment resource IDs</small></div><div class="ontology-stat"><span>Candidate terms</span><strong>${g.candidates.length}</strong><small>Rule extracted, review required</small></div><div class="ontology-stat"><span>Refresh mode</span><strong>Manual</strong><small>No background polling</small></div></div></div>`;
    document.getElementById('ontologyFilter').value=current.filter;document.getElementById('ontologyType').value=current.type;
    document.getElementById('ontologyFilter').addEventListener('input',e=>{current.filter=e.target.value;renderGraph();});document.getElementById('ontologyType').addEventListener('change',e=>{current.type=e.target.value;renderGraph();});
    renderGraph();renderInspector(current.selected);
  }

  async function renderOntology(force=false){
    const noticeId=noticeFromUrl()||current.noticeId;if(!noticeId)return;
    const notebook=document.getElementById('notebook');if(!notebook||notebook.classList.contains('hidden'))return;
    markActive('ontology');
    const mount=document.getElementById('viewMount');if(!force&&mount&&mount.querySelector('#ontologyRoot')&&current.noticeId===noticeId)return;
    const serial=++renderSerial;current.noticeId=noticeId;
    if(mount)mount.innerHTML='<section class="card"><div class="card-body empty-mini">Building technical ontology from the public opportunity record and source inventory…</div></section>';
    try{const data=await loadContract(noticeId);if(serial!==renderSerial)return;current.opportunity=data.opportunity;current.documents=data.documents;renderShell();}
    catch(e){if(serial!==renderSerial)return;if(mount)mount.innerHTML=`<section class="card"><div class="card-body"><h3>Technical ontology could not load</h3><p class="error">${esc(e.message||e)}</p></div></section>`;}
  }

  function routeOpen(notice){if(!notice)return;const u=new URL(location.href);u.searchParams.set('noticeId',notice);u.searchParams.set('view','ontology');location.href=u.toString();}
  function parseIdentifier(v){const raw=text(v),m=raw.match(/sam\.gov\/opp\/([^/?#]+)\/view/i);return m?decodeURIComponent(m[1]):raw;}
  function selectedSearchNotice(){const row=document.querySelector('#cbResultsBody tr.selected[data-id]');return row&&row.dataset.id;}

  function wireRouting(){
    document.addEventListener('click',e=>{
      const nav=e.target.closest('.nav-item[data-view]');
      if(nav&&nav.dataset.view!=='ontology'&&noticeFromUrl()) setUrlView(nav.dataset.view);
      const direct=e.target.closest('[data-open]');
      if(direct&&direct.dataset.open){e.preventDefault();e.stopImmediatePropagation();routeOpen(direct.dataset.open);return;}
      const quick=e.target.closest('.search-result[data-notice],.saved-card[data-notice]');
      if(quick&&quick.dataset.notice){e.preventDefault();e.stopImmediatePropagation();routeOpen(quick.dataset.notice);return;}
      if(e.target.closest('#cbDetailOpen')){const id=selectedSearchNotice();if(id){e.preventDefault();e.stopImmediatePropagation();routeOpen(id);}return;}
      if(e.target.closest('#cbOpenIdentifierBtn')){const input=document.getElementById('cbOpenIdentifier');const id=parseIdentifier(input&&input.value);if(id){e.preventDefault();e.stopImmediatePropagation();routeOpen(id);}return;}
    },true);
    document.addEventListener('keydown',e=>{if(e.key==='Enter'&&e.target&&e.target.id==='cbOpenIdentifier'){const id=parseIdentifier(e.target.value);if(id){e.preventDefault();e.stopImmediatePropagation();routeOpen(id);}}},true);
  }

  function observe(){
    const notebook=document.getElementById('notebook'),mount=document.getElementById('viewMount');
    const maybe=()=>{const p=new URLSearchParams(location.search);if(p.get('noticeId')&&(p.get('view')||'ontology')==='ontology')setTimeout(()=>renderOntology(false),0);};
    if(notebook)new MutationObserver(maybe).observe(notebook,{attributes:true,attributeFilter:['class']});
    if(mount)new MutationObserver(()=>{if(new URLSearchParams(location.search).get('view')==='ontology'&&!mount.querySelector('#ontologyRoot'))setTimeout(()=>renderOntology(false),0);}).observe(mount,{childList:true});
    maybe();
  }

  injectStyles();ensureNav();wireRouting();
  const params=new URLSearchParams(location.search);
  if(params.get('noticeId')&&(!params.get('view')||params.get('view')==='overview')){params.set('view','ontology');const u=new URL(location.href);u.search=params.toString();window.history.replaceState(null,'',u);}
  observe();
})();
