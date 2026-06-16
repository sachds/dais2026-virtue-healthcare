// Medical Desert Planner — one trust-signal substrate, four track panes.
const $ = (id) => document.getElementById(id);
const CAPS = ["icu", "maternity", "emergency", "oncology", "trauma", "nicu"];
const SIGNAL_LABEL = { strong: "Strong", partial: "Partial", weak: "Weak", none: "No claim" };
let SELECTED = null;
let OV = {};            // cached /api/overview (facility + scored counts)

function esc(s){return (s==null?"":String(s)).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));}
function badge(sig){return `<span class="sig ${esc(sig)}">${SIGNAL_LABEL[sig]||sig}</span>`;}
function parseArr(s){try{const a=JSON.parse(s);return Array.isArray(a)?a:[];}catch(e){return [];}}
function pct(x){ return x==null ? '—' : Math.round(x*100)+'%'; }

// ---- view / pane switching ----------------------------------------------- //
function activate(name){
  document.querySelectorAll(".pane").forEach(p=>p.classList.toggle("active", p.id==="pane-"+name));
  document.querySelectorAll(".tab").forEach(t=>t.classList.toggle("active", t.dataset.view===name));
}
function showView(name){
  activate(name);
  if(name==="desert") showDesert();
  else if(name==="readiness") showReadiness();
  else if(name==="trust" && !$("list").querySelector(".fac")) loadFacilities();
  window.scrollTo(0,0);
}
document.querySelectorAll(".tab").forEach(t=>t.onclick=()=>showView(t.dataset.view));

async function init(){
  OV = await (await fetch("/api/overview")).json();
  $("status").innerHTML = `<b>${OV.facilities?.toLocaleString()||0}</b> facilities · <b>${OV.scored?.toLocaleString()||0}</b> scored`;
  const st = await (await fetch("/api/states")).json();
  for(const s of st.states||[]){const o=document.createElement("option");o.value=s;o.textContent=s;$("state").appendChild(o);}
  showView("desert");
}

// ---- Track 2: Medical Desert gap map ------------------------------------- //
async function showDesert(){
  $("desert-body").innerHTML = `<div class="empty">Loading the gap map…</div>`;
  const g = await (await fetch("/api/desert")).json();
  renderDesert(g);
}
function cellLabel(c){ return c.status==='served' ? String(c.trusted) : (c.status==='gap' ? '0' : '·'); }
function cellBg(c){
  if(c.status!=='served') return "";
  const r = c.trusted_rate==null ? 0.5 : c.trusted_rate;
  const L = Math.round(74 - 36*r);
  return `background:hsl(157 47% ${L}%);color:${L<54?'#fff':'#1f3a2e'}`;
}
function renderDesert(g){
  const head = `<th>State</th>` + g.caps.map(c=>`<th>${esc(c)}</th>`).join("") + `<th title="NFHS-5 health burden">need</th>`;
  const rows = g.states.map(s=>{
    const cells = g.caps.map(cap=>{
      const c = s.cells[cap];
      const t = `${esc(s.state)} · ${esc(cap)} — ${c.trusted} of ${c.n_scored} evaluated show trusted evidence (${pct(c.trusted_rate)})`+(c.high_risk?' · HIGH-RISK gap':'');
      return `<td><span class="cell ${c.status}${c.high_risk?' hr':''}" style="${cellBg(c)}" title="${t}" onclick="drill('${esc(s.state).replace(/'/g,'')}','${cap}')">${cellLabel(c)}</span></td>`;
    }).join("");
    const d = s.demand;
    const pill = d
      ? `<span class="need ${d.tier}" title="NFHS-5: ${d.institutional_birth}% births in-facility · ${d.insurance}% insured · ${d.stunting}% child stunting · ${d.n_districts} districts">${d.tier}</span>`
      : `<span class="need unknown" title="no NFHS-5 match">–</span>`;
    return `<tr><td class="st">${esc(s.state)} <span class="muted">${s.n_total}</span></td>${cells}<td style="text-align:center">${pill}</td></tr>`;
  }).join("");
  const risks = (g.top_risks||[]).map(x=>{
    const rb = x.status==='gap'
      ? `<span class="sig weak">confirmed gap</span>`
      : `<span class="risk-badge ${x.tier}">${x.tier==='high'?'high-risk':'shortfall'}</span>`;
    const ctx = [];
    if(x.institutional_birth!=null) ctx.push(`${x.institutional_birth}% births in-facility`);
    if(x.insurance!=null) ctx.push(`${x.insurance}% insured`);
    const burden = ctx.length ? ` <span class="muted">· burden ${ctx.join(' · ')}</span>` : '';
    return `<div class="gaprow" onclick="drill('${esc(x.state).replace(/'/g,'')}','${x.capability}')">
       ${rb} <b style="text-transform:capitalize">${esc(x.capability)}</b> in ${esc(x.state)}
       <span class="muted"> — ${x.trusted} of ${x.n_scored} evaluated trusted (${pct(x.trusted_rate)})</span>${burden}</div>`;
  }).join("");
  $("desert-body").innerHTML = `
    <p class="legend">
      <span class="cell served" style="background:hsl(157 47% 66%)">&nbsp;</span><span class="cell served" style="background:hsl(157 47% 40%)">&nbsp;</span> thin → robust trusted supply
      <span class="cell gap">&nbsp;</span> confirmed gap
      <span class="cell datapoor">&nbsp;</span> too little data (need ≥${g.min_coverage})
      <span class="muted">· <b>need</b> = NFHS-5 health burden (${g.demand_states} states matched)</span>
    </p>
    <div class="heatwrap"><table class="heat"><thead><tr>${head}</tr></thead><tbody>${rows}</tbody></table></div>
    <div class="evidence-lbl" style="margin:16px 16px 6px">Highest-risk shortfalls — health burden × thin trusted supply · click to see the facilities</div>
    ${risks || '<div class="muted" style="padding:0 16px 14px">No demand-ranked shortfalls yet — more facilities need scoring.</div>'}`;
}
function drill(state, cap){
  activate("trust");
  $("state").value = state; $("capability").value = cap; $("signal").value = "";
  updateHint(); loadFacilities();
  window.scrollTo(0,0);
}
window.drill = drill;

// ---- Track 4: Data Readiness Desk ---------------------------------------- //
async function showReadiness(){
  $("readiness-body").innerHTML = `<div class="empty">Profiling the dataset…</div>`;
  const r = await (await fetch("/api/readiness")).json();
  renderReadiness(r);
}
function renderReadiness(r){
  const totalFac = OV.facilities || r.total || 0;
  const scored = OV.scored || 0;
  const d = r.signal_dist || {strong:0,partial:0,weak:0,none:0};
  const evald = (d.strong+d.partial+d.weak) || 1;
  const weakpct = Math.round(100*(d.weak||0)/evald);
  const scoredpct = totalFac ? Math.round(100*scored/totalFac) : 0;
  const card = (n,l,sub,cls)=>`<div class="stat ${cls||''}"><div class="stat-n">${n}${sub?` <span>${sub}</span>`:''}</div><div class="stat-l">${l}</div></div>`;
  const cards = [
    card(totalFac.toLocaleString(),"facilities"),
    card(scored.toLocaleString(),"evaluated",scoredpct+"%"),
    card((d.weak||0).toLocaleString(),"weak / suspicious claims",weakpct+"%","warn"),
    card((r.queue||[]).length,"in the review queue",null,"warn"),
    card((r.reviewed||0).toLocaleString(),"reviewed by an analyst"),
  ].join("");

  const cov = (r.coverage||[]).map(c=>{
    const col = c.pct>=80?'var(--strong)':(c.pct>=50?'var(--partial)':'var(--weak)');
    return `<div class="cov-row"><span class="cov-f">${esc(c.field.replace(/_/g,' '))}</span>
      <span class="cov-bar"><i style="width:${c.pct}%;background:${col}"></i></span><span class="cov-p">${c.pct}%</span></div>`;
  }).join("");

  const tot = (d.strong+d.partial+d.weak+d.none) || 1;
  const seg = (k,col)=>`<span class="db-seg" style="width:${100*(d[k]||0)/tot}%;background:${col}" title="${k}: ${(d[k]||0).toLocaleString()}"></span>`;
  const distbar = `<div class="distbar">${seg('strong','var(--strong)')}${seg('partial','var(--partial)')}${seg('weak','var(--weak)')}${seg('none','var(--none)')}</div>
    <div class="db-legend">
      <span><i style="background:var(--strong)"></i>strong ${(d.strong||0).toLocaleString()}</span>
      <span><i style="background:var(--partial)"></i>partial ${(d.partial||0).toLocaleString()}</span>
      <span><i style="background:var(--weak)"></i>weak ${(d.weak||0).toLocaleString()}</span>
      <span><i style="background:var(--none)"></i>no claim ${(d.none||0).toLocaleString()}</span>
    </div>
    <p class="muted" style="margin:10px 0 0"><b>${weakpct}%</b> of claims with any evidence are only weak — generic / unsourced text, not real capability.</p>`;

  const q = (r.queue||[]).map(x=>{
    const cls = x.flag==='over-claim' ? 'weak' : (x.flag.indexOf('weak')===0 ? 'weak' : 'partial');
    return `<div class="qrow" onclick="selectFacility('${esc(x.id)}')">
      <span class="sig ${cls}">${esc(x.flag)}</span>
      <b>${esc(x.name||'')}</b> <span class="muted">${esc([x.city,x.state].filter(Boolean).join(', '))} · ${esc(x.facility_type||'')}</span>
      <div class="muted" style="margin-top:2px">claims <b style="text-transform:capitalize">${esc(x.capability)}</b> — ${esc(x.signal)} (${Math.round((x.confidence||0)*100)}%)</div>
    </div>`;
  }).join("");

  $("readiness-body").innerHTML = `
    <div class="stat-cards">${cards}</div>
    <div class="rd-grid">
      <section class="panel">
        <h2>Field coverage — how complete the source records are</h2>
        <div class="body">${cov}</div>
      </section>
      <section class="panel">
        <h2>Evidence quality of evaluated claims</h2>
        <div class="body">${distbar}</div>
      </section>
    </div>
    <section class="panel">
      <h2>Needs human review — over‑claims &amp; contradictions · click to verify &amp; override</h2>
      <div class="body">${q || '<div class="empty">Review queue is clear.</div>'}</div>
    </section>`;
}

// ---- Track 1: Facility Trust Desk ---------------------------------------- //
["q","state","capability","signal"].forEach(id=>{
  $(id).addEventListener(id==="q"?"input":"change", debounce(()=>{updateHint();loadFacilities();},250));
});
function updateHint(){
  $("hint").textContent = $("capability").value
    ? "Ranked by trust signal — strongest evidence first."
    : "Pick a capability to rank facilities by trust signal.";
}
function debounce(fn,ms){let t;return(...a)=>{clearTimeout(t);t=setTimeout(()=>fn(...a),ms);};}

async function loadFacilities(){
  const p = new URLSearchParams({q:$("q").value,state:$("state").value,capability:$("capability").value,signal:$("signal").value,limit:50});
  const {facilities=[]} = await (await fetch("/api/facilities?"+p)).json();
  $("count").textContent = `· ${facilities.length}`;
  const cap = $("capability").value;
  $("list").innerHTML = facilities.length ? facilities.map(f=>{
    const sel = f.id===SELECTED ? "sel":"";
    let row;
    if(cap){
      row = `${badge(f.signal)} <span class="chip">${(f.confidence*100||0).toFixed(0)}% conf</span>
             <span class="chip">${f.n_evidence||0} evidence</span>`;
    } else {
      row = `<span class="chip">${f.n_strong||0} strong</span><span class="chip">${f.n_partial||0} partial</span>`;
    }
    return `<div class="fac ${sel}" onclick="selectFacility('${esc(f.id)}')">
      <div class="nm">${esc(f.name||"(unnamed)")}</div>
      <div class="meta">${esc([f.city,f.state].filter(Boolean).join(", "))} · ${esc(f.facility_type||"facility")}</div>
      <div class="row">${row}</div></div>`;
  }).join("") : `<div class="empty">No facilities match. ${ (OV.facilities||0)===0 ? "Data still loading…" : "Try widening the filters."}</div>`;
}

async function selectFacility(id){
  SELECTED = id;
  activate("trust");
  if(!$("list").querySelector(".fac")) loadFacilities();
  document.querySelectorAll(".fac").forEach(e=>e.classList.toggle("sel", e.getAttribute("onclick").includes(id)));
  $("fac-detail").innerHTML = `<div class="empty">Loading facility…</div>`;
  const d = await (await fetch("/api/facility/"+encodeURIComponent(id))).json();
  if(!d.facility){ $("fac-detail").innerHTML = `<div class="empty">Facility not found.</div>`; return; }
  const f = d.facility;
  $("detail-title").textContent = f.name || "Facility";
  const srcs = parseArr(f.source_urls).filter(Boolean).slice(0,3);
  const links = srcs.map(u=>`<a class="chip" href="${esc(u)}" target="_blank" rel="noopener">source ↗</a>`).join("");
  const caps = d.capabilities.map(c=>capCard(id,c)).join("");
  $("fac-detail").innerHTML = `
    <div class="fac-head">
      <div class="nm">${esc(f.name||"(unnamed)")}</div>
      <div class="meta">${esc([f.city,f.state,f.postcode].filter(Boolean).join(", "))} · ${esc(f.facility_type||"facility")}${f.operator_type?" · "+esc(f.operator_type):""}</div>
      <div class="links">${links||'<span class="chip">no source link</span>'}</div>
    </div>
    <div class="banner">Signals are evidence-based claims to verify, not certified facts. Confidence and the quoted text show how much to trust each one.</div>
    ${caps}
    <div class="actions">
      <textarea id="note" placeholder="Add a review note or decision for this facility…"></textarea>
    </div>
    <div class="actions" style="border-top:0;padding-top:0">
      <button class="btn" onclick="addNote('${esc(id)}')">Save note</button>
      <button class="btn ghost" onclick="shortlistFac('${esc(id)}')">Add to shortlist</button>
    </div>`;
}

function capCard(fid,c){
  const ovr = c.override && c.override!==c.signal;
  const ev = (c.evidence||[]);
  const evHtml = ev.length ? ev.map(e=>`<div class="ev"><span class="field">${esc(e.field||"")}</span> <span class="snip">"${esc(e.snippet||"")}"</span></div>`).join("")
                           : `<div class="no-ev">No supporting text found in the record.</div>`;
  const ovBtns = ["strong","partial","weak","none"].map(s=>{
    const cur = (c.override||c.signal);
    return `<button class="ov-btn ${cur===s?"act":""}" onclick="override('${esc(fid)}','${c.capability}','${s}')">${SIGNAL_LABEL[s]}</button>`;
  }).join("");
  return `<div class="cap">
    <div class="top">
      <span class="cap-name">${esc(c.capability)}</span>
      ${badge(c.override||c.signal)} ${ovr?`<span class="ov-note">overridden (was ${SIGNAL_LABEL[c.signal]})</span>`:""}
      <span class="conf"><span class="conf-bar"><i style="width:${Math.round((c.confidence||0)*100)}%"></i></span>${Math.round((c.confidence||0)*100)}%</span>
    </div>
    <div class="inner">
      ${c.rationale?`<div class="rationale">${esc(c.rationale)}</div>`:""}
      <div class="evidence-lbl">Cited evidence</div>
      ${evHtml}
      <div class="override"><span class="lbl">Analyst override:</span>${ovBtns}</div>
    </div></div>`;
}

async function review(payload){return (await fetch("/api/review",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)})).json();}
async function override(fid,cap,sig){await review({action:"override",facility_id:fid,capability:cap,new_signal:sig});selectFacility(fid);}
async function addNote(fid){const b=$("note").value.trim();if(!b)return;await review({action:"note",facility_id:fid,body:b});$("note").value="";$("note").placeholder="Saved ✓ — add another…";}
async function shortlistFac(fid){await review({action:"shortlist",facility_id:fid,shortlist:"default"});alert("Added to shortlist.");}

// ---- Track 3: Referral Copilot (governed multi-agent mesh) ---------------- //
async function runCopilot(){
  const q = $("cp-q").value.trim(); if(!q) return;
  activate("copilot");
  $("copilot-body").innerHTML = `<div class="empty">Planning → searching Lakebase → scrutinizing → challenging → governing…</div>`;
  try{
    const r = await (await fetch("/api/copilot",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({query:q})})).json();
    renderCopilot(r);
  }catch(e){ $("copilot-body").innerHTML = `<div class="empty">Copilot error: ${esc(e.message)}</div>`; }
}
function renderCopilot(r){
  const plan=r.plan||{};
  const chips=(plan.capabilities||[]).map(c=>`<span class="chip">${esc(c)}</span>`).join("")+(plan.location?` <span class="chip">📍 ${esc(plan.location)}</span>`:"");
  const trace=(r.trace||[]).map(s=>{
    const prov = s.model?`<span class="tr-prov">${esc(s.model)}</span>`:(s.tool?`<span class="tr-tool">${esc(s.tool)}</span>`:"");
    return `<div class="tr-step"><span class="tr-role">${esc(s.role||s.step)}</span><span class="tr-detail">${esc(s.detail||"")}</span>${prov}</div>`;
  }).join("");
  const vbadge=(v)=> v==='flag' ? `<span class="vb flag">⚠ flagged</span>` : `<span class="vb allow">✓ vetted</span>`;
  const sl=(r.shortlist||[]).map(s=>`
    <div class="cp-card" onclick="selectFacility('${esc(s.id)}')">
      <div class="cp-card-top">${vbadge(s.verdict)}<span class="nm">${esc(s.name||"")}</span>${s.cap?`<span class="chip">${esc(s.cap)}: ${esc(s.signal||'')}</span>`:""}</div>
      ${s.why?`<div class="why">${esc(s.why)}</div>`:""}
      ${s.caution?`<div class="caution">⚠ ${esc(s.caution)}</div>`:""}
    </div>`).join("");
  const bl=(r.blocked||[]).map(b=>`
    <div class="cp-blocked">
      <span class="vb block">✗ blocked</span> <b>${esc(b.name||"")}</b>
      <span class="muted">${esc([b.city,b.state].filter(Boolean).join(', '))}</span>
      <div class="muted">${esc((b.reasons||[])[0]||"")}</div>
    </div>`).join("");
  const demand = (r.demand && r.demand.need_index!=null)
    ? `<div class="cp-demand">📊 NFHS demand · <b>${esc(r.demand.state)}</b>: need ${r.demand.need_index} — ${r.demand.institutional_birth}% births in-facility, ${r.demand.insurance}% insured</div>` : "";
  $("copilot-body").innerHTML=`
    <div class="cp-plan"><b>Agent plan:</b> ${chips||'—'} · retrieved <b>${r.n_candidates||0}</b> evidence-backed candidates from Lakebase</div>
    <div class="evidence-lbl" style="margin:12px 16px 4px">How the agent worked — plan → retrieve → scrutinize → challenge → govern → compose</div>
    <div class="cp-trace">${trace}</div>
    ${r.answer?`<div class="cp-answer">${esc(r.answer)}</div>`:""}
    ${demand}
    <div class="evidence-lbl" style="margin:14px 16px 4px">Recommended — vetted &amp; governed · click any for full cited evidence</div>
    ${sl||'<div class="empty">No evidence-backed matches survived governance. Try a wider area.</div>'}
    ${bl?`<div class="evidence-lbl" style="margin:16px 16px 4px">Not recommended — blocked by policy</div>${bl}`:''}`;
}
window.cpEx=(q)=>{$("cp-q").value=q;runCopilot();};
$("cp-ask").onclick=runCopilot;
$("cp-q").addEventListener("keydown",e=>{if(e.key==="Enter")runCopilot();});

window.selectFacility=selectFacility;window.override=override;window.addNote=addNote;window.shortlistFac=shortlistFac;
init();
