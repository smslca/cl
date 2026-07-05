"""Render out/dashboard.html — the morning view, organized as four questions:

  1. Is the market condition good for trading?   (breadth regime + adv/decl)
  2. What are the hot sectors?                    (equal-weight sector returns)
  3. Who are the sector leaders?                  (top RS stocks in top sectors)
  4. Which sector/stock is smart money chasing?   (delivery-backed accumulation)

Sector membership comes from the latest constituents snapshot filtered to
config/sector_indices.csv. Static HTML, no server — open in a browser.
"""

import datetime
import json
import pathlib
import zoneinfo

import duckdb
import pandas as pd

from metrics import FEATURES_SQL

ROOT = pathlib.Path(__file__).resolve().parent
OUT = ROOT / "out"
SECTORS = ROOT / "config" / "sector_indices.csv"


def load(con: duckdb.DuckDBPyConnection):
    con.execute(f"CREATE TEMP VIEW f AS {FEATURES_SQL}")
    latest_cons = max((ROOT / "data" / "raw" / "constituents").glob("*.csv"))
    con.execute(f"""
        CREATE TEMP VIEW members AS
        SELECT DISTINCT c.symbol, c.index_name AS sector
        FROM read_csv_auto('{latest_cons}') c
        JOIN read_csv_auto('{SECTORS}') s ON c.index_name = s.indexSymbol
    """)
    con.execute("""
        CREATE TEMP VIEW fx AS
        SELECT *,
            lag(close, 5)  OVER sym AS close_1w,
            lag(close, 21) OVER sym AS close_1m,
            lag(close, 63) OVER sym AS close_3m,
            deliv_per > avg_deliv_20 AS deliv_expanding,
            sum(CASE WHEN deliv_per > avg_deliv_20 THEN 1 ELSE 0 END)
                OVER (PARTITION BY symbol ORDER BY d ROWS BETWEEN 4 PRECEDING AND CURRENT ROW) AS accum_5,
            close >= 0.85 * hi_252 AND days_in_252 >= 250 AS near_high
        FROM f WHERE history_days >= 50
        WINDOW sym AS (PARTITION BY symbol ORDER BY d)
    """)


def build_frames(con):
    breadth = con.execute("""
        SELECT d,
            sum(CASE WHEN close > prev_close THEN 1 ELSE 0 END) AS advances,
            sum(CASE WHEN close < prev_close THEN 1 ELSE 0 END) AS declines,
            round(100.0 * sum(CASE WHEN close > sma20 THEN 1 ELSE 0 END) / count(*), 1) AS pct20,
            round(100.0 * sum(CASE WHEN close > sma50 THEN 1 ELSE 0 END) / count(*), 1) AS pct50
        FROM fx GROUP BY d ORDER BY d
    """).df()

    sectors = con.execute("""
        WITH latest AS (SELECT max(d) AS d FROM fx),
        today AS (
            SELECT m.sector, x.*
            FROM fx x JOIN members m USING (symbol), latest WHERE x.d = latest.d
        ),
        accum AS (  -- 5-day average share of members with expanding delivery
            SELECT m.sector,
                round(100.0 * avg(CASE WHEN x.deliv_expanding THEN 1.0 ELSE 0 END), 0) AS accum_pct
            FROM fx x JOIN members m USING (symbol), latest
            WHERE x.d > latest.d - INTERVAL 9 DAY
            GROUP BY m.sector
        )
        SELECT t.sector,
            count(*) AS n,
            round(100 * avg(t.close / nullif(t.close_1w, 0) - 1), 1) AS ret_1w,
            round(100 * avg(t.close / nullif(t.close_1m, 0) - 1), 1) AS ret_1m,
            round(100 * avg(t.close / nullif(t.close_3m, 0) - 1), 1) AS ret_3m,
            round(100.0 * sum(CASE WHEN t.close > t.sma20 THEN 1 ELSE 0 END) / count(*), 0) AS pct_above_20,
            round(100 * avg(t.close / t.sma20 - 1), 1) AS ext_pct,
            any_value(a.accum_pct) AS accum_pct
        FROM today t JOIN accum a USING (sector)
        GROUP BY t.sector
        ORDER BY ret_1m DESC
    """).df()

    # PRIORITY sector = building up, not extended: above-median month, still
    # rising this week, members near support, delivery flowing in
    sectors["priority"] = (
        (sectors.ret_1m >= sectors.ret_1m.median())
        & (sectors.ret_1w > 0)
        & (sectors.ext_pct <= 5.0)
        & (sectors.accum_pct >= 55)
    )
    prio = list(sectors[sectors.priority].sector)

    prio_sql = ",".join(f"'{s}'" for s in prio) or "'__none__'"

    radar = con.execute("""
        WITH latest AS (SELECT max(d) AS d FROM fx),
        ranked AS (
            SELECT fx.*, percent_rank() OVER (ORDER BY ret_30d) AS rs_rank
            FROM fx, latest WHERE fx.d = latest.d AND ret_30d IS NOT NULL
        )
        SELECT r.symbol,
            coalesce(string_agg(DISTINCT m.sector, ', '), '—') AS sectors,
            r.close, round(r.ret_30d, 1) AS ret_30d,
            round(r.rs_rank, 2) AS rs_rank, round(r.rvol, 2) AS rvol,
            r.accum_5,
            round(100 * r.close / r.hi_252, 0) AS pct_of_52wk_high,
            round((r.close / r.sma20 - 1) * 100, 0) AS ext_pct,
            r.hi_10, r.lo_10,
            r.near_high
        FROM ranked r LEFT JOIN members m USING (symbol)
        WHERE r.accum_5 >= 4          -- delivery above average 4+ of last 5 sessions
          AND r.rs_rank >= 0.60
          AND r.close > r.sma20
        GROUP BY ALL ORDER BY r.accum_5 DESC, rs_rank DESC
        LIMIT 17
    """).df()

    # IPO = any symbol whose first appearance is after our history begins
    # (~2-year window), not just NIFTY IPO index members
    ipo = con.execute("""
        WITH latest AS (SELECT max(d) AS d FROM f),
        hist_start AS (SELECT min(d) AS d0 FROM f),
        first_seen AS (SELECT symbol, min(d) AS listed FROM f GROUP BY symbol),
        fipo AS (
            SELECT *,
                sum(CASE WHEN deliv_per > avg_deliv_20 THEN 1 ELSE 0 END)
                    OVER (PARTITION BY symbol ORDER BY d ROWS BETWEEN 4 PRECEDING AND CURRENT ROW) AS accum_5
            FROM f WHERE history_days >= 21
        )
        SELECT x.symbol, fs.listed, x.close,
            round(x.ret_30d, 1) AS ret_30d,
            round(x.rvol, 2) AS rvol,
            round(x.deliv_per, 1) AS deliv_per,
            round(x.avg_deliv_20, 1) AS avg_deliv_20,
            x.accum_5,
            round(100 * x.close / x.hi_252, 0) AS pct_of_high,
            round((x.close / x.sma20 - 1) * 100, 0) AS ext_pct,
            x.history_days
        FROM fipo x
        JOIN first_seen fs USING (symbol), latest, hist_start
        WHERE x.d = latest.d
          AND fs.listed > hist_start.d0 + INTERVAL 10 DAY
        ORDER BY ret_30d DESC NULLS LAST
    """).df()

    # the trigger list, with confluence flags baked in: PRIORITY-sector member,
    # radar streak this week, recent listing
    shortlist = con.execute(f"""
        WITH latest AS (SELECT max(d) AS d FROM fx),
        hist AS (SELECT min(d) AS d0 FROM f),
        first_seen AS (SELECT symbol, min(d) AS listed FROM f GROUP BY symbol),
        ranked AS (
            SELECT fx.*, percent_rank() OVER (ORDER BY ret_30d) AS rs_rank
            FROM fx, latest WHERE fx.d = latest.d AND ret_30d IS NOT NULL
        )
        SELECT r.symbol,
            coalesce(string_agg(DISTINCT m.sector, ', '), '—') AS sectors,
            r.close, round(r.ret_30d, 1) AS ret_30d,
            round(r.rs_rank, 2) AS rs_rank, round(r.rvol, 2) AS rvol,
            round(r.deliv_per, 1) AS deliv_per, round(r.avg_deliv_20, 1) AS avg_deliv_20,
            round(100 * r.close / r.hi_252, 0) AS pct_of_52wk_high,
            round((r.close / r.sma20 - 1) * 100, 0) AS ext_pct,
            r.low AS sig_low,
            r.accum_5,
            max(CASE WHEN m.sector IN ({prio_sql}) THEN 1 ELSE 0 END) AS in_priority,
            max(CASE WHEN fs.listed > hist.d0 + INTERVAL 10 DAY THEN 1 ELSE 0 END) AS is_new
        FROM ranked r
        LEFT JOIN members m USING (symbol)
        JOIN first_seen fs USING (symbol), hist
        WHERE r.rs_rank >= 0.80 AND r.rvol >= 1.5 AND r.close > r.sma20
          AND r.deliv_expanding AND r.near_high
        GROUP BY ALL ORDER BY rvol DESC
    """).df()

    return breadth, sectors, finalize_shortlist(shortlist), radar


def finalize_shortlist(shortlist: pd.DataFrame) -> pd.DataFrame:
    """Grade, sort and cap the shortlist — the exact list shown and persisted."""
    if shortlist.empty:
        return shortlist

    def _grade(r):
        g = {2: "A+", 1: "A"}.get(int(r.in_priority) + (1 if r.accum_5 >= 3 else 0), "B")
        # A+ is reserved for full-strength signals: below the tested 2x
        # volume bar, confluence alone cannot earn the top grade
        if g == "A+" and r.rvol < 2:
            g = "A"
        return g

    graded = shortlist.assign(grade=[_grade(r) for r in shortlist.itertuples()])
    return (
        graded.assign(gorder=graded.grade.map({"A+": 0, "A": 1, "B": 2}))
        .sort_values(["gorder", "rvol"], ascending=[True, False])
        .drop(columns="gorder")
        .head(10)
    )


def regime_verdict(breadth: pd.DataFrame) -> tuple[str, str, str]:
    now, prior = breadth.iloc[-1], breadth.iloc[-11]
    rising = now.pct20 >= prior.pct20
    if now.pct20 >= 55 and rising:
        return ("GOOD", "#1D9E75", "breadth ≥ 55% and rising — normal position sizing")
    if now.pct20 < 45 and not rising:
        return ("WEAK", "#D85A30", "breadth < 45% and falling — reduce exposure, smaller size")
    return ("MIXED", "#BA7517", "be selective — lean on the shortlist, not conviction")


def heat(v, lo=-8, hi=8):
    if pd.isna(v):
        return ""
    a = min(abs(v) / max(abs(lo), hi), 1) * 0.45
    color = "29,158,117" if v >= 0 else "216,90,48"
    return f"background: rgba({color},{a:.2f});"


def render(breadth, sectors, shortlist, radar) -> str:
    verdict, vcolor, vrule = regime_verdict(breadth)
    now = breadth.iloc[-1]
    day = pd.Timestamp(now.d).date()
    breadth = breadth.assign(
        adv_smooth=breadth.advances.rolling(10).mean().round(0),
        dec_smooth=breadth.declines.rolling(10).mean().round(0),
    )
    year = breadth.tail(250)
    chase = sectors.sort_values("accum_pct", ascending=False).head(3)

    sector_rows = "\n".join(
        f"<tr><td>{s.sector}{' <span class=badge>PRIORITY</span>' if s.priority else ''}</td>"
        f"<td style='{heat(s.ret_1w)}'>{s.ret_1w:+.1f}%</td>"
        f"<td style='{heat(s.ret_1m)}'>{s.ret_1m:+.1f}%</td>"
        f"<td style='{heat(s.ret_3m, -15, 15)}'>{s.ret_3m:+.1f}%</td>"
        f"<td>{s.pct_above_20:.0f}%</td>"
        f"<td style='{heat(s.accum_pct - 50, -50, 50)}'>{s.accum_pct:.0f}%</td>"
        f"<td style='{heat(s.ext_pct, -10, 10)}'>{s.ext_pct:+.1f}%"
        f"{' <span class=badge-a>hot but late</span>' if s.ext_pct > 7 else ''}</td></tr>"
        for s in sectors.itertuples()
    )

    on_shortlist = set(shortlist.symbol)
    def alert(r):
        trigger, floor = r.hi_10, r.lo_10
        prov_risk = (trigger - floor) / trigger * 100
        if prov_risk > 12:
            return f"<td>{trigger}</td><td colspan=2><span class=badge-a>not worth watching — {prov_risk:.0f}% wide</span></td>"
        return f"<td>{trigger}</td><td>{floor}</td><td>{prov_risk:.1f}%</td>"

    radar_rows = "\n".join(
        f"<tr><td class='sym'>{r.symbol}{' ★' if r.symbol in on_shortlist else ''}</td>"
        f"<td>{r.sectors}</td><td>{r.close}</td><td>{r.ret_30d:+.1f}%</td>"
        f"<td>{r.accum_5}/5</td>"
        f"<td>{r.pct_of_52wk_high:.0f}%</td>"
        f"{alert(r)}</tr>"
        for r in radar.itertuples()
    )

    if len(shortlist):
        # cloud renders fall back to the example config if risk.json is absent
        risk_path = ROOT / "config" / "risk.json"
        placeholder_risk = not risk_path.exists()
        if placeholder_risk:
            risk_path = ROOT / "config" / "risk.json.example"
        risk_cfg = json.loads(risk_path.read_text())
        capital = risk_cfg["capital_inr"]
        risk_amount = capital * risk_cfg["risk_per_trade_pct"] / 100

        def reason(r):
            bits = [
                f"{r.rvol}x normal volume" + (" (below the 2x tested bar)" if r.rvol < 2 else ""),
                f"beat {r.rs_rank * 100:.0f}% of all stocks this month",
                f"delivery {r.deliv_per}% vs {r.avg_deliv_20}% usual",
                f"{100 - r.pct_of_52wk_high:.0f}% below 52wk high",
            ]
            if r.ext_pct > 15:
                bits.append(f"stretched {r.ext_pct:+.0f}% over 20sma")
            return " · ".join(bits)

        def ticket(r):
            entry, stop = r.close, r.sig_low
            risk_pct = (entry - stop) / entry * 100
            if risk_pct < 0.3:  # closed on the day's low; stop has no room
                stop = round(entry * 0.97, 1)
                risk_pct = 3.0
            if risk_pct > 8:
                qty_cell = f"<span class=badge-a>skip — stop {risk_pct:.0f}% wide</span>"
            else:
                max_position = capital * risk_cfg["max_position_pct"] / 100
                qty = int(min(risk_amount / (entry - stop), max_position / entry))
                qty_cell = f"{qty}" if qty >= 1 else "<span class=badge-a>share price exceeds position cap</span>"
            return (f"<td>{entry}</td><td>{entry * 1.03:.1f}</td><td>{stop}</td>"
                    f"<td>{risk_pct:.1f}%</td><td>{qty_cell}</td>")

        def badges(r):
            out = ""
            if r.in_priority:
                out += "<span class=badge>PRIORITY sector</span> "
            if r.accum_5 >= 3:
                out += f"<span class=badge-t>on radar {int(r.accum_5)}/5</span> "
            if r.is_new:
                out += "<span class=badge-a>recent listing</span> "
            return out

        sl_rows = "\n".join(
            f"<tr><td><b>{r.grade}</b></td><td class='sym'>{r.symbol}</td>"
            f"<td>{r.ret_30d:+.1f}%</td>"
            f"{ticket(r)}"
            f"<td style='text-align:left'>{reason(r)}</td>"
            f"<td style='text-align:left'>{badges(r)}{r.sectors if r.sectors != '—' else ''}</td></tr>"
            for r in shortlist.itertuples()
        )
        sl_table = f"""<table><tr><th>grade</th><th>symbol</th><th>30d</th>
            <th>entry†</th><th>max chase†</th><th>stop†</th><th>risk</th><th>qty</th>
            <th style='text-align:left'>why it is here</th><th style='text-align:left'>confluence</th></tr>{sl_rows}</table>
        <p class="muted">† craft defaults, not backtested (unlike the screen itself): entry = signal close, valid up to
        +3%; gap past max chase = pass, it's a different trade. Stop = signal-day low — where the buyers proved they
        exist; broken means the thesis is dead. Qty = ₹{risk_amount:,.0f} risk ÷ stop distance, capped at no-leverage.
        Exit any holding on a close below its 20-SMA.
        {"<b>Qty here uses example config, not your capital — real sizing is on your local dashboard only.</b>" if placeholder_risk else ""}</p>"""
    else:
        sl_table = "<p class='muted'>No stock passes all four filters today. That is information too — sit tight.</p>"

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Market — {day}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.js"></script>
<style>
 body {{ font-family: -apple-system, sans-serif; max-width: 960px; margin: 2rem auto; padding: 0 1rem; color: #1a1a1a; }}
 h2 {{ margin-top: 2.5rem; font-size: 20px; }} h3 {{ margin: 0 0 8px; font-size: 14px; }}
 table {{ border-collapse: collapse; width: 100%; font-size: 14px; }}
 td, th {{ padding: 6px 10px; text-align: right; border-bottom: 1px solid #eee; }}
 td:first-child, th:first-child {{ text-align: left; }}
 .verdict {{ background: {vcolor}; color: white; padding: 1rem 1.5rem; border-radius: 10px;
             display: flex; align-items: baseline; gap: 1rem; flex-wrap: wrap; }}
 .verdict b {{ font-size: 26px; }} .muted {{ color: #777; font-size: 13px; }}
 .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 12px; }}
 .card {{ border: 1px solid #e5e5e5; border-radius: 10px; padding: 12px 14px; }}
 .leader {{ display: flex; gap: 8px; align-items: center; padding: 3px 0; font-size: 14px; }}
 .sym {{ font-weight: 600; min-width: 110px; display: inline-block; }}
 .badge {{ background: #E1F5EE; color: #085041; font-size: 11px; padding: 1px 7px; border-radius: 8px; }}
 .badge-t {{ background: #EEEDFE; color: #3C3489; font-size: 11px; padding: 1px 7px; border-radius: 8px; }}
 .badge-a {{ background: #FAEEDA; color: #854F0B; font-size: 11px; padding: 1px 7px; border-radius: 8px; }}
 .process {{ border: 1px solid #e5e5e5; border-radius: 10px; padding: 12px 18px; margin-top: 1rem; }}
 .process ol {{ margin: 6px 0 2px; padding-left: 1.3rem; }} .process li {{ padding: 2px 0; font-size: 14px; }}
</style></head><body>

<h1 style="font-size:22px">The market story <span class="muted">— {day}</span></h1>

<div class="process"><b style="font-size:14px">The process — nothing else matters</b>
<ol>
<li>Read the weather. WEAK → smaller size or sit out. You only control what you lose.</li>
<li>Shortlist empty → do nothing. Most days are do-nothing days.</li>
<li>Shortlist name + PRIORITY sector agree → candidate. Buy next day, don't wait for a dip.</li>
<li>Size by your risk rules. Write down why you entered.</li>
<li>Never buy the laggard because the leader is extended. Park extended leaders; re-enter when they rest.</li>
</ol></div>

<div class="process" style="margin-top:0.75rem"><b style="font-size:14px">How to read the numbers</b>
<div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(280px,1fr)); gap: 2px 24px; margin-top:6px; font-size:13px;">
<div><b>RS</b> — a rank, not a gain: "beat 93%" means only 7 of every 100 NSE stocks did better this month.</div>
<div><b>rvol</b> — today's volume ÷ own 20-day average. 2x = twice the normal interest. Below 2x = louder than usual, but below the level the backtest certified.</div>
<div><b>delivery X% vs Y%</b> — of every 100 shares traded, how many were taken home overnight (real ownership) vs bought-and-sold same day (churn). X = today, Y = the stock's own 20-day usual. X above Y = conviction buyers; X ≈ Y on a big-volume day = the extra activity was churn, loud not deep.</div>
<div><b>deliv streak</b> — of the last 5 sessions, how many had delivery above that usual. 4/5 = someone is taking stock home all week — quiet accumulation.</div>
<div><b>ext</b> — % above own 20-SMA. Stock &gt;15% (sector &gt;7%) = late; wait for it to rest.</div>
<div><b>of high</b> — % of 52-week high (or high since listing). Near 100% = no trapped sellers overhead.</div>
<div><b>accum</b> — share of a sector's members with delivery above their own average this week.</div>
</div></div>

<h2>1 · The weather — is today worth trading?</h2>
<div class="verdict"><b>{verdict}</b><span>{vrule}</span>
 <span>adv/decl today: {now.advances:.0f} / {now.declines:.0f} · {now.pct20}% above 20-SMA · {now.pct50}% above 50-SMA</span></div>
<div style="height: 220px; margin-top: 1rem;"><canvas id="breadth"></canvas></div>
<p class="muted" style="margin-top:1.5rem">Rising stocks (green) vs falling stocks (red), 10-day smoothed. Green on top = healthy participation. Red on top while the index holds = a few heavyweights carrying a rotting market.</p>
<div style="height: 200px;"><canvas id="advdec"></canvas></div>

<h2>2 · The flow — where is money rotating?</h2>
<p class="muted">PRIORITY = building up, still buyable: above-median month, rising week, ext ≤ 5%, accum ≥ 55%. Hot-but-late sectors are named and shamed.</p>
<table><tr><th>sector</th><th>1w</th><th>1m</th><th>3m</th><th>&gt;20-SMA</th><th>accum</th><th>ext</th></tr>
{sector_rows}</table>

<h2>3 · The trigger — SHORTLIST</h2>
<p class="muted">The only buy list on this page (backtested: +7.1% median 60-day excess, 61% win rate). Grade = confluence:
A+ = PRIORITY sector and was on radar this week · A = one of the two · B = signal alone.
Top 10 shown; pool admits volume from 1.5x so the list fills — names below the tested 2x bar say so in their reason,
and are capped at A: the top grade is reserved for full-strength signals with full confluence.
Heaviest sector accumulation right now: {", ".join(f"{r.sector} ({r.accum_pct:.0f}%)" for r in chase.itertuples())}.</p>
{sl_table}

<h2>4 · The waiting room — radar</h2>
<p class="muted">Not buyable — these are alerts, not orders. Delivery streak ≥ 4/5, footprints before a breakout.
"Watch above" = 10-day high; crossing it on volume is what would promote the name to the shortlist.
"Floor" = 10-day low, the rough stop zone <i>if</i> it ever triggers — shown so you can pre-judge whether a
future trigger is even worth taking. ★ = on the shortlist today.</p>
<table><tr><th>symbol</th><th>sectors</th><th>close</th><th>30d</th><th>deliv streak</th><th>of 52wk high</th><th>watch above</th><th>floor</th><th>if-triggered risk</th></tr>
{radar_rows}</table>

<details style="margin-top:3rem; border: 1px solid #e5e5e5; border-radius: 10px; padding: 12px 18px;">
<summary style="cursor:pointer; font-weight:600; font-size:14px;">Mentor's notes — open when tempted</summary>
<ol style="font-size:14px; line-height:1.6;">
<li><b>Rotation is bought while it's building, not after it's on the front page.</b> The difference between buying strength and buying someone's exit is <i>when in the move</i> you arrive.</li>
<li><b>"Not extended" must never decay into "buy the laggard."</b> The 4th-best stock in a hot sector is not a discount. If a priority sector has no actionable name, the answer is no trade — not scrolling down the member list.</li>
<li><b>Extension is a timing statement, never a quality statement.</b> Your backtest: the runaways were the biggest winners. Park extended leaders, don't delete them — pounce when they rest and requalify.</li>
<li><b>Your instincts are hypotheses, not vetoes.</b> The upper-wick fear and the wait-for-pullback comfort were both refuted by your own 505 days. Every "my mind says" goes to the data for trial before it touches an order.</li>
<li><b>Grade measures confluence, not signal strength.</b> An A+ with 1.8x volume is context agreeing about a whisper. Read the reason column before the grade.</li>
<li><b>The entry needs no finesse; the stop needs no mercy.</b> The tested edge bought the next close, dumbly. Stop = signal-day low, exit = close below 20-SMA, size = risk ÷ stop distance. All feelings live inside the qty column, nowhere else.</li>
<li><b>Tight stop means cheap to be wrong, not safe to be huge.</b> The position cap exists because four tight-stop days would otherwise concentrate the whole account.</li>
<li><b>Capital is promoted by adherence, not confidence.</b> 20 logged trades at ≥90% process adherence doubles the stake. Confidence follows winning streaks — the exact wrong time to add money. One overridden stop resets the count.</li>
<li><b>Top 1% traders don't think better — they act and journal.</b> Frameworks are in every book recited by losing traders. Take the setup, cut without negotiating, write it down, review monthly, survive to compound. This dashboard's P&amp;L is zero until you do.</li>
</ol>
</details>

<p class="muted" style="margin-top:1.5rem">Generated {datetime.datetime.now(zoneinfo.ZoneInfo("Asia/Kolkata")):%Y-%m-%d %H:%M} IST · data through {day} · rules: GOOD = breadth ≥ 55% & rising vs 10d ago; WEAK = &lt; 45% & falling.</p>

<script>
new Chart(document.getElementById('breadth'), {{
  type: 'line',
  data: {{ labels: {[str(x) for x in year.d.dt.date.tolist()]},
    datasets: [
      {{ label: '% above 20-SMA', data: {year.pct20.tolist()}, borderColor: '#378ADD', pointRadius: 0, borderWidth: 1.5 }},
      {{ label: '% above 50-SMA', data: {year.pct50.tolist()}, borderColor: '#BA7517', pointRadius: 0, borderWidth: 1.5, borderDash: [5,3] }}
    ] }},
  options: {{ responsive: true, maintainAspectRatio: false, interaction: {{ mode: 'index', intersect: false }},
    scales: {{ x: {{ ticks: {{ maxTicksLimit: 12 }} }}, y: {{ min: 0, max: 100 }} }},
    plugins: {{ annotation: undefined }} }}
}});
new Chart(document.getElementById('advdec'), {{
  type: 'line',
  data: {{ labels: {[str(x) for x in year.d.dt.date.tolist()]},
    datasets: [
      {{ label: 'Advancing stocks', data: {year.adv_smooth.tolist()}, borderColor: '#1D9E75', pointRadius: 0, borderWidth: 1.5 }},
      {{ label: 'Declining stocks', data: {year.dec_smooth.tolist()}, borderColor: '#E24B4A', pointRadius: 0, borderWidth: 1.5 }}
    ] }},
  options: {{ responsive: true, maintainAspectRatio: false, interaction: {{ mode: 'index', intersect: false }},
    scales: {{ x: {{ ticks: {{ maxTicksLimit: 12 }} }} }} }}
}});
</script>
</body></html>"""


def main() -> None:
    OUT.mkdir(exist_ok=True)
    con = duckdb.connect()
    load(con)
    breadth, sectors, shortlist, radar = build_frames(con)

    # persist the exact as-shown shortlist: forward-tracking evidence that
    # survives any future change to the screen's code or thresholds
    if len(shortlist):
        day = pd.Timestamp(breadth.iloc[-1].d).date()
        snap = ROOT / "data" / "shortlists" / f"{day}.csv"
        if not snap.exists():
            snap.parent.mkdir(parents=True, exist_ok=True)
            shortlist.assign(d=day).to_csv(snap, index=False)

    html = render(breadth, sectors, shortlist, radar)
    path = OUT / "dashboard.html"
    path.write_text(html)
    print(f"wrote {path} ({len(sectors)} sectors, {len(shortlist)} shortlist names)")


if __name__ == "__main__":
    main()
