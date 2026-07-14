"""Render the trader's ledger: docs/journal.html (+ out/journal.html copy).

Reads journal/trades.csv and the price history to give every position a
nightly health check — unrealized R, distance to stop, the 20-SMA exit rule
verdict, stop-cross flags — plus closed-trade stats and the realized-R curve.
Also auto-fills price_60d_after_exit (the regret column) once 60 calendar
days pass an exit; the machine remembers so the trader doesn't have to.
"""

import datetime
import pathlib

import duckdb
import pandas as pd

from dashboard import stage_tracker
from metrics import FEATURES_SQL

ROOT = pathlib.Path(__file__).resolve().parent
JPATH = ROOT / "journal" / "trades.csv"


def fill_regret_column(j: pd.DataFrame, con) -> bool:
    """price_60d_after_exit := first close on/after exit_date + 60 calendar days."""
    changed = False
    for i, r in j.iterrows():
        if pd.isna(r.exit_date) or not pd.isna(r.price_60d_after_exit):
            continue
        target = pd.Timestamp(r.exit_date) + pd.Timedelta(days=60)
        hit = con.execute(
            "SELECT close FROM f WHERE symbol = ? AND d >= ? ORDER BY d LIMIT 1",
            [r.symbol, target.date()],
        ).fetchone()
        if hit:
            j.loc[i, "price_60d_after_exit"] = hit[0]
            changed = True
    return changed


def main() -> None:
    con = duckdb.connect()
    con.execute(f"CREATE TEMP VIEW f AS {FEATURES_SQL}")
    j = pd.read_csv(JPATH)

    if fill_regret_column(j, con):
        j.to_csv(JPATH, index=False)
        print("regret column updated in journal/trades.csv")

    is_open = j.exit_price.isna()
    open_rows, closed = j[is_open], j[~is_open]

    # nightly health for open positions
    health = pd.DataFrame()
    if len(open_rows):
        syms = ",".join(f"'{s}'" for s in open_rows.symbol)
        health = con.execute(f"""
            SELECT symbol, d, close, low, round(sma20, 2) AS sma20
            FROM f WHERE symbol IN ({syms})
            QUALIFY row_number() OVER (PARTITION BY symbol ORDER BY d DESC) = 1
        """).df()

    open_html = ""
    for r in open_rows.itertuples():
        h = health[health.symbol == r.symbol].iloc[0]
        pnl = (h.close - r.entry_price) * r.qty
        run_r = pnl / r.risk_inr
        stop_gap = (h.close - r.stop) / h.close * 100
        days = len(con.execute(
            "SELECT DISTINCT d FROM f WHERE symbol = ? AND d >= ?", [r.symbol, r.entry_date]
        ).fetchall())
        if h.low <= r.stop:
            verdict = "<span class='badge-r'>stop crossed — confirm exit</span>"
        elif h.close <= h.sma20:
            verdict = "<span class='badge-r'>closed under 20-SMA — exit tomorrow</span>"
        else:
            verdict = "<span class='badge-g'>hold</span>"
        color = "#0F6E56" if pnl >= 0 else "#993C1D"
        open_html += (
            f"<tr><td class='sym'>{r.symbol}</td><td>{r.entry_date}</td><td>{r.entry_price}</td>"
            f"<td>{r.qty}</td><td>{r.stop}</td><td>{h.close}</td>"
            f"<td style='color:{color}'>{pnl:+,.0f} ({run_r:+.1f}R)</td>"
            f"<td>{stop_gap:.1f}%</td><td>{h.sma20}</td><td>{days}</td><td>{verdict}</td></tr>"
        )

    closed_html = ""
    for r in closed.itertuples():
        regret = ""
        if not pd.isna(r.price_60d_after_exit):
            moved = (r.price_60d_after_exit / r.exit_price - 1) * 100
            regret = f"{r.price_60d_after_exit} ({moved:+.0f}%)"
        color = "#0F6E56" if r.pnl_inr >= 0 else "#993C1D"
        closed_html += (
            f"<tr><td class='sym'>{r.symbol}</td><td>{r.entry_date}</td><td>{r.exit_date}</td>"
            f"<td>{r.entry_price}</td><td>{r.exit_price}</td><td>{r.exit_reason}</td>"
            f"<td style='color:{color}'>{r.pnl_inr:+,.0f}</td><td style='color:{color}'>{r.r_multiple:+.1f}R</td>"
            f"<td>{regret or '— (fills at +60d)'}</td></tr>"
        )

    n_closed = len(closed)
    stats = ""
    if n_closed:
        wins = (closed.pnl_inr > 0).mean() * 100
        stats = (f"{n_closed} closed · win rate {wins:.0f}% · total R {closed.r_multiple.sum():+.1f} · "
                 f"avg R {closed.r_multiple.mean():+.2f} · realized ₹{closed.pnl_inr.sum():+,.0f}")
    curve = closed.sort_values("exit_date")
    curve_labels = [str(x) for x in curve.exit_date.tolist()]
    curve_vals = curve.r_multiple.cumsum().round(2).tolist()

    today = datetime.date.today()
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Ledger — {today}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.js"></script>
<style>
 body {{ font-family: -apple-system, sans-serif; max-width: 960px; margin: 2rem auto; padding: 0 1rem; color: #1a1a1a; }}
 h2 {{ margin-top: 2rem; font-size: 19px; }}
 table {{ border-collapse: collapse; width: 100%; font-size: 13.5px; }}
 td, th {{ padding: 6px 9px; text-align: right; border-bottom: 1px solid #eee; }}
 td:first-child, th:first-child {{ text-align: left; }}
 .sym {{ font-weight: 600; }} .muted {{ color: #777; font-size: 12px; }}
 .badge-g {{ background: #E1F5EE; color: #085041; font-size: 11px; padding: 2px 8px; border-radius: 8px; }}
 .badge-r {{ background: #FCEBEB; color: #791F1F; font-size: 11px; padding: 2px 8px; border-radius: 8px; font-weight: 600; }}
</style></head><body>

<h1 style="font-size:22px">The trader's ledger <span class="muted">— {today}</span> <a href="index.html" style="font-size:13px; margin-left:10px;">dashboard →</a></h1>
{stage_tracker()}

<h2>Open positions — nightly health check</h2>
<p class="muted">Verdict column applies the exit rules for you: stop crossed, or a close below the 20-SMA, means the trade is over — no negotiation.</p>
<table><tr><th>symbol</th><th>entry date</th><th>entry</th><th>qty</th><th>stop</th><th>close</th>
<th>unrealized</th><th>to stop</th><th>20-SMA</th><th>days</th><th>verdict</th></tr>
{open_html or "<tr><td colspan=11 class='muted'>no open positions</td></tr>"}</table>

<h2>Closed trades</h2>
<p class="muted">{stats or "none yet"} · "+60d" = price 60 calendar days after exit — the regret column, auto-filled. It grades the exit rule, not you.</p>
<table><tr><th>symbol</th><th>in</th><th>out</th><th>entry</th><th>exit</th><th>reason</th><th>P&amp;L</th><th>R</th><th>+60d</th></tr>
{closed_html or "<tr><td colspan=9 class='muted'>none yet</td></tr>"}</table>

<h2>Realized R — the track record</h2>
<div style="height:200px"><canvas id="rc"></canvas></div>

<p class="muted" style="margin-top:2rem">Generated nightly from journal/trades.csv + price history. The honest sentence lives in the notes column — numbers are for the system, sentences are for the trader.</p>

<script>
new Chart(document.getElementById('rc'), {{
  type: 'line',
  data: {{ labels: {curve_labels}, datasets: [{{ label: 'cumulative R', data: {curve_vals},
    borderColor: '#1D9E75', pointRadius: 4, borderWidth: 2, stepped: true }}] }},
  options: {{ responsive: true, maintainAspectRatio: false, plugins: {{ legend: {{ display: false }} }} }}
}});
</script>
</body></html>"""

    for dest in (ROOT / "docs" / "journal.html", ROOT / "out" / "journal.html"):
        dest.parent.mkdir(exist_ok=True)
        dest.write_text(html)
    print(f"ledger: {len(open_rows)} open, {n_closed} closed -> docs/journal.html")


if __name__ == "__main__":
    main()
