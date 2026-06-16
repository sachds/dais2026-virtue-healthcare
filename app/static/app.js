// Medical Desert Planner — one trust-signal substrate, four track panes.
const $ = (id) => document.getElementById(id);
const CAPS = ["icu", "maternity", "emergency", "oncology", "trauma", "nicu"];
const SIGNAL_LABEL = { strong: "Strong", partial: "Partial", weak: "Weak", none: "No claim" };
let SELECTED = null;
let _curFacName = "";   // name of the facility open in the Trust Desk (for the "refer from here" handoff)
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

// ---- Focus spine: a shared working context carried across every scale ------ //
let FOCUS = { region:"", capability:"", facility:null };   // facility = {id, name}
function setFocus(patch){ Object.assign(FOCUS, patch||{}); renderFocus(); }
function clearFocus(){ FOCUS = { region:"", capability:"", facility:null }; renderFocus(); }
window.setFocus=setFocus; window.clearFocus=clearFocus;
function renderFocus(){
  const bar=$("focus-bar"); if(!bar) return;
  const f=FOCUS;
  if(!(f.region||f.capability||f.facility)){ bar.className="focus-bar"; bar.innerHTML=""; return; }
  bar.className="focus-bar on";
  const chips=[];
  if(f.region) chips.push(`<span class="fchip reg">🗺 ${esc(f.region)}<b class="fx" onclick="setFocus({region:''})">×</b></span>`);
  if(f.capability) chips.push(`<span class="fchip cap">${esc(f.capability.toUpperCase())}<b class="fx" onclick="setFocus({capability:''})">×</b></span>`);
  if(f.facility) chips.push(`<span class="fchip fac">🏥 ${esc(f.facility.name||'facility')}<b class="fx" onclick="setFocus({facility:null})">×</b></span>`);
  const acts=[];
  if(f.region){ acts.push(`<button class="fjump" onclick="focusGo('network')">⇄ Network</button>`);
                acts.push(`<button class="fjump" onclick="focusGo('trust')">🏥 ${f.facility?'Open facility':'Facilities'}</button>`); }
  else if(f.facility){ acts.push(`<button class="fjump" onclick="focusGo('trust')">🏥 Open facility</button>`); }
  if(f.facility) acts.push(`<button class="fjump pat" onclick="focusGo('refer')">✦ Refer a patient</button>`);
  bar.innerHTML=`<span class="focus-lbl">Focus</span>${chips.join("")}<span class="focus-acts">${acts.join("")}</span><button class="focus-clear" onclick="clearFocus()">clear ✕</button>`;
}
function focusGo(t){
  if(t==='network') openNetwork(FOCUS.capability||'icu', FOCUS.region);
  else if(t==='trust'){ if(FOCUS.facility) selectFacility(FOCUS.facility.id); else drill(FOCUS.region, FOCUS.capability||''); }
  else if(t==='refer' && FOCUS.facility){ activate('copilot'); $('cp-from').value=FOCUS.facility.name||''; $('cp-q').value=''; window.scrollTo(0,0); $('cp-q').focus(); }
}
window.focusGo=focusGo;

// ---- view / pane switching ----------------------------------------------- //
function activate(name){
  document.querySelectorAll(".pane").forEach(p=>p.classList.toggle("active", p.id==="pane-"+name));
  document.querySelectorAll(".tab").forEach(t=>t.classList.toggle("active", t.dataset.view===name));
}
function showView(name){
  activate(name);
  if(name==="home") showHome();
  else if(name==="desert") showDesert();
  else if(name==="readiness") showReadiness();
  else if(name==="network") showNetwork();
  else if(name==="publichealth") showPublicHealth();
  else if(name==="trust"){ loadShortlist(); if(!$("list").querySelector(".fac")) loadFacilities(); }
  window.scrollTo(0,0);
}
document.querySelectorAll(".tab").forEach(t=>t.onclick=()=>showView(t.dataset.view));

// Overview landing — fills the substrate stats; the scale cards route via showView()
function showHome(){
  const el=$("home-stats"); if(!el) return;
  const f=OV.facilities||0, s=OV.scored||0, pct=f?Math.round(100*s/f):0;
  if($("home-n")) $("home-n").textContent=f.toLocaleString();
  el.innerHTML = `<span class="hs"><b>${f.toLocaleString()}</b> facility records</span>
    <span class="hs"><b>${s.toLocaleString()}</b> evaluated for trust <span class="muted">(${pct}%)</span></span>
    <span class="hs"><b>${(OV.caps||[]).length||6}</b> capabilities, each cited</span>`;
}
async function init(){
  OV = await (await fetch("/api/overview")).json();
  $("status").innerHTML = `<b>${OV.facilities?.toLocaleString()||0}</b> facilities · <b>${OV.scored?.toLocaleString()||0}</b> scored`;
  const st = await (await fetch("/api/states")).json();
  for(const s of st.states||[]){const o=document.createElement("option");o.value=s;o.textContent=s;$("state").appendChild(o);}
  loadShortlist();
  showView("home");
}

// ---- Track 2: Medical Desert gap map ------------------------------------- //
let DESERT_VIEW = "map", DESERT_CAPS = [];
async function showDesert(){
  const chips = DESERT_VIEW==='map' ? `<div class="cap-chips">
      <span class="cap-chip-lbl">Deserts in:</span>
      <button class="cap-chip ${DESERT_CAPS.length===0?'on':''}" onclick="setDesertCaps([])">any</button>
      ${CAPS.map(c=>`<button class="cap-chip ${DESERT_CAPS.includes(c)?'on':''}" onclick="toggleDesertCap('${c}')">${c.toUpperCase()}</button>`).join("")}
    </div>` : "";
  $("desert-body").innerHTML = `
    <div class="desert-bar">
      <div class="seg">
        <button class="seg-btn ${DESERT_VIEW==='map'?'active':''}" onclick="setDesertView('map')">🗺 Map</button>
        <button class="seg-btn ${DESERT_VIEW==='table'?'active':''}" onclick="setDesertView('table')">▦ Table</button>
      </div>
      ${chips}
    </div>
    <div id="desert-view"><div class="empty">Loading…</div></div>`;
  (DESERT_VIEW==='map' ? showDesertMap : showDesertTable)();
}
function setDesertView(v){ DESERT_VIEW = v; showDesert(); }
function toggleDesertCap(c){ const i=DESERT_CAPS.indexOf(c); if(i>=0) DESERT_CAPS.splice(i,1); else DESERT_CAPS.push(c); showDesert(); }
function setDesertCaps(arr){ DESERT_CAPS = arr.slice(); showDesert(); }
window.setDesertView = setDesertView; window.toggleDesertCap = toggleDesertCap; window.setDesertCaps = setDesertCaps;
async function showDesertTable(){
  $("desert-view").innerHTML = `<div class="empty">Loading the gap map…</div>`;
  const g = await (await fetch("/api/desert")).json();
  renderDesert(g);
}
async function showDesertMap(){
  $("desert-view").innerHTML = `<div class="empty">Plotting districts…</div>`;
  if(DESERT_CAPS.length===0){
    const g = await (await fetch("/api/desertmap?capability=any")).json();
    g.capLabel = "any capability"; g.drillCap = "";
    renderDesertMap(g); return;
  }
  // combine the selected capabilities: a district is a GAP if it's a gap in ANY of them
  const results = await Promise.all(DESERT_CAPS.map(c=>fetch("/api/desertmap?capability="+encodeURIComponent(c)).then(r=>r.json())));
  const byDist = {};
  results.forEach((g,idx)=>{
    if(!g || !g.available) return;
    const cap = DESERT_CAPS[idx];
    (g.districts||[]).forEach(d=>{
      const e = byDist[d.district] || (byDist[d.district] = {district:d.district, state:d.state, lat:d.lat, lon:d.lon, n_fac:d.n_fac, perCap:{}, trusted:0, n_scored:0});
      e.perCap[cap] = d.status; e.trusted += d.trusted; e.n_scored += d.n_scored;
    });
  });
  const districts = Object.values(byDist).map(d=>{
    const sts = Object.values(d.perCap);
    d.status = sts.includes('gap') ? 'gap' : (sts.includes('served') ? 'served' : 'datapoor');
    return d;
  });
  renderDesertMap({available:true, districts, capLabel: DESERT_CAPS.map(c=>c.toUpperCase()).join(' + '), drillCap: DESERT_CAPS[0]});
}
function districtDrill(district, cap){
  activate("trust");
  if(cap && cap!=='any') setFocus({capability:cap});
  $("q").value = district; $("state").value = ""; $("capability").value = (cap && cap!=='any') ? cap : ""; $("signal").value = "";
  updateHint(); loadFacilities(); window.scrollTo(0,0);
}
window.districtDrill = districtDrill;
let _leaflet = null;
function renderDesertMap(g){
  if(!g.available){ $("desert-view").innerHTML = `<div class="empty">District map needs the PIN bridge — run load_pincode.py.</div>`; return; }
  const ds = (g.districts||[]).filter(d=>d.lat&&d.lon);
  const col={served:'#2fa37a', gap:'#e0564f', datapoor:'#94a3b8'};
  const order={datapoor:0, served:1, gap:2};   // draw gaps/served on top of grey
  ds.sort((a,b)=>order[a.status]-order[b.status]);
  const counts={served:0, gap:0, datapoor:0}; ds.forEach(d=>counts[d.status]++);
  const radius=d=>Math.max(3, Math.min(18, 2+Math.sqrt(d.n_fac)*1.2));
  const drillCap = g.drillCap!==undefined ? g.drillCap : (g.capability||"");
  const tip=d=>{
    const head = `${d.district}${d.state?', '+d.state:''}`;
    if(d.perCap){
      const gaps = Object.keys(d.perCap).filter(c=>d.perCap[c]==='gap');
      if(gaps.length) return `${head} — GAP in ${gaps.join(', ').toUpperCase()}`;
      return `${head} — ${d.status==='served'?'trusted supply':'too few scored'} · ${d.n_fac} facilities`;
    }
    return `${head} — ` + (d.status==='served' ? `${d.trusted} trusted of ${d.n_fac} facilities`
            : (d.status==='gap' ? `GAP — 0 trusted of ${d.n_scored} evaluated` : `${d.n_fac} facilities · too few scored`));
  };
  const capLbl = g.capLabel || (g.capability==='any' ? 'any capability' : (g.capability||'').toUpperCase());
  const legend = `
    <p class="legend">
      <span class="dot2" style="background:${col.served}"></span> trusted supply (${counts.served})
      <span class="dot2" style="background:${col.gap}"></span> confirmed gap (${counts.gap})
      <span class="dot2" style="background:${col.datapoor}"></span> too few scored (${counts.datapoor})
      <span class="muted">· ${ds.length} districts · bubble = # facilities · <b>${capLbl}</b> · click to drill in</span>
    </p>`;
  if(window.L){                                   // real geographic map: color-coded deserts on OSM tiles
    $("desert-view").innerHTML = legend + `<div id="dmap" class="dmap"></div>`;
    if(_leaflet){ try{ _leaflet.remove(); }catch(e){} _leaflet=null; }
    const map = L.map('dmap', {scrollWheelZoom:false});
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {maxZoom:11, attribution:'© OpenStreetMap'}).addTo(map);
    ds.forEach(d=>{
      L.circleMarker([d.lat, d.lon], {radius:radius(d), color:'#fff', weight:0.7, fillColor:col[d.status], fillOpacity:0.82})
        .bindTooltip(tip(d)).on('click', ()=>districtDrill(d.district, drillCap)).addTo(map);
    });
    const b = ds.length ? L.latLngBounds(ds.map(d=>[d.lat, d.lon])) : null;
    if(b) map.fitBounds(b, {padding:[16,16]}); else map.setView([22.6, 81], 4);
    _leaflet = map;
    setTimeout(()=>{ try{ map.invalidateSize(); if(b) map.fitBounds(b, {padding:[16,16]}); }catch(e){} }, 150);
  } else {                                        // SVG fallback (no tiles / Leaflet blocked)
    const W=540, H=600, LAT0=6, LAT1=37, LON0=68, LON1=98;
    const X=lon=>(lon-LON0)/(LON1-LON0)*W, Y=lat=>(LAT1-lat)/(LAT1-LAT0)*H;
    const dots = ds.map(d=>`<circle cx="${X(d.lon).toFixed(1)}" cy="${Y(d.lat).toFixed(1)}" r="${radius(d).toFixed(1)}" fill="${col[d.status]}" fill-opacity="0.8" stroke="#fff" stroke-width="0.5" onclick="districtDrill('${esc(d.district).replace(/'/g,'')}','${esc(drillCap)}')"><title>${esc(tip(d))}</title></circle>`).join("");
    $("desert-view").innerHTML = legend + `<div class="mapwrap"><svg viewBox="0 0 ${W} ${H}" class="desertmap" preserveAspectRatio="xMidYMid meet">${dots}</svg></div>`;
  }
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
    return `<div class="gaprow" onclick="openNetwork('${x.capability}','${esc(x.state).replace(/'/g,'')}')">
       ${rb} <b style="text-transform:capitalize">${esc(x.capability)}</b> in ${esc(x.state)}
       <span class="muted"> — ${x.trusted} of ${x.n_scored} evaluated trusted (${pct(x.trusted_rate)})</span>${burden}
       <span class="gaprow-go">⇄ examine the network →</span></div>`;
  }).join("");
  $("desert-view").innerHTML = `
    <p class="legend">
      <span class="cell served" style="background:hsl(157 47% 66%)">&nbsp;</span><span class="cell served" style="background:hsl(157 47% 40%)">&nbsp;</span> thin → robust trusted supply
      <span class="cell gap">&nbsp;</span> confirmed gap
      <span class="cell datapoor">&nbsp;</span> too little data (need ≥${g.min_coverage})
      <span class="muted">· <b>need</b> = NFHS-5 health burden (${g.demand_states} states matched)</span>
    </p>
    <div class="heatwrap"><table class="heat"><thead><tr>${head}</tr></thead><tbody>${rows}</tbody></table></div>
    <div class="evidence-lbl" style="margin:16px 16px 6px">Highest-risk shortfalls — health burden × thin trusted supply · <b>click to examine the region's care network →</b></div>
    ${risks || '<div class="muted" style="padding:0 16px 14px">No demand-ranked shortfalls yet — more facilities need scoring.</div>'}`;
}
function drill(state, cap){
  activate("trust");
  if(state||cap) setFocus({region:state||FOCUS.region, capability:cap||FOCUS.capability});
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
  document.querySelectorAll(".fac").forEach(e=>e.classList.toggle("sel", (e.getAttribute("onclick")||"").includes(id)));
  $("fac-detail").innerHTML = `<div class="empty">Loading facility…</div>`;
  const d = await (await fetch("/api/facility/"+encodeURIComponent(id))).json();
  if(!d.facility){ $("fac-detail").innerHTML = `<div class="empty">Facility not found.</div>`; return; }
  const f = d.facility;
  _curFacName = f.name || "";
  setFocus(!FOCUS.region && f.state ? {facility:{id,name:_curFacName}, region:f.state} : {facility:{id,name:_curFacName}});
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
      <button class="btn ghost" onclick="shortlistFac(event,'${esc(id)}')">★ Add to shortlist</button>
    </div>
    <div class="xscale">
      <span class="xscale-lbl">Take this further →</span>
      <button class="xbtn pat" onclick="referFrom()">✦ Refer a patient from here</button>
      <button class="xbtn net" onclick="openNetwork($('capability').value||'icu','${esc((f.state||'').replace(/'/g,''))}')">⇄ See its care network</button>
    </div>
    ${historyBlock(d.history)}`;
}
// the saved-work round-trip: show what this user has saved/revised on this facility
function historyBlock(history){
  const rows=(history||[]).map(h=>{
    const when = h.created_at ? new Date(h.created_at*1000).toLocaleDateString(undefined,{month:'short',day:'numeric'}) : '';
    const ic = {note:'📝', decision:'✅', override:'✎'}[h.action] || '·';
    const what = h.action==='override'
      ? `revised <b style="text-transform:capitalize">${esc(h.capability||'')}</b> → ${badge(h.new_signal||'none')}`
      : esc(h.body||'');
    return `<div class="hist-row"><span class="hist-ic">${ic}</span>
      <div class="hist-b">${what}<div class="muted">${esc(h.user_id||'planner')} · ${esc(h.action)}${when?' · '+when:''}</div></div></div>`;
  }).join("");
  return rows ? `<div class="evidence-lbl" style="margin:15px 0 5px">Your saved work on this facility · revise any signal above</div>
    <div class="hist">${rows}</div>` : "";
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
async function addNote(fid){const b=$("note").value.trim();if(!b)return;await review({action:"note",facility_id:fid,body:b});selectFacility(fid);}  // re-render → the note appears in "saved work"
async function shortlistFac(ev,fid){await review({action:"shortlist",facility_id:fid,shortlist:"default"});loadShortlist();if(ev&&ev.target){ev.target.textContent="★ Shortlisted ✓";ev.target.disabled=true;}}
// Your shortlist — saved facilities the planner can revisit and revise (remove)
async function loadShortlist(){
  const bar=$("shortlist-bar"); if(!bar) return;
  const {shortlist=[]}=await (await fetch("/api/shortlist?name=default")).json();
  if(!shortlist.length){ bar.className="shortlist-bar"; bar.innerHTML=""; return; }
  bar.className="shortlist-bar on";
  bar.innerHTML = `<span class="sl-lbl">★ Your shortlist <b>${shortlist.length}</b></span>` +
    shortlist.map(s=>`<span class="sl-chip" onclick="selectFacility('${esc(s.id)}')">${esc(s.name||'facility')}${s.city?` <span class="muted">${esc(s.city)}</span>`:''}<b class="sl-x" title="remove" onclick="event.stopPropagation();removeShortlist('${esc(s.id)}')">×</b></span>`).join("");
}
async function removeShortlist(fid){ await review({action:"unshortlist",facility_id:fid,shortlist:"default"}); loadShortlist(); }
window.removeShortlist=removeShortlist;
// cross-scale handoff: Facility (Trust Desk) → Patient (Referral Copilot) — refer FROM the open facility
function referFrom(){ if(!_curFacName) return; activate('copilot'); $('cp-from').value=_curFacName; $('cp-q').value=''; window.scrollTo(0,0); $('cp-q').focus(); }
window.referFrom=referFrom;

// ---- Track 3: Referral Copilot (governed multi-agent mesh) ---------------- //
async function runCopilot(){
  const q = $("cp-q").value.trim(); if(!q) return;
  const from = ($("cp-from")?.value||"").trim();
  activate("copilot");
  showLoading("copilot-body", from?["Identifying the referring provider","Retrieving from Lakebase","Scrutinizing the evidence","Governing the result","Writing the referral note"]:["Planning the need","Retrieving from Lakebase","Scrutinizing the evidence","Governing the result","Composing the referral"], "Referral Copilot");
  try{
    const r = await (await fetch("/api/copilot",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({query:q, from_facility:from})})).json();
    stopLoading(); renderCopilot(r);
  }catch(e){ stopLoading(); $("copilot-body").innerHTML = `<div class="empty">Copilot error: ${esc(e.message)}</div>`; }
}
let _referralCtx = null;
function refFromBanner(r){ return r.from_provider ? `<div class="ref-from">📋 Referring from <b>${esc(r.from_provider.name)}</b>${r.from_provider.city?` · <span class="muted">${esc(r.from_provider.city)}</span>`:''} — nearest destinations & a referral note</div>` : ""; }
function refNoteBlock(r){
  if(!r.from_provider || !r.referral_note) return "";
  _referralCtx = {from:r.from_provider.name, note:r.referral_note,
    destId:(r.shortlist&&r.shortlist[0]&&r.shortlist[0].id) || (r.ranking&&r.ranking[0]&&r.ranking[0].id) || (r.care_team&&r.care_team[0]&&r.care_team[0].facilities&&r.care_team[0].facilities[0]&&r.care_team[0].facilities[0].id) || null};
  return `<div class="evidence-lbl" style="margin:14px 16px 4px">Referral note — hand to the patient or send to the destination</div>
    <div class="ref-note">${mdLite(r.referral_note)}</div>
    <div style="padding:6px 16px 8px"><button class="btn" onclick="recordReferral(event)">✓ Record this referral</button></div>`;
}
async function recordReferral(ev){
  if(!_referralCtx) return;
  await review({action:"decision", facility_id:_referralCtx.destId, body:("Referral from "+_referralCtx.from+" — "+(_referralCtx.note||"")).slice(0,500), user_id:"provider"});
  if(ev&&ev.target){ ev.target.textContent="✓ Recorded to Lakebase"; ev.target.disabled=true; }
}
window.recordReferral=recordReferral;
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
    ${refFromBanner(r)}
    <div class="cp-plan"><b>Care team:</b> ${chips}</div>
    <div class="evidence-lbl" style="margin:12px 16px 4px">How the agent worked</div>
    <div class="cp-trace">${trace}</div>
    ${banner}
    ${r.answer?`<div class="cp-answer">${esc(r.answer)}</div>`:""}
    <div class="evidence-lbl" style="margin:14px 16px 4px">The care team — nearest provider for each specialty · click any for cited evidence</div>
    <div class="ct-grid">${roles}</div>
    ${refNoteBlock(r)}`;
}
function renderProcedure(r){
  const trace=(r.trace||[]).map(traceStep).join("");
  const rows=(r.ranking||[]).map((x,i)=>{
    const badges=(x.badges||[]).map(b=>`<span class="pr-badge${/NABH|JCI/.test(b)?' acc':''}">${esc(b)}</span>`).join("");
    const claims=(x.claims||[]).map(c=>`<span class="pr-claim" title="self‑reported · unverified marketing figure">⚠ ${esc(c.text)}</span>`).join("");
    return `<div class="pr-row" onclick="selectFacility('${esc(x.id)}')">
      <div class="pr-rank">${i+1}</div>
      <div class="pr-main">
        <div class="pr-top"><b>${esc(x.name||'')}</b>
          <span class="muted">${esc([x.city,x.state].filter(Boolean).join(', '))}${x.km!=null?' · '+x.km+' km':''}</span>
          <span class="pr-score" title="capability + accreditation proxy score (not an outcome)">proxy ${x.score}</span></div>
        <div class="pr-badges">${badges||'<span class="muted">no quality signals on record</span>'}</div>
        ${x.evidence?`<div class="pr-ev">"${esc(x.evidence)}"</div>`:""}
        ${x.caution?`<div class="pr-caution">⚠ ${esc(x.caution)}</div>`:""}
        ${claims?`<div class="pr-claims">${claims}</div>`:""}
      </div></div>`;
  }).join("");
  const where=r.anchored?'nearest in range':((r.plan&&r.plan.location)?('in '+r.plan.location):'nationwide');
  $("copilot-body").innerHTML=`
    ${refFromBanner(r)}
    <div class="cp-plan"><b>Procedure referral:</b> <span class="chip">${esc(r.procedure||'')}</span> · <b>${(r.n_matched||0).toLocaleString()}</b> facilities list it · ${esc(where)}</div>
    <div class="evidence-lbl" style="margin:12px 16px 4px">How the agent worked — match → score (accreditation + capability) → flag self‑reported claims → rank</div>
    <div class="cp-trace">${trace}</div>
    ${r.answer?`<div class="cp-answer">${esc(r.answer)}</div>`:""}
    <div class="pr-caveat">⚖ <b>Ranked by a capability + accreditation proxy — not verified outcomes.</b> ${esc(r.legend||'')}</div>
    <div class="evidence-lbl" style="margin:14px 16px 4px">Ranked destinations for ${esc(r.procedure||'')} · click any for full cited evidence</div>
    ${rows||'<div class="empty">No facilities list this procedure here. Try a wider area or drop the referring facility.</div>'}
    ${refNoteBlock(r)}`;
}
function renderCopilot(r){
  if(r && r.mode==="care_team"){ return renderCareTeam(r); }
  if(r && r.mode==="procedure"){ return renderProcedure(r); }
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
    ${refFromBanner(r)}
    <div class="cp-plan"><b>Agent plan:</b> ${chips||'—'} · retrieved <b>${r.n_candidates||0}</b> evidence-backed candidates from Lakebase</div>
    <div class="evidence-lbl" style="margin:12px 16px 4px">How the agent worked — plan → retrieve → scrutinize → challenge → govern → compose</div>
    <div class="cp-trace">${trace}</div>
    ${r.answer?`<div class="cp-answer">${esc(r.answer)}</div>`:""}
    ${demand}
    <div class="evidence-lbl" style="margin:14px 16px 4px">Recommended — vetted &amp; governed · click any for full cited evidence</div>
    ${sl||'<div class="empty">No evidence-backed matches survived governance. Try a wider area.</div>'}
    ${bl?`<div class="evidence-lbl" style="margin:16px 16px 4px">Not recommended — blocked by policy</div>${bl}`:''}
    ${refNoteBlock(r)}`;
}
window.cpEx=(q)=>{$("cp-q").value=q;runCopilot();};
$("cp-ask").onclick=runCopilot;
$("cp-q").addEventListener("keydown",e=>{if(e.key==="Enter")runCopilot();});

// ---- Care Network: coordinated Copilot instances → the system view -------- //
let _nwLoaded=false, _nwLeaflet=null, _nwRoute=null;
async function showNetwork(){
  if(_nwLoaded) return;                 // preserve the current result when tabbing back
  _nwLoaded=true;
  $("nw-cap").onchange=()=>loadNetworkStates(true);
  await loadNetworkStates(true);        // populate states (worst funnel first) + auto-run
}
async function loadNetworkStates(autorun){
  const cap=$("nw-cap").value, sel=$("nw-state");
  sel.innerHTML=`<option value="">loading…</option>`;
  const {states=[]}=await (await fetch("/api/network/states?capability="+encodeURIComponent(cap))).json();
  sel.innerHTML = states.length
    ? states.map(s=>`<option value="${esc(s.state)}">${esc(s.state)} — ${s.n_referrer}→${s.n_dest} (${s.ratio}:1)</option>`).join("")
    : `<option value="">no funnel data</option>`;
  if(autorun && states.length){ sel.value=states[0].state; runNetwork(); }
}
// cross-scale handoff: Population (Gap map) → Network (Care Network) for a specific state+capability
async function openNetwork(cap, state){
  activate('network'); _nwLoaded = true;            // suppress the auto-run-worst
  $('nw-cap').onchange = ()=>loadNetworkStates(true);
  $('nw-cap').value = CAPS.includes(cap) ? cap : 'icu';
  await loadNetworkStates(false);                    // populate the dropdown, don't auto-run
  if(state){
    const sel = $('nw-state');
    if(![...sel.options].some(o=>o.value===state)){ const o=document.createElement('option'); o.value=state; o.textContent=state; sel.insertBefore(o, sel.firstChild); }
    sel.value = state;
  }
  setFocus({region:state||FOCUS.region, capability:$('nw-cap').value});
  window.scrollTo(0,0); runNetwork();
}
window.openNetwork = openNetwork;
async function runNetwork(){
  const cap=$("nw-cap").value, state=$("nw-state").value;
  if(!state){ $("nw-body").innerHTML=`<div class="empty">No state selected.</div>`; return; }
  showLoading("nw-body", ["Coordinating a Copilot instance per facility","Routing each to its nearest trusted "+cap.toUpperCase(),"Aggregating the load — finding the chokepoints","Cross‑checking the top chokepoint's evidence","Writing the systemic‑risk finding"], "Care‑Network fleet");
  try{
    const r=await (await fetch("/api/network",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({capability:cap,state})})).json();
    stopLoading(); renderNetwork(r);
  }catch(e){ stopLoading(); $("nw-body").innerHTML=`<div class="empty">Network error: ${esc(e.message)}</div>`; }
}
window.runNetwork=runNetwork;
function nwTrustBadge(t){ return `<span class="sig ${t==='strong'?'strong':'partial'}">${t} evidence</span>`; }
function renderNetwork(r){
  const cap=(r.capability||'').toUpperCase();
  const trace=(r.trace||[]).map(traceStep).join("");
  const head=`<div class="cp-plan"><b>${cap} referral network · ${esc(r.state||'')}</b> — <b>${(r.n_referrer||0).toLocaleString()}</b> facilities with no trusted ${cap} route to <b>${r.n_dest||0}</b> trusted destination${r.n_dest===1?'':'s'}${(r.n_referrer_plotted<r.n_referrer)?` · plotting nearest ${r.n_referrer_plotted}`:''}</div>`;
  const finding = r.finding ? `<div class="nw-finding"><div class="nw-finding-h">⚠ Systemic risk — what the coordinated view sees</div>${esc(r.finding)}</div>` : "";
  if(r.no_destination){
    $("nw-body").innerHTML = head + `<div class="evidence-lbl" style="margin:12px 16px 4px">How the fleet worked</div><div class="cp-trace">${trace}</div>${finding}`;
    return;
  }
  const bn=(r.bottlenecks||[]).map((b,i)=>`
    <div class="nw-row ${b.spof?'spof':''}" onclick="selectFacility('${esc(b.id)}')">
      <div class="nw-deg"><b>${b.in_degree}</b><span>refs</span></div>
      <div class="nw-main">
        <div class="nw-top"><span class="nw-rank">#${i+1}</span><b>${esc(b.name||'')}</b>
          <span class="muted">${esc(b.city||'')}${b.avg_km!=null?' · avg '+b.avg_km+' km':''}</span>
          ${nwTrustBadge(b.trust)}<span class="nw-share">${b.share}%</span></div>
        ${b.why?`<div class="nw-why">⚠ ${esc(b.why)}</div>`:''}
        <div class="nw-xcheck">🏥 trust‑check this destination →</div>
      </div></div>`).join("");
  $("nw-body").innerHTML = head +
    `<div class="evidence-lbl" style="margin:12px 16px 4px">How the fleet worked — coordinate → fan‑out → aggregate → skeptic → synthesize</div>
     <div class="cp-trace">${trace}</div>
     ${finding}
     <div id="nw-map" class="dmap nw-map"></div>
     <p class="legend" style="padding:2px 16px">
       <span class="dot2" style="background:#2fa37a"></span> trusted (strong)
       <span class="dot2" style="background:#d97706"></span> partial evidence
       <span class="dot2" style="background:#fff;border:2px solid #dc2626"></span> single‑point‑of‑failure
       <span class="muted">· bubble = referral load · grey = referring facility · click a chokepoint for its evidence</span></p>
     <div class="evidence-lbl" style="margin:14px 16px 4px">Chokepoints — the destinations the region depends on · <b>click any to trust‑check it →</b></div>
     ${bn}
     <div class="nw-act">
       <span class="nw-act-lbl">Act on this →</span>
       <button class="btn ghost" onclick="runRoute()">⤳ Balance the load</button>
       <button class="btn ghost" onclick="runCircuit()">🗓 Provider circuit</button>
       <button class="btn ghost" onclick="runSiting()">⊕ Add capacity</button>
     </div>
     <div id="nw-routing"></div><div id="nw-circuit"></div><div id="nw-siting"></div>`;
  drawNetworkMap(r);
}
async function runRoute(){
  const cap=$("nw-cap").value, state=$("nw-state").value, el=$("nw-routing"); if(!el) return;
  showLoading("nw-routing", ["Modeling naive nearest‑routing","Capping each destination by fair‑share capacity","Re‑routing demand off the chokepoint","Writing the routing plan"], "Dispatch optimizer");
  el.scrollIntoView({behavior:"smooth",block:"center"});
  try{ const r=await (await fetch("/api/route",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({capability:cap,state})})).json(); stopLoading(); renderRoute(r); }
  catch(e){ stopLoading(); el.innerHTML=`<div class="empty">Routing error: ${esc(e.message)}</div>`; }
}
async function runCircuit(){
  const cap=$("nw-cap").value, state=$("nw-state").value, el=$("nw-circuit"); if(!el) return;
  showLoading("nw-circuit", ["Ranking facilities by isolation","Routing a nearest‑neighbour circuit","Scheduling the stops into days","Writing the circuit plan"], "Circuit scheduler");
  el.scrollIntoView({behavior:"smooth",block:"center"});
  try{ const r=await (await fetch("/api/circuit",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({capability:cap,state})})).json(); stopLoading(); renderCircuit(r); }
  catch(e){ stopLoading(); el.innerHTML=`<div class="empty">Circuit error: ${esc(e.message)}</div>`; }
}
window.runRoute=runRoute; window.runCircuit=runCircuit;
function renderRoute(r){
  const cap=(r.capability||'').toUpperCase();
  if(r.no_destination || !(r.nodes||[]).length){ $("nw-routing").innerHTML=`<div class="empty" style="margin:12px 16px">${esc(r.recommendation||'No credible destinations to route across.')}</div>`; return; }
  const trace=(r.trace||[]).map(traceStep).join("");
  const b=r.before, a=r.after, max=Math.max(b.max_load,1);
  if(r.no_relief){
    $("nw-routing").innerHTML=`
      <section class="panel" style="margin:14px 16px">
        <h2>⤳ Balance the load — capacity‑aware routing</h2>
        <div class="body">
          <div class="cp-trace" style="margin-left:0">${trace}</div>
          <div class="nw-rec warn"><div class="nw-rec-h">⤳ Routing can't fix this one</div>${esc(r.recommendation||'')}</div>
        </div>
      </section>`;
    return;
  }
  const bars=(r.nodes||[]).slice(0,8).map(n=>`
    <div class="rt-row">
      <span class="rt-name">${esc(n.name)} <span class="muted">${esc(n.city||'')}</span></span>
      <span class="rt-bars">
        <span class="rt-track"><i class="rt-naive" style="width:${Math.round(100*n.naive/max)}%"></i></span>
        <span class="rt-track"><i class="rt-bal" style="width:${Math.round(100*n.balanced/max)}%"></i></span>
      </span>
      <span class="rt-num"><b>${n.naive}</b>→<b class="g">${n.balanced}</b></span>
    </div>`).join("");
  $("nw-routing").innerHTML=`
    <section class="panel" style="margin:14px 16px">
      <h2>⤳ Balance the load — capacity‑aware routing</h2>
      <div class="body">
        <div class="cp-trace" style="margin-left:0">${trace}</div>
        ${r.recommendation?`<div class="nw-rec"><div class="nw-rec-h">⤳ Routing plan</div>${esc(r.recommendation)}</div>`:""}
        <div class="rt-head">Peak load <b class="r">${b.max_load}</b> → <b class="g">${a.max_load}</b> · cap ${r.cap}/destination · ${a.rerouted} rerouted · avg travel ${b.avg_km}→${a.avg_km} km</div>
        <div class="evidence-lbl" style="margin:10px 0 6px">Load per destination — <span style="color:var(--weak)">naive nearest</span> vs <span style="color:var(--strong)">balanced</span></div>
        ${bars}
        <div class="muted" style="margin-top:10px;font-size:12px">Routes demand across credible hospital destinations; capacity = fair share (bed counts too sparse to weight). No individual patients in the data.</div>
      </div>
    </section>`;
}
function renderCircuit(r){
  const cap=(r.capability||'').toUpperCase();
  if(r.no_destination || !(r.stops||[]).length){ $("nw-circuit").innerHTML=`<div class="empty" style="margin:12px 16px">${esc(r.recommendation||'Not enough supply/demand to schedule a circuit.')}</div>`; return; }
  const trace=(r.trace||[]).map(traceStep).join("");
  const stops=(r.stops||[]).map((s,i)=>`
    <div class="ci-row" onclick="selectFacility('${esc(s.id)}')">
      <span class="ci-day">Day ${s.day}</span>
      <span class="ci-stop"><b>${i+1}. ${esc(s.name)}</b> <span class="muted">${esc(s.city||'')}</span>
        <div class="muted">leg ${s.leg_km} km · ${s.from_care_km} km from nearest ${cap} today</div></span>
    </div>`).join("");
  $("nw-circuit").innerHTML=`
    <section class="panel" style="margin:14px 16px">
      <h2>🗓 Provider circuit — visiting ${cap} itinerary</h2>
      <div class="body">
        <div class="cp-trace" style="margin-left:0">${trace}</div>
        ${r.recommendation?`<div class="nw-rec"><div class="nw-rec-h">🗓 Scheduled circuit</div>${esc(r.recommendation)}</div>`:""}
        <div class="rt-head">From <b>${esc(r.hub.name)}</b> ${esc(r.hub.city||'')} · ${r.n_served} stops · ${r.total_km.toLocaleString()} km · ${r.days} day(s)</div>
        <div class="evidence-lbl" style="margin:10px 0 6px">Itinerary · click any stop for its record · route drawn on the map above</div>
        ${stops}
        <div class="muted" style="margin-top:10px;font-size:12px">A planned circuit over facilities + geography — no provider calendars exist to book against.</div>
      </div>
    </section>`;
  // draw the route on the network map
  if(_nwLeaflet && window.L){
    if(_nwRoute){ try{_nwRoute.forEach(l=>_nwLeaflet.removeLayer(l));}catch(e){} }
    _nwRoute=[];
    const line=L.polyline((r.geometry||[]),{color:'#7c3aed',weight:2.5,opacity:0.8,dashArray:'6 4'}).addTo(_nwLeaflet); _nwRoute.push(line);
    (r.stops||[]).forEach((s,i)=>{ const m=L.marker([s.lat,s.lon]).bindTooltip(`Day ${s.day} · stop ${i+1}: ${s.name}${s.city?', '+s.city:''}`); const cm=L.circleMarker([s.lat,s.lon],{radius:9,color:'#7c3aed',weight:2,fillColor:'#fff',fillOpacity:1}).bindTooltip(`Day ${s.day} · #${i+1} ${s.name}`).addTo(_nwLeaflet); _nwRoute.push(cm); });
    const hub=r.hub; if(hub){ const h=L.circleMarker([hub.lat,hub.lon],{radius:11,color:'#7c3aed',weight:3,fillColor:'#7c3aed',fillOpacity:0.6}).bindTooltip(`Hub: ${hub.name}`).addTo(_nwLeaflet); _nwRoute.push(h); }
    try{ _nwLeaflet.invalidateSize(); }catch(e){}
  }
}
async function runSiting(){
  const cap=$("nw-cap").value, state=$("nw-state").value, el=$("nw-siting");
  if(!el) return;
  showLoading("nw-siting", ["Evaluating every existing facility as a candidate site","Simulating re‑routing — travel saved + load relieved","Ranking the highest‑impact intervention","Writing the siting recommendation"], "Siting optimizer");
  el.scrollIntoView({behavior:"smooth",block:"center"});
  try{
    const r=await (await fetch("/api/siting",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({capability:cap,state})})).json();
    stopLoading(); renderSiting(r);
  }catch(e){ stopLoading(); el.innerHTML=`<div class="empty">Siting error: ${esc(e.message)}</div>`; }
}
window.runSiting=runSiting;
function renderSiting(r){
  const cap=(r.capability||'').toUpperCase();
  const trace=(r.trace||[]).map(traceStep).join("");
  const sites=(r.sites||[]);
  if(!sites.length){ $("nw-siting").innerHTML=`<div class="empty" style="margin:12px 16px">${esc(r.recommendation||'No high‑impact site found.')}</div>`; return; }
  const rec=r.recommendation?`<div class="nw-rec"><div class="nw-rec-h">⊕ Highest‑impact intervention</div>${esc(r.recommendation)}</div>`:"";
  const rows=sites.map((s,i)=>`
    <div class="nw-row site ${i===0?'best':''}" onclick="selectFacility('${esc(s.id)}')">
      <div class="nw-deg"><b>${s.captured}</b><span>closer</span></div>
      <div class="nw-main">
        <div class="nw-top"><span class="nw-rank">#${i+1}</span><b>${esc(s.name||'')}</b>
          <span class="muted">${esc(s.city||'')}${s.beds?' · '+s.beds+' beds':''}</span>
          <span class="nw-share">${s.km_saved_avg} km/ea</span></div>
        <div class="nw-why pos">✓ ${s.captured} facilities gain a closer ${cap} · ${(s.km_saved_total||0).toLocaleString()} km saved total${s.relieves_choke?` · pulls ${s.relieves_choke} off the chokepoint`:''}</div>
      </div></div>`).join("");
  $("nw-siting").innerHTML=`
    <section class="panel" style="margin:14px 16px">
      <h2>⊕ Where to add capacity — counterfactual siting</h2>
      <div class="body">
        <div class="cp-trace" style="margin-left:0">${trace}</div>
        ${rec}
        <div class="evidence-lbl" style="margin:12px 0 4px">Highest‑impact sites to resource next · click any for its record</div>
        ${rows}
      </div>
    </section>`;
  if(_nwLeaflet && window.L){           // drop "add here" markers on the network map
    sites.slice(0,3).forEach((s,i)=>{
      L.circleMarker([s.lat,s.lon],{radius:i===0?11:8,color:'#2563eb',weight:2.6,fillColor:'#2563eb',fillOpacity:i===0?0.55:0.32})
        .bindTooltip(`⊕ Add ${cap} here — ${s.name}${s.city?', '+s.city:''}: ${s.captured} facilities closer`).addTo(_nwLeaflet);
    });
    try{ _nwLeaflet.invalidateSize(); }catch(e){}
  }
}
function drawNetworkMap(r){
  const el=$("nw-map"); if(!el) return;
  if(!window.L){ el.innerHTML=`<div class="empty">Map needs Leaflet.</div>`; return; }
  if(_nwLeaflet){ try{_nwLeaflet.remove();}catch(e){} _nwLeaflet=null; }
  const map=L.map('nw-map',{scrollWheelZoom:false});
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:11,attribution:'© OpenStreetMap'}).addTo(map);
  const pts=[];
  (r.edges||[]).forEach(e=>{
    L.polyline([[e.flat,e.flon],[e.tlat,e.tlon]],{color:'#94a3b8',weight:0.5,opacity:0.22}).addTo(map);
    L.circleMarker([e.flat,e.flon],{radius:2.2,weight:0,fillColor:'#94a3b8',fillOpacity:0.5}).addTo(map);
    pts.push([e.flat,e.flon]);
  });
  const col=t=>t==='strong'?'#2fa37a':'#d97706';
  (r.nodes||[]).filter(n=>n.in_degree>0).forEach(n=>{
    const rad=Math.max(5,Math.min(26,4+Math.sqrt(n.in_degree)*2.4));
    L.circleMarker([n.lat,n.lon],{radius:rad,color:n.spof?'#dc2626':'#fff',weight:n.spof?2.6:0.8,fillColor:col(n.trust),fillOpacity:0.85})
      .bindTooltip(`${n.name}${n.city?', '+n.city:''} — ${n.in_degree} referrals (${n.share}%) · ${n.trust} evidence${n.spof?' · ⚠ '+(n.why||'single point of failure'):''}`)
      .on('click',()=>selectFacility(n.id)).addTo(map);
    pts.push([n.lat,n.lon]);
  });
  const b=pts.length?L.latLngBounds(pts):null;
  if(b) map.fitBounds(b,{padding:[18,18]}); else map.setView([22.6,81],4);
  _nwLeaflet=map;
  setTimeout(()=>{ try{ map.invalidateSize(); if(b) map.fitBounds(b,{padding:[18,18]}); }catch(e){} },150);
}

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
  $("ph-body").innerHTML = `<div class="empty">${m==='immun'
    ? 'Leave the district blank and hit Plan campaign to rank the worst‑immunized districts that have local supply — or name one.'
    : 'Name a district + disease, then Plan response — the agent designates isolation facilities from local capacity.'}</div>`;
}
window.setPhMode = setPhMode;
function setPhControls(){
  const back = `<button class="ph-back" onclick="showPublicHealth()">‹ all agents</button>`;
  if(PH_MODE==='immun')
    $("ph-controls").innerHTML = `<div class="ph-bar">${back}<input id="ph-region" placeholder="District (optional — blank = worst nationwide)"/><button class="btn" onclick="runImmun()">💉 Plan campaign</button></div>`;
  else if(PH_MODE==='outbreak')
    $("ph-controls").innerHTML = `<div class="ph-bar">${back}<input id="ph-oregion" placeholder="District (e.g. Jhansi)"/><input id="ph-disease" placeholder="Disease (e.g. measles)"/><button class="btn" onclick="runOutbreak()">🦠 Plan response</button></div>`;
  else
    $("ph-controls").innerHTML = `<div class="ph-bar">${back}</div>`;
}
// Public Health landing — a chooser of the three population-scale agents + a live NFHS at-a-glance
async function showPublicHealth(){
  document.querySelectorAll('[data-phm]').forEach(b=>b.classList.remove('active'));
  $("ph-controls").innerHTML = "";
  $("ph-body").innerHTML = `
    <div class="ph-home">
      <div id="ph-glance" class="ph-glance"></div>
      <div class="ph-cards">
        <div class="ph-card" onclick="setPhMode('immun')">
          <div class="ph-card-i">💉</div><h3>Immunization campaign</h3>
          <p>Find the lowest‑coverage districts that <b>also have local supply</b> to run it — then draft the campaign + health‑department referral.</p>
          <span class="ph-go">Plan a campaign →</span>
        </div>
        <div class="ph-card" onclick="setPhMode('burden')">
          <div class="ph-card-i">📊</div><h3>Disease burden</h3>
          <p>Benchmark prevalence — diabetes, hypertension, anaemia, stunting — by district vs the national baseline, and <b>escalate the worst</b> to WHO / UNICEF / government.</p>
          <span class="ph-go">See the benchmarks →</span>
        </div>
        <div class="ph-card" onclick="setPhMode('outbreak')">
          <div class="ph-card-i">🦠</div><h3>Outbreak response</h3>
          <p>Given a district + disease, <b>designate isolation facilities</b> from local capacity and brief each provider with targeted outreach.</p>
          <span class="ph-go">Plan a response →</span>
        </div>
      </div>
    </div>`;
  try{
    const b = await (await fetch('/api/publichealth/benchmarks')).json();
    const g = $("ph-glance");
    if(b && b.available && g){
      g.innerHTML = `<span class="phg-lbl">NFHS‑5 national baselines</span>` +
        (b.conditions||[]).map(c=>`<span class="phg"><b>${c.national}%</b> ${esc((c.label.split('—')[0]||'').replace(/\s*\(.*$/,'').trim())}</span>`).join("");
    }
  }catch(e){}
}
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
let _outbreak = {region:"", disease:""};
function renderOutbreak(r){
  _outbreak = {region:r.region||"", disease:r.disease||""};
  const trace = (r.trace||[]).map(traceStep).join("");
  const sup = (r.profile&&r.profile.supply)||{};
  const providers = (r.providers||[]).map(p=>`
    <div class="prov-row">
      <span><b>${esc(p.name||'')}</b> <span class="muted">${esc(p.facility_type||'')}${p.total_beds?' · '+p.total_beds+' beds':''}${p.n_doctors?' · '+p.n_doctors+' physicians':''}</span></span>
      <button class="bm-esc" style="color:var(--blue);background:var(--blue-soft);border-color:#cdddf5" onclick="runProviderOutreach('${esc(p.facility_id)}')">📣 Brief this provider</button>
    </div>`).join("");
  $("ph-body").innerHTML = `
    <div class="cp-plan"><b>Outbreak signal:</b> ${esc(r.disease||'disease')} in <b>${esc(r.region||'')}</b> · local capacity: ${sup.hospitals||0} hospitals · ${sup.beds||0} beds · ${sup.physicians||0} physicians</div>
    <div class="evidence-lbl" style="margin:12px 16px 4px">Agent — assess → protocol</div>
    <div class="cp-trace">${trace}</div>
    <div class="evidence-lbl" style="margin:12px 16px 4px">Isolation &amp; containment protocol</div>
    <div class="ph-plan">${mdLite(r.plan||'')}</div>
    ${providers?`<div class="evidence-lbl" style="margin:16px 16px 4px">Providers in ${esc(r.region||'')} — activate each with a targeted outreach</div>
      <div style="padding:0 16px">${providers}</div>`:''}
    <div id="provider-outreach"></div>`;
}
async function runProviderOutreach(fid){
  const el=$("provider-outreach"); if(!el) return;
  showLoading("provider-outreach", ["Profiling the provider","Drafting the outreach (alert · resources · CHWs)"], "Provider outreach agent");
  el.scrollIntoView({behavior:"smooth", block:"center"});
  try{
    const r=await (await fetch("/api/publichealth/provider_outreach",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({facility_id:fid, region:_outbreak.region, disease:_outbreak.disease})})).json();
    stopLoading(); renderProviderOutreach(r);
  }catch(e){ stopLoading(); el.innerHTML=`<div class="empty">Outreach error: ${esc(e.message)}</div>`; }
}
window.runProviderOutreach = runProviderOutreach;
function renderProviderOutreach(r){
  const trace=(r.trace||[]).map(traceStep).join("");
  const c=r.card||{};
  const meta=[c.type, c.beds?c.beds+' beds':null, c.doctors?c.doctors+' physicians':null, (c.services&&c.services.length)?c.services.join(', '):null].filter(Boolean).join(' · ');
  $("provider-outreach").innerHTML=`
    <section class="panel" style="margin-top:14px">
      <h2>📣 Provider outreach — ${esc(c.name||'')}</h2>
      <div class="body">
        <div class="cp-plan">${esc(meta)}</div>
        <div class="cp-trace">${trace}</div>
        <div class="ph-plan">${mdLite(r.plan||'')}</div>
      </div>
    </section>`;
  $("provider-outreach").scrollIntoView({behavior:"smooth", block:"start"});
}

// ---- Ask Care Compass: the app-wide assistant (every page, over the shared tools) -- //
const ASST_SUGG = {
  home: ["Where is the worst ICU gap?", "Balance the ICU load in Madhya Pradesh", "Disease burden benchmarks"],
  desert: ["Where is the worst gap right now?", "Map Bihar's ICU network", "Disease burden benchmarks"],
  network: ["Balance the load", "Where should I add capacity?", "Schedule a provider circuit"],
  trust: ["Is this facility's ICU claim credible?", "Refer a patient from here", "Map its care network"],
  copilot: ["Knee replacement near Pune", "Emergency + ICU near Patna", "Diabetic patient, 3 visits this month"],
  publichealth: ["Plan a campaign for the worst‑immunized district", "Disease burden benchmarks", "Contain a measles outbreak in Jhansi"],
  readiness: ["What needs human review?", "Where is the worst gap?", "Disease burden benchmarks"],
};
const PANE_LABEL = {home:'Overview',desert:'Gap map',network:'Care Network',trust:'Trust Desk',copilot:'Referral Copilot',publichealth:'Public Health',readiness:'Data Readiness'};
function curPane(){ return (document.querySelector('.pane.active')?.id||'pane-home').replace('pane-',''); }
function toggleAsst(force){
  const p=$("asst-panel"); const open = force===undefined ? !p.classList.contains('open') : !!force;
  p.classList.toggle('open', open);
  if(open){ updateAsstCtx(); $("asst-q").focus(); }
}
window.toggleAsst=toggleAsst;
function updateAsstCtx(){
  const pane=curPane(), f=FOCUS;
  const bits=[`<span class="actx-pane">on ${esc(PANE_LABEL[pane]||pane)}</span>`];
  if(f.region) bits.push(`<span class="actx-chip">🗺 ${esc(f.region)}</span>`);
  if(f.capability) bits.push(`<span class="actx-chip">${esc(f.capability.toUpperCase())}</span>`);
  if(f.facility) bits.push(`<span class="actx-chip">🏥 ${esc(f.facility.name)}</span>`);
  $("asst-ctx").innerHTML = bits.join("");
  $("asst-sugg").innerHTML = (ASST_SUGG[pane]||ASST_SUGG.home).map(s=>`<span class="asugg" onclick="asstEx('${esc(s).replace(/'/g,"\\'")}')">${esc(s)}</span>`).join("");
}
function asstEx(q){ $("asst-q").value=q; askAssistant(); }
window.asstEx=asstEx;
async function askAssistant(){
  const q=$("asst-q").value.trim(); if(!q) return;
  $("asst-sugg").innerHTML="";
  $("asst-body").innerHTML = `<div class="asst-loading">✦ Thinking — routing to the right agent over the shared tools…</div>`;
  try{
    const r=await (await fetch("/api/assistant",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({query:q, focus:FOCUS, page:curPane()})})).json();
    renderAsst(r);
  }catch(e){ $("asst-body").innerHTML=`<div class="asst-hint">Assistant error: ${esc(e.message)}</div>`; }
}
window.askAssistant=askAssistant;
let _asstGoto=null;
function renderAsst(r){
  _asstGoto=r.goto||null;
  const trace=(r.trace||[]).map(traceStep).join("");
  const items=(r.items||[]).map(x=>`<div class="aitem"><b>${esc((x.capability||'').toUpperCase())}</b> in ${esc(x.state||'')} <span class="muted">— ${x.trusted} of ${x.n_scored} trusted</span></div>`).join("");
  const goBtn = r.goto ? `<button class="btn asst-go" onclick="asstGoto()">${esc(r.goto.label||'Open the full view')} →</button>` : "";
  $("asst-body").innerHTML=`
    ${r.title?`<div class="asst-rtitle">${esc(r.title)}</div>`:""}
    <div class="evidence-lbl" style="margin:8px 0 4px">How I worked — same governed tools the panes use</div>
    <div class="cp-trace" style="margin-left:0">${trace}</div>
    ${r.answer?`<div class="asst-answer">${mdLite(r.answer)}</div>`:""}
    ${items?`<div class="aitems">${items}</div>`:""}
    ${goBtn}`;
}
function asstGoto(){
  const g=_asstGoto; if(!g) return;
  if(g.focus) setFocus(g.focus);
  if(g.facility) setFocus({facility:g.facility});
  toggleAsst(false);
  if(g.view==='network') openNetwork((g.focus&&g.focus.capability)||FOCUS.capability||'icu',(g.focus&&g.focus.region)||FOCUS.region);
  else if(g.view==='copilot'){ activate('copilot'); if(g.from!==undefined) $('cp-from').value=g.from||''; if(g.query){ $('cp-q').value=g.query; runCopilot(); } }
  else if(g.view==='trust'){ if(g.facility) selectFacility(g.facility.id); else drill(FOCUS.region,FOCUS.capability||''); }
  else if(g.view==='publichealth') showView('publichealth');
  else if(g.view==='desert') showView('desert');
  window.scrollTo(0,0);
}
window.asstGoto=asstGoto;
$("asst-q").addEventListener("keydown",e=>{ if(e.key==="Enter") askAssistant(); });

window.selectFacility=selectFacility;window.override=override;window.addNote=addNote;window.shortlistFac=shortlistFac;
init();
