"""Build config/symbol_industry.csv — sector labels for the whole liquid universe.

NSE's quote API (per-symbol industry taxonomy) sits behind Akamai bot
detection, so we use niftyindices.com constituent lists instead: plain CSVs
with an Industry column. Total Market (750) + Microcap 250 covers everything
liquid enough to reach the screen; anything smaller stays unmapped ("—").

Rerun monthly-ish: index reconstitutions add new listings.
"""

import io
import pathlib

import pandas as pd
import requests

ROOT = pathlib.Path(__file__).resolve().parent
OUT = ROOT / "config" / "symbol_industry.csv"

LISTS = [
    "https://niftyindices.com/IndexConstituent/ind_niftytotalmarket_list.csv",
    "https://niftyindices.com/IndexConstituent/ind_niftymicrocap250_list.csv",
]
HEADERS = {"user-agent": "Mozilla/5.0"}


def main() -> None:
    frames = []
    for url in LISTS:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        df = pd.read_csv(io.StringIO(resp.text))
        frames.append(df[["Symbol", "Industry"]])
        print(f"{url.rsplit('/', 1)[-1]}: {len(df)} symbols")

    merged = (
        pd.concat(frames)
        .rename(columns={"Symbol": "symbol", "Industry": "industry"})
        .drop_duplicates(subset="symbol")
        .sort_values("symbol")
    )
    merged.to_csv(OUT, index=False)
    print(f"wrote {len(merged)} symbol->industry mappings -> {OUT}")


if __name__ == "__main__":
    main()
