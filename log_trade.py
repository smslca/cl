"""Parse a trade issue into journal/trades.csv.

Reads the GitHub issue-form body from $ISSUE_BODY, validates against the data
and the system's rules, appends (BUY) or completes (SELL) a journal row, and
prints a markdown receipt to stdout. Exit 0 = logged; exit 1 = rejected (the
receipt explains why). DRY_RUN=1 validates without writing.

BUY entries self-assemble their signal state from the most recent shortlist
snapshot containing the symbol — the trader types four fields, the machine
fills the rest. Corridor breaches are logged but marked adherent=no.
"""

import datetime
import os
import pathlib
import sys
import zoneinfo

import duckdb
import pandas as pd

from metrics import FEATURES_SQL

ROOT = pathlib.Path(__file__).resolve().parent
JPATH = ROOT / "journal" / "trades.csv"
SNAPDIR = ROOT / "data" / "shortlists"
IST = zoneinfo.ZoneInfo("Asia/Kolkata")


class Reject(Exception):
    pass


def parse_issue(body: str) -> dict:
    """GitHub issue forms render as '### Label\\n\\nvalue' sections."""
    fields, label = {}, None
    for line in body.splitlines():
        if line.startswith("### "):
            label = line[4:].strip().lower()
            fields[label] = ""
        elif label is not None and line.strip():
            fields[label] += (" " if fields[label] else "") + line.strip()
    return {k: ("" if v.strip() == "_No response_" else v.strip()) for k, v in fields.items()}


def latest_quote(con, symbol: str):
    row = con.execute(
        "SELECT d, close, sma20 FROM f WHERE symbol = ? ORDER BY d DESC LIMIT 1", [symbol]
    ).fetchone()
    if not row:
        raise Reject(f"`{symbol}` not found in the data — check the spelling.")
    return row


def signal_state(symbol: str) -> pd.Series:
    """Most recent shortlist snapshot row for the symbol (last 5 snapshots)."""
    for snap in sorted(SNAPDIR.glob("*.csv"), reverse=True)[:5]:
        df = pd.read_csv(snap)
        hit = df[df.symbol == symbol]
        if len(hit):
            return hit.iloc[0]
    raise Reject(
        f"`{symbol}` was not on any shortlist in the last 5 sessions — "
        "this would be an off-system trade. If you really mean it, log it by editing "
        "journal/trades.csv manually; the annoyance is deliberate."
    )


def regime_for(con, d) -> str:
    rows = con.execute("""
        SELECT d, 100.0 * sum(CASE WHEN close > sma20 THEN 1 ELSE 0 END) / count(*) AS pct20
        FROM f WHERE history_days >= 50 AND d <= ? GROUP BY d ORDER BY d DESC LIMIT 11
    """, [d]).fetchall()
    now, prior = rows[0][1], rows[-1][1]
    if now >= 55 and now >= prior:
        return "GOOD"
    if now < 45 and now < prior:
        return "WEAK"
    return "MIXED"


def do_buy(con, j, f, today):
    sym, price, qty = f["symbol"].upper(), float(f["fill price"]), int(f["qty"])
    open_pos = j[j.exit_price.isna() & (j.symbol == sym)]
    if len(open_pos):
        raise Reject(f"Already holding {sym} (trade #{open_pos.iloc[0].trade_id}) — partial adds not supported.")

    d, close, _ = latest_quote(con, sym)
    if not 0.8 * close <= price <= 1.2 * close:
        raise Reject(f"Fill {price} is >20% away from {sym}'s last close {close} — typo?")

    sig = signal_state(sym)
    stop = float(sig.sig_low)
    if price <= stop:
        raise Reject(f"Fill {price} is at/below the stop {stop} — the signal is already dead. Pass.")
    corridor_ok = price <= float(sig.close) * 1.03
    risk = round((price - stop) * qty)

    row = {
        "trade_id": int(j.trade_id.max()) + 1 if len(j) else 1,
        "symbol": sym, "signal_date": sig.d, "entry_date": today.isoformat(),
        "entry_price": price, "qty": qty, "stop": stop, "gtt_set": "confirm",
        "grade": sig.grade, "signal_close": sig.close, "rvol": sig.rvol,
        "rs_rank": sig.rs_rank, "deliv_per": sig.deliv_per, "avg_deliv_20": sig.avg_deliv_20,
        "pct_of_52wk_high": sig.pct_of_52wk_high, "regime": regime_for(con, sig.d),
        "risk_inr": risk, "notes": f["the honest sentence"],
        "adherent": "yes" if corridor_ok else "no",
    }
    j = pd.concat([j, pd.DataFrame([row])], ignore_index=True)

    receipt = (
        f"**Trade #{row['trade_id']} logged — BUY {sym} ×{qty} @ {price}**\n\n"
        f"- signal {sig.d} (grade {sig.grade}, rvol {sig.rvol}x, deliv {sig.deliv_per}% vs {sig.avg_deliv_20}%)\n"
        f"- stop **{stop}** → risk **₹{risk:,}** — place the GTT now if you haven't\n"
        + ("" if corridor_ok else
           f"- ⚠️ **corridor breach**: fill is beyond max chase {float(sig.close) * 1.03:.1f} — marked adherent=no\n")
    )
    return j, receipt


def do_sell(con, j, f, today):
    sym, price, qty = f["symbol"].upper(), float(f["fill price"]), int(f["qty"])
    reason = f.get("exit reason (sell only)", "")
    if reason in ("", "—"):
        raise Reject("SELL needs an exit reason — stop_hit, sma20_close, time_stop or other.")
    open_pos = j[j.exit_price.isna() & (j.symbol == sym)]
    if not len(open_pos):
        raise Reject(f"No open position in {sym}.")
    i = open_pos.index[0]
    r = j.loc[i]
    if qty != int(r.qty):
        raise Reject(f"Open qty is {int(r.qty)}, you said {qty} — partial exits not supported yet.")

    pnl = round((price - r.entry_price) * qty, 1)
    rmult = round(pnl / r.risk_inr, 2)
    j.loc[i, ["exit_date", "exit_price", "exit_reason", "pnl_inr", "r_multiple"]] = [
        today.isoformat(), price, reason, pnl, rmult,
    ]
    j.loc[i, "notes"] = f"{r.notes} | exit: {f['the honest sentence']}"

    receipt = (
        f"**Trade #{int(r.trade_id)} closed — SELL {sym} ×{qty} @ {price}** ({reason})\n\n"
        f"- P&L **₹{pnl:+,.0f}** = **{rmult:+.2f}R** (entry {r.entry_price}, stop was {r.stop})\n"
        f"- the +60d regret column fills itself on {(today + datetime.timedelta(days=60)).isoformat()}\n"
    )
    return j, receipt


def main() -> int:
    body = os.environ.get("ISSUE_BODY", "")
    f = parse_issue(body)
    today = datetime.datetime.now(IST).date()
    con = duckdb.connect()
    con.execute(f"CREATE TEMP VIEW f AS {FEATURES_SQL}")
    j = pd.read_csv(JPATH)

    try:
        for key in ("action", "symbol", "fill price", "qty", "the honest sentence"):
            if not f.get(key):
                raise Reject(f"Missing field: {key}.")
        if f["action"].upper() == "BUY":
            j, receipt = do_buy(con, j, f, today)
        else:
            j, receipt = do_sell(con, j, f, today)
    except Reject as e:
        print(f"**Not logged.** {e}\n\nEdit this issue to fix it — editing re-triggers the check.")
        return 1

    n = len(j)
    adher = 100.0 * (j.adherent.fillna("yes") == "yes").mean()
    receipt += f"\nTracker: **{n}/20** · adherence **{adher:.0f}%**"
    if os.environ.get("DRY_RUN"):
        print(receipt + "\n\n_(dry run — nothing written)_")
        return 0
    j.to_csv(JPATH, index=False)
    print(receipt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
