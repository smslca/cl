// Morning gate notification — Cloudflare Worker, cron 9:16 IST Mon–Fri
// (see wrangler.toml). Rule (backtested on 982 entries, exp_morning_gate.py):
// no entries if NIFTY opens below −0.2% or above +0.5% of the previous
// close — both fear and euphoria openings lose. Holdings ride.
//
// Data: Yahoo ^NSEI *intraday* chart. The daily-bar `open` proved flaky
// (null at 9:16 on 2026-07-15, and retroactively null for completed
// sessions), but the 5m bars stream from the live feed: first bar's open
// ≈ auction open within ~0.01%, and meta.previousClose is reliable.
// NSE's own live API blocks datacenter IPs; Yahoo doesn't.
//
// Deploy:  npx wrangler deploy          (from this directory)
// Secrets: npx wrangler secret put TELEGRAM_BOT_TOKEN
//          npx wrangler secret put TELEGRAM_CHAT_ID
// Smoke test: open the worker URL — replies with the gate verdict,
// sends nothing (only the cron sends to Telegram).

const YAHOO =
  "https://query1.finance.yahoo.com/v8/finance/chart/%5ENSEI?interval=5m&range=1d";

const istDate = (secs) => new Date((secs + 19800) * 1000).toISOString().slice(0, 10);

function verdict(open, prev, label) {
  const pct = (100 * (open - prev)) / prev;
  const s = `NIFTY ${label} ${pct >= 0 ? "+" : ""}${pct.toFixed(2)}% (${open.toFixed(0)} vs ${prev.toFixed(0)})`;
  return pct < -0.2 || pct > 0.5
    ? `⛔ <b>Gate CLOSED</b> — ${s}. No entries today; holdings ride.`
    : `🚦 <b>Gate OPEN</b> — ${s}. Entries allowed per the shortlist.`;
}

// One attempt. Returns {msg, retry} — retry=true means the feed may still
// catch up and the cron path should try again before settling.
async function check() {
  const r = await fetch(YAHOO, { headers: { "User-Agent": "Mozilla/5.0" } });
  if (!r.ok)
    return { msg: `⚠️ Gate check failed — Yahoo returned ${r.status}. Check the open manually.`, retry: true };
  const res = (await r.json()).chart.result[0];
  const m = res.meta;
  const today = istDate(Math.floor(Date.now() / 1000));

  if (istDate(m.regularMarketTime) !== today)
    return { msg: "🏖 No NSE session today (holiday?) — no gate to check.", retry: false };

  const ts = res.timestamp ?? [];
  const open = res.indicators.quote[0]?.open?.[0];
  const prev = m.previousClose ?? m.chartPreviousClose;
  if (prev == null)
    return { msg: "⚠️ Gate check failed — no previous close in feed. Check manually.", retry: true };

  if (ts.length && istDate(ts[0]) === today && open != null)
    return { msg: verdict(open, prev, "opened"), retry: false };

  // session is live but the first bar hasn't landed — proxy on the live
  // tick, but only if it's actually live: a feed delayed by minutes would
  // serve a near-prev-close price and fake a "gate OPEN"
  const tickAge = Math.floor(Date.now() / 1000) - m.regularMarketTime;
  if (tickAge <= 120)
    return {
      msg: verdict(m.regularMarketPrice, prev, "at live price (open feed delayed)"),
      retry: true,
    };
  return {
    msg: `⚠️ Yahoo feed is ${Math.round(tickAge / 60)} min behind — no trustworthy open yet. Check manually before entering.`,
    retry: true,
  };
}

// Cron path: give the feed up to ~2.5 min to publish the real open.
async function gateMessage(retries = 3) {
  let last;
  for (let i = 0; ; i++) {
    last = await check();
    if (!last.retry || i >= retries) return last.msg;
    await new Promise((res) => setTimeout(res, 45_000));
  }
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
  // read-only and no retries: browsing the URL answers instantly and never
  // sends, so the public endpoint can't be used to spam the chat
  async fetch(req, env) {
    const msg = (await gateMessage(0)).replace(/<\/?b>/g, "");
    return new Response(msg, {
      headers: { "Content-Type": "text/plain; charset=utf-8" },
    });
  },
};
