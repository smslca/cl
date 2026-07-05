"""Iteration 2: does entry quality explain the missing edge?

Two hypotheses, same signal set as evaluate.py:
  A. Pullback entry — instead of chasing the next close, wait up to 5 trading
     days for a touch of the 10-SMA; enter there. Also reports the signals that
     never pulled back (the runaways) to expose what pullback-waiting misses.
  B. 52-week-high proximity — split signals by close >= 85% of the 252-day high
     (only for symbols with a full 252 days of history).

All outcomes are 20d and 60d close-to-close returns in excess of the
equal-weight market from the same entry day.
"""

import duckdb
import pandas as pd

from metrics import FEATURES_SQL

HZ = [20, 60]


def summarize(df: pd.DataFrame, label: str) -> dict:
    row = {"variant": label, "signals": len(df)}
    for n in HZ:
        col = df[f"excess_{n}d"].dropna()
        if len(col):
            row[f"win%_{n}d"] = round((col > 0).mean() * 100, 1)
            row[f"med_{n}d"] = round(col.median(), 2)
    return row


def main() -> None:
    con = duckdb.connect()
    con.execute(f"CREATE TEMP VIEW f AS {FEATURES_SQL}")
    con.execute("""
        CREATE TEMP VIEW fx AS
        SELECT *,
            lead(close, 20) OVER sym AS close_20,
            lead(close, 60) OVER sym AS close_60
        FROM f
        WHERE history_days >= 50
        WINDOW sym AS (PARTITION BY symbol ORDER BY d)
    """)
    con.execute("""
        CREATE TEMP VIEW mkt AS
        SELECT d,
            avg(close_20 / close - 1) AS mkt_20,
            avg(close_60 / close - 1) AS mkt_60
        FROM fx GROUP BY d
    """)
    con.execute("""
        CREATE TEMP VIEW sig AS
        SELECT * FROM (
            SELECT *, percent_rank() OVER (PARTITION BY d ORDER BY ret_30d) AS rs_rank
            FROM fx WHERE ret_30d IS NOT NULL
        )
        WHERE rs_rank >= 0.80 AND rvol >= 2.0 AND close > sma20 AND deliv_per > avg_deliv_20
    """)

    # every signal with its chase entry (next day) and, if any, the first
    # 10-SMA touch within 5 trading days as the pullback entry
    trades = con.execute("""
        WITH chase AS (
            SELECT s.symbol, s.d, s.close AS sig_close, s.hi_252, s.days_in_252, s.t,
                e.close_20 / e.close - 1 AS chase_ret_20,
                e.close_60 / e.close - 1 AS chase_ret_60,
                m.mkt_20 AS chase_mkt_20, m.mkt_60 AS chase_mkt_60
            FROM sig s
            JOIN fx e ON e.symbol = s.symbol AND e.t = s.t + 1
            JOIN mkt m ON m.d = e.d
        ),
        pullback AS (
            SELECT s.symbol, s.t,
                e.d AS entry_d,
                least(e.sma10, e.high) AS entry_price,  -- limit at sma10; gap-days fill at high (conservative)
                e.close_20 / least(e.sma10, e.high) - 1 AS pb_ret_20,
                e.close_60 / least(e.sma10, e.high) - 1 AS pb_ret_60,
                m.mkt_20 AS pb_mkt_20, m.mkt_60 AS pb_mkt_60,
                row_number() OVER (PARTITION BY s.symbol, s.t ORDER BY e.t) AS rn
            FROM sig s
            JOIN fx e ON e.symbol = s.symbol AND e.t BETWEEN s.t + 1 AND s.t + 5
                     AND e.low <= e.sma10
            JOIN mkt m ON m.d = e.d
        )
        SELECT c.*,
            p.entry_d,
            round((c.chase_ret_20 - c.chase_mkt_20) * 100, 2) AS chase_excess_20d,
            round((c.chase_ret_60 - c.chase_mkt_60) * 100, 2) AS chase_excess_60d,
            round((p.pb_ret_20 - p.pb_mkt_20) * 100, 2) AS pb_excess_20d,
            round((p.pb_ret_60 - p.pb_mkt_60) * 100, 2) AS pb_excess_60d,
            c.sig_close >= 0.85 * c.hi_252 AND c.days_in_252 >= 250 AS near_high,
            c.days_in_252 >= 250 AS valid_252
        FROM chase c
        LEFT JOIN pullback p ON p.symbol = c.symbol AND p.t = c.t AND p.rn = 1
        WHERE c.chase_ret_20 IS NOT NULL
    """).df()

    filled = trades[trades.entry_d.notna()]
    runaway = trades[trades.entry_d.isna()]

    print(f"signals: {len(trades)} | pulled back to 10-SMA within 5d: "
          f"{len(filled)} ({100 * len(filled) / len(trades):.0f}%)\n")

    rows = [
        summarize(trades.rename(columns=lambda c: c.replace("chase_", "")), "A0 chase everything (baseline)"),
        summarize(filled.rename(columns=lambda c: c.replace("chase_", "")), "A1 chase, pullback subset"),
        summarize(filled.rename(columns=lambda c: c.replace("pb_", "")), "A2 pullback entry, same subset"),
        summarize(runaway.rename(columns=lambda c: c.replace("chase_", "")), "A3 runaways (never pulled back)"),
    ]
    v = trades[trades.valid_252]
    rows += [
        summarize(v[v.near_high].rename(columns=lambda c: c.replace("chase_", "")), "B1 near 52wk high (chase)"),
        summarize(v[~v.near_high].rename(columns=lambda c: c.replace("chase_", "")), "B2 far from 52wk high (chase)"),
        summarize(filled[filled.near_high].rename(columns=lambda c: c.replace("pb_", "")), "C  near-high + pullback entry"),
    ]
    print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    main()
