// Energipilot dashboard cards: energy flow, today's plan, the car, the battery - or all of them.
// type: custom:energipilot-card   view: flow | plan | car | battery | overview
// Live numbers come straight from your own sensors (sensor.energipilot tells which ones), so they move at once.

const SENSOR = "sensor.energipilot";
const P = {
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/>',
  grid: '<path d="M12 2 7 22M12 2l5 20M8.5 9h7M7.3 15h9.4M5 6h14"/>',
  house: '<path d="M3 10.5 12 3l9 7.5"/><path d="M5 9.5V21h14V9.5"/><path d="M10 21v-6h4v6"/>',
  battery: '<rect x="7" y="4" width="10" height="17" rx="2.5"/><path d="M10 2h4M10 14l2-4 2 4h-4"/>',
  car: '<path d="M5 16h14M4 16v-3l2-5a2 2 0 0 1 1.9-1.4h8.2A2 2 0 0 1 18 8l2 5v3"/><circle cx="7.5" cy="16.5" r="1.8"/><circle cx="16.5" cy="16.5" r="1.8"/>',
  bolt: '<path d="M13 2 4 14h7l-1 8 9-12h-7z"/>', pause: '<rect x="6" y="5" width="4" height="14" rx="1"/><rect x="14" y="5" width="4" height="14" rx="1"/>',
  down: '<path d="M12 5v14M5 12l7 7 7-7"/>', up: '<path d="M12 19V5M5 12l7-7 7 7"/>',
};
const TX = {
  da: { sun: "Sol", grid: "Net", buy: "Køber", sell: "Sælger", charging: "Lader", discharging: "Aflader", idle: "Hviler", plugged: "Sat i", notPlugged: "Ikke sat i",
    plan: "Dagens plan", car: "Bilen", battery: "Batteri", target: "mål", price: "Pris nu", chargeNow: "Lad nu", readyAt: "Klar kl.", atMost: "Højst",
    cheap: "billig", mid: "normal", dear: "dyr", cheapest: "Billigste timer", noData: "Energipilot kører ikke endnu", tomorrow: "I morgen",
    reasons: { discharge: "Strømmen er dyr nu, så batteriet tager over.", charge: "Solen giver overskud - det gemmes.", grid: "Strømmen er billig - batteriet fyldes.", hold: "Strømmen gemmes til de dyre timer." },
    views: { overview: "Alt", flow: "Energiflow", plan: "Dagens plan", car: "Bilen", battery: "Batteri" }, view: "Visning", title: "Titel" },
  en: { sun: "Sun", grid: "Grid", buy: "Buying", sell: "Selling", charging: "Charging", discharging: "Discharging", idle: "Idle", plugged: "Plugged in", notPlugged: "Not plugged in",
    plan: "Today's plan", car: "The car", battery: "Battery", target: "target", price: "Price now", chargeNow: "Charge now", readyAt: "Ready at", atMost: "At most",
    cheap: "cheap", mid: "normal", dear: "dear", cheapest: "Cheapest hours", noData: "Energy Pilot isn't running yet", tomorrow: "Tomorrow",
    reasons: { discharge: "Power is expensive now, so the battery takes over.", charge: "The sun gives a surplus - it's stored.", grid: "Power is cheap - the battery fills up.", hold: "The power is kept for the expensive hours." },
    views: { overview: "Everything", flow: "Energy flow", plan: "Today's plan", car: "The car", battery: "Battery" }, view: "View", title: "Title" },
};
const COL = { discharge: "#a78bfa", charge: "#f5b544", grid: "#6ea8fe", hold: "#7c6cff" };
const DICON = { discharge: "down", charge: "up", grid: "bolt", hold: "pause" };

const lang = (h) => ((h?.locale?.language || h?.language || "da").startsWith("da") ? "da" : "en");
const ic = (n, size = 16) => `<svg class="ic" style="width:${size}px;height:${size}px" viewBox="0 0 24 24">${P[n]}</svg>`;
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

/* ---------- energy flow: every real path (sun→battery, grid→battery, battery→car …), shared by panel and card ---------- */
function flowPaths(f) {
  // Who feeds whom (W): the sun first to the house, then the car, the battery, the grid; the battery to the house and
  // the car; the grid covers the rest.
  const src = { pv: Math.max(0, f.pv || 0), batt: Math.max(0, -(f.battery ?? f.batt ?? 0)), grid: Math.max(0, f.grid || 0) };
  const need = { house: Math.max(0, f.house || 0), ev: Math.max(0, f.ev || 0), batt: Math.max(0, f.battery ?? f.batt ?? 0), grid: Math.max(0, -(f.grid || 0)) };
  const out = {};
  for (const s of ["pv", "batt", "grid"]) {
    for (const d of ["house", "ev", "batt", "grid"]) {
      if (s === d || (s === "grid" && d === "grid")) continue;
      const w = Math.min(src[s], need[d]);
      if (w > 1) { out[`${s}>${d}`] = w; src[s] -= w; need[d] -= w; }
    }
  }
  return out;
}
const FLOW_GEOM = {
  "pv>house": "M180 74 L180 116", "pv>batt": "M156 58 Q86 70 64 122", "pv>grid": "M204 58 Q274 70 296 122", "pv>ev": "M204 66 Q262 150 204 236",
  "batt>house": "M74 150 L146 150", "batt>ev": "M62 178 Q76 254 154 260", "batt>grid": "M66 172 Q180 236 294 172",
  "grid>house": "M286 150 L214 150", "grid>ev": "M298 178 Q284 254 206 260", "grid>batt": "M294 128 Q180 70 66 128",
};
const FLOW_COLOR = { pv: "var(--sun)", batt: "var(--batt)", grid: "var(--grid)", house: "var(--house)" };
function flowBeams(f, filterId) {
  const paths = flowPaths(f), out = [];
  for (const [key, w] of Object.entries(paths)) {
    const [s] = key.split(">");
    const d = FLOW_GEOM[key];
    if (!d) continue;
    const width = (1.6 + Math.min(3.2, w / 1200)).toFixed(1), dur = Math.max(0.7, Math.min(3.4, 2800 / w)).toFixed(2);
    out.push(`<path class="lane" d="${d}" style="stroke:${FLOW_COLOR[s]}"/>
      <path class="beam" d="${d}" style="stroke:${FLOW_COLOR[s]};stroke-width:${width};--d:${dur}s" filter="url(#${filterId})"/>`);
  }
  return out.join("");
}

class EnergipilotCard extends HTMLElement {
  setConfig(config) { this._config = { view: "overview", ...config }; if (!this.shadowRoot) this.attachShadow({ mode: "open" }); this._uid = Math.random().toString(36).slice(2, 7); }
  static getConfigElement() { return document.createElement("energipilot-card-editor"); }
  static getStubConfig() { return { view: "flow" }; }
  getCardSize() { return { flow: 5, plan: 4, car: 3, battery: 2, overview: 10 }[this._config.view] || 5; }
  getGridOptions() { return { columns: 12, min_columns: 6, rows: this.getCardSize() * 1.5 }; }

  set hass(hass) {
    this._hass = hass;
    const ep = hass.states[SENSOR];
    const roles = ep?.attributes?.roles || {};
    const live = Object.values(roles).filter(Boolean).map((e) => hass.states[e]?.state).join("|");
    const key = (ep?.last_updated || "") + live + hass.themes?.darkMode;
    if (key === this._key) return;
    const shape = (ep?.last_updated || "") + this._sig();
    this._key = key;
    if (shape !== this._shape || !this.shadowRoot.innerHTML) { this._shape = shape; this._render(); } else this._patch();
  }

  get t() { return TX[lang(this._hass)]; }
  _n(v, d = 1) { return v == null || isNaN(v) ? "–" : Number(v).toFixed(d).replace(".", lang(this._hass) === "da" ? "," : "."); }
  _num(e) { const s = e && this._hass.states[e]; const v = s ? parseFloat(s.state) : NaN; return isNaN(v) ? null : v; }
  _w(e) {
    if (Array.isArray(e)) { const all = e.map((x) => this._w(x)).filter((x) => x != null); return all.length ? all.reduce((a, b) => a + b, 0) : null; }  // several solar arrays
    const v = this._num(e); if (v == null) return null; return String(this._hass.states[e].attributes.unit_of_measurement || "W").toLowerCase() === "kw" ? v * 1000 : v;
  }
  _split(w) { if (w == null) return ["–", ""]; const a = Math.abs(w); return a >= 1000 ? [this._n(a / 1000, a >= 10000 ? 0 : 1), "kW"] : [String(Math.round(a)), "W"]; }

  _flow() {
    const r = this._hass.states[SENSOR]?.attributes?.roles || {};
    const pv = this._w(r.pv_power), house = this._w(r.house_power), batt = this._w(r.battery_power), soc = this._num(r.battery_soc);
    let grid = this._w(r.grid_power); const ev = this._w(r.ev_power);
    const plug = r.ev_plug ? this._hass.states[r.ev_plug]?.state === "on" : null;
    if (grid == null && pv != null && house != null) grid = house + (ev || 0) + (batt || 0) - pv;
    return { pv, house, batt, soc, grid, ev, plug, has: { pv: pv != null, battery: soc != null || batt != null, grid: grid != null, ev: !!(r.ev_power || r.ev_plug) } };
  }
  _sig() {
    const f = this._flow(), b = (w) => w == null || Math.abs(w) < 30 ? 0 : (w > 0 ? 1 : -1) * (Math.abs(w) > 3000 ? 3 : Math.abs(w) > 1200 ? 2 : 1);
    const p = flowPaths(f);
    return Object.keys(p).sort().map((k) => k + Math.min(3, Math.floor(p[k] / 1200))).join(",") + "|" + Object.values(f.has).join();
  }

  _render() {
    const ep = this._hass?.states[SENSOR], t = this.t, v = this._config.view;
    let body;
    if (!ep) body = `<div class="empty">${ic("bolt", 22)}<div>${t.noData}</div></div>`;
    else body = v === "plan" ? this._planHtml() : v === "car" ? this._carHtml() : v === "battery" ? this._batteryHtml() : v === "flow" ? this._flowHtml()
      : `${this._flowHtml()}${this._statusHtml()}${this._batteryHtml(true)}${this._carHtml(true)}${this._planHtml(true)}`;
    this.shadowRoot.innerHTML = `<style>${CSS}</style><ha-card>${this._config.title ? `<div class="title">${esc(this._config.title)}</div>` : ""}${body}</ha-card>`;
    this._wire();
  }
  _patch() {
    // Only the numbers - the beams keep running.
    const f = this._flow(), root = this.shadowRoot;
    const setv = (id, pair) => { const el = root.getElementById("v-" + id); if (el?.firstChild) { el.firstChild.nodeValue = pair[0]; const u = root.getElementById("u-" + id); if (u) u.textContent = pair[1] ? " " + pair[1] : ""; } };
    setv("sun", this._split(f.pv)); setv("house", this._split(f.house)); setv("grid", this._split(f.grid)); setv("battery", [this._n(f.soc, 0), "%"]);
    if (f.ev > 30) setv("car", this._split(f.ev));
    const ring = root.getElementById("soc"); if (ring) ring.setAttribute("stroke-dashoffset", 2 * Math.PI * 38 * (1 - (f.soc || 0) / 100));
    const bs = root.getElementById("bsoc"); if (bs?.firstChild) bs.firstChild.nodeValue = this._n(f.soc, 0);
    const bb = root.getElementById("bbar"); if (bb) bb.style.width = `${f.soc || 0}%`;
  }

  _node(id, x, y, color, value, unit, cap, extra = "", above = false, active = false) {
    return `<g transform="translate(${x} ${y})" class="node ${active ? "on" : ""}" style="--nc:${color}"><circle r="40" class="halo"/><circle r="33" class="nbg"/><circle r="33" fill="none" stroke="${color}" stroke-opacity=".6" stroke-width="1.4"/>${extra}
      <g transform="translate(-10 -21) scale(.84)" style="color:${color}"><svg width="24" height="24" viewBox="0 0 24 24" class="ic ${id === "sun" && active ? "spin" : ""}" style="width:24px;height:24px">${P[id]}</svg></g>
      <text class="val" y="17" id="v-${id}">${value}<tspan class="unit" id="u-${id}">${unit ? " " + unit : ""}</tspan></text>
      ${cap != null ? `<text class="cap" y="${above ? -42 : 50}">${esc(cap)}</text>` : ""}</g>`;
  }
  _flowHtml() {
    const f = this._flow(), t = this.t, h = f.has, gc = (f.grid || 0) < -30 ? "#3ddc97" : "#6ea8fe", r = 38, c = 2 * Math.PI * r;
    const [pv, pvu] = this._split(f.pv), [ho, hou] = this._split(f.house), [gr, gru] = this._split(f.grid), [ev, evu] = this._split(f.ev);
    const ring = `<circle r="${r}" fill="none" stroke="#a78bfa" stroke-width="2.5" stroke-linecap="round" stroke-dasharray="${c}" stroke-dashoffset="${c * (1 - (f.soc || 0) / 100)}" transform="rotate(-90)" id="soc"/>`;
    return `<div class="flow"><svg viewBox="-20 -20 400 352"><defs><filter id="g${this._uid}" filterUnits="userSpaceOnUse" x="-40" y="-40" width="480" height="430"><feGaussianBlur stdDeviation="2" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter></defs>
      ${h.pv ? '<path class="base" d="M180 74 L180 116"/>' : ""}${h.grid ? '<path class="base" d="M286 150 L214 150"/>' : ""}
      ${h.battery ? '<path class="base" d="M74 150 L146 150"/>' : ""}${h.ev ? '<path class="base" d="M180 184 L180 228"/>' : ""}
      ${flowBeams(f, "g" + this._uid)}
      ${h.pv ? this._node("sun", 180, 40, "#f5b544", pv, pvu, t.sun.toUpperCase(), "", true, (f.pv || 0) > 30) : ""}
      ${h.grid ? this._node("grid", 320, 150, gc, gr, gru, (f.grid < -30 ? t.sell : f.grid > 30 ? t.buy : t.grid).toUpperCase(), "", false, Math.abs(f.grid || 0) > 30) : ""}
      ${this._node("house", 180, 150, "var(--ep-house)", ho, hou, null, "", false, true)}
      ${h.battery ? this._node("battery", 40, 150, "#a78bfa", this._n(f.soc, 0), "%", (f.batt > 30 ? t.charging : f.batt < -30 ? t.discharging : t.idle).toUpperCase(), ring, false, Math.abs(f.batt || 0) > 30) : ""}
      ${h.ev ? this._node("car", 180, 260, "#f472b6", f.ev > 30 ? ev : "–", f.ev > 30 ? evu : "", (f.ev > 30 ? t.charging : f.plug ? t.plugged : t.notPlugged).toUpperCase(), "", false, (f.ev || 0) > 30) : ""}
    </svg></div>`;
  }
  _statusHtml() {
    const d = this._hass.states[SENSOR].attributes.decision, t = this.t;
    if (!d || !d.kind) return "";
    return `<div class="status" style="--c:${COL[d.kind]}"><span class="sic">${ic(DICON[d.kind], 18)}</span><div><b>${esc(d.text)}</b><span>${t.reasons[d.kind]}</span></div></div>`;
  }
  _batteryHtml(inline = false) {
    const f = this._flow(), d = this._hass.states[SENSOR].attributes.decision || {}, t = this.t;
    if (f.soc == null) return "";
    const state = f.batt > 30 ? `${t.charging} ${this._split(f.batt).join(" ")}` : f.batt < -30 ? `${t.discharging} ${this._split(f.batt).join(" ")}` : t.idle;
    return `<div class="${inline ? "sec" : "pad"}"><div class="eyebrow">${ic("battery")} ${t.battery}<span>${d.target != null ? `${t.target} ${this._n(d.target, 0)} %` : ""}</span></div>
      <div class="big"><span id="bsoc">${this._n(f.soc, 0)}</span><small>%</small> <em>${esc(state)}</em></div><div class="bar"><span id="bbar" style="width:${f.soc}%"></span></div></div>`;
  }
  _carHtml(inline = false) {
    const ev = this._hass.states[SENSOR].attributes.ev, f = this._flow(), t = this.t;
    if (!ev) return "";
    const charging = (f.ev || 0) > 30, e = ev.entities || {};
    return `<div class="${inline ? "sec" : "pad"}"><div class="eyebrow">${ic("car")} ${t.car}<span>${ev.session_kwh != null ? `${this._n(ev.session_kwh, 1)} kWh` : ""}</span></div>
      <div class="big" style="font-size:20px">${charging ? `${t.charging} ${this._split(f.ev).join(" ")}` : f.plug ? t.plugged : t.notPlugged}</div>
      ${e.ev_manual ? `<div class="ctl"><b>${t.chargeNow}</b><button class="tg ${this._hass.states[e.ev_manual]?.state === "on" ? "on" : ""}" data-toggle="${e.ev_manual}"></button></div>` : ""}
      ${e.ev_ready ? `<div class="ctl"><b>${t.readyAt}</b><input type="time" data-time="${e.ev_ready}" value="${esc(String(this._hass.states[e.ev_ready]?.state || "").slice(0, 5))}"></div>` : ""}
      ${e.ev_cap ? `<div class="ctl"><b>${t.atMost}</b><span class="rg"><input type="range" min="0" max="${this._hass.states[e.ev_cap]?.attributes.max || 100}" value="${this._hass.states[e.ev_cap]?.state}" data-cap="${e.ev_cap}"><i id="capv">${this._n(this._num(e.ev_cap), 0)} kWh</i></span></div>` : ""}
    </div>`;
  }
  _planHtml(inline = false) {
    const a = this._hass.states[SENSOR].attributes, t = this.t, hrs = (a.plan || []).filter((h) => h.price != null || h.sun != null);
    if (!hrs.length) return "";
    const W = 18, H = 150, top = 10, bot = 18, width = hrs.length * W, y0 = H - bot, ph = H - top - bot;
    const pmin = Math.min(0, a.price_min ?? 0), pmax = (a.price_max || 1) * 1.08, emax = Math.max(1, ...hrs.map((h) => Math.max(h.sun || 0, h.house || 0))) * 1.15;
    const now = new Date(), col = (p) => { const x = (p - a.price_min) / Math.max(0.01, a.price_max - a.price_min); return `hsl(${Math.round(150 - 150 * x)} 70% ${x > .66 ? 60 : 52}%)`; };
    let ni = -1;
    const bars = hrs.map((h, i) => {
      const d = new Date(h.t), bh = h.price != null ? ((h.price - pmin) / (pmax - pmin)) * ph : 0, cur = d.getHours() === now.getHours() && d.getDate() === now.getDate();
      if (cur) ni = i;
      return `${h.price != null ? `<rect x="${i * W + 4}" y="${y0 - bh}" width="${W - 8}" height="${bh}" rx="2.5" fill="${col(h.price)}" opacity="${d < now && !cur ? .25 : .85}"/>` : ""}
        ${h.charge ? `<rect x="${i * W + 4}" y="${y0 + 3}" width="${W - 8}" height="3" rx="1.5" fill="#a78bfa"/>` : ""}
        ${d.getHours() % 6 === 0 ? `<text class="ax" x="${i * W + W / 2}" y="${H - 3}">${String(d.getHours()).padStart(2, "0")}</text>` : ""}
        ${d.getHours() === 0 && i ? `<line x1="${i * W}" x2="${i * W}" y1="${top}" y2="${y0}" class="day"/>` : ""}`;
    }).join("");
    const pts = (k) => hrs.map((h, i) => h[k] != null ? `${(i * W + W / 2).toFixed(1)},${(y0 - (h[k] / emax) * ph).toFixed(1)}` : null).filter(Boolean);
    const sun = pts("sun"), house = pts("house"), nx = ni >= 0 ? ni * W + (now.getMinutes() / 60) * W : null;
    return `<div class="${inline ? "sec" : "pad"}"><div class="eyebrow">${t.plan}<span>${(a.cheapest || []).slice(0, 3).map((c) => new Date(c).getHours().toString().padStart(2, "0") + ":00").join(" · ")}</span></div>
      <div class="pw"><svg width="${width}" height="${H}" viewBox="0 0 ${width} ${H}"><defs><linearGradient id="s${this._uid}" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="#f5b544" stop-opacity=".35"/><stop offset="1" stop-color="#f5b544" stop-opacity="0"/></linearGradient></defs>
        ${bars}${sun.length > 1 ? `<polygon points="${sun[0].split(",")[0]},${y0} ${sun.join(" ")} ${sun[sun.length - 1].split(",")[0]},${y0}" fill="url(#s${this._uid})"/><polyline points="${sun.join(" ")}" fill="none" stroke="#f5b544" stroke-width="1.8"/>` : ""}
        ${house.length > 1 ? `<polyline points="${house.join(" ")}" fill="none" stroke="var(--ep-house)" stroke-width="1.4" stroke-dasharray="4 3" opacity=".8"/>` : ""}
        ${nx != null ? `<line x1="${nx}" x2="${nx}" y1="2" y2="${y0}" stroke="var(--primary-text-color)" stroke-width="1.3"/>` : ""}</svg></div></div>`;
  }

  _wire() {
    const r = this.shadowRoot, h = this._hass;
    r.querySelectorAll("[data-toggle]").forEach((b) => b.onclick = () => { const on = !b.classList.contains("on"); b.classList.toggle("on", on); h.callService("input_boolean", on ? "turn_on" : "turn_off", { entity_id: b.dataset.toggle }); });
    r.querySelectorAll("[data-time]").forEach((i) => i.onchange = () => h.callService("input_datetime", "set_datetime", { entity_id: i.dataset.time, time: i.value + ":00" }));
    r.querySelectorAll("[data-cap]").forEach((i) => { i.oninput = () => (r.getElementById("capv").textContent = `${i.value} kWh`); i.onchange = () => h.callService("input_number", "set_value", { entity_id: i.dataset.cap, value: Number(i.value) }); });
    const pw = r.querySelector(".pw"), nl = pw?.querySelector("line[stroke-width='1.3']");
    if (pw && nl) pw.scrollLeft = Math.max(0, Number(nl.getAttribute("x1")) - pw.clientWidth / 3);
  }
}

const CSS = `
  :host { --ep-house: var(--primary-text-color); --house: var(--primary-text-color); --sun:#f5b544; --batt:#a78bfa; --grid:#6ea8fe; --car:#f472b6; }
  .lane { fill:none; stroke-width:1.2; stroke-opacity:.18; }
  .node .halo { fill:var(--nc); opacity:0; } .node.on .halo { animation:halo 3s ease-in-out infinite; }
  @keyframes halo { 0%,100% { opacity:.05; r:36px; } 50% { opacity:.16; r:42px; } }
  .spin { animation:spin 18s linear infinite; transform-origin:12px 12px; } @keyframes spin { to { transform:rotate(360deg); } }
  ha-card { overflow:hidden; padding:4px 0; }
  .title { font-size:16px; font-weight:600; padding:12px 16px 0; }
  .ic { stroke:currentColor; fill:none; stroke-width:1.8; stroke-linecap:round; stroke-linejoin:round; vertical-align:-3px; }
  .flow { padding:8px 10px 0; } .flow svg { width:100%; height:auto; display:block; overflow:visible; }
  .nbg { fill:var(--secondary-background-color, rgba(127,127,127,.12)); }
  .val { font:650 17px var(--paper-font-body1_-_font-family, system-ui); fill:var(--primary-text-color); text-anchor:middle; letter-spacing:-.02em; }
  .unit { font-size:11px; font-weight:500; fill:var(--secondary-text-color); }
  .cap { font:600 10.5px system-ui; fill:var(--secondary-text-color); text-anchor:middle; letter-spacing:.08em; }
  .base { fill:none; stroke:var(--divider-color, rgba(127,127,127,.25)); stroke-width:1.5; }
  .beam { fill:none; stroke-width:2.2; stroke-linecap:round; stroke-dasharray:14 46; animation:beam var(--d) linear infinite; }
  .beam.rev { animation-direction:reverse; } @keyframes beam { to { stroke-dashoffset:-60; } }
  .status { display:flex; gap:12px; align-items:center; margin:6px 16px 4px; padding:12px; border-radius:14px; background:color-mix(in srgb, var(--c) 10%, transparent); }
  .sic { width:34px; height:34px; border-radius:10px; display:grid; place-items:center; color:var(--c); background:color-mix(in srgb, var(--c) 16%, transparent); flex:none; }
  .status b { display:block; font-weight:600; } .status span { font-size:13px; color:var(--secondary-text-color); }
  .pad { padding:14px 16px; } .sec { padding:14px 16px; border-top:1px solid var(--divider-color); margin-top:6px; }
  .eyebrow { display:flex; align-items:center; gap:6px; font-size:11px; font-weight:650; text-transform:uppercase; letter-spacing:.09em; color:var(--secondary-text-color); margin-bottom:8px; }
  .eyebrow span { margin-left:auto; letter-spacing:.02em; text-transform:none; font-weight:600; }
  .big { font-size:28px; font-weight:650; letter-spacing:-.03em; } .big small { font-size:13px; color:var(--secondary-text-color); font-weight:500; }
  .big em { font-style:normal; font-size:13px; font-weight:500; color:var(--secondary-text-color); margin-left:8px; letter-spacing:0; }
  .bar { height:4px; border-radius:2px; background:var(--secondary-background-color); margin-top:10px; overflow:hidden; } .bar span { display:block; height:100%; background:#a78bfa; border-radius:2px; transition:width 1s; }
  .ctl { display:flex; align-items:center; justify-content:space-between; gap:10px; padding:10px 0 0; margin-top:10px; border-top:1px solid var(--divider-color); }
  .ctl b { font-weight:600; font-size:14px; }
  .tg { width:46px; height:28px; border-radius:14px; border:0; background:var(--disabled-color, #bbb); position:relative; cursor:pointer; flex:none; }
  .tg::after { content:""; position:absolute; top:2px; left:2px; width:24px; height:24px; border-radius:50%; background:#fff; transition:.2s; box-shadow:0 1px 3px rgba(0,0,0,.3); }
  .tg.on { background:#f472b6; } .tg.on::after { left:20px; }
  input[type=time] { font:600 16px system-ui; color:var(--primary-text-color); background:var(--secondary-background-color); border:0; border-radius:10px; padding:6px 8px; }
  .rg { display:flex; align-items:center; gap:10px; flex:1; max-width:60%; } .rg input { flex:1; accent-color:#f472b6; } .rg i { font-style:normal; font-weight:600; min-width:56px; text-align:right; font-size:14px; }
  .pw { overflow-x:auto; scrollbar-width:none; margin:0 -16px; padding:0 16px; } .pw::-webkit-scrollbar { display:none; }
  .ax { font:500 10px system-ui; fill:var(--secondary-text-color); text-anchor:middle; } .day { stroke:var(--divider-color); stroke-dasharray:2 4; }
  .empty { display:flex; gap:10px; align-items:center; padding:20px; color:var(--secondary-text-color); }
  @media (prefers-reduced-motion: reduce) { .beam { animation:none; } }
`;

class EnergipilotCardEditor extends HTMLElement {
  setConfig(c) { this._config = c || {}; this._render(); }
  set hass(h) { this._hass = h; this._render(); }
  _render() {
    if (!this._hass || !this._config) return;
    const t = TX[lang(this._hass)];
    if (!this._form) {
      this._form = document.createElement("ha-form");
      this._form.computeLabel = (s) => ({ view: t.view, title: t.title })[s.name];
      this._form.addEventListener("value-changed", (e) => {
        const config = { ...e.detail.value }; Object.keys(config).forEach((k) => (config[k] === "" || config[k] == null) && delete config[k]);
        this._config = config;
        this.dispatchEvent(new CustomEvent("config-changed", { detail: { config }, bubbles: true, composed: true }));
      });
      this.appendChild(this._form);
    }
    this._form.hass = this._hass;
    this._form.data = { view: "overview", ...this._config };
    this._form.schema = [
      { name: "view", selector: { select: { mode: "list", options: Object.entries(t.views).map(([value, label]) => ({ value, label })) } } },
      { name: "title", selector: { text: {} } },
    ];
  }
}

if (!customElements.get("energipilot-card")) {
  customElements.define("energipilot-card", EnergipilotCard);
  customElements.define("energipilot-card-editor", EnergipilotCardEditor);
  window.customCards = window.customCards || [];
  window.customCards.push({ type: "energipilot-card", name: "Energipilot", preview: true,
    description: "Energiflow, dagens plan, bilen og batteriet - kun det du har." });
}
