"""Derived metrics over the bhavcopy history using DuckDB.

Produces, from data/raw/bhavcopy/*.csv:
  out/breadth.csv          — daily market-regime gauge (advances, % above 20/50-day SMA)
  out/shortlist_<date>.csv — latest day's candidates: RS leaders with volume,
                             delivery, and trend confirmation

All metrics are relative to each stock's own history, so they get sharper as
the backfill deepens. Needs ~50 trading days minimum to be meaningful.
"""

import pathlib

import duckdb
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parent
BHAV_GLOB = str(ROOT / "data" / "raw" / "bhavcopy" / "*.csv")
OUT = ROOT / "out"

FEATURES_SQL = f"""
WITH eq AS (
    SELECT DISTINCT
        SYMBOL AS symbol,
        CAST(strptime(DATE1, '%d-%b-%Y') AS DATE) AS d,
        CLOSE_PRICE AS close,
        PREV_CLOSE AS prev_close,
        HIGH_PRICE AS high,
        LOW_PRICE AS low,
        TTL_TRD_QNTY AS volume,
        TRY_CAST(DELIV_PER AS DOUBLE) AS deliv_per
    FROM read_csv_auto('{BHAV_GLOB}', union_by_name=true)
    WHERE SERIES = 'EQ'
),
feat AS (
    SELECT *,
        avg(volume)    OVER w20 AS avg_vol_20,
        avg(close)     OVER w10 AS sma10,
        max(high)      OVER w10 AS hi_10,
        min(low)       OVER w10 AS lo_10,
        avg(close)     OVER w20 AS sma20,
        avg(close)     OVER w50 AS sma50,
        avg(deliv_per) OVER w20 AS avg_deliv_20,
        max(high)      OVER w252 AS hi_252,
        count(*)       OVER w252 AS days_in_252,
        lag(close, 30) OVER (PARTITION BY symbol ORDER BY d) AS close_30d_ago,
        row_number()   OVER (PARTITION BY symbol ORDER BY d) AS t,
        count(*)       OVER (PARTITION BY symbol) AS history_days
    FROM eq
    WINDOW
        w10 AS (PARTITION BY symbol ORDER BY d ROWS BETWEEN 9 PRECEDING AND CURRENT ROW),
        w20 AS (PARTITION BY symbol ORDER BY d ROWS BETWEEN 19 PRECEDING AND CURRENT ROW),
        w50 AS (PARTITION BY symbol ORDER BY d ROWS BETWEEN 49 PRECEDING AND CURRENT ROW),
        w252 AS (PARTITION BY symbol ORDER BY d ROWS BETWEEN 251 PRECEDING AND CURRENT ROW)
)
SELECT *,
    volume / nullif(avg_vol_20, 0) AS rvol,
    (close / nullif(close_30d_ago, 0) - 1) * 100 AS ret_30d
FROM feat
"""


def main() -> None:
    OUT.mkdir(exist_ok=True)
    con = duckdb.connect()
    con.execute(f"CREATE TEMP VIEW features AS {FEATURES_SQL}")

    breadth = con.execute("""
        SELECT d,
            count(*) AS stocks,
            sum(CASE WHEN close > prev_close THEN 1 ELSE 0 END) AS advances,
            sum(CASE WHEN close < prev_close THEN 1 ELSE 0 END) AS declines,
            round(100.0 * sum(CASE WHEN close > sma20 THEN 1 ELSE 0 END) / count(*), 1) AS pct_above_sma20,
            round(100.0 * sum(CASE WHEN close > sma50 THEN 1 ELSE 0 END) / count(*), 1) AS pct_above_sma50
        FROM features
        GROUP BY d
        ORDER BY d
    """).df()
    breadth.to_csv(OUT / "breadth.csv", index=False)

    shortlist = con.execute("""
        WITH latest AS (
            SELECT *,
                percent_rank() OVER (ORDER BY ret_30d) AS rs_rank
            FROM features
            WHERE d = (SELECT max(d) FROM features)
              AND history_days >= 50
              AND ret_30d IS NOT NULL
        )
        SELECT symbol, d, close,
            round(ret_30d, 1) AS ret_30d,
            round(rs_rank, 3) AS rs_rank,
            round(rvol, 2) AS rvol,
            round(deliv_per, 1) AS deliv_per,
            round(avg_deliv_20, 1) AS avg_deliv_20
        FROM latest
        WHERE rs_rank >= 0.80          -- top-quintile 30d relative strength
          AND rvol >= 2.0              -- volume buster vs own 20d average
          AND close > sma20            -- trend confirmation
          AND deliv_per > avg_deliv_20 -- delivery expanding: accumulation, not churn
        ORDER BY rvol DESC
    """).df()

    if breadth.empty:
        print("no bhavcopy history yet — run backfill.py first")
        return

    latest = breadth.iloc[-1]
    latest_day = pd.Timestamp(latest["d"]).date()
    shortlist_path = OUT / f"shortlist_{latest_day}.csv"
    shortlist.to_csv(shortlist_path, index=False)

    print(f"breadth: {len(breadth)} days -> {OUT / 'breadth.csv'}")
    print(
        f"regime {latest_day}: {latest['advances']:.0f}/{latest['declines']:.0f} adv/dec, "
        f"{latest['pct_above_sma20']}% above 20sma, {latest['pct_above_sma50']}% above 50sma"
    )
    print(f"shortlist: {len(shortlist)} candidates -> {shortlist_path}")
    if not shortlist.empty:
        print(shortlist.to_string(index=False))


if __name__ == "__main__":
    main()
