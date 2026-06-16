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

// progressive "the agent is working" indicator — walks the real pipeline steps while we wait.
let _loadTimer=null;
function showLoading(elId, steps, lead){
  clearInterval(_loadTimer);
  const el=$(elId); if(!el) return;
  let i=0;
  const render=()=>{ el.innerHTML = `<div class="loading-steps">${lead?`<div class="ls-lead">${esc(lead)}</div>`:""}${
    steps.map((s,j)=>`<div class="ls-step ${j<i?'done':(j===i?'active':'')}"><span class="ls-mark">${j<i?'✓':''}</span>${esc(s)}</div>`).join("")}</div>`; };
  render();
  _loadTimer=setInterval(()=>{ if(i<steps.length-1){ i++; render(); } else { clearInterval(_loadTimer); } }, 1500);
}
function stopLoading(){ clearInterval(_loadTimer); }

// ---- view / pane switching ----------------------------------------------- //
function activate(name){
  document.querySelectorAll(".pane").forEach(p=>p.classList.toggle("active", p.id==="pane-"+name));
  document.querySelectorAll(".tab").forEach(t=>t.classList.toggle("active", t.dataset.view===name));
}
function showView(name){
  activate(name);
  if(name==="desert") showDesert();
  else if(name==="readiness") showReadiness();
  else if(name==="publichealth") showPublicHealth();
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
let DESERT_VIEW = "map", DESERT_CAP = "any";
async function showDesert(){
  $("desert-body").innerHTML = `
    <div class="desert-bar">
      <div class="seg">
        <button class="seg-btn ${DESERT_VIEW==='map'?'active':''}" onclick="setDesertView('map')">🗺 Map</button>
        <button class="seg-btn ${DESERT_VIEW==='table'?'active':''}" onclick="setDesertView('table')">▦ Table</button>
      </div>
      <select id="desert-cap" style="display:${DESERT_VIEW==='map'?'':'none'}" onchange="DESERT_CAP=this.value;showDesertMap()">
        <option value="any" ${DESERT_CAP==='any'?'selected':''}>Trusted supply: any capability</option>
        ${CAPS.map(c=>`<option value="${c}" ${c===DESERT_CAP?'selected':''}>${c.toUpperCase()} deserts</option>`).join("")}
      </select>
    </div>
    <div id="desert-view"><div class="empty">Loading…</div></div>`;
  (DESERT_VIEW==='map' ? showDesertMap : showDesertTable)();
}
function setDesertView(v){ DESERT_VIEW = v; showDesert(); }
window.setDesertView = setDesertView;
async function showDesertTable(){
  $("desert-view").innerHTML = `<div class="empty">Loading the gap map…</div>`;
  const g = await (await fetch("/api/desert")).json();
  renderDesert(g);
}
async function showDesertMap(){
  $("desert-view").innerHTML = `<div class="empty">Plotting districts…</div>`;
  const g = await (await fetch("/api/desertmap?capability="+encodeURIComponent(DESERT_CAP))).json();
  renderDesertMap(g);
}
function districtDrill(district, cap){
  activate("trust");
  $("q").value = district; $("state").value = ""; $("capability").value = (cap && cap!=='any') ? cap : ""; $("signal").value = "";
  updateHint(); loadFacilities(); window.scrollTo(0,0);
}
window.districtDrill = districtDrill;
function renderDesertMap(g){
  if(!g.available){ $("desert-view").innerHTML = `<div class="empty">District map needs the PIN bridge — run load_pincode.py.</div>`; return; }
  const ds = (g.districts||[]).filter(d=>d.lat&&d.lon);
  const W=540, H=600, LAT0=6, LAT1=37, LON0=68, LON1=98;
  const X=lon=>(lon-LON0)/(LON1-LON0)*W, Y=lat=>(LAT1-lat)/(LAT1-LAT0)*H;
  const col={served:'#34a877', gap:'#e0564f', datapoor:'#cbd5e1'};
  const order={datapoor:0, served:1, gap:2};   // draw gaps/served on top of grey
  ds.sort((a,b)=>order[a.status]-order[b.status]);
  const counts={served:0, gap:0, datapoor:0}; ds.forEach(d=>counts[d.status]++);
  const dots = ds.map(d=>{
    const r = Math.max(2.5, Math.min(15, 2+Math.sqrt(d.n_fac)*1.1));
    const detail = d.status==='served' ? `${d.trusted} trusted of ${d.n_fac} facilities`
                  : (d.status==='gap' ? `GAP — 0 trusted of ${d.n_scored} evaluated` : `${d.n_fac} facilities · too few scored`);
    return `<circle cx="${X(d.lon).toFixed(1)}" cy="${Y(d.lat).toFixed(1)}" r="${r.toFixed(1)}" fill="${col[d.status]}" fill-opacity="0.78" stroke="#fff" stroke-width="0.5" onclick="districtDrill('${esc(d.district).replace(/'/g,'')}','${esc(g.capability)}')"><title>${esc(d.district)}${d.state?', '+esc(d.state):''} — ${detail}</title></circle>`;
  }).join("");
  const capLbl = g.capability==='any' ? 'any capability' : g.capability.toUpperCase();
  $("desert-view").innerHTML = `
    <p class="legend">
      <span class="dot2" style="background:${col.served}"></span> trusted supply (${counts.served})
      <span class="dot2" style="background:${col.gap}"></span> confirmed gap (${counts.gap})
      <span class="dot2" style="background:${col.datapoor}"></span> too few scored (${counts.datapoor})
      <span class="muted">· ${ds.length} districts · bubble = # facilities · <b>${capLbl}</b> · click to drill in</span>
    </p>
    <div class="mapwrap"><svg viewBox="0 0 ${W} ${H}" class="desertmap" preserveAspectRatio="xMidYMid meet">${dots}</svg></div>`;
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
  $("desert-view").innerHTML = `
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
  const [r, s, dist] = await Promise.all([
    fetch("/api/readiness").then(x=>x.json()),
    fetch("/api/services").then(x=>x.json()),
    fetch("/api/districts").then(x=>x.json()),
  ]);
  renderReadiness(r, s, dist);
}
// supply mapped to district (PIN bridge)
function districtSection(d){
  if(!d || !d.available) return "";
  const num = (x)=> x ? x.toLocaleString() : '<span class="muted">—</span>';
  const rows = (d.districts||[]).map(x=>`<tr>
    <td class="svc-cat">${esc(x.district)} <span class="muted" style="font-weight:400">${esc(x.state||'')}</span></td>
    <td>${num(x.facilities)}</td>
    <td>${num(x.beds)}</td>
    <td>${num(x.physicians)}</td>
    <td>${x.missing_beds ? `<span style="color:var(--weak)">${x.missing_beds}</span>` : '0'}</td>
  </tr>`).join("");
  return `
    <section class="panel">
      <h2>Geographic distribution — facilities &amp; capacity by district</h2>
      <div class="body">
        <p class="muted" style="margin:0 0 11px"><b>${d.mapped.toLocaleString()}</b> facilities mapped to <b>${d.n_districts}</b> districts via the India Post PIN bridge. Top districts by facility count:</p>
        <table class="svc-table dist">
          <thead><tr><th>District</th><th>Facilities</th><th>Beds</th><th>Physicians</th><th>No bed count</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    </section>`;
}
// classification + capacity + completeness (facility_services)
function servicesSection(s){
  if(!s || !s.available) return "";
  const totalFac = s.total_facilities||1;
  const cats = (s.categories||[]).map(c=>{
    const w = Math.round(100*c.offered/totalFac);
    return `<tr>
      <td class="svc-cat">${esc(c.label)}</td>
      <td><div class="svc-off"><span class="svc-bar"><i style="width:${w}%"></i></span><b>${c.offered.toLocaleString()}</b> <span class="muted">${w}%</span></div></td>
      <td>${c.with_specialists.toLocaleString()}</td>
      <td>${c.beds ? c.beds.toLocaleString() : '<span class="muted">—</span>'}</td>
    </tr>`;
  }).join("");
  const mbpct = s.inpatient ? Math.round(100*s.missing_beds/s.inpatient) : 0;
  return `
    <section class="panel">
      <h2>Clinical classification &amp; capacity — providers by service line</h2>
      <div class="body">
        <p class="muted" style="margin:0 0 11px"><b>${s.total_beds.toLocaleString()}</b> beds across <b>${s.with_beds.toLocaleString()}</b> facilities · avg <b>${s.avg_categories}</b> service lines per provider · specialties &amp; procedures classified into 7 categories.</p>
        <div class="svc-flags">
          <div class="flagcard warn"><b>${s.missing_beds.toLocaleString()} / ${s.inpatient.toLocaleString()}</b> inpatient facilities (${mbpct}%) have no bed count<span>rule · facilities must have beds</span></div>
          <div class="flagcard ${s.missing_specialty?'warn':''}"><b>${s.missing_specialty.toLocaleString()}</b> providers have no specialty attached<span>rule · physicians must have a specialty</span></div>
        </div>
        <table class="svc-table">
          <thead><tr><th>Service line</th><th>Facilities offering</th><th>with specialist</th><th>stated beds</th></tr></thead>
          <tbody>${cats}</tbody>
        </table>
      </div>
    </section>`;
}
function renderReadiness(r, s, dist){
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
    ${servicesSection(s)}
    ${districtSection(dist)}
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

function cardinalityStrip(c){
  const k = c.cardinality; if(!k) return "";
  const eff = c.override||c.signal;
  const lowflag = (eff==='strong'||eff==='partial') && k.specialists===0;
  return `<div class="cardinality ${lowflag?'flag':''}">
    <span class="card-lbl">Corroboration</span>
    <span class="card-lvl ${k.level}">${k.level}</span>
    <span class="card-stat"><b>${k.specialists}</b> ${esc(c.capability)} specialist${k.specialists===1?'':'s'}</span>
    <span class="card-stat"><b>${k.doctors!=null?k.doctors:'—'}</b> physicians</span>
    <span class="card-stat"><b>${k.sources||0}</b> sources</span>
    ${k.beds?`<span class="card-stat"><b>${k.beds}</b> beds</span>`:''}
    ${lowflag?`<span class="card-warn">⚠ no ${esc(c.capability)} specialists on record — claim not corroborated</span>`:''}
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
      ${cardinalityStrip(c)}
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
  showLoading("copilot-body", ["Planning the need","Retrieving from Lakebase","Scrutinizing the evidence","Governing the result","Composing the referral"], "Referral Copilot");
  try{
    const r = await (await fetch("/api/copilot",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({query:q})})).json();
    stopLoading(); renderCopilot(r);
  }catch(e){ stopLoading(); $("copilot-body").innerHTML = `<div class="empty">Copilot error: ${esc(e.message)}</div>`; }
}
function renderCareTeam(r){
  const p=r.plan||{};
  const chips=`<span class="chip" style="text-transform:capitalize">${esc(p.condition||'')}</span>`+(p.location?` <span class="chip">📍 ${esc(p.location)}</span>`:"")+(p.visits?` <span class="chip">${p.visits} visits/mo</span>`:"");
  const trace=(r.trace||[]).map(traceStep).join("");
  const banner=r.escalation?`<div class="ct-escalate">⤴ Escalate · ${esc(r.escalation)}</div>`:"";
  const roles=(r.care_team||[]).map(role=>{
    const facs=(role.facilities||[]).map((f,i)=>`<div class="ct-fac${i===0?' near':''}" onclick="selectFacility('${esc(f.id)}')">
      ${i===0?'<span class="ct-nearest">nearest</span> ':''}<b>${esc(f.name||'')}</b>
      <div class="muted">${esc([f.city,f.state].filter(Boolean).join(', '))}${f.km!=null?' · '+f.km+' km':''}</div></div>`).join("");
    return `<div class="ct-role"><div class="ct-role-h">${esc(role.role)}</div>${facs||'<div class="muted" style="padding:6px 0">No local provider found.</div>'}</div>`;
  }).join("");
  $("copilot-body").innerHTML=`
    <div class="cp-plan"><b>Care team:</b> ${chips}</div>
    <div class="evidence-lbl" style="margin:12px 16px 4px">How the agent worked</div>
    <div class="cp-trace">${trace}</div>
    ${banner}
    ${r.answer?`<div class="cp-answer">${esc(r.answer)}</div>`:""}
    <div class="evidence-lbl" style="margin:14px 16px 4px">The care team — nearest provider for each specialty · click any for cited evidence</div>
    <div class="ct-grid">${roles}</div>`;
}
function renderCopilot(r){
  if(r && r.mode==="care_team"){ return renderCareTeam(r); }
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

// ---- Public Health: population-scale agents ------------------------------ //
let PH_MODE = "immun";
function traceStep(s){
  const prov = s.model?`<span class="tr-prov">${esc(s.model)}</span>`:(s.tool?`<span class="tr-tool">${esc(s.tool)}</span>`:"");
  return `<div class="tr-step"><span class="tr-role">${esc(s.role||s.step)}</span><span class="tr-detail">${esc(s.detail||"")}</span>${prov}</div>`;
}
function mdLite(s){
  return esc(s)
    .replace(/^\s*([-*_])\1{2,}\s*$/gm,'')
    .replace(/^#{1,3}\s+(.*)$/gm,'<h3>$1</h3>')
    .replace(/^#{4,6}\s+(.*)$/gm,'<h4>$1</h4>')
    .replace(/\*\*(.+?)\*\*/g,'<b>$1</b>')
    .replace(/^\s*[-*]\s+(.*)$/gm,'• $1')
    .replace(/\n/g,'<br>');
}
function setPhMode(m){
  PH_MODE = m;
  document.querySelectorAll('[data-phm]').forEach(b=>b.classList.toggle('active', b.dataset.phm===m));
  setPhControls();
  if(m==='burden'){ showBurden(); return; }
  $("ph-body").innerHTML = `<div class="empty">${m==='immun'?'Find the under‑immunized districts and draft a campaign.':'Enter a district + disease to draft an isolation protocol.'}</div>`;
}
window.setPhMode = setPhMode;
function setPhControls(){
  if(PH_MODE==='immun')
    $("ph-controls").innerHTML = `<div class="ph-bar"><input id="ph-region" placeholder="District (optional — leave blank for worst nationwide)"/><button class="btn" onclick="runImmun()">💉 Plan campaign</button></div>`;
  else if(PH_MODE==='outbreak')
    $("ph-controls").innerHTML = `<div class="ph-bar"><input id="ph-oregion" placeholder="District (e.g. Jhansi)"/><input id="ph-disease" placeholder="Disease (e.g. measles)"/><button class="btn" onclick="runOutbreak()">🦠 Plan response</button></div>`;
  else $("ph-controls").innerHTML = "";
}
function showPublicHealth(){ setPhControls(); }
async function showBurden(){
  $("ph-body").innerHTML = `<div class="empty">Benchmarking disease prevalence across districts…</div>`;
  const b = await (await fetch("/api/publichealth/benchmarks")).json();
  renderBurden(b);
}
function renderBurden(b){
  if(!b || !b.available){ $("ph-body").innerHTML = `<div class="empty">Benchmarks need the NFHS district data — run load_nfhs_district.py.</div>`; return; }
  const bmRow = (district, state, v, nat, extra, cond)=>{
    const over = nat!=null ? (v-nat).toFixed(1) : null;
    return `<div class="bm-row">
      <span class="bm-d">${esc(district)} <span class="muted">${esc(state||'')}</span></span>
      <span class="bm-bar"><i style="width:${Math.min(100,v)}%"></i></span>
      <span class="bm-v">${extra||`${v}%`}${over!=null?` <span class="muted">+${over} vs ${nat}%</span>`:''}</span>
      <button class="bm-esc" onclick="runEscalate('${esc(district).replace(/'/g,'')}','${cond}')">⚑ escalate</button>
    </div>`;
  };
  const conds = (b.conditions||[]).map(c=>`
    <section class="panel" style="margin-bottom:14px">
      <h2>${esc(c.label)} · national benchmark <b style="color:var(--ink)">${c.national}%</b></h2>
      <div class="body">${(c.worst||[]).map(w=>bmRow(w.district,w.state,w.v,c.national,null,c.key)).join("")}</div>
    </section>`).join("");
  const nut = (b.nutrition||[]).map(n=>bmRow(n.district,n.state,n.anemia+n.stunting,null,
     `<b style="color:var(--weak)">${n.anemia}%</b> anaemia · <b style="color:var(--partial)">${n.stunting}%</b> stunting`,"child malnutrition (anaemia + stunting)")).join("");
  $("ph-body").innerHTML = `
    <div class="evidence-lbl" style="margin:2px 16px 8px">Prevalence vs national benchmark — worst districts · click ⚑ to escalate to the right organizations</div>
    ${conds}
    <section class="panel"><h2>Anaemia × stunting — combined child‑nutrition burden (they go together)</h2><div class="body">${nut}</div></section>
    <div id="ph-escalation"></div>`;
}
async function runEscalate(district, condition){
  const el = $("ph-escalation"); if(!el) return;
  showLoading("ph-escalation", ["Assessing "+district,"Coordinating the escalation (WHO / NGO / gov)"], "Escalation agent");
  el.scrollIntoView({behavior:"smooth", block:"center"});
  try{
    const r = await (await fetch("/api/publichealth/escalate",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({district,condition})})).json();
    stopLoading(); renderEscalation(r);
  }catch(e){ stopLoading(); el.innerHTML = `<div class="empty">Escalation error: ${esc(e.message)}</div>`; }
}
window.runEscalate = runEscalate;
function renderEscalation(r){
  const trace = (r.trace||[]).map(traceStep).join("");
  $("ph-escalation").innerHTML = `
    <section class="panel" style="margin-top:14px">
      <h2>⚑ Escalation — ${esc(r.district||'')} · ${esc(r.condition||'')}</h2>
      <div class="body"><div class="cp-trace">${trace}</div><div class="ph-plan">${mdLite(r.plan||'')}</div></div>
    </section>`;
  $("ph-escalation").scrollIntoView({behavior:"smooth", block:"start"});
}
async function runImmun(){
  const region = ($("ph-region").value||"").trim();
  showLoading("ph-body", ["Ranking under‑immunized districts","Checking local supply to run it","Drafting the campaign"], "Immunization agent");
  try{
    const r = await (await fetch("/api/publichealth/immunization",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({region})})).json();
    stopLoading(); renderImmun(r);
  }catch(e){ stopLoading(); $("ph-body").innerHTML = `<div class="empty">Agent error: ${esc(e.message)}</div>`; }
}
async function runOutbreak(){
  const region = ($("ph-oregion").value||"").trim(), disease = ($("ph-disease").value||"").trim();
  if(!region){ $("ph-body").innerHTML = `<div class="empty">Enter a district.</div>`; return; }
  showLoading("ph-body", ["Assessing local isolation capacity","Designating isolation facilities","Drafting the containment protocol"], "Outbreak response agent");
  try{
    const r = await (await fetch("/api/publichealth/outbreak",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({region,disease})})).json();
    stopLoading(); renderOutbreak(r);
  }catch(e){ stopLoading(); $("ph-body").innerHTML = `<div class="empty">Agent error: ${esc(e.message)}</div>`; }
}
window.runImmun = runImmun; window.runOutbreak = runOutbreak;
function renderImmun(r){
  const trace = (r.trace||[]).map(traceStep).join("");
  const targets = (r.targets||[]).map(t=>`<tr>
    <td class="svc-cat">${esc(t.district)} <span class="muted" style="font-weight:400">${esc(t.state||'')}</span></td>
    <td><b style="color:var(--weak)">${t.immunization}%</b></td>
    <td>${t.facilities}</td><td>${t.physicians}</td></tr>`).join("");
  $("ph-body").innerHTML = `
    <div class="evidence-lbl" style="margin:2px 16px 4px">Agent — target → plan</div>
    <div class="cp-trace">${trace}</div>
    ${targets?`<div class="evidence-lbl" style="margin:12px 16px 4px">Under‑immunized targets (with local supply to run it)</div>
      <div style="padding:0 16px"><table class="svc-table dist"><thead><tr><th>District</th><th>Fully immunized</th><th>Facilities</th><th>Physicians</th></tr></thead><tbody>${targets}</tbody></table></div>`:''}
    <div class="evidence-lbl" style="margin:14px 16px 4px">Campaign plan</div>
    <div class="ph-plan">${mdLite(r.plan||'')}</div>`;
}
function renderOutbreak(r){
  const trace = (r.trace||[]).map(traceStep).join("");
  const sup = (r.profile&&r.profile.supply)||{};
  const top = (r.profile&&r.profile.top_facilities)||[];
  const caps = top.map(t=>`<span class="chip">${esc(t.name)} · ${t.total_beds||0} beds</span>`).join(" ");
  $("ph-body").innerHTML = `
    <div class="cp-plan"><b>Outbreak signal:</b> ${esc(r.disease||'disease')} in <b>${esc(r.region||'')}</b> · local capacity: ${sup.hospitals||0} hospitals · ${sup.beds||0} beds · ${sup.physicians||0} physicians</div>
    <div class="evidence-lbl" style="margin:12px 16px 4px">Agent — assess → protocol</div>
    <div class="cp-trace">${trace}</div>
    ${caps?`<div style="padding:2px 16px 0">${caps}</div>`:''}
    <div class="evidence-lbl" style="margin:12px 16px 4px">Isolation &amp; containment protocol</div>
    <div class="ph-plan">${mdLite(r.plan||'')}</div>`;
}

window.selectFacility=selectFacility;window.override=override;window.addNote=addNote;window.shortlistFac=shortlistFac;
init();
