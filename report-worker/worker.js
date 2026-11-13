// Energy Pilot receiver - a Cloudflare Worker. Three jobs:
//
// 1. "Get help" (POST /): a test result, the diagnostics and up to 3 pictures, sent when the user presses the
//    button. Stored in a PRIVATE GitHub repository with an issue, so only the developer sees it.
// 2. Learning together (POST /t): small anonymous lines from every installation that hasn't turned it off - which
//    brands work, what the self-test mended, errors in the app, and a daily summary (version, country, what the
//    house has, savings per month rounded). Never names, places, or use hour by hour. Counted in a D1 database.
//    When 3 installations found the same fix, it is confirmed and every installation with that brand gets it
//    (GET /fixes); the developer gets an issue. New app errors also give an issue.
// 3. Every Monday (cron): one issue with the week's overview.
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

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/fixes") return fixes(env);
    if (request.method === "GET") return json({ ok: true, service: "energy-pilot-reports" });
    if (request.method !== "POST") return json({ error: "method" }, 405);
    if (request.headers.get("x-ep-client") !== "energy-pilot") return json({ error: "client" }, 403);
    if (url.pathname === "/t") return telemetry(request, env);
    return report(request, env);
  },
  async scheduled(_event, env) {
    await weekly(env);
  },
};

// ---------- 1. Get help ----------
async function report(request, env) {
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
  if (!diag || typeof diag !== "object" || !diag.version || !diag.settings) return json({ error: "content" }, 400);

  const id = `${new Date().toISOString().slice(0, 10).replaceAll("-", "")}-${crypto.randomUUID().slice(0, 6)}`;
  const gh = github(env);
  const base = `https://github.com/${env.REPORT_REPO}/blob/main`;
  const pics = [];
  for (const [n, img] of (Array.isArray(body.images) ? body.images.slice(0, 3) : []).entries()) {
    if (!img || typeof img.data !== "string" || img.data.length > 3_000_000) continue;
    const name = `reports/${id}-${n + 1}.jpg`;
    const r = await gh(`contents/${name}`, "PUT", { message: `Report ${id} picture ${n + 1}`, content: img.data });
    if (r.ok) pics.push(`![${String(img.name || "picture").replaceAll("]", "")}](${base}/${name}?raw=true)`);
  }
  delete body.images;
  const file = `reports/${id}.json`;
  const put = await gh(`contents/${file}`, "PUT", { message: `Report ${id}`, content: b64(JSON.stringify(body, null, 1)) });
  if (!put.ok) return json({ error: "store", status: put.status }, 502);

  const t = body.test || {};
  const results = (t.results || []).map((r) => `| ${r.part} | ${r.step} | ${mark(r.result)} | ${detail(r)} |`);
  const lines = [
    `**${id}** · Energy Pilot ${diag.version} · profile \`${body.profile || "?"}\` · ${diag.ha?.country || "?"}`,
    "",
    body.note ? `> ${String(body.note).slice(0, 4000).replaceAll("\n", "\n> ")}\n` : "",
    pics.length ? `${pics.join("\n")}\n` : "",
    results.length ? ["| Part | Step | Result | Details |", "|---|---|---|---|", ...results].join("\n") : "_No test result - diagnostics only._",
    "",
    `Diagnostics: [${file}](${base}/${file})${body.lang ? ` · language ${body.lang}` : ""}`,
  ];
  const failed = (t.results || []).some((r) => r.result === "failed");
  const issue = await gh("issues", "POST", {
    title: `${failed ? "❌" : t.results?.length ? "✅" : "📄"} ${body.profile || "report"} · ${diag.version} · ${id}`,
    body: lines.join("\n"), labels: [failed ? "test-failed" : "report"],
  });
  const made = issue.ok ? await issue.json() : {};
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
  ]);
  schemaReady = true;
}

async function telemetry(request, env) {
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
  const day = new Date().toISOString().slice(0, 10), db = env.DB;
  const s = (v, n = 80) => (v == null ? null : String(v).slice(0, n));

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
          await github(env)("issues", "POST", { title: `🔧 Confirmed fix: ${key[0]} · ${key[1]}: ${key[2]} → ${key[3]}`, labels: ["confirmed-fix"],
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
      await github(env)("issues", "POST", { title: `🐞 App error: ${s(b.text, 80)}`, labels: ["app-error"],
        body: `First seen ${day} in version ${s(b.version, 20)}.\n\n\`\`\`\n${text}\n\`\`\`` });
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
  const errs = ((await db.prepare("SELECT e.text, e.count, e.version, (SELECT COUNT(*) FROM error_installs i WHERE i.hash = e.hash) AS installs FROM errors e WHERE e.last_seen >= ?1 ORDER BY installs DESC, e.count DESC LIMIT 10").bind(since).all()).results || []);
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
  await github(env)("issues", "POST", { title: `📊 Week ${new Date().toISOString().slice(0, 10)}: ${rows.length} installations`, body, labels: ["weekly"] });
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
