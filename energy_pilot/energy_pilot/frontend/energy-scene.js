// Shared visual layer only. Control decisions and sensor normalization stay with the caller.
const ART = new URL('./art/', import.meta.url).href;
const ART_VERSION = new URL(import.meta.url).search;
export const artUrl = name => `${ART}${name}.png${ART_VERSION}`;
const escape = (s) => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const points = { pv:[146,224], batt:[132,345], grid:[600,230], ev:[560,365], house:[358,315] };
const colours = { pv:'#edbd66', batt:'#b6a1ed', grid:'#80b8e2', ev:'#75c9d5', house:'#c8d9e4' };
const installed = (f, k) => k === 'house' || !!f.has?.[{batt:'battery',ev:'ev',pv:'pv',grid:'grid'}[k]];
const rng = i => { const v = Math.sin(i * 127.1 + 19.7) * 43758.5453; return v - Math.floor(v); };
const batteryCaption = (f, labels, split) => {
  const w=f.battery??f.batt;
  return [w>100?labels.charging:w< -100?labels.discharging:labels.idle,
    Math.abs(w)>100?split(w).join(' '):''].filter(Boolean).join(' ');
};

export const sceneStyles = `
.ep-scene { --ep-ink:#edf4fb; --ep-sub:#a9bdce; position:relative; isolation:isolate; overflow:hidden; border-radius:20px; background:#0d1b2b; color:var(--ep-ink); }
.ep-stage { position:relative; aspect-ratio:720/448; overflow:hidden; background:linear-gradient(#0b172e,#21334a 64%,#183b36); }
.ep-scene[data-time=day] .ep-stage { background:linear-gradient(#b6d7e9,#e5e4d4 67%,#5a7d64); }
.ep-scene[data-time=dusk] .ep-stage { background:linear-gradient(#243347,#b28587 58%,#65726b); }
.ep-scene[data-season=winter] .ep-stage { background:linear-gradient(#182c46,#a7b6c4 68%,#c3d0d5); }
.ep-scene[data-season=winter][data-time=day] .ep-stage { background:linear-gradient(#a8c9dd,#e1e8eb 68%,#d4dfe2); }
.ep-stage > svg.ep-world { position:absolute; inset:0; display:block; width:100%; height:100%; overflow:hidden; }
.ep-world text { font-family:inherit; }
.ep-garden { filter:saturate(.62) brightness(.9); }
.ep-scene[data-time=night] .ep-garden { filter:saturate(.45) brightness(.75); }
.ep-scene[data-weather=rainy] .ep-garden,.ep-scene[data-weather=pouring] .ep-garden,.ep-scene[data-weather=lightning-rainy] .ep-garden { filter:saturate(.35) brightness(.7); }
.ep-object { filter:drop-shadow(0 10px 8px #0006) saturate(.72); }
.ep-scene[data-time=day] .ep-object { filter:drop-shadow(0 8px 8px #0004) saturate(.65) brightness(1.08); }
.ep-scene[data-time=night] .ep-object { filter:drop-shadow(0 8px 8px #0008) saturate(.65) brightness(.86); }
.ep-route { fill:none; stroke-width:5; stroke-linecap:round; stroke:#05141d; opacity:.65; }
.ep-route-edge { fill:none; stroke-width:1.2; stroke-linecap:round; opacity:.28; }
.ep-current { fill:none; stroke-linecap:round; stroke-dasharray:2 10 30 130; animation:ep-current var(--ep-speed,3s) linear infinite; }
.ep-current-soft { stroke-width:9; opacity:.16; filter:blur(3px); }
.ep-current-core { stroke-width:2.6; opacity:.95; }
@keyframes ep-current { to { stroke-dashoffset:-172; } }
.ep-stars { animation:ep-shimmer 5s ease-in-out infinite alternate; }
@keyframes ep-shimmer { to { opacity:.3; } }
.ep-cloud { animation:ep-cloud 45s ease-in-out infinite alternate; filter:blur(16px); }
@keyframes ep-cloud { to { transform:translateX(55px); } }
.ep-rain { animation:ep-rain var(--ep-fall,1s) linear infinite; }
@keyframes ep-rain { to { transform:translate(-65px,510px); } }
.ep-snow { animation:ep-snow var(--ep-fall,12s) linear infinite; }
@keyframes ep-snow { to { transform:translate(36px,520px); } }
.ep-sway { animation:ep-sway 3.5s ease-in-out infinite alternate; }
@keyframes ep-sway { to { transform:translateX(14px); } }
.ep-leaf { animation:ep-leaf var(--ep-fall,14s) linear infinite; transform-box:fill-box; transform-origin:center; }
@keyframes ep-leaf { to { transform:translate(100px,510px) rotate(290deg); } }
.ep-fog { animation:ep-fog 24s ease-in-out infinite alternate; }
@keyframes ep-fog { to { transform:translateX(80px); opacity:.2; } }
.ep-light { animation:ep-light var(--ep-twinkle,3s) ease-in-out infinite alternate; }
@keyframes ep-light { to { opacity:.35; } }
.ep-spark { animation:ep-spark 8s ease-out infinite; transform-box:fill-box; transform-origin:center; }
@keyframes ep-spark { 0%,64%,100% { opacity:0; transform:scale(.15); } 68% { opacity:.9; } 85% { opacity:0; transform:scale(1.5); } }
.ep-ember { animation:ep-ember 6s ease-out infinite; }
@keyframes ep-ember { to { transform:translate(30px,-130px); opacity:0; } }
.ep-lightning { opacity:0; animation:ep-lightning 13s linear infinite; }
@keyframes ep-lightning { 0%,95%,96%,98%,100% { opacity:0; } 95.2% { opacity:.2; } 97% { opacity:.1; } }
.ep-weather { position:absolute; top:14px; right:14px; max-width:65%; padding:6px 10px; border-radius:20px; color:#edf4fb; background:#101d2bd9; border:1px solid #b9d3e425; font-size:12px; backdrop-filter:blur(8px); }
.ep-meters { display:flex; gap:1px; background:#91b8c41c; border-top:1px solid #91b8c42a; position:relative; }
.ep-meter { flex:1; min-width:0; padding:12px 5px 14px; text-align:center; background:#102133; font-size:11px; color:var(--ep-sub); }
.ep-meter-label { display:flex; gap:5px; justify-content:center; align-items:center; }
.ep-meter-label svg { width:15px!important; height:15px!important; stroke:var(--ep-tone); fill:none; stroke-width:1.8; }
.ep-meter strong { color:var(--ep-ink); display:block; margin-top:4px; font-size:16px; font-weight:650; font-variant-numeric:tabular-nums; white-space:nowrap; }
.ep-meter small { font-size:10px; color:var(--ep-sub); font-weight:500; }
.ep-meter-caption { display:block; min-height:13px; font-size:9px; margin-top:2px; color:var(--ep-tone); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.ep-scene[data-ep-light=true] .ep-meter { background:#f0f6f8; }
.ep-scene[data-ep-light=true] { --ep-ink:#183144; --ep-sub:#526879; }
.ep-scene[data-ep-light=true] .ep-meter-caption { color:#526879; }
@media(max-width:420px) { .ep-meter { padding:10px 3px; } .ep-meter strong { font-size:14px; } .ep-weather { top:10px; right:10px; font-size:11px; } }
@media(prefers-reduced-motion:reduce) { .ep-scene *, .ep-scene *::before, .ep-scene *::after { animation:none!important; transition:none!important; } .ep-spark { opacity:.65; } .ep-lightning { display:none; } }
`;

function atmosphere(sc) {
  if (!sc) return '';
  const night = sc.time === 'night', cond = sc.condition || '', season = sc.season;
  let out = '';
  if (night && !/rain|pouring|fog|cloudy|lightning/.test(cond)) {
    out += `<g class="ep-stars">${Array.from({length:28},(_,i)=>`<circle cx="${rng(i)*720}" cy="${rng(i+80)*155}" r="${.5+rng(i+30)}" fill="#e0ebf6" opacity="${.3+rng(i+4)*.5}"/>`).join('')}</g><circle cx="586" cy="65" r="17" fill="#e6e1cd" opacity=".8"/>`;
  } else if (!/rain|pouring|fog|lightning/.test(cond)) {
    out += `<circle cx="586" cy="65" r="22" fill="#f5d79e" opacity=".7"/>`;
  }
  if (/cloud|rain|pouring|snow|lightning/.test(cond)) out += `<g class="ep-cloud" fill="${night?'#8399b8':'#ecf0ef'}" opacity=".09"><ellipse cx="130" cy="77" rx="140" ry="22"/><ellipse cx="450" cy="49" rx="165" ry="24"/></g>`;
  return out;
}

function particles(sc) {
  if (!sc) return '';
  const cond = sc.condition || '', hol = sc.holiday?.key;
  let out = '';
  // Weather remains visible during festivities; near and far layers move at different speeds.
  if (/rain|pouring|hail|lightning/.test(cond)) {
    out += Array.from({length:cond==='pouring'?65:40},(_,i)=>`<line class="ep-rain" x1="${rng(i)*820}" y1="-65" x2="${rng(i)*820-2}" y2="${-60+rng(i+20)*13}" stroke="#b3d6ea" stroke-width="${i%3===0?1.4:.65}" opacity="${i%3===0?.45:.22}" style="--ep-fall:${.6+rng(i+1)*.7}s;animation-delay:-${rng(i+4)*2}s"/>`).join('');
    out += Array.from({length:8},(_,i)=>`<ellipse cx="${55+i*89}" cy="${379+rng(i)*45}" rx="9" ry="1.5" fill="none" stroke="#acced8" opacity=".14" class="ep-light"/>`).join('');
  }
  if (/snow/.test(cond)) out += Array.from({length:45},(_,i)=>`<g class="ep-snow" style="--ep-fall:${7+rng(i+8)*11}s;animation-delay:-${rng(i)*22}s"><circle class="ep-sway" cx="${rng(i+3)*720}" cy="-65" r="${.7+rng(i+2)*2}" fill="#f1f5f5" opacity="${.35+rng(i+9)*.5}"/></g>`).join('');
  if (cond==='fog') out += [0,1,2].map(i=>`<ellipse class="ep-fog" cx="${80+i*220}" cy="${245+i*57}" rx="260" ry="30" fill="#c8d8e0" opacity=".12" style="animation-delay:-${i*9}s;filter:blur(13px)"/>`).join('');
  if (/lightning/.test(cond)) out += '<rect class="ep-lightning" width="720" height="448" fill="#eff5ff"/>';
  if (!/rain|pouring|snow|lightning/.test(cond) && ['spring','autumn'].includes(sc.season)) {
    out += Array.from({length:12},(_,i)=>`<g transform="translate(${rng(i+9)*720},-30)"><path class="ep-leaf" style="--ep-fall:${13+rng(i)*12}s;animation-delay:-${rng(i+2)*30}s" d="M0 0 Q8 -7 11 0 Q4 8 0 0" fill="${sc.season==='spring'?['#f3d4df','#e9e2db'][i%2]:['#bd783f','#b55235','#d7a657'][i%3]}" opacity=".8"/></g>`).join('');
  }
  if (sc.season==='summer' && sc.time!=='day') out += Array.from({length:8},(_,i)=>`<circle class="ep-light" cx="${50+rng(i)*620}" cy="${280+rng(i+7)*120}" r="1.3" fill="#e4e8a2" style="animation-delay:-${i*.7}s"/>`).join('');
  if (hol==='nytaar' || hol==='bonfire') out += [0,1,2].map(i=>`<g transform="translate(${130+i*200},${55+i%2*30})"><g class="ep-spark" style="animation-delay:-${i*2.3}s">${Array.from({length:14},(_,j)=>{const a=j*Math.PI/7;return `<path d="M${Math.cos(a)*7} ${Math.sin(a)*7} L${Math.cos(a)*30} ${Math.sin(a)*30}" stroke="${['#e6bb71','#b7c9eb','#d6a3b8'][i]}" stroke-width="1.5"/>`;}).join('')}</g></g>`).join('');
  if (['midsummer','bonfire'].includes(hol)) out += Array.from({length:14},(_,i)=>`<circle class="ep-ember" cx="${70+rng(i)*90}" cy="390" r="1.2" fill="#eab06c" style="animation-delay:-${i*.7}s"/>`).join('');
  if (hol==='carnival') out += Array.from({length:20},(_,i)=>`<rect class="ep-leaf" x="${rng(i)*720}" y="-30" width="4" height="2" fill="${['#b7c9eb','#dbb0c0','#e5c873'][i%3]}" style="--ep-fall:${10+rng(i)*10}s;animation-delay:-${i*1.1}s"/>`).join('');
  return out;
}

function decorations(sc) {
  const h=sc?.holiday;
  if (!h) return '';
  const safeColours=(h.colours||[]).filter(c=>/^#[0-9a-f]{3,8}$/i.test(c));
  const colours=safeColours.length?safeColours:['#e2bd79'];
  let out='';
  if (['jul','paaske','halloween','national','thanksgiving','lunar','diwali','eid'].includes(h.key)) {
    out += '<path d="M254 223 L365 141 L480 207" fill="none" stroke="#394238" stroke-width="1.4"/>';
    out += Array.from({length:22},(_,i)=>{const a=i/21, x=254+a*226,y=a<.49?223-a*168:141+(a-.49)*130; return `<circle class="ep-light" cx="${x}" cy="${y}" r="2" fill="${colours[i%colours.length]}" style="--ep-twinkle:${2+rng(i)*3}s;animation-delay:-${rng(i+2)*4}s;filter:drop-shadow(0 0 3px ${colours[i%colours.length]})"/>`;}).join('');
  }
  if(h.key==='halloween') out += '<g fill="#c78648"><ellipse cx="254" cy="356" rx="9" ry="7"/><ellipse cx="271" cy="361" rx="6" ry="5"/></g>';
  if(h.key==='paaske') out += '<g fill="#e6c9b5"><ellipse cx="255" cy="355" rx="3" ry="5"/><ellipse cx="268" cy="359" rx="3" ry="5"/></g>';
  if(h.key==='national') out += `<path d="M488 231 V290" stroke="#c9d3d5"/><path d="M489 232h30v18h-30z" fill="${colours[0]}"/><path d="M489 238h30v6h-30z" fill="${colours[1]||colours[0]}" opacity=".8"/>`;
  return out;
}

const icons={pv:'<circle cx="12" cy="12" r="4"/><path d="M12 1v4m0 14v4M1 12h4m14 0h4M4 4l3 3m10 10 3 3M4 20l3-3M17 7l3-3"/>',house:'<path d="m3 11 9-8 9 8M5 9v12h14V9m-10 12v-7h6v7"/>',batt:'<rect x="6" y="4" width="12" height="17" rx="2"/><path d="M10 1h4m-2 7-3 6h6l-3 5"/>',ev:'<path d="m3 15 2-7h14l2 7v5h-3v-3H6v3H3zM4 13h16"/>',grid:'<path d="m12 2-6 20m6-20 6 20M5 7h14M7 13h10M5 19h14"/>'};

export function renderEnergyScene(f, sc, {connections={},labels={},format=(v)=>v==null?'–':String(v),split=(v)=>[format(v),'W'],id='ep',light=false}={}) {
  const season=sc?.season || '', time=sc?.time || (light?'day':'night');
  const snow=season==='winter';
  const image=(name,x,y,w,h,extra='')=>`<image class="ep-object" href="${ART+name+'.png'+ART_VERSION}" x="${x}" y="${y}" width="${w}" height="${h}" ${extra}/>`;
  const routes=Object.entries(points).filter(([k])=>k!=='house'&&installed(f,k)).map(([k,[x,y]])=>`<path class="ep-route" d="M${x} ${y} Q${x} 376 358 330"/><path class="ep-route-edge" d="M${x} ${y} Q${x} 376 358 330" stroke="${colours[k]}"/>`).join('');
  const currents=Object.entries(connections).map(([key,w])=>{
    const [src,dst]=key.split('>');
    if(!points[src]||!points[dst]||!installed(f,src)||!installed(f,dst)||!(w>1)) return '';
    const [x,y]=points[src],[a,b]=points[dst], mid='358 330';
    const d=src==='house'?`M358 315 L${a} ${b}`:dst==='house'?`M${x} ${y} Q${x} 376 ${mid} L358 315`:`M${x} ${y} Q${x} 376 ${mid} Q${a} 376 ${a} ${b}`;
    const speed=Math.max(1.4,Math.min(5,4600/w)).toFixed(2);
    return `<g data-flow="${key}" style="--ep-speed:${speed}s" stroke="${colours[src]}"><path class="ep-current ep-current-soft" d="${d}"/><path class="ep-current ep-current-core" d="${d}"/></g>`;
  }).join('');
  const values={pv:split(f.pv),house:split(f.house),batt:[format(f.soc,0),'%'],ev:split(f.ev),grid:split(f.grid)};
  const ids={pv:'sun',house:'house',batt:'battery',ev:'car',grid:'grid'};
  const captions={batt:batteryCaption(f,labels,split),grid:f.grid< -30?labels.sell:f.grid>30?labels.buy:'',ev:f.ev>30?labels.charging:f.plug?labels.plugged:labels.notPlugged};
  const meters=['pv','house','batt','ev','grid'].filter(k=>installed(f,k)).map(k=>`<div class="ep-meter" data-equipment="${k}" style="--ep-tone:${colours[k]}"><span class="ep-meter-label"><svg viewBox="0 0 24 24" aria-hidden="true">${icons[k]}</svg>${escape(labels[k]||k)}</span><strong id="v-${ids[k]}">${escape(values[k][0])}<small id="u-${ids[k]}"> ${escape(values[k][1])}</small></strong><span class="ep-meter-caption" id="c-${ids[k]}">${escape(captions[k]||'')}</span></div>`).join('');
  return `<section class="ep-scene" data-season="${escape(season)}" data-time="${escape(time)}" data-weather="${escape(sc?.condition||'')}" data-ep-light="${!!light}" aria-label="${escape(labels.flow||'Energy flow')}"><div class="ep-stage"><svg class="ep-world" viewBox="0 0 720 448" aria-hidden="true"><image class="ep-garden" href="${ART+( ['spring','summer','autumn','winter'].includes(season)?season:'summer')+'_'+(['day','dusk','night'].includes(time)?time:'day')+'.png'+ART_VERSION}" width="720" height="448" preserveAspectRatio="xMidYMid slice"/>${atmosphere(sc)}${routes}${image(snow?'house-winter':'house',213,76,308,308)}${f.has?.pv?image('solar',65,93,167,157):''}${f.has?.grid?image('grid',553,104,104,146):''}${f.has?.battery?image('battery',68,263,129,113):''}${f.has?.ev?image('charger',584,272,56,94)+image('car',458,285,167,122):''}${decorations(sc)}${currents}${particles(sc)}</svg>${sc?.outdoor!=null?`<div class="ep-weather">${time==='night'?'☾':/rain|pouring/.test(sc.condition||'')?'☂':/snow/.test(sc.condition||'')?'❄':'☀'} ${escape(format(sc.outdoor,0))}°</div>`:''}</div><div class="ep-meters">${meters}</div></section>`;
}

export function patchEnergyScene(root, f, {format,split,labels={}}) {
  const values={sun:split(f.pv),house:split(f.house),grid:split(f.grid),battery:[format(f.soc,0),'%'],car:split(f.ev)};
  for(const [id,pair] of Object.entries(values)) {
    const el=root.querySelector('#v-'+id), unit=root.querySelector('#u-'+id);
    if(el?.firstChild) el.firstChild.nodeValue=pair[0];
    if(unit) unit.textContent=' '+(pair[1]||'');
  }
  const cap={battery:batteryCaption(f,labels,split),grid:f.grid< -30?labels.sell:f.grid>30?labels.buy:'',car:f.ev>30?labels.charging:f.plug?labels.plugged:labels.notPlugged};
  for(const [id,value] of Object.entries(cap)){const el=root.querySelector('#c-'+id);if(el)el.textContent=value||'';}
}
