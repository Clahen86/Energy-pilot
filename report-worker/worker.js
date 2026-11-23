// Energy Pilot receiver - a Cloudflare Worker. Three jobs:
//
// Apps: Energy Pilot ⚡, Madplan 🍽️, Replace Device 🔁, Update Guard 🛡️, Database Doctor 🩺, Heat Pilot 🔥, House Chat 💬, Appliance Watch 🧺 (header x-ep-client).
//
// 1. "Get help" (POST /): a test result, the diagnostics and up to 3 pictures, sent when the user presses the
//    button. Stored in a PRIVATE GitHub repository with an issue, so only the developer sees it.
// 2. Learning together (POST /t): small anonymous lines from every installation that hasn't turned it off - which
//    brands work, what the self-test mended, errors in the app, and a daily summary (version, country, what the
//    house has, savings per month rounded). Never names, places, or use hour by hour. Counted in a D1 database.
//    When 3 installations found the same fix, it is confirmed and every installation with that brand gets it
//    (GET /fixes); the developer gets an issue. New app errors also give an issue.
// 3. Every Monday (cron): one issue with the week's overview.
// 4. Answers (POST /replies, POST /reply): write a comment on a help report's issue and the app that sent it shows
//    it to the user (it asks every hour with its own install id - nobody else can read it). The user can write back
//    from the app: that becomes a new comment on the same issue, and a closed issue opens again.
//    A comment on an app-error issue reaches every installation that had that error (no writing back - nobody in
//    particular sent it).
//
// Settings (Workers -> your worker -> Settings):
//   GITHUB_TOKEN  (secret) fine-grained token: Contents + Issues read/write on the private repository only
//   REPORT_REPO   (text)   owner/name of the private repository, e.g. Clahen86/energy-pilot-reports
//   DB            (D1 binding) a D1 database - the tables are made by the worker itself
//   Trigger: Cron  0 7 * * 1  (Mondays 07:00 UTC) for the weekly overview

const MAX_BYTES = 9_000_000; // a diagnostics file is usually 50-300 kB, plus up to 3 pictures
const PER_HOUR = 5; // help reports from one address per hour
const T_PER_HOUR = 60; // small lines from one address per hour
const CONFIRM = 3; // installations that must find the same fix before everyone gets it
// The apps that may send - each gets its own label and mark, so the issues can be told apart (filter by label).
// prefix: what an app's error hashes start with in the shared errors table (Energy Pilot's are plain hex).
const APPS = {
  "energy-pilot": { label: "energy-pilot", mark: "⚡", name: "Energy Pilot", prefix: "" },
  madplan: { label: "madplan", mark: "🍽️", name: "Madplan", prefix: "m" },
  "replace-device": { label: "replace-device", mark: "🔁", name: "Replace Device", prefix: "rd:" },
  "update-guard": { label: "update-guard", mark: "🛡️", name: "Update Guard", prefix: "ug:" },
  "database-doctor": { label: "database-doctor", mark: "🩺", name: "Database Doctor", prefix: "dd:" },
  "heat-pilot": { label: "heat-pilot", mark: "🔥", name: "Heat Pilot", prefix: "hp:" },
  "hus-chat": { label: "hus-chat", mark: "💬", name: "House Chat", prefix: "hc:" },
  "appliance-watch": { label: "appliance-watch", mark: "🧺", name: "Appliance Watch", prefix: "aw:" },
};
// SQL that keeps one app's rows of the errors table (column c).
const ofApp = (app, c = "hash") => app === "energy-pilot" ? `${c} NOT LIKE 'm%' AND ${c} NOT LIKE '%:%'` : `${c} LIKE '${APPS[app].prefix}%'`;

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/fixes") return fixes(env);
    if (request.method === "GET" && url.pathname === "/stats") return stats(url, env);
    if (request.method === "GET" && url.pathname === "/approve") return approve(url, env);
    if (request.method === "GET" && url.pathname === "/export") return exportHours(url, env);
    if (request.method === "GET") return json({ ok: true, service: "energy-pilot-reports" });
    if (request.method !== "POST") return json({ error: "method" }, 405);
    if (url.pathname === "/models") return putModels(request, env);
    const app = request.headers.get("x-ep-client");
    if (!APPS[app]) return json({ error: "client" }, 403);
    if (url.pathname === "/t") return telemetry(request, env, app);
    if (url.pathname === "/replies") return replies(request, env, app);
    if (url.pathname === "/reply") return userReply(request, env, app);
    if (url.pathname === "/sky" && app === "energy-pilot") return sky(request, env);
    return report(request, env, app);
  },
  async scheduled(_event, env) {
    try { await env.DB.prepare("DELETE FROM hours WHERE day < ?1").bind(new Date(Date.now() - 400 * 864e5).toISOString().slice(0, 10)).run(); } catch { /* not there yet */ }
    try { await env.DB.prepare("DELETE FROM sky WHERE t < ?1").bind(Date.now() - 2 * 3600e3).run(); } catch { /* not there yet */ }
    try { await env.DB.prepare("DELETE FROM seen WHERE day < ?1").bind(new Date(Date.now() - 120 * 864e5).toISOString().slice(0, 10)).run(); } catch { /* not there yet */ }
    await weekly(env);
  },
};

// ---------- 1. Get help ----------
async function report(request, env, app = "energy-pilot") {
  const A = APPS[app];
  const size = Number(request.headers.get("content-length") || 0);
  if (size > MAX_BYTES) return json({ error: "too_big" }, 413);
  if (!(await allowed(request, "r", PER_HOUR))) return json({ error: "rate" }, 429);
  let body;
  try {
    const text = await request.text();
    if (text.length > MAX_BYTES) return json({ error: "too_big" }, 413);
    body = JSON.parse(text);
  } catch {
    return json({ error: "json" }, 400);
  }
  const diag = body.diagnostics;
  if (!diag || typeof diag !== "object" || !diag.version || (app === "energy-pilot" && !diag.settings)) return json({ error: "content" }, 400);

  const id = `${new Date().toISOString().slice(0, 10).replaceAll("-", "")}-${crypto.randomUUID().slice(0, 6)}`;
  const gh = github(env);
  const base = `https://github.com/${env.REPORT_REPO}/blob/main`;
  const pics = [];
  for (const [n, img] of (Array.isArray(body.images) ? body.images.slice(0, 3) : []).entries()) {
    if (!img || typeof img.data !== "string" || img.data.length > 3_000_000) continue;
    const name = `reports/${app}/${id}-${n + 1}.jpg`;
    const r = await gh(`contents/${name}`, "PUT", { message: `Report ${id} picture ${n + 1}`, content: img.data });
    if (r.ok) pics.push(`![${String(img.name || "picture").replaceAll("]", "")}](${base}/${name}?raw=true)`);
  }
  delete body.images;
  const file = `reports/${app}/${id}.json`;
  const put = await gh(`contents/${file}`, "PUT", { message: `Report ${id}`, content: b64(JSON.stringify(body, null, 1)) });
  if (!put.ok) return json({ error: "store", status: put.status }, 502);

  const t = body.test || {};
  const results = (t.results || []).map((r) => `| ${r.part} | ${r.step} | ${mark(r.result)} | ${detail(r)} |`);
  const lines = [
    `**${id}** · ${A.name} ${diag.version}${body.profile ? ` · profile \`${body.profile}\`` : ""} · ${diag.ha?.country || "?"}`,
    "",
    body.note ? `> ${String(body.note).slice(0, 4000).replaceAll("\n", "\n> ")}\n` : "",
    pics.length ? `${pics.join("\n")}\n` : "",
    results.length ? ["| Part | Step | Result | Details |", "|---|---|---|---|", ...results].join("\n") : "_No test result - diagnostics only._",
    "",
    `Diagnostics: [${file}](${base}/${file})${body.lang ? ` · language ${body.lang}` : ""}`,
  ];
  const failed = (t.results || []).some((r) => r.result === "failed");
  const issue = await gh("issues", "POST", {
    title: `${A.mark} ${A.name}: ${failed ? "❌" : t.results?.length ? "✅" : "📄"} ${body.profile || "report"} · ${diag.version} · ${id}`,
    body: lines.join("\n") + "\n\n_Comments here reach the user in the app._", labels: [A.label, failed ? "test-failed" : "report"],
  });
  const made = issue.ok ? await issue.json() : {};
  const install = String(body.install || diag.settings?.install_id || "").slice(0, 40);
  if (made.number && env.DB && /^[a-f0-9-]{16,40}$/.test(install)) {
    await schema(env);
    await env.DB.prepare("INSERT OR REPLACE INTO reports (id, app, issue, install, day) VALUES (?1, ?2, ?3, ?4, ?5)")
      .bind(id, app, made.number, install, new Date().toISOString().slice(0, 10)).run();
  }
  return json({ ok: true, id, issue: made.number || null });
}

// ---------- 2. Learning together ----------
let schemaReady = false;
async function schema(env) {
  if (schemaReady || !env.DB) return;
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS installs (id TEXT PRIMARY KEY, first_seen TEXT, last_seen TEXT, data TEXT)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS fixes (profile TEXT, intent TEXT, opt_from TEXT, opt_to TEXT, install TEXT, day TEXT, PRIMARY KEY (profile, intent, opt_from, opt_to, install))"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS confirmed (profile TEXT, intent TEXT, opt_from TEXT, opt_to TEXT, day TEXT, PRIMARY KEY (profile, intent, opt_from, opt_to))"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS tests (install TEXT, part TEXT, profile TEXT, model TEXT, day TEXT, ok INTEGER, failed TEXT, PRIMARY KEY (install, part, profile))"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS errors (hash TEXT PRIMARY KEY, first_seen TEXT, last_seen TEXT, count INTEGER, version TEXT, text TEXT)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS error_installs (hash TEXT, install TEXT, PRIMARY KEY (hash, install))"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS autofix (key TEXT, install TEXT, day TEXT, PRIMARY KEY (key, install))"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS m_installs (id TEXT PRIMARY KEY, first_seen TEXT, last_seen TEXT, data TEXT)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS m_offers (day TEXT, chain TEXT, install TEXT, n INTEGER, PRIMARY KEY (day, chain, install))"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS m_alerts (day TEXT, chain TEXT, PRIMARY KEY (day, chain))"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS m_nomatch (term TEXT, install TEXT, day TEXT, PRIMARY KEY (term, install))"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS reports (id TEXT PRIMARY KEY, app TEXT, issue INTEGER, install TEXT, day TEXT)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS error_issues (hash TEXT PRIMARY KEY, issue INTEGER)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS seen (app TEXT, install TEXT, day TEXT, country TEXT, PRIMARY KEY (app, install, day))"),
    // how each installation is set up (the daily question; names cleaned unless the user shares them): the newest only
    env.DB.prepare("CREATE TABLE IF NOT EXISTS observed (install TEXT, profile TEXT, model TEXT, intent TEXT, day TEXT, PRIMARY KEY (install, profile, intent))"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS hours (install TEXT, day TEXT, data TEXT, PRIMARY KEY (install, day))"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS sky (install TEXT PRIMARY KEY, cell TEXT, lat REAL, lon REAL, t INTEGER, ratio REAL, down INTEGER)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS setups (app TEXT, install TEXT, day TEXT, data TEXT, PRIMARY KEY (app, install))"),
  ]);
  try { await env.DB.prepare("ALTER TABLE seen ADD COLUMN version TEXT").run(); } catch { /* there already */ }
  try { await env.DB.prepare("ALTER TABLE tests ADD COLUMN version TEXT").run(); } catch { /* there already */ }
  // A confirmed fix goes out only once the developer has approved it (stats page): an install id is just text the app
  // makes, so "3 homes" could be one person - and a fix could otherwise turn charging into selling for every home.
  try { await env.DB.prepare("ALTER TABLE confirmed ADD COLUMN approved INTEGER DEFAULT 0").run(); } catch { /* there already */ }
  schemaReady = true;
}

async function telemetry(request, env, app = "energy-pilot") {
  if (!env.DB) return json({ error: "no_db" }, 503);
  if (!(await allowed(request, "t", T_PER_HOUR))) return json({ error: "rate" }, 429);
  let b;
  try {
    const text = await request.text();
    if (text.length > 50_000) return json({ error: "too_big" }, 413);
    b = JSON.parse(text);
  } catch {
    return json({ error: "json" }, 400);
  }
  const install = String(b.install || "").slice(0, 40);
  if (!/^[a-f0-9-]{16,40}$/.test(install)) return json({ error: "install" }, 400);
  await schema(env);
  await markSeen(env, request, app, install);
  const day = new Date().toISOString().slice(0, 10), db = env.DB;
  const s = (v, n = 80) => (v == null ? null : String(v).slice(0, n));
  if (app === "madplan") return madplan(env, b, install, day, s);
  if (app !== "energy-pilot") return otherApp(env, b, install, day, s, app);

  if (b.kind === "daily") {
    const data = JSON.stringify(b.data || {}).slice(0, 20_000);
    await db.prepare("INSERT INTO installs (id, first_seen, last_seen, data) VALUES (?1, ?2, ?2, ?3) ON CONFLICT(id) DO UPDATE SET last_seen = ?2, data = ?3")
      .bind(install, day, data).run();
  } else if (b.kind === "test") {
    for (const part of ["battery", "car"]) {
      const res = (b.results || []).filter((r) => r.part === part);
      if (!res.length) continue;
      const failed = res.filter((r) => r.result === "failed")
        .map((r) => `${r.step}:${s(r.why, 30)}${r.offline ? "@" + s(r.offline, 50) : ""}`).join(",");
      await db.prepare("INSERT OR REPLACE INTO tests (install, part, profile, model, day, ok, failed, version) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)")
        .bind(install, part, s(part === "car" ? b.charger : b.profile), s(b.model), day, failed ? 0 : 1, failed || null, s(b.version, 20)).run();
    }
    for (const r of (b.results || []).filter((x) => x.result === "fixed" && (x.part === "battery" || x.part === "car"))) {
      // a charger's fixes are kept under "car:<integration>" (Energy Pilot's control.py looks them up so)
      const prof = r.part === "car" ? (b.charger ? `car:${s(b.charger, 60)}` : null) : s(b.profile);
      if (!prof) continue;
      const key = [prof, s(r.step, 20), s(r.option_from), s(r.option_to)];
      await db.prepare("INSERT OR IGNORE INTO fixes (profile, intent, opt_from, opt_to, install, day) VALUES (?1, ?2, ?3, ?4, ?5, ?6)")
        .bind(...key, install, day).run();
      const n = (await db.prepare("SELECT COUNT(*) AS n FROM fixes WHERE profile = ?1 AND intent = ?2 AND opt_from = ?3 AND opt_to = ?4").bind(...key).first()).n;
      if (n >= CONFIRM) {
        const fresh = await db.prepare("INSERT OR IGNORE INTO confirmed (profile, intent, opt_from, opt_to, day) VALUES (?1, ?2, ?3, ?4, ?5)").bind(...key, day).run();
        if (fresh.meta?.changes) {
          await github(env)("issues", "POST", { title: `⚡ Energy Pilot: 🔧 confirmed fix ${key[0]} · ${key[1]}: ${key[2]} → ${key[3]}`, labels: ["energy-pilot", "confirmed-fix"],
            body: `${n} installations with profile \`${key[0]}\` found that **${key[1]}** works with \`${key[3]}\` instead of \`${key[2]}\`.\n\nIt is handed out only once approved on the stats page ("Fixes to approve"). Check it first, then put it in the profile in \`adapters.py\` so new users have it from the start.` });
        }
      }
    }
  } else if (b.kind === "error") {
    const hash = s(b.hash, 40), text = s(b.text, 300);
    if (!hash) return json({ error: "hash" }, 400);
    const known = await db.prepare("SELECT count FROM errors WHERE hash = ?1").bind(hash).first();
    await db.prepare("INSERT INTO errors (hash, first_seen, last_seen, count, version, text) VALUES (?1, ?2, ?2, 1, ?3, ?4) ON CONFLICT(hash) DO UPDATE SET last_seen = ?2, count = count + 1, version = ?3")
      .bind(hash, day, s(b.version, 20), text).run();
    const added = await db.prepare("INSERT OR IGNORE INTO error_installs (hash, install) VALUES (?1, ?2)").bind(hash, install).run();
    if (known && added.meta?.changes) {
      // Seen in a second installation: the label "autofix" starts the GitHub Action that tries a fix as a pull request
      // (.github/workflows/autofix.yml) - the developer merges it or not. Never for an error only one home had.
      const n = (await db.prepare("SELECT COUNT(*) AS n FROM error_installs WHERE hash = ?1").bind(hash).first()).n;
      const iss = await db.prepare("SELECT issue FROM error_issues WHERE hash = ?1").bind(hash).first();
      if (n === 2 && iss?.issue) {
        try { await github(env)(`issues/${iss.issue}/labels`, "POST", { labels: ["autofix"] }); } catch { /* the issue stays as it is */ }
      }
    }
    if (!known) {
      const r = await github(env)("issues", "POST", { title: `⚡ Energy Pilot: 🐞 ${s(b.text, 80)}`, labels: ["energy-pilot", "app-error"],
        body: `First seen ${day} in version ${s(b.version, 20)}.\n\n\`\`\`\n${text}\n\`\`\`\n\n_Comments here reach every installation that had this error._` });
      await rememberIssue(db, hash, r);
    }
  } else if (b.kind === "observed") {
    // An order that worked in daily control (Energy Pilot's control._observe) - counts like a passed test step
    const prof = s(b.profile, 60), intent = s(b.intent, 20);
    if (!prof || !["charge", "hold", "normal", "export"].includes(intent)) return json({ error: "observed" }, 400);
    await db.prepare("INSERT OR REPLACE INTO observed (install, profile, model, intent, day) VALUES (?1, ?2, ?3, ?4, ?5)")
      .bind(install, prof, s(b.model), intent, day).run();
  } else if (b.kind === "hours") {
    // Yesterday hour by hour (Energy Pilot's telemetry.hours_line) - kept for the models trained on all houses
    const d = String(b.day || "").slice(0, 10);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(d) || !Array.isArray(b.hours)) return json({ error: "hours" }, 400);
    const n = (v) => (Number.isFinite(Number(v)) && v !== null ? Math.round(Number(v) * 1000) / 1000 : null);
    const pair = (v) => (Array.isArray(v) ? [n(v[0]), n(v[1])] : [null, null]);
    const rows = b.hours.slice(0, 25).map((r) => ({ h: n(r.h), house: pair(r.house), sun: pair(r.sun), soc: pair(r.soc), price: n(r.price) }));
    await db.prepare("INSERT OR REPLACE INTO hours (install, day, data) VALUES (?1, ?2, ?3)").bind(install, d, JSON.stringify(rows)).run();
  } else if (b.kind === "autofix") {
    await db.prepare("INSERT OR IGNORE INTO autofix (key, install, day) VALUES (?1, ?2, ?3)").bind(s(b.key, 40), install, day).run();
  } else {
    return json({ error: "kind" }, 400);
  }
  return json({ ok: true });
}

// The developer approves (or drops) a confirmed fix from the stats page - only approved ones are handed out.
async function approve(url, env) {
  if (!env.STATS_KEY || url.searchParams.get("key") !== env.STATS_KEY) return new Response("Not found", { status: 404 });
  await schema(env);
  const p = url.searchParams, key = [p.get("profile"), p.get("intent"), p.get("from"), p.get("to")];
  if (key.some((x) => !x)) return new Response("Missing", { status: 400 });
  if (p.get("no") === "1") await env.DB.prepare("DELETE FROM confirmed WHERE profile = ?1 AND intent = ?2 AND opt_from = ?3 AND opt_to = ?4").bind(...key).run();
  else await env.DB.prepare("UPDATE confirmed SET approved = 1 WHERE profile = ?1 AND intent = ?2 AND opt_from = ?3 AND opt_to = ?4").bind(...key).run();
  return Response.redirect(`${url.origin}/stats?key=${encodeURIComponent(env.STATS_KEY)}`, 302);
}

async function fixes(env) {
  if (!env.DB) return json({ fixes: [], tested: {} });
  // Emergency stop: the variable COMMON_OFF = 1 (Cloudflare: Settings > Variables) hands out no shared knowledge at
  // all - every Energy Pilot drops what it had at its next daily fetch and runs on its own learning.
  const off = String(env.COMMON_OFF || "") === "1";
  await schema(env);
  const f = await env.DB.prepare("SELECT profile, intent, opt_from AS 'from', opt_to AS 'to' FROM confirmed WHERE approved = 1").all();
  const t = await env.DB.prepare("SELECT profile, SUM(ok) AS ok, COUNT(*) AS n FROM tests GROUP BY profile").all();
  const tested = Object.fromEntries((t.results || []).map((r) => [r.profile, { ok: r.ok, n: r.n }]));
  // orders that worked in daily control, per profile: how many installations saw each (last 60 days)
  try {
    const o = await env.DB.prepare("SELECT profile, intent, COUNT(DISTINCT install) AS n FROM observed WHERE day >= ?1 GROUP BY profile, intent")
      .bind(new Date(Date.now() - 60 * 864e5).toISOString().slice(0, 10)).all();
    for (const r of o.results || []) ((tested[r.profile] = tested[r.profile] || { ok: 0, n: 0 }).seen = tested[r.profile].seen || {})[r.intent] = r.n;
  } catch { /* none yet */ }
  let common = {};
  if (!off) try { common = await sharedKnowledge(env); } catch { /* never in the way of the fixes */ }
  try {
    const row = await env.DB.prepare("SELECT v FROM meta WHERE k = 'models'").first();
    const models = row ? safe(row.v).m : null;
    if (models && models.sensors && !off) common = { ...common, sensors: models.sensors };
  } catch { /* none yet */ }
  return new Response(JSON.stringify({ fixes: f.results || [], tested, common }), {
    headers: { "content-type": "application/json", "cache-control": "public, max-age=3600" } });
}

// Shared knowledge: what installations have learned themselves (the daily line's "learned"), added up once a day so a
// new installation can start from it. Only groups of at least CONFIRM installations that agree (the middle half
// within 25 % of the median) - a spread-out group says nothing about the next house.
const TAPER_BANDS = [98, 95, 90, 85]; // the levels Energy Pilot watches charging at (blend.py)
const OWN_DAYS = 14; // an installation's own learning counts from this many days
// The group "houses like this one" (the same in Energy Pilot's common.peer_key)
const peerKey = (d) => d.country && Number(d.battery_kwh) > 0
  ? `${d.country}|${Math.round(Number(d.battery_kwh) / 5) * 5}|${(d.has || {}).car ? "car" : "nocar"}` : null;
async function sharedKnowledge(env) {
  const row = await env.DB.prepare("SELECT v FROM meta WHERE k = 'common'").first();
  const old = row ? safe(row.v) : null;
  if (old && Date.now() - old.t < 864e5) return old.c;
  const since = new Date(Date.now() - 30 * 864e5).toISOString().slice(0, 10);
  const week = new Date(Date.now() - 7 * 864e5).toISOString().slice(0, 10); // a week old at least (see sky())
  const rows = (await env.DB.prepare("SELECT data, last_seen FROM installs WHERE last_seen >= ?1 AND first_seen <= ?2").bind(since, week).all()).results || [];
  const sun = {}, eff = {}, taper = {}, peers = {}, health = {}, tariffs = {}, tunes = {};
  const recent = new Date(Date.now() - 2 * 864e5).toISOString().slice(0, 10);
  const add = (map, key, v) => { if (key && Number.isFinite(v)) (map[key] = map[key] || []).push(v); };
  for (const r of rows) {
    const d = safe(r.data) || {}, l = d.learned || {};
    if (d.country && d.sun_source && l.days >= OWN_DAYS && l.sun) {
      add(sun, `${d.country}|${d.sun_source}|cloudy`, Number(l.sun.cloudy));
      add(sun, `${d.country}|${d.sun_source}|clear`, Number(l.sun.clear));
    }
    if (d.profile && l.battery_type) add(eff, `${d.profile}|${l.battery_type}`, Number(l.eff));
    // Houses like this one: same country, battery size (5 kWh steps), car or not - what they saved this month so far
    // (only lines from the last two days, so the month has run as long for all), with and without a feature.
    const pk = peerKey(d);
    if (pk && r.last_seen >= recent && Number.isFinite(Number(d.saved_month))) {
      const g = (peers[pk] = peers[pk] || { all: [], f: {} }), v = Number(d.saved_month);
      g.all.push(v);
      for (const f of ["export", "targets"]) {
        const side = (d.features || {})[f] ? "on" : "off";
        ((g.f[f] = g.f[f] || { on: [], off: [] })[side]).push(v);
      }
    }
    // Its own settings, tested on its own days (tune.py) - per inverter profile and houses like this one: brands are never mixed
    if (d.profile && pk && l.tune) {
      const f = Number(l.tune.f), m = Number(l.tune.m);
      if (f >= 0.8 && f <= 1.25 && m >= -0.15 && m <= 0.3) (tunes[`${d.profile}|${pk}`] = tunes[`${d.profile}|${pk}`] || []).push([f, m]);
    }
    // The grid tariff typed in, per ~10 km cell (the same grid company, most likely)
    if (l.tariff && /^-?\d{1,2}\.\d\|-?\d{1,3}\.\d{2}$/.test(String(l.cell || ""))) {
      const tk = ["low", "high", "peak"].map((k) => Number(l.tariff[k]).toFixed(3)).join("|");
      const cellT = (tariffs[l.cell] = tariffs[l.cell] || {});
      cellT[tk] = (cellT[tk] || 0) + 1;
    }
    // The battery's health: usable kWh learned against the label, per model
    if (d.model && Number(l.cap) > 0 && Number(l.nominal) > 0) add(health, String(d.model), Number(l.cap) / Number(l.nominal));
    if (d.profile && d.model && Array.isArray(l.taper)) {
      // a level missing from an installation's curve means it charged at full speed there
      const seen = Object.fromEntries(l.taper.map(([lvl, sh]) => [String(lvl), Number(sh)]));
      for (const band of TAPER_BANDS) add(taper, `${d.profile}|${d.model}|${band}`, seen[band] ?? 1);
    }
  }
  const agreed = (vals, lo, hi) => {
    const v = vals.filter((x) => x >= lo && x <= hi).sort((a, b) => a - b);
    if (v.length < CONFIRM) return null;
    const q = (p) => v[Math.min(v.length - 1, Math.floor(p * (v.length - 1) + 0.5))], med = q(0.5);
    return (q(0.75) - q(0.25)) / med <= 0.25 ? { med: Math.round(med * 100) / 100, n: v.length } : null;
  };
  const c = { sun: {}, eff: {}, taper: {}, peers: {}, health: {}, tariff: {}, tune: {} };
  for (const key of new Set(Object.keys(sun).map((k) => k.replace(/\|(cloudy|clear)$/, "")))) {
    const cl = agreed(sun[`${key}|cloudy`] || [], 0.3, 2), cr = agreed(sun[`${key}|clear`] || [], 0.3, 2);
    if (cl && cr) c.sun[key] = { cloudy: cl.med, clear: cr.med, n: Math.min(cl.n, cr.n) };
  }
  for (const [key, vals] of Object.entries(eff)) {
    const a = agreed(vals, 0.7, 0.95);
    if (a) c.eff[key] = { eff: a.med, n: a.n };
  }
  for (const key of new Set(Object.keys(taper).map((k) => k.replace(/\|\d+$/, "")))) {
    const bands = TAPER_BANDS.map((b) => [b, agreed(taper[`${key}|${b}`] || [], 0.2, 1)]);
    if (bands.some(([, a]) => !a)) continue; // the curve only when every level agrees
    const curve = bands.filter(([, a]) => a.med < 0.95).map(([b, a]) => [b, a.med]).sort((x, y) => x[0] - y[0]);
    if (curve.length) c.taper[key] = { taper: curve, n: Math.min(...bands.map(([, a]) => a.n)) };
  }
  const med = (v) => { const s = [...v].sort((a, b) => a - b), n = s.length; return n % 2 ? s[(n - 1) / 2] : (s[n / 2 - 1] + s[n / 2]) / 2; };
  for (const [key, g] of Object.entries(peers)) {
    if (g.all.length < CONFIRM) continue;
    const out = { saved: Math.round(med(g.all)), n: g.all.length, features: {} };
    for (const [f, s] of Object.entries(g.f)) {
      if (s.on.length >= CONFIRM && s.off.length >= CONFIRM) out.features[f] = { on: Math.round(med(s.on)), off: Math.round(med(s.off)), n: s.on.length + s.off.length };
    }
    c.peers[key] = out;
  }
  for (const [cell, counts] of Object.entries(tariffs)) {
    const [tk, n] = Object.entries(counts).sort((a, b) => b[1] - a[1])[0];
    if (n < CONFIRM) continue; // at least three neighbours typed exactly the same
    const [low, high, peak] = tk.split("|").map(Number);
    c.tariff[cell] = { low, high, peak, n };
  }
  for (const [key, vals] of Object.entries(health)) {
    const v = vals.filter((x) => x >= 0.5 && x <= 1.1);
    if (v.length >= CONFIRM) c.health[key] = { ratio: Math.round(med(v) * 100) / 100, n: v.length };
  }
  // A start for new houses only where at least three agree: within one step (0.05) of the middle on both knobs, and
  // three in four of the group - a spread-out group hands out nothing.
  for (const [key, v] of Object.entries(tunes)) {
    if (v.length < CONFIRM) continue;
    const mf = med(v.map((x) => x[0])), mm = med(v.map((x) => x[1]));
    const near = v.filter(([f, m]) => Math.abs(f - mf) <= 0.051 && Math.abs(m - mm) <= 0.051).length;
    if (near >= CONFIRM && near * 4 >= v.length * 3) c.tune[key] = { f: Math.round(mf * 100) / 100, m: Math.round(mm * 100) / 100, n: near };
  }
  await env.DB.prepare("INSERT OR REPLACE INTO meta (k, v) VALUES ('common', ?1)").bind(JSON.stringify({ t: Date.now(), c })).run();
  return c;
}

// The sky network: every quarter of an hour an installation tells how its sun compares with its own forecast right now
// (and whether its grid is down), for a cell of about 10 x 10 km - never its position. It gets back the same for the
// cells around it from the last 20 minutes: clouds seen by houses upwind reach it later, and a grid that fails at
// several houses nearby may fail here too. Only cells with at least two installations are handed out.
const SKY_FRESH_MS = 20 * 60e3;
async function sky(request, env) {
  if (!env.DB || String(env.COMMON_OFF || "") === "1") return json({ near: [] });
  // 4 an hour per installation; room for a few behind one address (a shared connection)
  if (!(await allowed(request, "s", 30))) return json({ error: "rate" }, 429);
  let b;
  try { b = await request.json(); } catch { return json({ error: "json" }, 400); }
  const install = String(b.install || "").slice(0, 40), cell = String(b.cell || "");
  if (!/^[a-f0-9-]{16,40}$/.test(install)) return json({ error: "install" }, 400);
  const m = /^(-?\d{1,2}\.\d)\|(-?\d{1,3}\.\d{2})$/.exec(cell);
  if (!m) return json({ error: "cell" }, 400);
  const lat = Number(m[1]) + 0.05, lon = Number(m[2]) + 0.075; // the cell's middle
  if (Math.abs(lat) > 90 || Math.abs(lon) > 180) return json({ error: "cell" }, 400);
  const ratio = Number.isFinite(Number(b.ratio)) && b.ratio !== null ? Math.min(3, Math.max(0, Number(b.ratio))) : null;
  const down = b.down === true ? 1 : b.down === false ? 0 : null;
  await schema(env);
  const now = Date.now();
  await env.DB.prepare("INSERT OR REPLACE INTO sky (install, cell, lat, lon, t, ratio, down) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)")
    .bind(install, cell, lat, lon, now, ratio, down).run();
  // Only installations that have sent their daily line for at least a week count - a made-up one can't raise a
  // false power cut (which would have batteries charge at a dear hour) or fake clouds.
  const week = new Date(now - 7 * 864e5).toISOString().slice(0, 10);
  const rows = (await env.DB.prepare(
    "SELECT s.cell, s.lat, s.lon, s.ratio, s.down FROM sky s JOIN installs i ON i.id = s.install AND i.first_seen <= ?7 " +
    "WHERE s.t > ?1 AND s.install != ?2 AND s.lat BETWEEN ?3 AND ?4 AND s.lon BETWEEN ?5 AND ?6")
    .bind(now - SKY_FRESH_MS, install, lat - 0.8, lat + 0.8, lon - 1.4, lon + 1.4, week).all()).results || [];
  const cells = {};
  for (const r of rows) {
    const c = (cells[r.cell] = cells[r.cell] || { cell: r.cell, lat: r.lat, lon: r.lon, ratios: [], down: 0, reporting: 0 });
    if (r.ratio !== null) c.ratios.push(r.ratio);
    if (r.down !== null) { c.reporting += 1; c.down += r.down; }
  }
  const near = [];
  for (const c of Object.values(cells)) {
    const v = c.ratios.sort((x, y) => x - y), n = v.length;
    const out = { cell: c.cell, lat: c.lat, lon: c.lon, n, down: c.reporting >= 2 ? c.down : 0, reporting: c.reporting };
    if (n >= 2) out.ratio = Math.round((n % 2 ? v[(n - 1) / 2] : (v[n / 2 - 1] + v[n / 2]) / 2) * 100) / 100;
    if (out.ratio !== undefined || out.down) near.push(out);
  }
  return json({ near, t: now });
}

// The hourly lines for training (a GitHub Action with the secret EXPORT_KEY): a page of days from `since`, each with
// the installation's kind of home (country, inverter, battery size, car …) - never its install id, only a stable alias.
async function exportHours(url, env) {
  if (!env.EXPORT_KEY || url.searchParams.get("key") !== env.EXPORT_KEY) return new Response("Not found", { status: 404 });
  if (!env.DB) return json({ rows: [] });
  await schema(env);
  if (url.searchParams.get("what") === "setups") return exportSetups(env);
  if (url.searchParams.get("what") === "tests") {
    // the self-test per profile (last 60 days): how many passed, and what failed - for the nightly failure report
    const since = new Date(Date.now() - 60 * 864e5).toISOString().slice(0, 10);
    const rows = (await env.DB.prepare("SELECT part, profile, model, ok, failed, version FROM tests WHERE day >= ?1").bind(since).all()).results || [];
    return json({ rows });
  }
  const since = (url.searchParams.get("since") || "2000-01-01").slice(0, 10);
  const offset = Math.max(0, parseInt(url.searchParams.get("offset") || "0", 10) || 0);
  const rows = (await env.DB.prepare(
    "SELECT h.install, h.day, h.data, i.data AS meta FROM hours h LEFT JOIN installs i ON i.id = h.install " +
    "WHERE h.day >= ?1 ORDER BY h.day, h.install LIMIT 500 OFFSET ?2").bind(since, offset).all()).results || [];
  const alias = async (id) => {
    const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(`${env.EXPORT_KEY}|${id}`));
    return [...new Uint8Array(buf)].slice(0, 8).map((x) => x.toString(16).padStart(2, "0")).join("");
  };
  const out = [];
  for (const r of rows) {
    const m = safe(r.meta);
    out.push({ home: await alias(r.install), day: r.day, hours: safe(r.data),
      kind: { country: m.country, profile: m.profile, model: m.model, battery_kwh: m.battery_kwh, has: m.has, charger: m.charger,
              price: m.price, sun_source: m.sun_source } });
  }
  return json({ rows: out, next: rows.length === 500 ? offset + 500 : null });
}

// Energy Pilot's setups (last 30 days) for training the sensor finder: what each sensor is used for, its integration,
// translation key, unit and kind - the names already have the user's own words taken out. A stable alias per home.
async function exportSetups(env) {
  const since = new Date(Date.now() - 30 * 864e5).toISOString().slice(0, 10);
  const rows = (await env.DB.prepare("SELECT install, data FROM setups WHERE app = 'energy-pilot' AND day >= ?1").bind(since).all()).results || [];
  const out = [];
  for (const r of rows) {
    const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(`${env.EXPORT_KEY}|${r.install}`));
    const home = [...new Uint8Array(buf)].slice(0, 8).map((x) => x.toString(16).padStart(2, "0")).join("");
    const d = safe(r.data);
    out.push({ home, devices: (d.devices || []).map((v) => ({ kind: v.kind, platform: v.platform, profile: v.profile, ok: v.ok,
      entities: (v.entities || []).map((e) => ({ name: e.name, use: e.use, platform: e.platform, key: e.key,
        unit: e.unit_of_measurement, device_class: e.device_class })) })) });
  }
  return json({ rows: out });
}

// The models the nightly training made (a GitHub Action with EXPORT_KEY): kept here and handed out with the fixes.
async function putModels(request, env) {
  const url = new URL(request.url);
  if (!env.EXPORT_KEY || url.searchParams.get("key") !== env.EXPORT_KEY) return new Response("Not found", { status: 404 });
  const text = await request.text();
  if (text.length > 400_000) return json({ error: "size" }, 413);
  const m = safe(text);
  if (!m || typeof m !== "object") return json({ error: "json" }, 400);
  await schema(env);
  await env.DB.prepare("INSERT OR REPLACE INTO meta (k, v) VALUES ('models', ?1)").bind(JSON.stringify({ t: Date.now(), m })).run();
  return json({ ok: true });
}

// ---------- 3. The week's overview ----------
async function weekly(env) {
  if (!env.DB) return;
  await schema(env);
  const db = env.DB, since = new Date(Date.now() - 7 * 864e5).toISOString().slice(0, 10);
  const rows = ((await db.prepare("SELECT id, first_seen, data FROM installs WHERE last_seen >= ?1").bind(since).all()).results || [])
    .map((r) => ({ ...r, d: safe(r.data) }));
  const count = (f) => Object.entries(rows.reduce((a, r) => { const k = f(r.d) ?? "?"; a[k] = (a[k] || 0) + 1; return a; }, {}))
    .sort((a, b) => b[1] - a[1]).map(([k, n]) => `${k} ${n}`).join(" · ") || "–";
  const avg = (f) => { const v = rows.map((r) => f(r.d)).filter((x) => typeof x === "number"); return v.length ? (v.reduce((a, b) => a + b, 0) / v.length).toFixed(1) : "–"; };
  const has = (k) => rows.filter((r) => r.d.has?.[k]).length;
  const controlled = rows.filter((r) => Object.values(r.d.modes || {}).includes("control"));
  const tests = ((await db.prepare("SELECT profile, part, SUM(ok) AS ok, COUNT(*) AS n, GROUP_CONCAT(failed, ' / ') AS failed FROM tests GROUP BY profile, part ORDER BY n DESC").all()).results || []);
  const errs = ((await db.prepare(`SELECT e.text, e.count, e.version, (SELECT COUNT(*) FROM error_installs i WHERE i.hash = e.hash) AS installs FROM errors e WHERE e.last_seen >= ?1 AND ${ofApp("energy-pilot", "e.hash")} ORDER BY installs DESC, e.count DESC LIMIT 10`).bind(since).all()).results || []);
  const af = ((await db.prepare("SELECT key, COUNT(*) AS n FROM autofix GROUP BY key ORDER BY n DESC").all()).results || []);
  const body = [
    `## Week to ${new Date().toISOString().slice(0, 10)}`,
    `**Installations active:** ${rows.length} · new this week: ${rows.filter((r) => r.first_seen >= since).length}`,
    `**Controlling:** ${controlled.length} · in shadow only: ${rows.length - controlled.length} · days in shadow before control (avg): ${avg((d) => d.days_to_control)}`,
    `**Versions:** ${count((d) => d.version)}`,
    `**Home Assistant:** ${count((d) => d.ha)}`,
    `**Countries:** ${count((d) => d.country)} · **languages:** ${count((d) => d.lang)}`,
    `**Has:** battery ${has("battery")} · car ${has("car")} · solar ${has("pv")} · runs cheaply ${has("things")} · several batteries ${has("batteries")}`,
    `**Profiles:** ${count((d) => d.profile)} · **chargers:** ${count((d) => d.charger)} · **prices:** ${count((d) => d.price)}`,
    `**Unknown battery integrations:** ${(() => { const a = {}; rows.filter((r) => !r.d.profile && r.d.has?.battery).forEach((r) => { const k = r.d.battery_integration || "?"; a[k] = (a[k] || 0) + 1; }); return Object.entries(a).sort((x, y) => y[1] - x[1]).map(([k, n]) => `${k} ${n}`).join(" · ") || "–"; })()}`,
    `**Saved per month (avg, own currency):** ${avg((d) => d.saved_month)} · battery kWh (avg): ${avg((d) => d.battery_kwh)}`,
    `**Forecast error, sun (avg):** ${avg((d) => d.sun_err)} · **house:** ${avg((d) => d.house_err)} · sources: ${count((d) => d.sun_source)}`,
    `**Features:** ${["export", "targets", "things", "power_tariff", "offgrid"].map((k) => `${k} ${rows.filter((r) => r.d.features?.[k]).length}`).join(" · ")}`,
    "", "### Tests", "| Profile | Part | ✅ | of | Fails |", "|---|---|---|---|---|",
    ...tests.map((t) => `| ${t.profile} | ${t.part} | ${t.ok} | ${t.n} | ${(t.failed || "").slice(0, 120)} |`),
    "", "### App errors this week", ...(errs.length ? errs.map((e) => `- ${e.installs} installs · ${e.count}× · ${e.version}: \`${String(e.text).slice(0, 120)}\``) : ["- none"]),
    "", "### Mended by itself", af.length ? af.map((a) => `${a.key} ${a.n}`).join(" · ") : "–",
  ].join("\n");
  await github(env)("issues", "POST", { title: `⚡ Energy Pilot: 📊 week ${new Date().toISOString().slice(0, 10)} · ${rows.length} installations`, body, labels: ["energy-pilot", "weekly"] });
  await madplanWeekly(env, since);
}

// ---------- Madplan ----------
// Lines from the Madplan integration: a daily summary (version, chains, features - never rules, allergies, household,
// recipes or shopping lists), offers found per chain (0 from several homes = that source broke: an issue at once),
// ingredient names the product search couldn't match (to improve the search), and app errors.
async function madplan(env, b, install, day, s) {
  const db = env.DB, gh = github(env);
  if (b.kind === "daily") {
    await db.prepare("INSERT INTO m_installs (id, first_seen, last_seen, data) VALUES (?1, ?2, ?2, ?3) ON CONFLICT(id) DO UPDATE SET last_seen = ?2, data = ?3")
      .bind(install, day, JSON.stringify(b.data || {}).slice(0, 10_000)).run();
  } else if (b.kind === "offers") {
    for (const [chain, n] of Object.entries(b.offers || {}).slice(0, 20)) {
      await db.prepare("INSERT OR REPLACE INTO m_offers (day, chain, install, n) VALUES (?1, ?2, ?3, ?4)").bind(day, s(chain, 40), install, Number(n) || 0).run();
      if (Number(n) > 0) continue;
      const empty = (await db.prepare("SELECT COUNT(*) AS n FROM m_offers WHERE day = ?1 AND chain = ?2 AND n = 0").bind(day, s(chain, 40)).first()).n;
      if (empty >= 2) {
        const fresh = await db.prepare("INSERT OR IGNORE INTO m_alerts (day, chain) VALUES (?1, ?2)").bind(day, s(chain, 40)).run();
        if (fresh.meta?.changes) await gh("issues", "POST", { title: `🍽️ Madplan: ${s(chain, 40)} giver 0 tilbud (${day})`, labels: ["madplan", "offers"],
          body: `${empty} homes got no offers from **${s(chain, 40)}** today. The source may have changed.` });
      }
    }
  } else if (b.kind === "nomatch") {
    for (const term of (b.terms || []).slice(0, 30)) {
      await db.prepare("INSERT OR IGNORE INTO m_nomatch (term, install, day) VALUES (?1, ?2, ?3)").bind(s(String(term).toLowerCase(), 40), install, day).run();
    }
  } else if (b.kind === "error") {
    const hash = "m" + s(b.hash, 39), text = s(b.text, 300);
    const known = await db.prepare("SELECT count FROM errors WHERE hash = ?1").bind(hash).first();
    await db.prepare("INSERT INTO errors (hash, first_seen, last_seen, count, version, text) VALUES (?1, ?2, ?2, 1, ?3, ?4) ON CONFLICT(hash) DO UPDATE SET last_seen = ?2, count = count + 1, version = ?3")
      .bind(hash, day, s(b.version, 20), text).run();
    await db.prepare("INSERT OR IGNORE INTO error_installs (hash, install) VALUES (?1, ?2)").bind(hash, install).run();
    if (!known) await rememberIssue(db, hash, await gh("issues", "POST", { title: `🍽️ Madplan: 🐞 ${s(b.text, 80)}`, labels: ["madplan", "app-error"],
      body: `First seen ${day} in version ${s(b.version, 20)}.\n\n\`\`\`\n${text}\n\`\`\`\n\n_Comments here reach every installation that had this error._` }));
  } else {
    return json({ error: "kind" }, 400);
  }
  return json({ ok: true });
}

// ---------- The other apps (Replace Device, Update Guard, Database Doctor, Heat Pilot) ----------
// Only errors in the app for now: each new one gets an issue, and a comment on it reaches the installations that had it.
async function otherApp(env, b, install, day, s, app) {
  const A = APPS[app], db = env.DB;
  if (b.kind !== "error") return json({ ok: true, ignored: b.kind });
  const hash = A.prefix + s(b.hash, 40 - A.prefix.length), text = s(b.text, 300);
  if (!b.hash) return json({ error: "hash" }, 400);
  const known = await db.prepare("SELECT count FROM errors WHERE hash = ?1").bind(hash).first();
  await db.prepare("INSERT INTO errors (hash, first_seen, last_seen, count, version, text) VALUES (?1, ?2, ?2, 1, ?3, ?4) ON CONFLICT(hash) DO UPDATE SET last_seen = ?2, count = count + 1, version = ?3")
    .bind(hash, day, s(b.version, 20), text).run();
  await db.prepare("INSERT OR IGNORE INTO error_installs (hash, install) VALUES (?1, ?2)").bind(hash, install).run();
  if (!known) await rememberIssue(db, hash, await github(env)("issues", "POST", { title: `${A.mark} ${A.name}: 🐞 ${s(b.text, 80)}`, labels: [A.label, "app-error"],
    body: `First seen ${day} in version ${s(b.version, 20)}.\n\n\`\`\`\n${text}\n\`\`\`\n\n_Comments here reach every installation that had this error._` }));
  return json({ ok: true });
}

async function madplanWeekly(env, since) {
  const db = env.DB;
  const rows = ((await db.prepare("SELECT first_seen, data FROM m_installs WHERE last_seen >= ?1").bind(since).all()).results || []).map((r) => ({ ...r, d: safe(r.data) }));
  if (!rows.length) return;
  const count = (f) => Object.entries(rows.reduce((a, r) => { for (const k of [].concat(f(r.d) ?? "?")) a[k] = (a[k] || 0) + 1; return a; }, {}))
    .sort((a, b) => b[1] - a[1]).map(([k, n]) => `${k} ${n}`).join(" · ") || "–";
  const offers = ((await db.prepare("SELECT chain, AVG(n) AS avg, SUM(n = 0) AS empty, COUNT(*) AS n FROM m_offers WHERE day >= ?1 GROUP BY chain ORDER BY chain").bind(since).all()).results || []);
  const miss = ((await db.prepare("SELECT term, COUNT(*) AS n FROM m_nomatch GROUP BY term ORDER BY n DESC LIMIT 25").all()).results || []);
  const errs = ((await db.prepare("SELECT text, count, version FROM errors WHERE hash LIKE 'm%' AND last_seen >= ?1 ORDER BY count DESC LIMIT 10").bind(since).all()).results || []);
  const body = [
    `**Installations active:** ${rows.length} · new: ${rows.filter((r) => r.first_seen >= since).length}`,
    `**Versions:** ${count((d) => d.version)} · **HA:** ${count((d) => d.ha)}`,
    `**Main chain:** ${count((d) => d.chain)} · **also shops at:** ${count((d) => d.extra || [])}`,
    `**AI:** ${count((d) => d.ai)} · **Salling key:** ${rows.filter((r) => r.d.salling).length} · **profiles (avg):** ${(rows.reduce((a, r) => a + (r.d.profiles || 0), 0) / rows.length).toFixed(1)}`,
    `**Features:** ${["auto_plan", "rester", "mine_retter", "kcal", "mail"].map((k) => `${k} ${rows.filter((r) => r.d.features?.[k]).length}`).join(" · ")}`,
    "", "### Offers per chain this week", "| Chain | Avg offers | Days with 0 | Lines |", "|---|---|---|---|",
    ...offers.map((o) => `| ${o.chain} | ${Number(o.avg).toFixed(0)} | ${o.empty} | ${o.n} |`),
    "", "### Ingredients the search couldn't match", miss.length ? miss.map((m) => `${m.term} (${m.n})`).join(" · ") : "–",
    "", "### App errors", ...(errs.length ? errs.map((e) => `- ${e.count}× · ${e.version}: \`${String(e.text).slice(0, 120)}\``) : ["- none"]),
  ].join("\n");
  await github(env)("issues", "POST", { title: `🍽️ Madplan: 📊 week ${new Date().toISOString().slice(0, 10)} · ${rows.length} installations`, body, labels: ["madplan", "weekly"] });
}

// ---------- 4. Answers ----------
const USER_MARK = "💬 **The user wrote back in the app:**";
const REPLY_DAYS = 60;

async function readBody(request, max = 20_000) {
  try {
    const text = await request.text();
    return text.length > max ? null : JSON.parse(text);
  } catch {
    return null;
  }
}

// Reports sent before answers existed: found once from the issues and their stored files.
async function backfill(env) {
  const db = env.DB, gh = github(env);
  if (await db.prepare("SELECT v FROM meta WHERE k = 'backfill'").first()) return;
  for (const app of Object.keys(APPS)) {
    const r = await gh(`issues?state=all&per_page=100&labels=${APPS[app].label}`, "GET");
    if (!r.ok) return;
    for (const i of await r.json()) {
      const id = (String(i.title).match(/· (\d{8}-[a-f0-9]{6})$/) || [])[1];
      if (!id || await db.prepare("SELECT id FROM reports WHERE id = ?1").bind(id).first()) continue;
      const f = await gh(`contents/reports/${app}/${id}.json`, "GET");
      if (!f.ok) continue;
      const rep = safe(new TextDecoder().decode(Uint8Array.from(atob(((await f.json()).content || "").replaceAll("\n", "")), (c) => c.charCodeAt(0))));
      const install = String(rep.install || rep.diagnostics?.settings?.install_id || "").slice(0, 40);
      if (/^[a-f0-9-]{16,40}$/.test(install)) {
        await db.prepare("INSERT OR IGNORE INTO reports (id, app, issue, install, day) VALUES (?1, ?2, ?3, ?4, ?5)")
          .bind(id, app, i.number, install, String(i.created_at).slice(0, 10)).run();
      }
    }
  }
  await db.prepare("INSERT OR REPLACE INTO meta (k, v) VALUES ('backfill', ?1)").bind(new Date().toISOString()).run();
}

async function rememberIssue(db, hash, r) {
  if (!r?.ok) return;
  const i = await r.json();
  if (i.number) await db.prepare("INSERT OR REPLACE INTO error_issues (hash, issue) VALUES (?1, ?2)").bind(hash, i.number).run();
}

// App-error issues made before their numbers were kept: matched once by their title (the error's first 80 letters).
async function backfillErrors(env) {
  const db = env.DB, gh = github(env);
  if (await db.prepare("SELECT v FROM meta WHERE k = 'backfill_errors'").first()) return;
  const r = await gh("issues?state=all&per_page=100&labels=app-error", "GET");
  if (!r.ok) return;
  for (const i of await r.json()) {
    const app = Object.keys(APPS).find((k) => String(i.title).startsWith(`${APPS[k].mark} ${APPS[k].name}: 🐞 `));
    if (!app) continue;
    const text = String(i.title).slice(`${APPS[app].mark} ${APPS[app].name}: 🐞 `.length);
    const e = await db.prepare(`SELECT hash FROM errors WHERE substr(text, 1, 80) = ?1 AND ${ofApp(app)}`).bind(text).first();
    if (e) await db.prepare("INSERT OR IGNORE INTO error_issues (hash, issue) VALUES (?1, ?2)").bind(e.hash, i.number).run();
  }
  await db.prepare("INSERT OR REPLACE INTO meta (k, v) VALUES ('backfill_errors', ?1)").bind(new Date().toISOString()).run();
}

// An issue's comments, kept 5 minutes so many installations asking don't each go to GitHub.
async function comments(env, issue) {
  const key = new Request(`https://ep-cache.local/comments/${issue}`);
  const hit = await caches.default.match(key);
  if (hit) return hit.json();
  const gh = github(env);
  const [i, c] = await Promise.all([gh(`issues/${issue}`, "GET"), gh(`issues/${issue}/comments?per_page=50`, "GET")]);
  if (!i.ok || !c.ok) return null;
  const info = await i.json();
  const d = { state: info.state, closed_at: info.closed_at || null, body: String(info.body || ""), list: (await c.json()).map((x) => ({ body: String(x.body || ""), t: x.created_at })) };
  await caches.default.put(key, new Response(JSON.stringify(d), { headers: { "cache-control": "max-age=300" } }));
  return d;
}

// ---------- 4. How many use the apps ----------
// One row per app, installation and day, with the country Cloudflare sees for the connection - nothing the app sends.
// ---------- how the apps are set up ----------
const cut = (v, n = 80) => (v == null ? null : String(v).slice(0, n));
function cleanSetup(su) {
  const ent = (e) => {
    const o = { name: cut(e?.name, 120), use: cut(e?.use, 40), platform: cut(e?.platform, 40), key: cut(e?.key, 60), state: cut(e?.state, 40) };
    for (const k of ["unit_of_measurement", "device_class", "min", "max", "step", "min_temp", "max_temp", "target_temp_step"]) if (e?.[k] != null) o[k] = cut(e[k], 30);
    for (const k of ["options", "hvac_modes", "preset_modes", "fan_modes", "operation_list"]) if (Array.isArray(e?.[k])) o[k] = e[k].slice(0, 25).map((x) => cut(x, 40));
    return o;
  };
  const dev = (d) => ({
    kind: cut(d?.kind, 30), platform: cut(d?.platform, 40), profile: cut(d?.profile, 40), manufacturer: cut(d?.manufacturer, 60), model: cut(d?.model, 60),
    ok: typeof d?.ok === "boolean" ? d.ok : null, errors: (Array.isArray(d?.errors) ? d.errors : []).slice(0, 5).map((x) => cut(x, 200)),
    entities: (Array.isArray(d?.entities) ? d.entities : []).slice(0, 70).map(ent),
    extra: d?.extra && typeof d.extra === "object" ? Object.fromEntries(Object.entries(d.extra).slice(0, 20).map(([k, v]) => [cut(k, 40), typeof v === "object" ? cut(JSON.stringify(v), 120) : cut(v, 60)])) : undefined,
  });
  const flat = (o, n = 40) => (o && typeof o === "object" ? Object.fromEntries(Object.entries(o).slice(0, n).map(([k, v]) => [cut(k, 40), typeof v === "number" || typeof v === "boolean" ? v : cut(v, 60)])) : {});
  return { devices: (Array.isArray(su.devices) ? su.devices : []).slice(0, 30).map(dev), features: flat(su.features), sizes: flat(su.sizes), counts: flat(su.counts), full: !!su.full };
}
async function saveSetup(env, app, install, su) {
  try {
    await env.DB.prepare("INSERT OR REPLACE INTO setups (app, install, day, data) VALUES (?1, ?2, ?3, ?4)")
      .bind(app, install, new Date().toISOString().slice(0, 10), JSON.stringify(cleanSetup(su))).run();
  } catch { /* never in the way of the answers */ }
}
async function setupSection(env, ago, only = null, nv = null) {
  const rows = (await env.DB.prepare("SELECT app, install, data FROM setups WHERE day >= ?1").bind(ago(30)).all()).results || [];
  // Each home's newest version (from its daily call) - shown on each setup, or only that version's homes (&new=1).
  const verOf = {};
  for (const r of (await env.DB.prepare("SELECT app, install, version FROM seen WHERE day >= ?1 AND version IS NOT NULL ORDER BY day").bind(ago(30)).all()).results || []) verOf[r.app + "|" + r.install] = r.version;
  const esc = (t) => String(t ?? "").replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" })[c]);
  const byApp = {};
  for (const r of rows) { const d = safe(r.data); if (d) { d._install = r.install; (byApp[r.app] = byApp[r.app] || []).push(d); } }
  const vals = (e) => e.options?.join(" · ") || e.hvac_modes?.join(" · ") || e.preset_modes?.join(" · ") || e.operation_list?.join(" · ")
    || [e.min != null || e.max != null ? `${e.min ?? "?"}–${e.max ?? "?"}` : "", e.min_temp != null ? `${e.min_temp}–${e.max_temp}°` : "", e.unit_of_measurement || ""].filter(Boolean).join(" ") || (e.state ? "on/off" : "");
  const kindTag = (k, known) => `<span class="tag ${({ inverter: "inv", battery: "bat", charger: "chg" })[k] || "oth"}${known ? "" : " unk"}">${esc(String(k || "device").toUpperCase())}${known ? "" : " ?"}</span>`;
  let html = "";
  for (const app of Object.keys(APPS)) {
    // "Newest only": the features, sizes and counts too - not only the device cards.
    const list = (byApp[app] || []).filter((s) => !(only && app === "energy-pilot") || verOf[app + "|" + s._install] === only);
    if (!list.length) continue;
    const groups = {};
    for (const s of list) for (const d of s.devices || []) {
      const ver = verOf[app + "|" + s._install] || "?";
      if (only && app === "energy-pilot" && ver !== only) continue;
      const key = `${d.kind}|${d.platform || "?"}`, g = groups[key] = groups[key] || { kind: d.kind, platform: d.platform || "?", n: 0, inst: new Set(), fullInst: new Set(), profiles: {}, models: {}, ok: 0, bad: 0, errors: {}, ents: {}, full: 0, vers: {} };
      if (!g.inst.has(s._install)) g.vers[ver] = (g.vers[ver] || 0) + 1;
      g.n++; g.inst.add(s._install); if (s.full) g.fullInst.add(s._install); g.full = g.fullInst.size;
      if (d.profile) g.profiles[d.profile] = (g.profiles[d.profile] || 0) + 1;
      const m = [d.manufacturer, d.model].filter(Boolean).join(" "); if (m) g.models[m] = (g.models[m] || 0) + 1;
      if (d.ok === true) g.ok++; else if (d.ok === false) g.bad++;
      for (const e of d.errors || []) g.errors[e] = (g.errors[e] || 0) + 1;
      for (const e of d.entities || []) { const k = `${e.name}|${e.use || ""}`; g.ents[k] = g.ents[k] || { ...e, n: 0 }; g.ents[k].n++; }
    }
    const feats = {}, sizes = {}, counts = {}, choices = {};
    for (const s of list) {
      for (const [k, v] of Object.entries(s.features || {})) {
        if (typeof v === "string") { const kk = k.replace(/^to_/, ""); choices[kk] = choices[kk] || {}; choices[kk][v] = (choices[kk][v] || 0) + 1; }  // a choice, not on/off
        else if (v) feats[k] = (feats[k] || 0) + 1;
      }
      for (const [k, v] of Object.entries(s.sizes || {})) { sizes[k] = sizes[k] || {}; sizes[k][v] = (sizes[k][v] || 0) + 1; }
      for (const [k, v] of Object.entries(s.counts || {})) if (typeof v === "number") { counts[k] = counts[k] || []; counts[k].push(v); }
    }
    const chips = (o) => Object.entries(o).sort((a, b) => b[1] - a[1]).map(([k, n]) => `<span class="ch">${esc(k)} <b>${n}</b></span>`).join("") || "–";
    const cards = Object.values(groups).sort((a, b) => b.inst.size - a.inst.size || b.n - a.n).map((g) => {
      const known = Object.keys(g.profiles).length > 0 || !["inverter", "battery", "charger"].includes(g.kind);
      const ents = Object.values(g.ents).sort((a, b) => b.n - a.n).slice(0, 60);
      const open = !known || g.bad > 0 || Object.keys(g.errors).length > 0;
      return `<div class="card dv"><details ${open ? "open" : ""}><summary>${kindTag(g.kind, known)}<span class="nm">${esc(g.platform)}</span><span class="cnt">${g.inst.size} install${g.inst.size === 1 ? "" : "s"}${g.n > g.inst.size ? ` · ${g.n} devices` : ""}${Object.keys(g.profiles).length ? ` · profile ${esc(Object.keys(g.profiles).join(", "))}` : ["inverter", "battery", "charger"].includes(g.kind) ? " · no profile" : ""}${g.full ? ` ⭐${g.full}` : ""}</span><span class="vers">${Object.entries(g.vers).sort((a, b) => b[1] - a[1]).map(([v, n]) => `<span class="vtag${app === "energy-pilot" && v === nv ? " ok" : ""}">${esc(v)}${n > 1 ? " ×" + n : ""}</span>`).join("")}</span></summary>
<div class="sum">${g.ok + g.bad ? `<span>Control <b class="${g.bad ? "bad" : "ok"}">${g.ok}/${g.ok + g.bad} ok</b></span>` : ""}${Object.keys(g.models).length ? `<span>${chips(g.models)}</span>` : ""}</div>
${ents.length ? `<table class="et"><tr><th>Name</th><th>Used for</th><th>Values</th><th class="n">Seen</th></tr>${ents.map((e) => `<tr><td><code>${esc(e.name)}</code>${e.key ? `<div class="sm">${esc(e.key)}</div>` : ""}</td><td>${e.use ? `<span class="role">${esc(e.use)}</span>` : ""}</td><td class="vals">${esc(vals(e))}</td><td class="n">${e.n}</td></tr>`).join("")}</table>` : ""}
${Object.entries(g.errors).map(([e, n]) => `<div class="err">❌ <b>${esc(e)}</b> · ${n}</div>`).join("")}</details></div>`;
    }).join("");
    const avgs = Object.entries(counts).map(([k, a]) => `<span class="ch">${esc(k)} <b>${Math.round((a.reduce((x, y) => x + y, 0) / a.length) * 10) / 10}</b></span>`).join("");
    html += `<h2>${APPS[app].mark} ${esc(APPS[app].name)} · setups (${list.length})</h2>
${Object.keys(feats).length || Object.keys(sizes).length || Object.keys(choices).length || avgs ? `<div class="card" style="margin-bottom:12px">${Object.keys(feats).length ? `<div class="row"><i>Turned on</i>${chips(feats)}</div>` : ""}${Object.entries(choices).map(([k, o]) => `<div class="row"><i>${esc(k.replace(/_/g, " "))}</i>${chips(Object.fromEntries(Object.entries(o).map(([v, n]) => [`→ ${v}`, n])))}</div>`).join("")}${Object.entries(sizes).map(([k, o]) => `<div class="row"><i>${esc(k)}</i>${chips(o)}</div>`).join("")}${avgs ? `<div class="row"><i>Average</i>${avgs}</div>` : ""}</div>` : ""}
${cards}`;
  }
  return html ? `<h2 style="margin-top:36px">🔧 How they're set up</h2><p>The devices each app works with – names without the user's own device name (⭐ = full names shared), what each is used for, and what fails. Last 30 days.</p>${html}` : "";
}

async function markSeen(env, request, app, install, version = null) {
  try {
    await env.DB.prepare("INSERT INTO seen (app, install, day, country, version) VALUES (?1, ?2, ?3, ?4, ?5) ON CONFLICT(app, install, day) DO UPDATE SET version = COALESCE(excluded.version, seen.version)")
      .bind(app, install, new Date().toISOString().slice(0, 10), String(request.cf?.country || "?").slice(0, 2), version ? String(version).slice(0, 20) : null).run();
  } catch { /* counting never stops an answer */ }
}
// The newest release of each app on GitHub (looked up at most every 6 hours): its version, the first line of the
// release text (shown on the update card), and whether it says "Important:".
const REPOS = { "energy-pilot": "Energy-pilot", madplan: "ha-madplan", "replace-device": "ha-replace-device", "update-guard": "ha-update-guard",
  "database-doctor": "ha-database-doctor", "heat-pilot": "heat-pilot", "hus-chat": "ha-hus-chat", "appliance-watch": "appliance-watch" };
async function latestOf(env, app) {
  const repo = REPOS[app]; if (!repo) return null;
  const k = "latest:" + app, row = await env.DB.prepare("SELECT v FROM meta WHERE k = ?1").bind(k).first(), old = row ? safe(row.v) : null;
  if (old && Date.now() - (old.t || 0) < 36e5) return old.l;  // asked GitHub within the hour
  const h = { accept: "application/vnd.github+json", "user-agent": "energy-pilot-reports", ...(env.GITHUB_TOKEN ? { authorization: `Bearer ${env.GITHUB_TOKEN}` } : {}) };
  const num = (v) => String(v || "").replace(/^v/, "").split(".").map((x) => parseInt(x, 10) || 0);
  const newer = (a, b) => { const x = num(a), y = num(b); for (let i = 0; i < 3; i++) if ((x[i] || 0) !== (y[i] || 0)) return (x[i] || 0) > (y[i] || 0); return false; };
  let l = null;
  try {
    // The newest of the latest Release and the tags: a version that is only tagged counts too.
    let rel = null, tag = null;
    const r = await fetch(`https://api.github.com/repos/Clahen86/${repo}/releases/latest`, { headers: h });
    if (r.ok) {
      const j = await r.json(), body = String(j.body || "");
      // the first point of the release text (a point can run over several lines)
      const raw = body.split("\n").map((x) => x.trim()), head = /^(#+\s*)?(new|fixed|fixes|improvements|nyt|rettet|rettelser|forbedringer)$/i;
      let i = raw.findIndex((x) => x && !head.test(x)), line = i < 0 ? "" : raw[i].replace(/^[-*>#\s]+/, "");
      while (i >= 0 && raw[i + 1] && !/^[-*]/.test(raw[i + 1]) && !head.test(raw[i + 1])) line += " " + raw[++i];
      line = line.replace(/`/g, "");
      rel = { version: String(j.tag_name || "").replace(/^v/, ""), note: line.slice(0, 160), important: /important:/i.test(body), date: String(j.published_at || "").slice(0, 10), repo: `Clahen86/${repo}` };
    }
    const t = await fetch(`https://api.github.com/repos/Clahen86/${repo}/tags?per_page=30`, { headers: h });
    if (t.ok) {
      const names = ((await t.json()) || []).map((x) => String(x.name || "")).filter((x) => /^v?\d+\.\d+/.test(x));
      const top = names.reduce((m, x) => (!m || newer(x, m) ? x : m), "");
      if (top) tag = { version: top.replace(/^v/, ""), note: "", important: false, date: "", repo: `Clahen86/${repo}` };
    }
    l = rel && tag ? (newer(tag.version, rel.version) ? tag : rel) : rel || tag;
    // a version only tagged: the date it was first seen here (the apps count "behind" from it)
    if (l && !l.date) l.date = old?.l?.version === l.version && old.l.date ? old.l.date : new Date().toISOString().slice(0, 10);
  } catch { /* GitHub away: keep the old one */ }
  l = l || old?.l || null;
  await env.DB.prepare("INSERT OR REPLACE INTO meta (k, v) VALUES (?1, ?2)").bind(k, JSON.stringify({ t: Date.now(), l })).run();
  return l;
}
const flag = (cc) => /^[A-Z]{2}$/.test(cc) ? String.fromCodePoint(...[...cc].map((c) => 127397 + c.charCodeAt(0))) : "🌐";
async function stats(url, env) {
  if (!env.STATS_KEY || url.searchParams.get("key") !== env.STATS_KEY) return new Response("Not found", { status: 404 });
  await schema(env);
  const ago = (d) => new Date(Date.now() - d * 864e5).toISOString().slice(0, 10), db = env.DB;
  const q = async (sql, ...a) => (await db.prepare(sql).bind(...a).all()).results || [];
  const per = await q("SELECT app, COUNT(DISTINCT CASE WHEN day >= ?1 THEN install END) AS w, COUNT(DISTINCT install) AS m FROM seen WHERE day >= ?2 GROUP BY app", ago(7), ago(30));
  const fresh = await q("SELECT app, COUNT(*) AS n FROM (SELECT app, install, MIN(day) AS f FROM seen GROUP BY app, install) WHERE f >= ?1 GROUP BY app", ago(7));
  const lands = await q("SELECT app, country, COUNT(DISTINCT install) AS n FROM seen WHERE day >= ?1 GROUP BY app, country ORDER BY n DESC", ago(30));
  const vers = await q("SELECT app, version, COUNT(DISTINCT install) AS n FROM seen WHERE day >= ?1 AND version IS NOT NULL GROUP BY app, version ORDER BY n DESC", ago(7));
  await Promise.all(Object.keys(REPOS).map((a) => latestOf(env, a).catch(() => null)));  // the newest version, asked at most hourly
  const latestRows = await q("SELECT k, v FROM meta WHERE k LIKE 'latest:%'");
  const newest = Object.fromEntries(latestRows.map((r) => [r.k.slice(7), safe(r.v)?.l?.version]));
  const since = (await q("SELECT MIN(day) AS d FROM seen"))[0]?.d || "–";
  const esc = (t) => String(t).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" })[c]);
  const rows = Object.keys(APPS).map((k) => {
    const p = per.find((r) => r.app === k) || { w: 0, m: 0 }, f = (fresh.find((r) => r.app === k) || { n: 0 }).n;
    const l = lands.filter((r) => r.app === k).map((r) => `<span>${flag(r.country)} ${esc(r.country)} <b>${r.n}</b></span>`).join("");
    const vs = vers.filter((r) => r.app === k), onNew = vs.filter((r) => r.version === newest[k]).reduce((a, r) => a + r.n, 0), tot = vs.reduce((a, r) => a + r.n, 0);
    const vline = vs.length ? `<div class="vs">${vs.map((r) => `<span class="${r.version === newest[k] ? "ok" : ""}">${esc(r.version)}: <b>${r.n}</b></span>`).join(" · ")}${newest[k] ? ` · <em>${Math.round(100 * onNew / tot)} % on ${esc(newest[k])}</em>` : ""}</div>` : (newest[k] ? `<div class="vs"><em>newest ${esc(newest[k])}</em></div>` : "");
    return `<tr><td><b>${esc(APPS[k].name)}</b>${vline}${l ? `<div class="cm c">${l}</div>` : ""}</td><td class="n">${p.w}</td><td class="n">${p.m}</td><td class="n">${f ? "+" + f : "–"}</td><td class="c">${l || "–"}</td></tr>`;
  }).join("");
  const all = (await q("SELECT COUNT(DISTINCT install) AS n FROM seen WHERE day >= ?1", ago(30)))[0]?.n || 0;
  // the rest, from what the apps already send: Energy Pilot's and Madplan's daily lines, self-tests, app errors, help
  const tally = (rows, f) => Object.entries(rows.reduce((a, r) => { for (const k of [].concat(f(r.d) ?? "?")) a[k] = (a[k] || 0) + 1; return a; }, {}))
    .sort((a, b) => b[1] - a[1]).map(([k, n]) => `<span class="ch">${esc(k)} <b>${n}</b></span>`).join("") || "–";
  const avg = (rows, f) => { const v = rows.map((r) => f(r.d)).filter((x) => typeof x === "number"); return v.length ? (v.reduce((a, b) => a + b, 0) / v.length).toFixed(1) : "–"; };
  const ep = (await q("SELECT first_seen, data FROM installs WHERE last_seen >= ?1", ago(30))).map((r) => ({ ...r, d: safe(r.data) || {} }));
  const mp = (await q("SELECT first_seen, data FROM m_installs WHERE last_seen >= ?1", ago(30))).map((r) => ({ ...r, d: safe(r.data) || {} }));
  // "Newest only" (&new=1): just the homes on Energy Pilot's newest version - is a fault still there?
  const onlyNew = url.searchParams.get("new") === "1" && newest["energy-pilot"];
  const tests = onlyNew
    ? await q("SELECT profile, part, SUM(ok) AS ok, COUNT(*) AS n, GROUP_CONCAT(failed, ' / ') AS failed, GROUP_CONCAT(COALESCE(version, '?')) AS vers FROM tests WHERE version = ?1 GROUP BY profile, part ORDER BY n DESC LIMIT 30", newest["energy-pilot"])
    : await q("SELECT profile, part, SUM(ok) AS ok, COUNT(*) AS n, GROUP_CONCAT(failed, ' / ') AS failed, GROUP_CONCAT(COALESCE(version, '?')) AS vers FROM tests GROUP BY profile, part ORDER BY n DESC LIMIT 30");
  const verChips = (list, nv) => { const c = {}; for (const v of list) c[v] = (c[v] || 0) + 1;
    return Object.entries(c).sort((a, b) => b[1] - a[1]).map(([v, n]) => `<span class="vtag${v === nv ? " ok" : ""}">${esc(v)}${n > 1 ? " ×" + n : ""}</span>`).join(""); };
  const fixesN = (await q("SELECT COUNT(*) AS n FROM confirmed WHERE approved = 1"))[0]?.n || 0;
  const waiting = await q("SELECT profile, intent, opt_from, opt_to, day FROM confirmed WHERE COALESCE(approved, 0) = 0 ORDER BY day DESC LIMIT 20");
  const apLink = (f, no) => `/approve?key=${encodeURIComponent(env.STATS_KEY)}&profile=${encodeURIComponent(f.profile)}&intent=${encodeURIComponent(f.intent)}&from=${encodeURIComponent(f.opt_from)}&to=${encodeURIComponent(f.opt_to)}${no ? "&no=1" : ""}`;
  const mended = await q("SELECT key, COUNT(*) AS n FROM autofix GROUP BY key ORDER BY n DESC LIMIT 12");
  const errs = await q("SELECT e.hash, e.text, e.count, e.version, e.last_seen, (SELECT COUNT(*) FROM error_installs i WHERE i.hash = e.hash) AS installs, (SELECT issue FROM error_issues x WHERE x.hash = e.hash) AS issue FROM errors e WHERE e.last_seen >= ?1 ORDER BY installs DESC, e.count DESC LIMIT 25", ago(30));
  const appOf = (h) => Object.keys(APPS).find((k) => k !== "energy-pilot" && APPS[k].prefix && h.startsWith(APPS[k].prefix)) || "energy-pilot";
  const help = await q("SELECT app, COUNT(*) AS n, MAX(day) AS last FROM reports WHERE day >= ?1 GROUP BY app ORDER BY n DESC", ago(30));
  const helpLast = await q("SELECT id, app, issue, day FROM reports ORDER BY day DESC LIMIT 8");
  const gh = (n) => n && env.REPORT_REPO ? `<a href="https://github.com/${esc(env.REPORT_REPO)}/issues/${n}">#${n}</a>` : "";
  // "Newest only": the top card counts just the homes on that version too.
  const epv = onlyNew ? ep.filter((r) => r.d.version === newest["energy-pilot"]) : ep;
  const has = (k) => epv.filter((r) => r.d.has?.[k]).length;
  const sections = `
<h2>⚡ Energy Pilot · ${onlyNew ? `${epv.length} of ${ep.length}` : ep.length} active</h2><p class="vtoggle">${onlyNew ? `Showing self-tests and setups from <b>${esc(newest["energy-pilot"])}</b> only · <a href="?key=${encodeURIComponent(url.searchParams.get("key"))}">show all versions</a>` : `<a href="?key=${encodeURIComponent(url.searchParams.get("key"))}&new=1">Newest version only${newest["energy-pilot"] ? " (" + esc(newest["energy-pilot"]) + ")" : ""}</a>`}</p><div class="card">
<div class="row"><i>Inverters</i>${tally(epv, (d) => d.profile)}</div><div class="row"><i>Chargers</i>${tally(epv, (d) => d.charger)}</div>
<div class="row"><i>Prices</i>${tally(epv, (d) => d.price)}</div><div class="row"><i>Versions</i>${tally(epv, (d) => d.version)}</div>
<div class="row"><i>Home Assistant</i>${tally(epv, (d) => d.ha)}</div><div class="row"><i>Countries</i>${tally(epv, (d) => d.country)}</div><div class="row"><i>Languages</i>${tally(epv, (d) => d.lang)}</div>
<div class="row"><i>Has</i><span class="ch">battery <b>${has("battery")}</b></span><span class="ch">car <b>${has("car")}</b></span><span class="ch">solar <b>${has("pv")}</b></span><span class="ch">controlling <b>${epv.filter((r) => Object.values(r.d.modes || {}).includes("control")).length}</b></span></div>
<div class="row"><i>Saved / month (avg)</i><span class="ch"><b>${avg(epv, (d) => d.saved_month)}</b></span><i style="margin-left:12px">Battery kWh (avg)</i><span class="ch"><b>${avg(epv, (d) => d.battery_kwh)}</b></span></div>
${waiting.length ? `<div class="row"><i>Fixes to approve</i>${waiting.map((f) => `<span class="ch">${esc(f.profile)} · ${esc(f.intent)}: ${esc(f.opt_from)} → ${esc(f.opt_to)} <a href="${apLink(f)}">approve</a> · <a href="${apLink(f, true)}">drop</a></span>`).join("")}</div>` : ""}
<div class="row"><i>Fixes confirmed</i><span class="ch"><b>${fixesN}</b></span><i style="margin-left:12px">Mended by itself</i>${mended.map((m) => `<span class="ch">${esc(m.key)} <b>${m.n}</b></span>`).join("") || "–"}</div></div>
<h3>Self-test</h3><table><tr><th>Inverter</th><th>Part</th><th class="n">Passed</th><th>What failed</th><th>Versions</th></tr>${tests.map((t) => `<tr><td>${esc(t.profile)}</td><td>${esc(t.part)}</td><td class="n">${t.ok} / ${t.n}</td><td class="sm">${esc((t.failed || "").slice(0, 140))}</td><td class="sm">${verChips(String(t.vers || "").split(","), newest["energy-pilot"])}</td></tr>`).join("") || `<tr><td colspan="5">–</td></tr>`}</table>
<h2>🍽️ Madplan · ${mp.length} active</h2><div class="card">
<div class="row"><i>Main chain</i>${tally(mp, (d) => d.chain)}</div><div class="row"><i>Also shops at</i>${tally(mp, (d) => d.extra || [])}</div>
<div class="row"><i>Versions</i>${tally(mp, (d) => d.version)}</div><div class="row"><i>AI</i>${tally(mp, (d) => d.ai)}</div></div>
<h2>🐞 App errors · last 30 days</h2><table><tr><th>App</th><th class="n">Installs</th><th class="n">Times</th><th>Version</th><th>Error</th></tr>
${errs.map((e) => `<tr><td>${APPS[appOf(e.hash)].mark}</td><td class="n">${e.installs}</td><td class="n">${e.count}</td><td>${esc(e.version || "")}</td><td class="sm">${esc(String(e.text).slice(0, 140))} ${gh(e.issue)}</td></tr>`).join("") || `<tr><td colspan="5">No errors 🎉</td></tr>`}</table>
<h2>🛟 Help messages · last 30 days</h2><div class="card"><div class="row">${help.map((h) => `<span class="ch">${APPS[h.app]?.mark || ""} ${esc(APPS[h.app]?.name || h.app)} <b>${h.n}</b></span>`).join("") || "–"}</div>
<div class="row"><i>Latest</i>${helpLast.map((h) => `<span class="ch">${APPS[h.app]?.mark || ""} ${esc(h.day)} ${gh(h.issue)}</span>`).join("") || "–"}</div></div>
${await setupSection(env, ago, onlyNew ? newest["energy-pilot"] : null, newest["energy-pilot"])}`;
  const html = `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>App users</title>
<style>body{margin:0;font-family:-apple-system,Inter,Segoe UI,Roboto,sans-serif;background:#0f1220;color:#eef0f7}main{max-width:900px;margin:0 auto;padding:22px 16px}
h1{font-size:24px;margin:0 0 4px}p{color:#9aa3b8;margin:0 0 18px;font-size:14px}.big{font-size:44px;font-weight:800;margin:6px 0 18px}
table{width:100%;border-collapse:collapse;background:#171b2e;border-radius:16px;overflow:hidden}th,td{padding:11px 12px;text-align:left;border-bottom:1px solid #232945;font-size:14px}
th{color:#9aa3b8;font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.04em}.n{text-align:right;font-variant-numeric:tabular-nums}.c span{display:inline-block;margin:2px 10px 2px 0;white-space:nowrap}
h2{font-size:18px;margin:30px 0 10px}h3{font-size:14px;color:#9aa3b8;margin:16px 0 8px;text-transform:uppercase;letter-spacing:.04em}
.card{background:#171b2e;border-radius:16px;padding:12px 14px}.row{display:flex;flex-wrap:wrap;align-items:center;gap:6px;padding:6px 0;border-bottom:1px solid #232945}.row:last-child{border-bottom:0}
.row i{font-style:normal;color:#9aa3b8;font-size:12px;min-width:120px}.ch{background:#232945;border-radius:99px;padding:4px 10px;font-size:13px}.vtag{display:inline-block;background:#232945;color:#9aa3b8;border-radius:6px;padding:1px 6px;margin:1px 3px 1px 0;font-size:11px}.vtag.ok{background:#1f3a2c;color:#5be39a}.vers{margin-left:8px}.vtoggle{margin:-4px 0 10px;font-size:13px}.vtoggle a{color:#8ab4ff}.ch b{color:#ffd34d}
.sm{font-size:12.5px;color:#c9cfe0}a{color:#8fb8ff}
.cm{display:none;margin-top:4px;font-size:12.5px}
.vs{margin-top:4px;font-size:12px;color:#9aa3b8}.vs span{display:inline-block;margin-right:8px}.vs span.ok{color:#5be3a0}.vs em{font-style:normal}
.dv{margin-bottom:12px}.dv summary{list-style:none;cursor:pointer;display:flex;align-items:center;gap:8px;flex-wrap:wrap}.dv summary::-webkit-details-marker{display:none}
.tag{font-size:11px;font-weight:700;border-radius:99px;padding:2px 8px;background:#2f3557;color:#c9cfe0}.tag.inv{background:#2a3b6b;color:#9fc1ff}.tag.bat{background:#1f4a39;color:#5be3a0}.tag.chg{background:#4a3a1f;color:#ffd34d}.tag.unk{background:#4a1f2a;color:#ff8fa3}
.nm{font-weight:700;font-size:15px}.cnt{margin-left:auto;color:#9aa3b8;font-size:12.5px}.ok{color:#5be3a0}.bad{color:#ff8fa3}
.sum{display:flex;gap:14px;font-size:12.5px;color:#9aa3b8;margin-top:6px;flex-wrap:wrap}.sum b{color:#eef0f7}.sum b.ok{color:#5be3a0}.sum b.bad{color:#ff8fa3}
table.et{margin-top:10px;background:transparent}table.et td,table.et th{padding:7px 6px;font-size:12.5px;vertical-align:top}
code{font-family:ui-monospace,Menlo,monospace;font-size:12px;color:#c9d6ff;word-break:break-all}.role{background:#232945;border-radius:99px;padding:2px 8px;font-size:11.5px;white-space:nowrap}
.vals{color:#9aa3b8}.err{margin-top:10px;background:#2a1820;border-radius:10px;padding:8px 10px;font-size:12.5px}
@media(max-width:600px){.apps th:nth-child(5),.apps td:nth-child(5){display:none}.cm{display:block}}</style></head><body><main>
<h1>Who uses the apps</h1><p>Installations that asked in – one per app and day, with the country of the connection. Counting since ${esc(since)}. Installations that turned sharing off aren't counted.</p>
<div class="big">${all}<span style="font-size:15px;color:#9aa3b8;font-weight:500"> installations in the last 30 days</span></div>
<table class="apps"><tr><th>App</th><th class="n">7 days</th><th class="n">30 days</th><th class="n">New this week</th><th>Countries (30 days)</th></tr>${rows}</table>${sections}</main></body></html>`;
  return new Response(html, { headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store" } });
}

// One message to installations on an old version: they can't be updated from here, but every version since 0.71 asks
// for answers each day and shows a note with a notification. Fixed text and time, so it comes once and "Close" keeps it away.
const UPDATE_NOTE = {
  "energy-pilot": {
    below: [0, 95, 0], t: "2026-11-22T08:00:00Z", error: "Update available",
    text: "You're on an old version of Energy Pilot. Since then: safer control, fixed inverter profiles and better savings. " +
      "Update under Settings → Add-ons → Energy Pilot, and turn on Auto update there so you get fixes by yourself.",
  },
};

function oldVersionNote(app, version) {
  const n = UPDATE_NOTE[app];
  const v = String(version || "").match(/^(\d+)\.(\d+)\.(\d+)/);
  if (!n || !v) return null; // "dev" and unknown builds: nothing
  const mine = v.slice(1, 4).map(Number);
  const older = mine[0] !== n.below[0] ? mine[0] < n.below[0] : mine[1] !== n.below[1] ? mine[1] < n.below[1] : mine[2] < n.below[2];
  return older ? { error: n.error, hash: "update-note", state: "open", closed_at: null, msgs: [{ from: "dev", text: n.text, t: n.t }] } : null;
}

async function replies(request, env, app) {
  if (!env.DB) return json({ reports: [] });
  if (!(await allowed(request, "q", 30))) return json({ error: "rate" }, 429);
  const b = await readBody(request, 80_000);
  const install = String(b?.install || "").slice(0, 40);
  if (!/^[a-f0-9-]{16,40}$/.test(install)) return json({ error: "install" }, 400);
  await schema(env);
  await markSeen(env, request, app, install, b?.version);
  if (b?.setup && typeof b.setup === "object") await saveSetup(env, app, install, b.setup);
  await backfill(env);
  const since = new Date(Date.now() - REPLY_DAYS * 864e5).toISOString().slice(0, 10);
  const rows = (await env.DB.prepare("SELECT id, issue, day FROM reports WHERE install = ?1 AND app = ?2 AND day >= ?3 ORDER BY day DESC LIMIT 5")
    .bind(install, app, since).all()).results || [];
  const out = [];
  for (const row of rows) {
    const d = await comments(env, row.issue);
    if (!d) continue;
    const msgs = d.list.map((x) => {
      const mine = x.body.startsWith(USER_MARK);
      const raw = mine ? x.body.slice(USER_MARK.length) : x.body;
      const pics = (raw.match(/^!\[/gm) || []).length;
      const text = (mine ? raw.split("\n").filter((l) => !l.startsWith("![")).join("\n").trim().replace(/^> ?/gm, "") : raw);
      return { from: mine ? "you" : "dev", text: text.slice(0, 4000), t: x.t, ...(mine && pics ? { pics } : {}) };
    });
    out.push({ id: row.id, day: row.day, state: d.state, closed_at: d.closed_at, ...asked(d.body || ""), msgs });
  }
  // Notes on app errors this installation had (the last 60 days).
  await backfillErrors(env);
  const errs = (await env.DB.prepare(`SELECT x.hash, x.issue, e.text FROM error_installs ei JOIN error_issues x ON x.hash = ei.hash JOIN errors e ON e.hash = ei.hash
      WHERE ei.install = ?1 AND e.last_seen >= ?2 AND ${ofApp(app, "ei.hash")} ORDER BY e.last_seen DESC LIMIT 5`)
    .bind(install, since).all()).results || [];
  const notes = [];
  for (const e of errs) {
    const d = await comments(env, e.issue);
    const msgs = (d?.list || []).filter((x) => !x.body.startsWith(USER_MARK)).map((x) => ({ from: "dev", text: x.body.slice(0, 4000), t: x.t }));
    if (msgs.length) notes.push({ error: String(e.text).slice(0, 120), hash: e.hash, state: d.state, closed_at: d.closed_at, msgs });
  }
  const old = oldVersionNote(app, b?.version);
  if (old) notes.unshift(old);
  let latest = null;
  try { latest = await latestOf(env, app); } catch { /* answers come first */ }
  return json({ reports: out, notes, latest });
}

// What the user wrote when sending the report (the quoted lines at the top of the issue), and how many pictures.
function asked(body) {
  const lines = body.split("\n"), q = [];
  let i = lines.findIndex((l) => l.startsWith(">"));
  while (i >= 0 && i < lines.length && lines[i].startsWith(">")) q.push(lines[i++].replace(/^> ?/, ""));
  const pics = (body.match(/^!\[/gm) || []).length;
  return { question: q.join("\n").trim().slice(0, 4000) || null, ...(pics ? { question_pics: pics } : {}) };
}

async function userReply(request, env, app) {
  if (!env.DB) return json({ error: "no_db" }, 503);
  if (!(await allowed(request, "u", 10))) return json({ error: "rate" }, 429);
  const b = await readBody(request, MAX_BYTES);
  const install = String(b?.install || "").slice(0, 40), text = String(b?.text || "").trim().slice(0, 4000);
  const imgs = (Array.isArray(b?.images) ? b.images.slice(0, 3) : []).filter((i) => i && typeof i.data === "string" && i.data.length <= 3_000_000);
  if (!/^[a-f0-9-]{16,40}$/.test(install) || (!text && !imgs.length)) return json({ error: "content" }, 400);
  await schema(env);
  const row = await env.DB.prepare("SELECT issue FROM reports WHERE id = ?1 AND install = ?2 AND app = ?3").bind(String(b.id || ""), install, app).first();
  if (!row) return json({ error: "unknown" }, 404);
  const gh = github(env);
  const base = `https://github.com/${env.REPORT_REPO}/blob/main`, stamp = Date.now().toString(36), pics = [];
  for (const [n, img] of imgs.entries()) {  // pictures in an answer: stored beside the report's own
    const name = `reports/${app}/${String(b.id).slice(0, 40)}-r${stamp}-${n + 1}.jpg`;
    const p = await gh(`contents/${name}`, "PUT", { message: `Reply picture ${n + 1}`, content: img.data });
    if (p.ok) pics.push(`![${String(img.name || "picture").replaceAll("]", "")}](${base}/${name}?raw=true)`);
  }
  const quote = text ? `> ${text.replaceAll("\n", "\n> ")}` : "";
  const r = await gh(`issues/${row.issue}/comments`, "POST", { body: [USER_MARK, quote, pics.join("\n")].filter(Boolean).join("\n\n") });
  if (!r.ok) return json({ error: "store", status: r.status }, 502);
  await gh(`issues/${row.issue}`, "PATCH", { state: "open" });
  return json({ ok: true });
}

// ---------- helpers ----------
async function allowed(request, kind, limit) {
  const ip = request.headers.get("cf-connecting-ip") || "unknown";
  const key = new Request(`https://ep-limit.local/${kind}/${encodeURIComponent(ip)}/${new Date().toISOString().slice(0, 13)}`);
  const seen = Number((await (await caches.default.match(key))?.text()) || 0);
  if (seen >= limit) return false;
  await caches.default.put(key, new Response(String(seen + 1), { headers: { "cache-control": "max-age=3600" } }));
  return true;
}

function github(env) {
  return (path, method, data) => fetch(`https://api.github.com/repos/${env.REPORT_REPO}/${path}`, {
    method,
    headers: { authorization: `Bearer ${env.GITHUB_TOKEN}`, accept: "application/vnd.github+json",
               "user-agent": "energy-pilot-reports", "content-type": "application/json" },
    body: JSON.stringify(data),
  });
}

function mark(result) {
  return ({ ok: "✅", fixed: "🔧", failed: "❌", skipped: "⏭️" })[result] || result;
}

function detail(r) {
  if (r.result === "fixed") return `\`${r.entity}\`: \`${r.option_from}\` → \`${r.option_to}\``;
  if (r.result === "failed") return `${r.why || ""} ${(r.rejected || []).map((x) => `\`${x.entity}\`=${x.value}`).join(", ")}`;
  return r.why || "";
}

function safe(text) {
  try { return JSON.parse(text) || {}; } catch { return {}; }
}

function b64(text) {
  const bytes = new TextEncoder().encode(text);
  let s = "";
  for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(s);
}

function json(data, status = 200) {
  return new Response(JSON.stringify(data), { status, headers: { "content-type": "application/json" } });
}
