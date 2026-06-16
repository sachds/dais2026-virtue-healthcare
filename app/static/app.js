// Facility Trust Desk — planner-facing UI over precomputed, evidence-attached trust signals.
const $ = (id) => document.getElementById(id);
const CAPS = ["icu", "maternity", "emergency", "oncology", "trauma", "nicu"];
const SIGNAL_LABEL = { strong: "Strong", partial: "Partial", weak: "Weak", none: "No claim" };
let SELECTED = null;

function esc(s){return (s==null?"":String(s)).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));}
function badge(sig){return `<span class="sig ${esc(sig)}">${SIGNAL_LABEL[sig]||sig}</span>`;}
function parseArr(s){try{const a=JSON.parse(s);return Array.isArray(a)?a:[];}catch(e){return [];}}

async function init(){
  const ov = await (await fetch("/api/overview")).json();
  $("status").innerHTML = `<b>${ov.facilities?.toLocaleString()||0}</b> facilities · <b>${ov.scored?.toLocaleString()||0}</b> scored`;
  const st = await (await fetch("/api/states")).json();
  for(const s of st.states||[]){const o=document.createElement("option");o.value=s;o.textContent=s;$("state").appendChild(o);}
  showDesert();
  loadFacilities();
}

// ---- Track 2: Medical Desert gap map ----
async function showDesert(){
  $("detail-title").textContent = "Care gaps by state — trusted supply vs. coverage";
  $("detail").innerHTML = `<div class="empty">Loading the gap map…</div>`;
  const g = await (await fetch("/api/desert")).json();
  renderDesert(g);
}
function cellLabel(c){ return c.status==='served' ? String(c.trusted) : (c.status==='gap' ? '0' : '·'); }
function renderDesert(g){
  const head = `<th>State</th>` + g.caps.map(c=>`<th>${esc(c)}</th>`).join("");
  const rows = g.states.map(s=>{
    const cells = g.caps.map(cap=>{
      const c = s.cells[cap];
      const t = `${esc(s.state)} · ${esc(cap)} — ${c.trusted} trusted of ${c.n_scored} evaluated`;
      return `<td><span class="cell ${c.status}" title="${t}" onclick="drill('${esc(s.state).replace(/'/g,'')}','${cap}')">${cellLabel(c)}</span></td>`;
    }).join("");
    return `<tr><td class="st">${esc(s.state)} <span class="muted">${s.n_total}</span></td>${cells}</tr>`;
  }).join("");
  const gaps = (g.top_gaps||[]).map(x=>`<div class="gaprow" onclick="drill('${esc(x.state).replace(/'/g,'')}','${x.capability}')">
     <span class="sig weak">confirmed gap</span> <b style="text-transform:capitalize">${esc(x.capability)}</b> in ${esc(x.state)}
     <span class="muted"> — 0 trusted of ${x.n_scored} evaluated</span></div>`).join("");
  $("detail").innerHTML = `
    <p class="legend">
      <span class="cell served">&nbsp;</span> trusted supply
      <span class="cell gap">&nbsp;</span> confirmed gap
      <span class="cell datapoor">&nbsp;</span> too little data (need ≥${g.min_coverage})
      <span class="muted">· cell number = facilities with strong/partial evidence</span>
    </p>
    <div class="heatwrap"><table class="heat"><thead><tr>${head}</tr></thead><tbody>${rows}</tbody></table></div>
    <div class="evidence-lbl" style="margin:16px 16px 6px">Highest-risk confirmed gaps — click to see the facilities behind the call</div>
    ${gaps || '<div class="muted" style="padding:0 16px 14px">No confirmed gaps yet — more facilities need scoring.</div>'}`;
}
function drill(state, cap){
  $("state").value = state; $("capability").value = cap; $("signal").value = "";
  updateHint(); loadFacilities();
  document.querySelector("main").scrollIntoView({behavior:"smooth", block:"start"});
}
$("nav-map").onclick = showDesert;
window.drill = drill;

// ---- Track 4: Data Readiness Desk ----
async function showReadiness(){
  $("detail-title").textContent = "Data readiness — what to fix before trusting this data";
  $("detail").innerHTML = `<div class="empty">Profiling the dataset…</div>`;
  const r = await (await fetch("/api/readiness")).json();
  renderReadiness(r);
}
function renderReadiness(r){
  const cov = (r.coverage||[]).map(c=>{
    const col = c.pct>=80?'var(--strong)':(c.pct>=50?'var(--partial)':'var(--weak)');
    return `<div class="cov-row"><span class="cov-f">${esc(c.field.replace(/_/g,' '))}</span>
      <span class="cov-bar"><i style="width:${c.pct}%;background:${col}"></i></span><span class="cov-p">${c.pct}%</span></div>`;
  }).join("");
  const d = r.signal_dist||{strong:0,partial:0,weak:0,none:0};
  const weakpct = Math.round(100*(d.weak||0)/((d.strong+d.partial+d.weak)||1));
  const q = (r.queue||[]).map(x=>{
    const cls = x.flag==='over-claim' ? 'weak' : (x.flag.indexOf('weak')===0 ? 'weak' : 'partial');
    return `<div class="qrow" onclick="selectFacility('${esc(x.id)}')">
      <span class="sig ${cls}">${esc(x.flag)}</span>
      <b>${esc(x.name||'')}</b> <span class="muted">${esc([x.city,x.state].filter(Boolean).join(', '))} · ${esc(x.facility_type||'')}</span>
      <div class="muted" style="margin-top:2px">claims <b style="text-transform:capitalize">${esc(x.capability)}</b> — ${esc(x.signal)} (${Math.round((x.confidence||0)*100)}%)</div>
    </div>`;
  }).join("");
  $("detail").innerHTML = `
    <div class="evidence-lbl" style="margin:14px 16px 6px">Field coverage — how complete the source records are</div>
    ${cov}
    <div class="evidence-lbl" style="margin:16px 16px 4px">Evidence quality of evaluated claims</div>
    <p class="muted" style="margin:2px 16px">${d.strong} strong · ${d.partial} partial · <b style="color:var(--weak)">${d.weak} weak / suspicious</b> · ${d.none} no-claim — <b>${weakpct}%</b> of claims with any evidence are only weak.</p>
    <div class="evidence-lbl" style="margin:16px 16px 4px">Needs human review — high-leverage records (${r.reviewed||0} reviewed) · click to verify &amp; override</div>
    ${q || '<div class="muted" style="padding:0 16px 14px">Review queue is clear.</div>'}`;
}
$("nav-ready").onclick = showReadiness;

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
  }).join("") : `<div class="empty">No facilities match. ${ $("status").textContent.startsWith("<b>0") ? "Data still loading…" : "Try widening the filters."}</div>`;
}

async function selectFacility(id){
  SELECTED = id;
  document.querySelectorAll(".fac").forEach(e=>e.classList.toggle("sel", e.getAttribute("onclick").includes(id)));
  const d = await (await fetch("/api/facility/"+encodeURIComponent(id))).json();
  if(!d.facility){return;}
  const f = d.facility;
  $("detail-title").textContent = f.name || "Facility";
  const srcs = parseArr(f.source_urls).filter(Boolean).slice(0,3);
  const links = srcs.map(u=>`<a class="chip" href="${esc(u)}" target="_blank" rel="noopener">source ↗</a>`).join("");
  const caps = d.capabilities.map(c=>capCard(id,c)).join("");
  $("detail").innerHTML = `
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

function renderOverview(ov){
  const rows = (ov.caps||CAPS).map(cap=>{
    const g = ov.grid[cap]||{};
    const cell=(s,col)=>`<td><span class="n" style="color:${col}">${(g[s]||0).toLocaleString()}</span></td>`;
    return `<tr><td>${cap}</td>
      ${cell("strong","var(--strong)")}${cell("partial","var(--partial)")}${cell("weak","var(--weak)")}${cell("none","var(--none)")}</tr>`;
  }).join("");
  $("detail").innerHTML = `
    <p style="color:var(--muted);margin:4px 6px 14px">How many facilities show each level of evidence for each capability. Pick a capability + trust level on the left to drill in.</p>
    <table class="grid">
      <tr><th>Capability</th>
        <th><span class="dot" style="background:var(--strong)"></span>Strong</th>
        <th><span class="dot" style="background:var(--partial)"></span>Partial</th>
        <th><span class="dot" style="background:var(--weak)"></span>Weak</th>
        <th><span class="dot" style="background:var(--none)"></span>No claim</th></tr>
      ${rows}
    </table>`;
}
// ---- Referral Copilot (live agent) ----
async function runCopilot(){
  const q = $("cp-q").value.trim(); if(!q) return;
  $("detail-title").textContent = "Referral Copilot";
  $("detail").innerHTML = `<div class="empty">Planning → searching Lakebase → reasoning over evidence…</div>`;
  try{
    const r = await (await fetch("/api/copilot",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({query:q})})).json();
    renderCopilot(r);
  }catch(e){ $("detail").innerHTML = `<div class="empty">Copilot error: ${esc(e.message)}</div>`; }
}
function renderCopilot(r){
  const plan=r.plan||{};
  const chips=(plan.capabilities||[]).map(c=>`<span class="chip">${esc(c)}</span>`).join("")+(plan.location?` <span class="chip">📍 ${esc(plan.location)}</span>`:"");
  const sl=(r.shortlist||[]).map(s=>`
    <div class="cp-card" onclick="selectFacility('${esc(s.id)}')">
      <div class="nm">${esc(s.name||"")}</div>
      ${s.why?`<div class="why">${esc(s.why)}</div>`:""}
      ${s.caution?`<div class="caution">⚠ ${esc(s.caution)}</div>`:""}
    </div>`).join("");
  $("detail").innerHTML=`
    <div class="cp-plan"><b>Agent:</b> parsed need ${chips||'—'} · retrieved <b>${r.n_candidates||0}</b> evidence-backed candidates from Lakebase</div>
    <div class="cp-answer">${esc(r.answer||"")}</div>
    <div class="evidence-lbl" style="margin:14px 16px 4px">Shortlist — click any to see full cited evidence</div>
    ${sl||'<div class="empty">No evidence-backed matches. Try a wider area.</div>'}`;
}
window.cpEx=(q)=>{$("cp-q").value=q;runCopilot();};
$("cp-ask").onclick=runCopilot;
$("cp-q").addEventListener("keydown",e=>{if(e.key==="Enter")runCopilot();});

window.selectFacility=selectFacility;window.override=override;window.addNote=addNote;window.shortlistFac=shortlistFac;
init();
