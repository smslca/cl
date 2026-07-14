"""Trial for the parked morning-gate idea: does the market's opening gap on
entry day predict signal outcomes?

Signals = the tested screen (RS>=0.80, rvol>=2, >20SMA, delivery expanding,
near 52wk high). Entry = next day's OPEN, only if within the corridor
(above stop, <= +3% of signal close) — the live rules. Market gap = median
open-vs-prev-close across the whole universe that morning. Outcomes bucketed
by that gap; if red-open buckets aren't clearly worse, the gate isn't earned.
"""

import duckdb
import pandas as pd

from metrics import FEATURES_SQL

BHAV = "read_csv_auto('data/raw/bhavcopy/*.csv', union_by_name=true)"

con = duckdb.connect()
con.execute(f"CREATE TEMP VIEW f AS {FEATURES_SQL}")
con.execute(f"""
    CREATE TEMP VIEW opens AS
    SELECT SYMBOL AS symbol, CAST(strptime(DATE1, '%d-%b-%Y') AS DATE) AS d,
           OPEN_PRICE AS open, PREV_CLOSE AS prev_close
    FROM {BHAV} WHERE SERIES = 'EQ' AND OPEN_PRICE > 0 AND PREV_CLOSE > 0
""")

df = con.execute("""
    WITH fx AS (
        SELECT *, lead(close, 20) OVER sym AS exit_close
        FROM f WHERE history_days >= 50
        WINDOW sym AS (PARTITION BY symbol ORDER BY d)
    ),
    mktgap AS (
        SELECT d, median(open / prev_close - 1) * 100 AS gap
        FROM opens GROUP BY d
    ),
    mktfwd AS (
        SELECT d, avg(exit_close / close - 1) AS m20 FROM fx GROUP BY d
    ),
    sig AS (
        SELECT * FROM (
            SELECT fx.*, percent_rank() OVER (PARTITION BY d ORDER BY ret_30d) AS rs
            FROM fx WHERE ret_30d IS NOT NULL)
        WHERE rs >= 0.80 AND rvol >= 2 AND close > sma20
          AND deliv_per > avg_deliv_20
          AND close >= 0.85 * hi_252 AND days_in_252 >= 250
    )
    SELECT s.symbol, s.d,
        g.gap AS mkt_gap,
        (e.exit_close / o.open - 1) * 100 - m.m20 * 100 AS excess_20d
    FROM sig s
    JOIN fx e   ON e.symbol = s.symbol AND e.t = s.t + 1
    JOIN opens o ON o.symbol = s.symbol AND o.d = e.d
    JOIN mktgap g ON g.d = e.d
    JOIN mktfwd m ON m.d = e.d
    WHERE o.open > s.low                  -- corridor floor: above the stop
      AND o.open <= s.close * 1.03        -- corridor ceiling: max chase
      AND e.exit_close IS NOT NULL
""").df()

df["bucket"] = pd.cut(
    df.mkt_gap,
    [-99, -1.0, -0.5, -0.15, 0.15, 0.5, 99],
    labels=["gap < -1%", "-1% .. -0.5%", "-0.5% .. -0.15%", "flat ±0.15%", "+0.15% .. +0.5%", "gap > +0.5%"],
)

out = df.groupby("bucket", observed=True).agg(
    n=("excess_20d", "size"),
    win_pct=("excess_20d", lambda s: round((s > 0).mean() * 100, 1)),
    med=("excess_20d", "median"),
    mean=("excess_20d", "mean"),
    p10=("excess_20d", lambda s: s.quantile(0.10)),
).round(2)
print(f"{len(df)} corridor-valid entries\n")
print(out.to_string())
print("\nif the gate skipped every entry on gap < -0.5% mornings:")
kept = df[df.mkt_gap >= -0.5]
cut = df[df.mkt_gap < -0.5]
for name, part in [("kept", kept), ("skipped", cut)]:
    if len(part):
        print(f"  {name}: n={len(part)}, win {100*(part.excess_20d>0).mean():.1f}%, "
              f"med {part.excess_20d.median():+.2f}%, mean {part.excess_20d.mean():+.2f}%")
