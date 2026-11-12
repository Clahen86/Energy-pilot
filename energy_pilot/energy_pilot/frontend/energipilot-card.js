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
  da: { evs: {"soc": "Batteri", "to": "Lad til", "trip": "100 % til turen", "reached": "Nået målet"}, leg: {"price": "Pris", "sun": "Sol", "house": "Huset", "soc": "Batteriniveau", "car": "Bilen lader", "export": "Batteriet sælger"}, sun: "Sol", grid: "Net", buy: "Køber", sell: "Sælger", charging: "Lader", discharging: "Aflader", idle: "Hviler", plugged: "Sat i", notPlugged: "Ikke sat i",
    plan: "Dagens plan", car: "Bilen", battery: "Batteri", target: "mål", price: "Pris nu", chargeNow: "Lad nu", readyAt: "Klar kl.", atMost: "Højst",
    cheap: "billig", mid: "normal", dear: "dyr", cheapest: "Billigste timer", noData: "Energipilot kører ikke endnu", tomorrow: "I morgen",
    reasons: { discharge: "Strømmen er dyr nu, så batteriet tager over.", charge: "Solen giver overskud - det gemmes.", grid: "Strømmen er billig - batteriet fyldes.", hold: "Strømmen gemmes til de dyre timer." },
    views: { overview: "Alt", flow: "Energiflow", plan: "Dagens plan", car: "Bilen", battery: "Batteri" }, view: "Visning", title: "Titel" },
  en: { evs: {"soc": "Battery", "to": "Charge to", "trip": "100 % for the trip", "reached": "Target reached"}, leg: {"price": "Price", "sun": "Sun", "house": "House", "soc": "Battery level", "car": "Car charges", "export": "Battery sells"}, sun: "Sun", grid: "Grid", buy: "Buying", sell: "Selling", charging: "Charging", discharging: "Discharging", idle: "Idle", plugged: "Plugged in", notPlugged: "Not plugged in",
    plan: "Today's plan", car: "The car", battery: "Battery", target: "target", price: "Price now", chargeNow: "Charge now", readyAt: "Ready at", atMost: "At most",
    cheap: "cheap", mid: "normal", dear: "dear", cheapest: "Cheapest hours", noData: "Energy Pilot isn't running yet", tomorrow: "Tomorrow",
    reasons: { discharge: "Power is expensive now, so the battery takes over.", charge: "The sun gives a surplus - it's stored.", grid: "Power is cheap - the battery fills up.", hold: "The power is kept for the expensive hours." },
    views: { overview: "Everything", flow: "Energy flow", plan: "Today's plan", car: "The car", battery: "Battery" }, view: "View", title: "Title" },
  de: {"evs": {"soc": "Batterie", "to": "Laden bis", "trip": "100 % für die Fahrt", "reached": "Ziel erreicht"}, "leg": {"price": "Preis", "sun": "Sonne", "house": "Haus", "soc": "Batteriestand", "car": "Auto lädt", "export": "Batterie speist ein"}, "sun": "Sonne", "grid": "Netz", "buy": "Bezug", "sell": "Einspeisung", "charging": "Lädt", "discharging": "Entlädt", "idle": "Ruht", "plugged": "Angesteckt", "notPlugged": "Nicht angesteckt", "plan": "Plan für heute", "car": "Das Auto", "battery": "Batterie", "target": "Ziel", "price": "Preis jetzt", "chargeNow": "Jetzt laden", "readyAt": "Fertig um", "atMost": "Höchstens", "cheap": "günstig", "mid": "normal", "dear": "teuer", "cheapest": "Günstigste Stunden", "noData": "Energy Pilot läuft noch nicht", "tomorrow": "Morgen", "reasons": {"discharge": "Strom ist jetzt teuer, also übernimmt die Batterie.", "charge": "Die Sonne liefert Überschuss – er wird gespeichert.", "grid": "Strom ist günstig – die Batterie füllt sich.", "hold": "Der Strom wird für die teuren Stunden aufgehoben."}, "views": {"overview": "Alles", "flow": "Energiefluss", "plan": "Plan für heute", "car": "Das Auto", "battery": "Batterie"}, "view": "Ansicht", "title": "Titel"},
  fr: {"evs": {"soc": "Batterie", "to": "Charger jusqu'à", "trip": "100 % pour le trajet", "reached": "Objectif atteint"}, "leg": {"price": "Prix", "sun": "Soleil", "house": "Maison", "soc": "Niveau batterie", "car": "La voiture charge", "export": "La batterie vend"}, "sun": "Soleil", "grid": "Réseau", "buy": "Achat", "sell": "Vente", "charging": "En charge", "discharging": "En décharge", "idle": "Au repos", "plugged": "Branchée", "notPlugged": "Non branchée", "plan": "Plan du jour", "car": "La voiture", "battery": "Batterie", "target": "objectif", "price": "Prix actuel", "chargeNow": "Charger maintenant", "readyAt": "Prête à", "atMost": "Au maximum", "cheap": "bon marché", "mid": "normal", "dear": "cher", "cheapest": "Heures les moins chères", "noData": "Energy Pilot ne tourne pas encore", "tomorrow": "Demain", "reasons": {"discharge": "L'électricité est chère, la batterie prend le relais.", "charge": "Le soleil donne un surplus – il est stocké.", "grid": "L'électricité est bon marché – la batterie se remplit.", "hold": "L'énergie est gardée pour les heures chères."}, "views": {"overview": "Tout", "flow": "Flux d'énergie", "plan": "Plan du jour", "car": "La voiture", "battery": "Batterie"}, "view": "Vue", "title": "Titre"},
  nl: {"evs": {"soc": "Accu", "to": "Laden tot", "trip": "100 % voor de rit", "reached": "Doel bereikt"}, "leg": {"price": "Prijs", "sun": "Zon", "house": "Huis", "soc": "Batterijniveau", "car": "Auto laadt", "export": "Batterij verkoopt"}, "sun": "Zon", "grid": "Net", "buy": "Afname", "sell": "Teruglevering", "charging": "Laadt", "discharging": "Ontlaadt", "idle": "Rust", "plugged": "Aangesloten", "notPlugged": "Niet aangesloten", "plan": "Plan voor vandaag", "car": "De auto", "battery": "Batterij", "target": "doel", "price": "Prijs nu", "chargeNow": "Nu laden", "readyAt": "Klaar om", "atMost": "Maximaal", "cheap": "goedkoop", "mid": "normaal", "dear": "duur", "cheapest": "Goedkoopste uren", "noData": "Energy Pilot draait nog niet", "tomorrow": "Morgen", "reasons": {"discharge": "Stroom is nu duur, dus de batterij neemt het over.", "charge": "De zon geeft een overschot – het wordt opgeslagen.", "grid": "Stroom is goedkoop – de batterij vult zich.", "hold": "De stroom wordt bewaard voor de dure uren."}, "views": {"overview": "Alles", "flow": "Energiestroom", "plan": "Plan voor vandaag", "car": "De auto", "battery": "Batterij"}, "view": "Weergave", "title": "Titel"},
  sv: {"evs": {"soc": "Batteri", "to": "Ladda till", "trip": "100 % till resan", "reached": "Målet nått"}, "leg": {"price": "Pris", "sun": "Sol", "house": "Huset", "soc": "Batterinivå", "car": "Bilen laddar", "export": "Batteriet säljer"}, "sun": "Sol", "grid": "Nät", "buy": "Köper", "sell": "Säljer", "charging": "Laddar", "discharging": "Laddar ur", "idle": "Vilar", "plugged": "Inkopplad", "notPlugged": "Inte inkopplad", "plan": "Dagens plan", "car": "Bilen", "battery": "Batteri", "target": "mål", "price": "Pris nu", "chargeNow": "Ladda nu", "readyAt": "Klar kl.", "atMost": "Högst", "cheap": "billigt", "mid": "normalt", "dear": "dyrt", "cheapest": "Billigaste timmarna", "noData": "Energy Pilot körs inte än", "tomorrow": "I morgon", "reasons": {"discharge": "Strömmen är dyr nu, så batteriet tar över.", "charge": "Solen ger överskott – det lagras.", "grid": "Strömmen är billig – batteriet fylls.", "hold": "Strömmen sparas till de dyra timmarna."}, "views": {"overview": "Allt", "flow": "Energiflöde", "plan": "Dagens plan", "car": "Bilen", "battery": "Batteri"}, "view": "Vy", "title": "Titel"},
  nb: {"evs": {"soc": "Batteri", "to": "Lad til", "trip": "100 % til turen", "reached": "Målet nådd"}, "leg": {"price": "Pris", "sun": "Sol", "house": "Huset", "soc": "Batterinivå", "car": "Bilen lader", "export": "Batteriet selger"}, "sun": "Sol", "grid": "Nett", "buy": "Kjøper", "sell": "Selger", "charging": "Lader", "discharging": "Lader ut", "idle": "Hviler", "plugged": "Koblet til", "notPlugged": "Ikke koblet til", "plan": "Dagens plan", "car": "Bilen", "battery": "Batteri", "target": "mål", "price": "Pris nå", "chargeNow": "Lad nå", "readyAt": "Klar kl.", "atMost": "Høyst", "cheap": "billig", "mid": "normal", "dear": "dyr", "cheapest": "Billigste timer", "noData": "Energipilot kjører ikke ennå", "tomorrow": "I morgen", "reasons": {"discharge": "Strømmen er dyr nå, så batteriet tar over.", "charge": "Solen gir overskudd – det lagres.", "grid": "Strømmen er billig – batteriet fylles.", "hold": "Strømmen spares til de dyre timene."}, "views": {"overview": "Alt", "flow": "Energiflyt", "plan": "Dagens plan", "car": "Bilen", "battery": "Batteri"}, "view": "Visning", "title": "Tittel"},
};
const COL = { discharge: "#a78bfa", charge: "#f5b544", grid: "#6ea8fe", hold: "#7c6cff" };
const DICON = { discharge: "down", charge: "up", grid: "bolt", hold: "pause" };

const lang = (h) => {
  const c = String(h?.locale?.language || h?.language || "en").slice(0, 2).toLowerCase();
  return c === "no" || c === "nn" ? "nb" : TX[c] ? c : "en";
};
const ic = (n, size = 16) => `<svg class="ic" style="width:${size}px;height:${size}px" viewBox="0 0 24 24">${P[n]}</svg>`;
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

/* ---------- energy flow: every real path (sun→battery, grid→battery, battery→car …), shared by panel and card ---------- */
// below this the inverter is only trimming (zero export, a battery topping up the gap): shown as idle, not as selling
const NOISE_W = 100;
const quiet = (w) => (w == null || Math.abs(w) < NOISE_W ? 0 : w);
function flowPaths(f) {
  // Who feeds whom (W): the sun first to the house, then the car, the battery, the grid; the battery to the house and
  // the car; the grid covers the rest.
  const src = { pv: Math.max(0, f.pv || 0), batt: Math.max(0, -quiet(f.battery ?? f.batt)), grid: Math.max(0, quiet(f.grid)) };
  const need = { house: Math.max(0, f.house || 0), ev: Math.max(0, f.ev || 0), batt: Math.max(0, quiet(f.battery ?? f.batt)), grid: Math.max(0, -quiet(f.grid)) };
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

/* ---------- the card's energy picture dressed like the app: time of day, real weather, the season and the day's holiday (by country) ----------
   The card stays the same: a soft tint behind it, a few particles, and for a holiday a ring of lights around the house.
   ?hol=jul&season=winter&wx=snowy&t=night previews another day. */
const C_SCENE_ICONS = {
  moon: '<path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"/>',
  cloudsun: '<path d="M12 4v1.5M6.3 6.3l1 1M4 12h1.5M17.7 6.3l-1 1"/><path d="M8 12a4 4 0 0 1 7.6-1.8"/><path d="M9 20h8.5a3.5 3.5 0 0 0 0-7h-.6A5 5 0 0 0 7 14.5 3 3 0 0 0 9 20z"/>',
  cloud: '<path d="M7 18h10.5a3.5 3.5 0 0 0 0-7h-.6A5 5 0 0 0 7 12.5 3 3 0 0 0 7 18z"/>',
  rain: '<path d="M7 15h10.5a3.5 3.5 0 0 0 0-7h-.6A5 5 0 0 0 7 9.5 3 3 0 0 0 7 15z"/><path d="M9 18l-1 3M13 18l-1 3M17 18l-1 3"/>',
  snow: '<path d="M7 14h10.5a3.5 3.5 0 0 0 0-7h-.6A5 5 0 0 0 7 8.5 3 3 0 0 0 7 14z"/><path d="M9 18h.01M13 18h.01M17 18h.01M11 21h.01M15 21h.01"/>',
  storm: '<path d="M7 14h10.5a3.5 3.5 0 0 0 0-7h-.6A5 5 0 0 0 7 8.5 3 3 0 0 0 7 14z"/><path d="M13 14l-2 4h3l-2 4"/>',
};
function cardSceneInfo(hass, cfg) {
  const s = hass?.states["sensor.energipilot"]?.attributes?.scene;
  if (!s || cfg?.scene === false) return null;
  return { ...s, time: s.time || "day", dark: !!hass.themes?.darkMode };
}
const C_SCENE_HOL = { jul: ["#ff4d5e", "#ffd34d", "#3ddc84", "#4dc3ff"], paaske: ["#ffb3cf", "#ffe680", "#a8e6a1", "#9fd0ff"], halloween: ["#ff8a2a", "#9b5de5"],
  national: ["#c8102e", "#ffffff"], midsummer: ["#ffb02e", "#ff7a2a"], nytaar: ["#ff5d8f", "#ffd84d", "#5dd6ff"], carnival: ["#ff5d8f", "#ffd84d", "#5dd6ff", "#3ddc84", "#a78bfa"],
  thanksgiving: ["#e8892c", "#c4542a", "#f0b04a"], lunar: ["#e0262a", "#ffd34d"], diwali: ["#ffb02e", "#ff7a2a", "#ffe08a"], eid: ["#1f9e5a", "#ffd34d"], bonfire: ["#ff7a2a", "#ffd84d"] };
const C_RINGED = new Set(["jul", "paaske", "halloween", "national", "thanksgiving", "lunar", "diwali", "eid"]);
function cardSunIcon(sc) {
  const c = sc?.condition || "";
  if (!sc) return null;
  if (/lightning/.test(c)) return "storm";
  if (/snow/.test(c)) return "snow";
  if (/rain|pouring|hail/.test(c)) return "rain";
  if (sc.time === "night") return "moon";
  if (c === "cloudy" || c === "fog") return "cloud";
  if (c === "partlycloudy" || (sc.cloud ?? 0) > 40) return "cloudsun";
  return null;  // the plain sun
}
function cardHouseRing(sc) {
  const h = sc?.holiday;
  if (!h) return "";
  const cols = h.colours || C_SCENE_HOL[h.key] || [], light = !sc.dark;
  let s = "";
  if (["midsummer", "bonfire", "halloween", "paaske", "diwali"].includes(h.key)) s += `<circle r="44" fill="none" stroke="${cols[0]}" stroke-width="7" opacity="${h.key === "paaske" ? .22 : .3}" filter="url(#sc-blur4)" class="sc-breathe"/>`;
  if (!C_RINGED.has(h.key)) return s;
  const n = 18;
  for (let k = 0; k < n; k++) {
    const a = k / n * Math.PI * 2, x = (Math.cos(a) * 41).toFixed(1), y = (Math.sin(a) * 41).toFixed(1), c = cols[k % cols.length];
    const edge = light && /^#f{3,6}$/i.test(c) ? ` stroke="#c9ced8" stroke-width=".6"` : "";
    s += `<circle cx="${x}" cy="${y}" r="5.5" fill="${c}" opacity=".3" filter="url(#sc-blur2)"/><circle cx="${x}" cy="${y}" r="2.2" fill="${c}"${edge} class="sc-twinkle" style="animation-delay:${(k * .23).toFixed(2)}s"/>`;
  }
  return s;
}
function cardSceneSvg(sc) {
  if (!sc) return "";
  const { time, dark } = sc, night = time === "night", dusk = time === "dusk", cond = sc.condition || "";
  const W = 400, H = 360, rnd = (k) => { const h = Math.sin(k * 127.1 + 311.7) * 43758.5453; return h - Math.floor(h); };
  const tint = { winter: "#cfe0ff", spring: "#d6f2c8", summer: "#ffecc0", autumn: "#ffd8b0" }[sc.season] || "#e6ecf5";
  const top = night ? (dark ? "#2a3a78" : "#8f9fe0") : dusk ? "#ffb98a" : tint;
  let s = `<defs><radialGradient id="sc-sky" cx=".5" cy="0" r="1.05"><stop offset="0" stop-color="${top}" stop-opacity="${dark ? (night ? .55 : .28) : (night ? .38 : .7)}"/><stop offset="1" stop-color="${top}" stop-opacity="0"/></radialGradient>
    <filter id="sc-blur2" x="-80%" y="-80%" width="260%" height="260%"><feGaussianBlur stdDeviation="2"/></filter>
    <filter id="sc-blur4" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="4"/></filter></defs>
    <rect width="${W}" height="${H}" fill="url(#sc-sky)"/>`;
  if (night) s += Array.from({ length: 20 }, (_, k) => `<circle class="sc-twinkle" cx="${(rnd(k) * W).toFixed(0)}" cy="${(rnd(k + 40) * 150 + 6).toFixed(0)}" r="${rnd(k + 9) > .8 ? 1.3 : .8}" fill="${dark ? "#fff" : "#5a68b8"}" opacity="${dark ? .7 : .45}" style="animation-delay:${(k * .37).toFixed(2)}s"/>`).join("");
  // one kind of particles at a time: the holiday's, else the real weather's, else the season's
  const h = sc.holiday?.key, cols = sc.holiday?.colours || [];
  let parts = "";
  if (h === "nytaar" || h === "bonfire" && (night || dusk)) {
    parts = [[80, 52], [320, 44], [200, 26]].map(([x, y], i) => `<g class="sc-burst" style="animation-delay:${i * .9}s;transform-origin:${x}px ${y}px">${Array.from({ length: 12 }, (_, k) => { const a = k / 12 * Math.PI * 2; return `<line x1="${x + Math.cos(a) * 5}" y1="${y + Math.sin(a) * 5}" x2="${x + Math.cos(a) * 19}" y2="${y + Math.sin(a) * 19}" stroke="${(cols.length ? cols : C_SCENE_HOL.nytaar)[i % 3]}" stroke-width="1.8" stroke-linecap="round"/>`; }).join("")}</g>`).join("");
  } else if (h === "carnival") {
    parts = Array.from({ length: 26 }, (_, k) => `<rect class="sc-fall" x="${(rnd(k) * W).toFixed(0)}" y="${(rnd(k + 7) * H - H).toFixed(0)}" width="5" height="2.6" rx="1" fill="${cols[k % cols.length]}" opacity=".6" style="animation-delay:-${(rnd(k + 3) * 14).toFixed(1)}s;animation-duration:${(10 + rnd(k) * 6).toFixed(1)}s;--r:${(rnd(k + 5) * 360).toFixed(0)}deg"/>`).join("");
  } else if (h === "midsummer" || h === "bonfire") {
    parts = Array.from({ length: 18 }, (_, k) => `<circle class="sc-rise" cx="${(200 + (rnd(k) - .5) * 220).toFixed(0)}" cy="${H + 10}" r="${(1 + rnd(k + 4) * 1.6).toFixed(1)}" fill="${["#ffb02e", "#ff7a2a", "#fff0a0"][k % 3]}" opacity=".7" style="animation-delay:-${(rnd(k + 2) * 9).toFixed(1)}s;animation-duration:${(7 + rnd(k) * 4).toFixed(1)}s"/>`).join("");
  } else if (h === "lunar" || h === "diwali" || h === "eid") {
    parts = Array.from({ length: 14 }, (_, k) => `<circle class="sc-twinkle" cx="${(rnd(k) * W).toFixed(0)}" cy="${(rnd(k + 8) * H).toFixed(0)}" r="1.6" fill="${cols[k % cols.length]}" style="animation-delay:${(k * .4).toFixed(1)}s"/>`).join("");
  } else if (/rain|pouring|lightning-rainy|hail/.test(cond)) {
    parts = Array.from({ length: cond === "pouring" ? 34 : 22 }, (_, k) => `<line class="sc-rain" x1="${(rnd(k) * W).toFixed(0)}" y1="-14" x2="${(rnd(k) * W - 4).toFixed(0)}" y2="-2" stroke="${dark ? "#7cb7ff" : "#5b8fd6"}" stroke-width="1.2" opacity=".35" stroke-linecap="round" style="animation-delay:-${(rnd(k + 1) * 1.2).toFixed(2)}s"/>`).join("");
  } else if (/snow/.test(cond)) {
    parts = Array.from({ length: 26 }, (_, k) => `<circle class="sc-fall" cx="${(rnd(k) * W).toFixed(0)}" cy="${(rnd(k + 7) * H - H).toFixed(0)}" r="${(1.2 + rnd(k + 3) * 1.4).toFixed(1)}" fill="${dark ? "#ffffff" : "#8fb0dc"}" opacity="${dark ? .75 : .6}" style="animation-delay:-${(rnd(k + 3) * 14).toFixed(1)}s;animation-duration:${(9 + rnd(k) * 5).toFixed(1)}s"/>`).join("");
  } else if (cond === "fog") {
    parts = [0, 1, 2].map((k) => `<ellipse class="sc-drift" cx="${120 + k * 90}" cy="${120 + k * 70}" rx="190" ry="26" fill="${dark ? "#c9d3e6" : "#ffffff"}" opacity="${dark ? .08 : .5}" filter="url(#sc-blur4)" style="animation-delay:-${k * 9}s"/>`).join("");
  } else if (sc.season === "spring") {
    parts = Array.from({ length: 8 }, (_, k) => `<ellipse class="sc-fall" cx="${(rnd(k) * W).toFixed(0)}" cy="${(rnd(k + 9) * H - H).toFixed(0)}" rx="4" ry="2.3" fill="${["#ffc4d6", "#ffffff", "#ffd9e4"][k % 3]}" stroke="#f3a9c0" stroke-width=".6" opacity=".85" style="animation-delay:-${(rnd(k + 2) * 20).toFixed(1)}s;animation-duration:${(16 + rnd(k) * 8).toFixed(1)}s;--r:${(rnd(k + 5) * 360).toFixed(0)}deg"/>`).join("");
  } else if (sc.season === "summer") {
    const c = night || dusk ? "#d9ff7a" : "#ffd36b";
    parts = Array.from({ length: 9 }, (_, k) => `<g class="sc-float" style="animation-delay:-${(rnd(k) * 12).toFixed(1)}s"><circle cx="${(rnd(k) * W).toFixed(0)}" cy="${(rnd(k + 9) * H).toFixed(0)}" r="1.8" fill="${c}" class="sc-twinkle" style="animation-delay:${(k * .5).toFixed(1)}s"/></g>`).join("");
  } else if (sc.season === "autumn") {
    parts = Array.from({ length: 8 }, (_, k) => `<path class="sc-fall" transform="translate(${(rnd(k) * W).toFixed(0)} ${(rnd(k + 9) * H - H).toFixed(0)})" d="M0 -5 q4 2.5 0 10 q-4 -7.5 0 -10z" fill="${["#e8892c", "#c4542a", "#f0b04a"][k % 3]}" opacity=".75" style="animation-delay:-${(rnd(k + 2) * 18).toFixed(1)}s;animation-duration:${(14 + rnd(k) * 6).toFixed(1)}s;--r:${(rnd(k + 5) * 360).toFixed(0)}deg"/>`).join("");
  } else if (sc.season === "winter" && sc.outdoor != null && sc.outdoor <= 0) {
    parts = [[118, 120], [282, 112], [42, 190], [356, 196], [118, 262], [282, 270], [200, 64]].map(([x, y], k) => `<g transform="translate(${x} ${y})" class="sc-twinkle" style="animation-delay:${k * .6}s"><path d="M0 -4 V4 M-4 0 H4 M-2.6 -2.6 L2.6 2.6 M-2.6 2.6 L2.6 -2.6" stroke="${dark ? "#dfe9ff" : "#8fb6e6"}" stroke-width="1" stroke-linecap="round"/></g>`).join("");
  }
  s += parts;
  if (/lightning/.test(cond)) s += `<rect width="${W}" height="${H}" fill="#fff" class="sc-flash"/>`;
  return `<svg class="scene" viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid slice" aria-hidden="true">${s}</svg>`;
}

class EnergipilotCard extends HTMLElement {
  setConfig(config) { this._config = { view: "overview", ...config }; if (!this.shadowRoot) this.attachShadow({ mode: "open" }); this._uid = Math.random().toString(36).slice(2, 7); }
  static getConfigElement() { return document.createElement("energipilot-card-editor"); }
  static getStubConfig() { return { view: "flow" }; }
  getCardSize() { return { flow: 5, plan: 4, car: 3, battery: 2, overview: 10 }[this._config.view] || 5; }
  getGridOptions() { return { columns: 12, min_columns: 6, rows: "auto" }; }  // as tall as what it shows

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
  _n(v, d = 1) { return v == null || isNaN(v) ? "–" : Number(v).toFixed(d).replace(".", lang(this._hass) === "en" ? "." : ","); }
  _num(e) { const s = e && this._hass.states[e]; const v = s ? parseFloat(s.state) : NaN; return isNaN(v) ? null : v; }
  _w(e) {
    if (Array.isArray(e)) { const all = e.map((x) => this._w(x)).filter((x) => x != null); return all.length ? all.reduce((a, b) => a + b, 0) : null; }  // several solar arrays
    const v = this._num(e); if (v == null) return null; return String(this._hass.states[e].attributes.unit_of_measurement || "W").toLowerCase() === "kw" ? v * 1000 : v;
  }
  _split(w) { if (w == null) return ["–", ""]; const a = Math.abs(w); return a >= 1000 ? [this._n(a / 1000, a >= 10000 ? 0 : 1), "kW"] : [String(Math.round(a)), "W"]; }

  _flow() {
    const r = this._hass.states[SENSOR]?.attributes?.roles || {};
    const sign = this._hass.states[SENSOR]?.attributes?.battery_sign || 1;  // Fox ESS and others count discharging as positive
    const rawBatt = this._w(r.battery_power);
    const pv = this._w(r.pv_power), house = this._w(r.house_power), batt = rawBatt == null ? null : rawBatt * sign, soc = this._num(r.battery_soc);
    let grid = this._w(r.grid_power); const ev = this._w(r.ev_power);
    const plug = r.ev_plug ? this._hass.states[r.ev_plug]?.state === "on" : null;
    if (grid == null && pv != null && house != null) grid = house + (ev || 0) + (batt || 0) - pv;
    return { pv, house, batt, soc, grid, ev, plug, has: { pv: pv != null, battery: soc != null || batt != null, grid: grid != null, ev: !!(r.ev_power || r.ev_plug) } };
  }
  _sig() {
    const f = this._flow(), b = (w) => w == null || Math.abs(w) < 30 ? 0 : (w > 0 ? 1 : -1) * (Math.abs(w) > 3000 ? 3 : Math.abs(w) > 1200 ? 2 : 1);
    const p = flowPaths(f);
    const sc = this._hass?.states[SENSOR]?.attributes?.scene;
    return Object.keys(p).sort().map((k) => k + Math.min(3, Math.floor(p[k] / 1200))).join(",") + "|" + Object.values(f.has).join()
      + "|" + JSON.stringify(sc || null) + (this._hass?.themes?.darkMode ? "d" : "l");
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

  _node(id, x, y, color, value, unit, cap, extra = "", above = false, active = false, iconId = null) {
    return `<g transform="translate(${x} ${y})" class="node ${active ? "on" : ""}" style="--nc:${color}"><circle r="40" class="halo"/><circle r="33" class="nbg"/><circle r="33" fill="none" stroke="${color}" stroke-opacity=".6" stroke-width="1.4"/>${extra}
      <g transform="translate(-10 -21) scale(.84)" style="color:${color}"><svg width="24" height="24" viewBox="0 0 24 24" class="ic ${id === "sun" && active && !iconId ? "spin" : ""}" style="width:24px;height:24px">${iconId ? C_SCENE_ICONS[iconId] : P[id]}</svg></g>
      <text class="val" y="17" id="v-${id}">${value}<tspan class="unit" id="u-${id}">${unit ? " " + unit : ""}</tspan></text>
      ${cap != null ? `<text class="cap" y="${above ? -42 : 50}">${esc(cap)}</text>` : ""}</g>`;
  }
  _flowHtml() {
    const f = this._flow(), t = this.t, h = f.has, gc = (f.grid || 0) < -NOISE_W ? "#3ddc97" : "#6ea8fe", r = 38, c = 2 * Math.PI * r;
    const [pv, pvu] = this._split(f.pv), [ho, hou] = this._split(f.house), [gr, gru] = this._split(f.grid), [ev, evu] = this._split(f.ev);
    const ring = `<circle r="${r}" fill="none" stroke="#a78bfa" stroke-width="2.5" stroke-linecap="round" stroke-dasharray="${c}" stroke-dashoffset="${c * (1 - (f.soc || 0) / 100)}" transform="rotate(-90)" id="soc"/>`;
    const sc = cardSceneInfo(this._hass, this._config);
    return `<div class="flow">${cardSceneSvg(sc)}<svg class="dia" viewBox="-20 -20 400 352"><defs><filter id="sc-blur2" x="-80%" y="-80%" width="260%" height="260%"><feGaussianBlur stdDeviation="2"/></filter><filter id="sc-blur4" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="4"/></filter><filter id="g${this._uid}" filterUnits="userSpaceOnUse" x="-40" y="-40" width="480" height="430"><feGaussianBlur stdDeviation="2" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter></defs>
      ${h.pv ? '<path class="base" d="M180 74 L180 116"/>' : ""}${h.grid ? '<path class="base" d="M286 150 L214 150"/>' : ""}
      ${h.battery ? '<path class="base" d="M74 150 L146 150"/>' : ""}${h.ev ? '<path class="base" d="M180 184 L180 228"/>' : ""}
      ${flowBeams(f, "g" + this._uid)}
      ${h.pv ? this._node("sun", 180, 40, "#f5b544", pv, pvu, t.sun.toUpperCase(), "", true, (f.pv || 0) > 30, cardSunIcon(sc)) : ""}
      ${h.grid ? this._node("grid", 320, 150, gc, gr, gru, (f.grid < -NOISE_W ? t.sell : f.grid > NOISE_W ? t.buy : t.grid).toUpperCase(), "", false, Math.abs(f.grid || 0) > NOISE_W) : ""}
      ${this._node("house", 180, 150, "var(--ep-house)", ho, hou, null, cardHouseRing(sc), false, true)}
      ${h.battery ? this._node("battery", 40, 150, "#a78bfa", this._n(f.soc, 0), "%", (f.batt > NOISE_W ? t.charging : f.batt < -NOISE_W ? t.discharging : t.idle).toUpperCase(), ring, false, Math.abs(f.batt || 0) > NOISE_W) : ""}
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
    const state = f.batt > NOISE_W ? `${t.charging} ${this._split(f.batt).join(" ")}` : f.batt < -NOISE_W ? `${t.discharging} ${this._split(f.batt).join(" ")}` : t.idle;
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
      ${ev.soc_known ? this._evSoc(ev) : ""}
      ${e.ev_cap && !ev.soc_known ? `<div class="ctl"><b>${t.atMost}</b><span class="rg"><input type="range" min="0" max="${this._hass.states[e.ev_cap]?.attributes.max || 100}" value="${this._hass.states[e.ev_cap]?.state}" data-cap="${e.ev_cap}"><i id="capv">${this._n(this._num(e.ev_cap), 0)} kWh</i></span></div>` : ""}
    </div>`;
  }
  _evSoc(ev) {
    // The car's level with the target as a mark; the target and the trip through Energy Pilot's own entities.
    const E = this.t.evs, h = this._hass, ids = Object.keys(h.states);
    const to = ids.find((x) => x.startsWith("number.") && x.endsWith("charge_to")), trip = ids.find((x) => x.startsWith("switch.") && x.endsWith("next_trip"));
    const soc = ev.soc;
    return `<div class="ctl"><b>${E.soc}</b><span style="font-size:20px;font-weight:700">${soc != null ? this._n(soc, 0) : "–"}<small style="font-size:12px"> %</small></span></div>
      <div class="evb"><span style="width:${soc ?? 0}%"></span><i style="left:${ev.target}%"></i></div>
      ${to ? `<div class="ctl"><b>${E.to}</b><span class="seg">${[70, 80, 90, 100].map((v) => `<button data-to="${to}" data-v="${v}" class="${!ev.trip && ev.everyday === v ? "on" : ""}">${v}</button>`).join("")}</span></div>` : ""}
      ${trip ? `<div class="ctl"><b>${E.trip}</b><button class="tg ${ev.trip ? "on" : ""}" data-sw="${trip}"></button></div>` : ""}`;
  }
  _planHtml(inline = false) {
    const a = this._hass.states[SENSOR].attributes, t = this.t, hrs = (a.plan || []).filter((h) => h.price != null || h.sun != null);
    if (!hrs.length) return "";
    const W = 18, H = 150, top = 10, bot = 22, width = hrs.length * W, y0 = H - bot, ph = H - top - bot;
    const pmin = Math.min(0, a.price_min ?? 0), pmax = (a.price_max || 1) * 1.08, emax = Math.max(1, ...hrs.map((h) => Math.max(h.sun || 0, h.house || 0))) * 1.15;
    const now = new Date(), col = (p) => { const x = (p - a.price_min) / Math.max(0.01, a.price_max - a.price_min); return `hsl(${Math.round(150 - 150 * x)} 70% ${x > .66 ? 60 : 52}%)`; };
    let ni = -1;
    const bars = hrs.map((h, i) => {
      const d = new Date(h.t), bh = h.price != null ? ((h.price - pmin) / (pmax - pmin)) * ph : 0, cur = d.getHours() === now.getHours() && d.getDate() === now.getDate();
      if (cur) ni = i;
      return `${h.price != null ? `<rect x="${i * W + 4}" y="${y0 - bh}" width="${W - 8}" height="${bh}" rx="2.5" fill="${col(h.price)}" opacity="${d < now && !cur ? .25 : .85}"/>` : ""}
        ${h.charge ? `<rect x="${i * W + 4}" y="${y0 + 3}" width="${W - 8}" height="3" rx="1.5" fill="var(--batt)"/>` : ""}
        ${h.export ? `<rect x="${i * W + 4}" y="${y0 + 3}" width="${W - 8}" height="3" rx="1.5" fill="var(--grid)"/>` : ""}
        ${h.car ? `<rect x="${i * W + 4}" y="${y0 + 8}" width="${W - 8}" height="3" rx="1.5" fill="var(--car)"/>` : ""}
        ${d.getHours() % 6 === 0 ? `<text class="ax" x="${i * W + W / 2}" y="${H - 3}">${String(d.getHours()).padStart(2, "0")}</text>` : ""}
        ${d.getHours() === 0 && i ? `<line x1="${i * W}" x2="${i * W}" y1="${top}" y2="${y0}" class="day"/>` : ""}`;
    }).join("");
    const pts = (k) => hrs.map((h, i) => h[k] != null ? `${(i * W + W / 2).toFixed(1)},${(y0 - (h[k] / emax) * ph).toFixed(1)}` : null).filter(Boolean);
    const soc = hrs.map((h, i) => h.soc != null ? `${(i * W + W / 2).toFixed(1)},${(y0 - (h.soc / 100) * ph).toFixed(1)}` : null).filter(Boolean);
    const L = t.leg, dot = (c, x) => `<span><i style="background:${c}"></i>${x}</span>`;
    const legend = `<div class="lg">${dot("linear-gradient(90deg,hsl(150 70% 52%),hsl(0 70% 60%))", L.price)}${dot("var(--sun)", L.sun)}${dot("var(--ep-house)", L.house)}${soc.length > 1 ? dot("var(--batt)", L.soc) : ""}${hrs.some((h) => h.car) ? dot("var(--car)", L.car) : ""}${hrs.some((h) => h.export) ? dot("var(--grid)", L.export) : ""}</div>`;
    const sun = pts("sun"), house = pts("house"), nx = ni >= 0 ? ni * W + (now.getMinutes() / 60) * W : null;
    return `<div class="${inline ? "sec" : "pad"}"><div class="eyebrow">${t.plan}<span>${(a.cheapest || []).slice(0, 3).map((c) => new Date(c).getHours().toString().padStart(2, "0") + ":00").join(" · ")}</span></div>
      <div class="pw"><svg width="${width}" height="${H}" viewBox="0 0 ${width} ${H}"><defs><linearGradient id="s${this._uid}" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="#f5b544" stop-opacity=".35"/><stop offset="1" stop-color="#f5b544" stop-opacity="0"/></linearGradient></defs>
        ${bars}${sun.length > 1 ? `<polygon points="${sun[0].split(",")[0]},${y0} ${sun.join(" ")} ${sun[sun.length - 1].split(",")[0]},${y0}" fill="url(#s${this._uid})"/><polyline points="${sun.join(" ")}" fill="none" stroke="#f5b544" stroke-width="1.8"/>` : ""}
        ${house.length > 1 ? `<polyline points="${house.join(" ")}" fill="none" stroke="var(--ep-house)" stroke-width="1.4" stroke-dasharray="4 3" opacity=".8"/>` : ""}
        ${soc.length > 1 ? `<polyline points="${soc.join(" ")}" fill="none" stroke="var(--batt)" stroke-width="2.2" stroke-linejoin="round"/>` : ""}
        ${nx != null ? `<line x1="${nx}" x2="${nx}" y1="2" y2="${y0}" stroke="var(--primary-text-color)" stroke-width="1.3"/>` : ""}</svg></div>${legend}</div>`;
  }

  _wire() {
    const r = this.shadowRoot, h = this._hass;
    r.querySelectorAll("[data-toggle]").forEach((b) => b.onclick = () => { const on = !b.classList.contains("on"); b.classList.toggle("on", on); h.callService("input_boolean", on ? "turn_on" : "turn_off", { entity_id: b.dataset.toggle }); });
    r.querySelectorAll("[data-to]").forEach((b) => b.onclick = () => h.callService("number", "set_value", { entity_id: b.dataset.to, value: Number(b.dataset.v) }));
    r.querySelectorAll("[data-sw]").forEach((b) => b.onclick = () => { const on = !b.classList.contains("on"); b.classList.toggle("on", on); h.callService("switch", on ? "turn_on" : "turn_off", { entity_id: b.dataset.sw }); });
    r.querySelectorAll("[data-time]").forEach((i) => i.onchange = () => h.callService("input_datetime", "set_datetime", { entity_id: i.dataset.time, time: i.value + ":00" }));
    r.querySelectorAll("[data-cap]").forEach((i) => { i.oninput = () => (r.getElementById("capv").textContent = `${i.value} kWh`); i.onchange = () => h.callService("input_number", "set_value", { entity_id: i.dataset.cap, value: Number(i.value) }); });
    // The plan opens at the time now, not at midnight. The card is often drawn before Home Assistant shows it
    // (no width yet), so it waits until it has one.
    const toNow = (tries = 0) => {
      const pw = r.querySelector(".pw"), nl = pw?.querySelector("line[stroke-width='1.3']");
      if (!pw || !nl) return;
      if (!pw.clientWidth) { if (tries < 40) setTimeout(() => toNow(tries + 1), 150); return; }
      const svg = pw.querySelector("svg"), vb = svg?.viewBox?.baseVal, scale = vb && vb.width ? svg.getBoundingClientRect().width / vb.width : 1;
      pw.scrollLeft = Math.max(0, Number(nl.getAttribute("x1")) * scale - pw.clientWidth / 3);
    };
    requestAnimationFrame(() => toNow());
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
  .flow { padding:8px 10px 0; position:relative; overflow:hidden; } .flow svg.dia { width:100%; height:auto; display:block; overflow:visible; position:relative; }
  .flow > svg.scene { position:absolute; inset:0; width:100%; height:100%; pointer-events:none; }
  .sc-twinkle { animation:sctw 3.2s ease-in-out infinite; } @keyframes sctw { 50% { opacity:.25; } }
  .sc-breathe { animation:scbr 4s ease-in-out infinite; } @keyframes scbr { 50% { opacity:.12; } }
  .sc-fall { animation:scfall 12s linear infinite; } @keyframes scfall { from { transform:translate(0,0) rotate(var(--r,0deg)); } to { transform:translate(30px,420px) rotate(calc(var(--r,0deg) + 200deg)); } }
  .sc-rain { animation:scrain 1.1s linear infinite; } @keyframes scrain { to { transform:translate(-14px,390px); } }
  .sc-rise { animation:scrise 9s ease-out infinite; } @keyframes scrise { from { transform:translate(0,0); opacity:.8; } to { transform:translate(18px,-300px); opacity:0; } }
  .sc-float { animation:scfl 12s ease-in-out infinite alternate; } @keyframes scfl { to { transform:translate(22px,-16px); } }
  .sc-drift { animation:scdr 30s ease-in-out infinite alternate; } @keyframes scdr { to { transform:translateX(40px); } }
  .sc-burst { animation:scbu 2.8s ease-out infinite; opacity:0; } @keyframes scbu { 0% { transform:scale(.1); opacity:0; } 12% { opacity:1; } 70% { transform:scale(1); opacity:.8; } 100% { transform:scale(1.1); opacity:0; } }
  .sc-flash { opacity:0; animation:scfla 9s linear infinite; } @keyframes scfla { 0%,93%,100% { opacity:0; } 94% { opacity:.4; } 96% { opacity:.25; } }
  @media (prefers-reduced-motion: reduce) { .sc-twinkle, .sc-breathe, .sc-fall, .sc-rain, .sc-rise, .sc-float, .sc-drift, .sc-burst, .sc-flash { animation:none !important; } .sc-burst { opacity:.8; } }
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
  .evb { position:relative; height:7px; border-radius:5px; background:var(--secondary-background-color, rgba(127,127,127,.2)); margin:2px 0 10px; } .evb span { position:absolute; inset:0 auto 0 0; border-radius:5px; background:var(--car); }
  .evb i { position:absolute; top:-4px; width:2px; height:15px; margin-left:-1px; background:var(--primary-text-color); }
  .seg { display:inline-flex; gap:2px; background:var(--secondary-background-color, rgba(127,127,127,.15)); border-radius:9px; padding:2px; } .seg button { border:0; background:transparent; color:var(--secondary-text-color); padding:5px 8px; border-radius:7px; font:inherit; font-size:12px; font-weight:600; cursor:pointer; } .seg button.on { background:var(--primary-color, #03a9f4); color:var(--text-primary-color, #fff); }
  .lg { display:flex; flex-wrap:wrap; gap:4px 12px; margin-top:8px; font-size:11px; color:var(--secondary-text-color); } .lg span { display:flex; align-items:center; gap:5px; } .lg i { width:10px; height:3px; border-radius:2px; display:inline-block; }
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
