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
    if (request.method === "GET") return json({ ok: true, service: "energy-pilot-reports" });
    if (request.method !== "POST") return json({ error: "method" }, 405);
    const app = request.headers.get("x-ep-client");
    if (!APPS[app]) return json({ error: "client" }, 403);
    if (url.pathname === "/t") return telemetry(request, env, app);
    if (url.pathname === "/replies") return replies(request, env, app);
    if (url.pathname === "/reply") return userReply(request, env, app);
    return report(request, env, app);
  },
  async scheduled(_event, env) {
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
  ]);
  try { await env.DB.prepare("ALTER TABLE seen ADD COLUMN version TEXT").run(); } catch { /* there already */ }
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
      const failed = res.filter((r) => r.result === "failed").map((r) => `${r.step}:${s(r.why, 30)}`).join(",");
      await db.prepare("INSERT OR REPLACE INTO tests (install, part, profile, model, day, ok, failed) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)")
        .bind(install, part, s(part === "car" ? b.charger : b.profile), s(b.model), day, failed ? 0 : 1, failed || null).run();
    }
    for (const r of (b.results || []).filter((x) => x.result === "fixed" && x.part === "battery")) {
      const key = [s(b.profile), s(r.step, 20), s(r.option_from), s(r.option_to)];
      await db.prepare("INSERT OR IGNORE INTO fixes (profile, intent, opt_from, opt_to, install, day) VALUES (?1, ?2, ?3, ?4, ?5, ?6)")
        .bind(...key, install, day).run();
      const n = (await db.prepare("SELECT COUNT(*) AS n FROM fixes WHERE profile = ?1 AND intent = ?2 AND opt_from = ?3 AND opt_to = ?4").bind(...key).first()).n;
      if (n >= CONFIRM) {
        const fresh = await db.prepare("INSERT OR IGNORE INTO confirmed (profile, intent, opt_from, opt_to, day) VALUES (?1, ?2, ?3, ?4, ?5)").bind(...key, day).run();
        if (fresh.meta?.changes) {
          await github(env)("issues", "POST", { title: `⚡ Energy Pilot: 🔧 confirmed fix ${key[0]} · ${key[1]}: ${key[2]} → ${key[3]}`, labels: ["energy-pilot", "confirmed-fix"],
            body: `${n} installations with profile \`${key[0]}\` found that **${key[1]}** works with \`${key[3]}\` instead of \`${key[2]}\`.\n\nEvery installation with this profile now gets it. Put it in the profile in \`adapters.py\` so new users have it from the start.` });
        }
      }
    }
  } else if (b.kind === "error") {
    const hash = s(b.hash, 40), text = s(b.text, 300);
    if (!hash) return json({ error: "hash" }, 400);
    const known = await db.prepare("SELECT count FROM errors WHERE hash = ?1").bind(hash).first();
    await db.prepare("INSERT INTO errors (hash, first_seen, last_seen, count, version, text) VALUES (?1, ?2, ?2, 1, ?3, ?4) ON CONFLICT(hash) DO UPDATE SET last_seen = ?2, count = count + 1, version = ?3")
      .bind(hash, day, s(b.version, 20), text).run();
    await db.prepare("INSERT OR IGNORE INTO error_installs (hash, install) VALUES (?1, ?2)").bind(hash, install).run();
    if (!known) {
      const r = await github(env)("issues", "POST", { title: `⚡ Energy Pilot: 🐞 ${s(b.text, 80)}`, labels: ["energy-pilot", "app-error"],
        body: `First seen ${day} in version ${s(b.version, 20)}.\n\n\`\`\`\n${text}\n\`\`\`\n\n_Comments here reach every installation that had this error._` });
      await rememberIssue(db, hash, r);
    }
  } else if (b.kind === "autofix") {
    await db.prepare("INSERT OR IGNORE INTO autofix (key, install, day) VALUES (?1, ?2, ?3)").bind(s(b.key, 40), install, day).run();
  } else {
    return json({ error: "kind" }, 400);
  }
  return json({ ok: true });
}

async function fixes(env) {
  if (!env.DB) return json({ fixes: [], tested: {} });
  await schema(env);
  const f = await env.DB.prepare("SELECT profile, intent, opt_from AS 'from', opt_to AS 'to' FROM confirmed").all();
  const t = await env.DB.prepare("SELECT profile, SUM(ok) AS ok, COUNT(*) AS n FROM tests GROUP BY profile").all();
  const tested = Object.fromEntries((t.results || []).map((r) => [r.profile, { ok: r.ok, n: r.n }]));
  return new Response(JSON.stringify({ fixes: f.results || [], tested }), {
    headers: { "content-type": "application/json", "cache-control": "public, max-age=3600" } });
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
  const d = { state: info.state, closed_at: info.closed_at || null, list: (await c.json()).map((x) => ({ body: String(x.body || ""), t: x.created_at })) };
  await caches.default.put(key, new Response(JSON.stringify(d), { headers: { "cache-control": "max-age=300" } }));
  return d;
}

// ---------- 4. How many use the apps ----------
// One row per app, installation and day, with the country Cloudflare sees for the connection - nothing the app sends.
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
  const latestRows = await q("SELECT k, v FROM meta WHERE k LIKE 'latest:%'");
  const newest = Object.fromEntries(latestRows.map((r) => [r.k.slice(7), safe(r.v)?.l?.version]));
  const since = (await q("SELECT MIN(day) AS d FROM seen"))[0]?.d || "–";
  const esc = (t) => String(t).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" })[c]);
  const rows = Object.keys(APPS).map((k) => {
    const p = per.find((r) => r.app === k) || { w: 0, m: 0 }, f = (fresh.find((r) => r.app === k) || { n: 0 }).n;
    const l = lands.filter((r) => r.app === k).map((r) => `<span>${flag(r.country)} ${esc(r.country)} <b>${r.n}</b></span>`).join("");
    const vs = vers.filter((r) => r.app === k), onNew = vs.filter((r) => r.version === newest[k]).reduce((a, r) => a + r.n, 0), tot = vs.reduce((a, r) => a + r.n, 0);
    const vline = vs.length ? `<div class="vs">${vs.map((r) => `<span class="${r.version === newest[k] ? "ok" : ""}">${esc(r.version)} <b>${r.n}</b></span>`).join("")}${newest[k] ? ` · <em>${Math.round(100 * onNew / tot)} % on ${esc(newest[k])}</em>` : ""}</div>` : (newest[k] ? `<div class="vs"><em>newest ${esc(newest[k])}</em></div>` : "");
    return `<tr><td><b>${esc(APPS[k].name)}</b>${vline}${l ? `<div class="cm c">${l}</div>` : ""}</td><td class="n">${p.w}</td><td class="n">${p.m}</td><td class="n">${f ? "+" + f : "–"}</td><td class="c">${l || "–"}</td></tr>`;
  }).join("");
  const all = (await q("SELECT COUNT(DISTINCT install) AS n FROM seen WHERE day >= ?1", ago(30)))[0]?.n || 0;
  // the rest, from what the apps already send: Energy Pilot's and Madplan's daily lines, self-tests, app errors, help
  const tally = (rows, f) => Object.entries(rows.reduce((a, r) => { for (const k of [].concat(f(r.d) ?? "?")) a[k] = (a[k] || 0) + 1; return a; }, {}))
    .sort((a, b) => b[1] - a[1]).map(([k, n]) => `<span class="ch">${esc(k)} <b>${n}</b></span>`).join("") || "–";
  const avg = (rows, f) => { const v = rows.map((r) => f(r.d)).filter((x) => typeof x === "number"); return v.length ? (v.reduce((a, b) => a + b, 0) / v.length).toFixed(1) : "–"; };
  const ep = (await q("SELECT first_seen, data FROM installs WHERE last_seen >= ?1", ago(30))).map((r) => ({ ...r, d: safe(r.data) || {} }));
  const mp = (await q("SELECT first_seen, data FROM m_installs WHERE last_seen >= ?1", ago(30))).map((r) => ({ ...r, d: safe(r.data) || {} }));
  const tests = await q("SELECT profile, part, SUM(ok) AS ok, COUNT(*) AS n, GROUP_CONCAT(failed, ' / ') AS failed FROM tests GROUP BY profile, part ORDER BY n DESC LIMIT 30");
  const fixesN = (await q("SELECT COUNT(*) AS n FROM confirmed"))[0]?.n || 0;
  const mended = await q("SELECT key, COUNT(*) AS n FROM autofix GROUP BY key ORDER BY n DESC LIMIT 12");
  const errs = await q("SELECT e.hash, e.text, e.count, e.version, e.last_seen, (SELECT COUNT(*) FROM error_installs i WHERE i.hash = e.hash) AS installs, (SELECT issue FROM error_issues x WHERE x.hash = e.hash) AS issue FROM errors e WHERE e.last_seen >= ?1 ORDER BY installs DESC, e.count DESC LIMIT 25", ago(30));
  const appOf = (h) => Object.keys(APPS).find((k) => k !== "energy-pilot" && APPS[k].prefix && h.startsWith(APPS[k].prefix)) || "energy-pilot";
  const help = await q("SELECT app, COUNT(*) AS n, MAX(day) AS last FROM reports WHERE day >= ?1 GROUP BY app ORDER BY n DESC", ago(30));
  const helpLast = await q("SELECT id, app, issue, day FROM reports ORDER BY day DESC LIMIT 8");
  const gh = (n) => n && env.REPORT_REPO ? `<a href="https://github.com/${esc(env.REPORT_REPO)}/issues/${n}">#${n}</a>` : "";
  const has = (k) => ep.filter((r) => r.d.has?.[k]).length;
  const sections = `
<h2>⚡ Energy Pilot · ${ep.length} active</h2><div class="card">
<div class="row"><i>Inverters</i>${tally(ep, (d) => d.profile)}</div><div class="row"><i>Chargers</i>${tally(ep, (d) => d.charger)}</div>
<div class="row"><i>Prices</i>${tally(ep, (d) => d.price)}</div><div class="row"><i>Versions</i>${tally(ep, (d) => d.version)}</div>
<div class="row"><i>Home Assistant</i>${tally(ep, (d) => d.ha)}</div><div class="row"><i>Countries</i>${tally(ep, (d) => d.country)}</div><div class="row"><i>Languages</i>${tally(ep, (d) => d.lang)}</div>
<div class="row"><i>Has</i><span class="ch">battery <b>${has("battery")}</b></span><span class="ch">car <b>${has("car")}</b></span><span class="ch">solar <b>${has("pv")}</b></span><span class="ch">controlling <b>${ep.filter((r) => Object.values(r.d.modes || {}).includes("control")).length}</b></span></div>
<div class="row"><i>Saved / month (avg)</i><span class="ch"><b>${avg(ep, (d) => d.saved_month)}</b></span><i style="margin-left:12px">Battery kWh (avg)</i><span class="ch"><b>${avg(ep, (d) => d.battery_kwh)}</b></span></div>
<div class="row"><i>Fixes confirmed</i><span class="ch"><b>${fixesN}</b></span><i style="margin-left:12px">Mended by itself</i>${mended.map((m) => `<span class="ch">${esc(m.key)} <b>${m.n}</b></span>`).join("") || "–"}</div></div>
<h3>Self-test</h3><table><tr><th>Inverter</th><th>Part</th><th class="n">Passed</th><th>What failed</th></tr>${tests.map((t) => `<tr><td>${esc(t.profile)}</td><td>${esc(t.part)}</td><td class="n">${t.ok} / ${t.n}</td><td class="sm">${esc((t.failed || "").slice(0, 140))}</td></tr>`).join("") || `<tr><td colspan="4">–</td></tr>`}</table>
<h2>🍽️ Madplan · ${mp.length} active</h2><div class="card">
<div class="row"><i>Main chain</i>${tally(mp, (d) => d.chain)}</div><div class="row"><i>Also shops at</i>${tally(mp, (d) => d.extra || [])}</div>
<div class="row"><i>Versions</i>${tally(mp, (d) => d.version)}</div><div class="row"><i>AI</i>${tally(mp, (d) => d.ai)}</div></div>
<h2>🐞 App errors · last 30 days</h2><table><tr><th>App</th><th class="n">Installs</th><th class="n">Times</th><th>Version</th><th>Error</th></tr>
${errs.map((e) => `<tr><td>${APPS[appOf(e.hash)].mark}</td><td class="n">${e.installs}</td><td class="n">${e.count}</td><td>${esc(e.version || "")}</td><td class="sm">${esc(String(e.text).slice(0, 140))} ${gh(e.issue)}</td></tr>`).join("") || `<tr><td colspan="5">No errors 🎉</td></tr>`}</table>
<h2>🛟 Help messages · last 30 days</h2><div class="card"><div class="row">${help.map((h) => `<span class="ch">${APPS[h.app]?.mark || ""} ${esc(APPS[h.app]?.name || h.app)} <b>${h.n}</b></span>`).join("") || "–"}</div>
<div class="row"><i>Latest</i>${helpLast.map((h) => `<span class="ch">${APPS[h.app]?.mark || ""} ${esc(h.day)} ${gh(h.issue)}</span>`).join("") || "–"}</div></div>`;
  const html = `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>App users</title>
<style>body{margin:0;font-family:-apple-system,Inter,Segoe UI,Roboto,sans-serif;background:#0f1220;color:#eef0f7}main{max-width:900px;margin:0 auto;padding:22px 16px}
h1{font-size:24px;margin:0 0 4px}p{color:#9aa3b8;margin:0 0 18px;font-size:14px}.big{font-size:44px;font-weight:800;margin:6px 0 18px}
table{width:100%;border-collapse:collapse;background:#171b2e;border-radius:16px;overflow:hidden}th,td{padding:11px 12px;text-align:left;border-bottom:1px solid #232945;font-size:14px}
th{color:#9aa3b8;font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.04em}.n{text-align:right;font-variant-numeric:tabular-nums}.c span{display:inline-block;margin:2px 10px 2px 0;white-space:nowrap}
h2{font-size:18px;margin:30px 0 10px}h3{font-size:14px;color:#9aa3b8;margin:16px 0 8px;text-transform:uppercase;letter-spacing:.04em}
.card{background:#171b2e;border-radius:16px;padding:12px 14px}.row{display:flex;flex-wrap:wrap;align-items:center;gap:6px;padding:6px 0;border-bottom:1px solid #232945}.row:last-child{border-bottom:0}
.row i{font-style:normal;color:#9aa3b8;font-size:12px;min-width:120px}.ch{background:#232945;border-radius:99px;padding:4px 10px;font-size:13px}.ch b{color:#ffd34d}
.sm{font-size:12.5px;color:#c9cfe0}a{color:#8fb8ff}
.cm{display:none;margin-top:4px;font-size:12.5px}
.vs{margin-top:4px;font-size:12px;color:#9aa3b8}.vs span{display:inline-block;margin-right:8px}.vs span.ok{color:#5be3a0}.vs em{font-style:normal}
@media(max-width:600px){.apps th:nth-child(5),.apps td:nth-child(5){display:none}.cm{display:block}}</style></head><body><main>
<h1>Who uses the apps</h1><p>Installations that asked in – one per app and day, with the country of the connection. Counting since ${esc(since)}. Installations that turned sharing off aren't counted.</p>
<div class="big">${all}<span style="font-size:15px;color:#9aa3b8;font-weight:500"> installations in the last 30 days</span></div>
<table class="apps"><tr><th>App</th><th class="n">7 days</th><th class="n">30 days</th><th class="n">New this week</th><th>Countries (30 days)</th></tr>${rows}</table>${sections}</main></body></html>`;
  return new Response(html, { headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store" } });
}

async function replies(request, env, app) {
  if (!env.DB) return json({ reports: [] });
  if (!(await allowed(request, "q", 30))) return json({ error: "rate" }, 429);
  const b = await readBody(request);
  const install = String(b?.install || "").slice(0, 40);
  if (!/^[a-f0-9-]{16,40}$/.test(install)) return json({ error: "install" }, 400);
  await schema(env);
  await markSeen(env, request, app, install, b?.version);
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
      const text = mine ? x.body.slice(USER_MARK.length).trim().replace(/^> ?/gm, "") : x.body;
      return { from: mine ? "you" : "dev", text: text.slice(0, 4000), t: x.t };
    });
    out.push({ id: row.id, day: row.day, state: d.state, closed_at: d.closed_at, msgs });
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
  let latest = null;
  try { latest = await latestOf(env, app); } catch { /* answers come first */ }
  return json({ reports: out, notes, latest });
}

async function userReply(request, env, app) {
  if (!env.DB) return json({ error: "no_db" }, 503);
  if (!(await allowed(request, "u", 10))) return json({ error: "rate" }, 429);
  const b = await readBody(request);
  const install = String(b?.install || "").slice(0, 40), text = String(b?.text || "").trim().slice(0, 4000);
  if (!/^[a-f0-9-]{16,40}$/.test(install) || !text) return json({ error: "content" }, 400);
  await schema(env);
  const row = await env.DB.prepare("SELECT issue FROM reports WHERE id = ?1 AND install = ?2 AND app = ?3").bind(String(b.id || ""), install, app).first();
  if (!row) return json({ error: "unknown" }, 404);
  const gh = github(env);
  const r = await gh(`issues/${row.issue}/comments`, "POST", { body: `${USER_MARK}\n\n> ${text.replaceAll("\n", "\n> ")}` });
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
