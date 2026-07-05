"""Backtest the shortlist signal over the full bhavcopy history.

Signal (same as metrics.py shortlist): top-quintile 30d RS, RVOL >= 2,
close > SMA20, delivery % above its own 20d average.

Entry at next day's close (no look-ahead). Forward returns measured at
5/20/60 trading days, in excess of the equal-weight market over the same
window. Results are split by breadth regime on signal day.

Outputs out/backtest_signals.csv (every historical signal with outcomes)
and prints the summary.
"""

import pathlib

import duckdb
import pandas as pd

from metrics import FEATURES_SQL

ROOT = pathlib.Path(__file__).resolve().parent
OUT = ROOT / "out"

HORIZONS = [5, 20, 60]


def main() -> None:
    OUT.mkdir(exist_ok=True)
    con = duckdb.connect()
    con.execute(f"CREATE TEMP VIEW features AS {FEATURES_SQL}")

    fwd_cols = ",\n            ".join(
        # entry at next close; exit N trading days after entry
        f"lead(close, {n + 1}) OVER sym / nullif(lead(close, 1) OVER sym, 0) - 1 AS fwd_{n}d"
        for n in HORIZONS
    )
    excess_cols = ",\n        ".join(
        f"round((s.fwd_{n}d - m.mkt_fwd_{n}d) * 100, 2) AS excess_{n}d" for n in HORIZONS
    )
    mkt_cols = ",\n            ".join(f"avg(fwd_{n}d) AS mkt_fwd_{n}d" for n in HORIZONS)

    signals = con.execute(f"""
        WITH fwd AS (
            SELECT *,
                {fwd_cols},
                percent_rank() OVER (PARTITION BY d ORDER BY ret_30d) AS rs_rank
            FROM features
            WHERE history_days >= 50 AND ret_30d IS NOT NULL
            WINDOW sym AS (PARTITION BY symbol ORDER BY d)
        ),
        market AS (  -- equal-weight forward return of the whole eligible universe
            SELECT d,
                {mkt_cols},
                100.0 * sum(CASE WHEN close > sma20 THEN 1 ELSE 0 END) / count(*) AS breadth_sma20
            FROM fwd
            GROUP BY d
        )
        SELECT s.symbol, s.d, s.close,
            round(s.ret_30d, 1) AS ret_30d,
            round(s.rvol, 2) AS rvol,
            round(m.breadth_sma20, 1) AS breadth_sma20,
            CASE WHEN m.breadth_sma20 >= 50 THEN 'healthy' ELSE 'weak' END AS regime,
            {excess_cols}
        FROM fwd s
        JOIN market m USING (d)
        WHERE s.rs_rank >= 0.80
          AND s.rvol >= 2.0
          AND s.close > s.sma20
          AND s.deliv_per > s.avg_deliv_20
          AND s.fwd_20d IS NOT NULL   -- need at least the 20d outcome
        ORDER BY s.d
    """).df()

    signals.to_csv(OUT / "backtest_signals.csv", index=False)
    print(f"{len(signals)} historical signals -> {OUT / 'backtest_signals.csv'}\n")

    def summarize(group: pd.DataFrame) -> dict:
        row = {"signals": len(group)}
        for n in HORIZONS:
            col = group[f"excess_{n}d"].dropna()
            if len(col):
                row[f"win%_{n}d"] = round((col > 0).mean() * 100, 1)
                row[f"med_excess_{n}d"] = round(col.median(), 2)
        return row

    summary = pd.DataFrame(
        {
            "ALL": summarize(signals),
            "healthy regime": summarize(signals[signals.regime == "healthy"]),
            "weak regime": summarize(signals[signals.regime == "weak"]),
        }
    ).T
    print(summary.to_string())


if __name__ == "__main__":
    main()
