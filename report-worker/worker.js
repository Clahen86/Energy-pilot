// Energy Pilot report receiver - a Cloudflare Worker.
//
// Energy Pilot sends a test result and its diagnostics here when the user presses "Send to the developer".
// The worker stores the file in a PRIVATE GitHub repository and opens an issue there, so only the developer sees it.
// Nothing is kept in Cloudflare.
//
// Settings (Workers -> your worker -> Settings -> Variables and secrets):
//   GITHUB_TOKEN  (secret) fine-grained token with Contents + Issues: read and write on the private repository only
//   REPORT_REPO   (text)   owner/name of the private repository, e.g. Clahen86/energy-pilot-reports

const MAX_BYTES = 9_000_000; // a diagnostics file is usually 50-300 kB, plus up to 3 pictures
const PER_HOUR = 5; // reports from one address per hour

export default {
  async fetch(request, env) {
    if (request.method === "GET") return json({ ok: true, service: "energy-pilot-reports" });
    if (request.method !== "POST") return json({ error: "method" }, 405);
    if (request.headers.get("x-ep-client") !== "energy-pilot") return json({ error: "client" }, 403);
    const size = Number(request.headers.get("content-length") || 0);
    if (size > MAX_BYTES) return json({ error: "too_big" }, 413);

    // A few reports per address and hour - enough for anyone, too few for spam.
    const ip = request.headers.get("cf-connecting-ip") || "unknown";
    const hour = new Date().toISOString().slice(0, 13);
    const key = new Request(`https://ep-limit.local/${encodeURIComponent(ip)}/${hour}`);
    const cache = caches.default;
    const seen = Number((await (await cache.match(key))?.text()) || 0);
    if (seen >= PER_HOUR) return json({ error: "rate" }, 429);
    await cache.put(key, new Response(String(seen + 1), { headers: { "cache-control": "max-age=3600" } }));

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
    const repo = env.REPORT_REPO;
    const gh = (path, method, data) => fetch(`https://api.github.com/repos/${repo}/${path}`, {
      method,
      headers: { authorization: `Bearer ${env.GITHUB_TOKEN}`, accept: "application/vnd.github+json",
                 "user-agent": "energy-pilot-reports", "content-type": "application/json" },
      body: JSON.stringify(data),
    });

    // 1. The pictures (if any) and the full file in the private repository.
    const base = `https://github.com/${repo}/blob/main`;
    const pics = [];
    for (const [n, img] of (Array.isArray(body.images) ? body.images.slice(0, 3) : []).entries()) {
      if (!img || typeof img.data !== "string" || img.data.length > 3_000_000) continue;
      const name = `reports/${id}-${n + 1}.jpg`;
      const r = await gh(`contents/${name}`, "PUT", { message: `Report ${id} picture ${n + 1}`, content: img.data });
      if (r.ok) pics.push(`![${String(img.name || "picture").replaceAll("]", "")}](${base}/${name}?raw=true)`);
    }
    delete body.images;
    const file = `reports/${id}.json`;
    const pretty = JSON.stringify(body, null, 1);
    const put = await gh(`contents/${file}`, "PUT", { message: `Report ${id}`, content: b64(pretty) });
    if (!put.ok) return json({ error: "store", status: put.status }, 502);

    // 2. An issue with the short version and a link to the file.
    const t = body.test || {};
    const results = (t.results || []).map((r) => `| ${r.part} | ${r.step} | ${({ ok: "✅", fixed: "🔧", failed: "❌", skipped: "⏭️" })[r.result] || r.result} | ${detail(r)} |`);
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
      body: lines.join("\n"),
      labels: [failed ? "test-failed" : "report"],
    });
    const made = issue.ok ? await issue.json() : {};
    return json({ ok: true, id, issue: made.number || null });
  },
};

function detail(r) {
  if (r.result === "fixed") return `\`${r.entity}\`: \`${r.option_from}\` → \`${r.option_to}\``;
  if (r.result === "failed") return `${r.why || ""} ${(r.rejected || []).map((x) => `\`${x.entity}\`=${x.value}`).join(", ")}`;
  return r.why || "";
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
