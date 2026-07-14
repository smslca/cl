// Morning gate notification — Cloudflare Worker, cron 9:16 IST Mon–Fri
// (see wrangler.toml). Rule (backtested on 982 entries, exp_morning_gate.py):
// no entries if NIFTY opens below −0.2% or above +0.5% of the previous
// close — both fear and euphoria openings lose. Holdings ride.
//
// Data: Yahoo ^NSEI daily bars — the NSE open is fixed in the pre-open
// auction by ~9:08, so a 9:16 fetch always has it. NSE's own live API
// blocks datacenter IPs; Yahoo doesn't.
//
// Deploy:  npx wrangler deploy          (from this directory)
// Secrets: npx wrangler secret put TELEGRAM_BOT_TOKEN
//          npx wrangler secret put TELEGRAM_CHAT_ID
// Smoke test: open the worker URL — replies with the gate verdict,
// sends nothing (only the cron sends to Telegram).

const YAHOO =
  "https://query1.finance.yahoo.com/v8/finance/chart/%5ENSEI?interval=1d&range=5d";

async function gateMessage() {
  const r = await fetch(YAHOO, { headers: { "User-Agent": "Mozilla/5.0" } });
  if (!r.ok)
    return `⚠️ Gate check failed — Yahoo returned ${r.status}. Check the open manually before entering.`;
  const res = (await r.json()).chart.result[0];
  const ts = res.timestamp;
  const q = res.indicators.quote[0];
  const n = ts.length - 1;

  const istDate = (secs) => new Date((secs + 19800) * 1000).toISOString().slice(0, 10);
  const today = istDate(Math.floor(Date.now() / 1000));
  if (n < 1 || istDate(ts[n]) !== today)
    return "🏖 No NSE session today (holiday?) — no gate to check.";

  const open = q.open[n];
  const prev = q.close[n - 1];
  if (open == null || prev == null)
    return "⚠️ Gate check failed — open not published yet. Check manually before entering.";

  const pct = (100 * (open - prev)) / prev;
  const s = `NIFTY opened ${pct >= 0 ? "+" : ""}${pct.toFixed(2)}% (${open.toFixed(0)} vs ${prev.toFixed(0)})`;
  return pct < -0.2 || pct > 0.5
    ? `⛔ <b>Gate CLOSED</b> — ${s}. No entries today; holdings ride.`
    : `🚦 <b>Gate OPEN</b> — ${s}. Entries allowed per the shortlist.`;
}

async function send(env, text) {
  const r = await fetch(
    `https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/sendMessage`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chat_id: env.TELEGRAM_CHAT_ID, text, parse_mode: "HTML" }),
    },
  );
  if (!r.ok) throw new Error(`telegram ${r.status}: ${await r.text()}`);
}

export default {
  async scheduled(event, env, ctx) {
    await send(env, await gateMessage());
  },
  // read-only: browsing the URL shows the verdict but never sends,
  // so the public endpoint can't be used to spam the chat
  async fetch(req, env) {
    const msg = (await gateMessage()).replace(/<\/?b>/g, "");
    return new Response(msg, {
      headers: { "Content-Type": "text/plain; charset=utf-8" },
    });
  },
};
