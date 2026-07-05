"""Daily snapshot job: pull NSE data for the latest trading day into data/raw/.

Idempotent — safe to run multiple times a day or on weekends (re-anchors to the
last trading day and skips files that already exist).
"""

import datetime
import pathlib
import sys

import pandas as pd

from nse_client import NSEClient, NotFound, fetch_bhavcopy, normalize, write_snapshot

ROOT = pathlib.Path(__file__).resolve().parent
RAW = ROOT / "data" / "raw"
WATCH_INDICES = ROOT / "config" / "watch_indices.csv"

ALL_INDICES_URL = "https://www.nseindia.com/api/allIndices"
HEATMAP_URL = "https://www.nseindia.com/api/heatmap-symbols?indices={index}"
TOTAL_MARKET_URL = (
    "https://www.nseindia.com/api/NextApi/apiClient/marketWatchApi"
    "?functionName=getIndicesData&symbol=NIFTY%20TOTAL%20MKT"
)


def find_latest_trading_day(client: NSEClient) -> tuple[datetime.date, pd.DataFrame]:
    """Walk back from today until a bhavcopy exists; that file anchors the trade date."""
    day = datetime.date.today()
    for _ in range(7):
        try:
            return day, fetch_bhavcopy(client, day)
        except NotFound:
            day -= datetime.timedelta(days=1)
    raise RuntimeError("no bhavcopy found in the last 7 days — NSE format may have changed")


def fetch_indices(client: NSEClient) -> pd.DataFrame:
    return pd.DataFrame(client.get_json(ALL_INDICES_URL)["data"])


def fetch_constituents(client: NSEClient) -> pd.DataFrame:
    watch = pd.read_csv(WATCH_INDICES)
    frames = []
    for index_name in watch["indexSymbol"]:
        df = pd.DataFrame(client.get_json(HEATMAP_URL.format(index=index_name)))
        df["index_name"] = index_name
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


def fetch_total_market(client: NSEClient) -> pd.DataFrame:
    payload = client.get_json(TOTAL_MARKET_URL)
    return pd.DataFrame(payload["data"]["data"])


def main() -> int:
    client = NSEClient()
    trade_date, bhavcopy = find_latest_trading_day(client)
    stamp = trade_date.isoformat()
    print(f"trade date: {stamp}")

    datasets = [
        ("bhavcopy", lambda: bhavcopy, 1000),
        ("indices", lambda: normalize(fetch_indices(client)), 50),
        ("constituents", lambda: normalize(fetch_constituents(client)), 500),
        ("total_market", lambda: normalize(fetch_total_market(client)), 500),
    ]

    failures = 0
    for name, fetch, min_rows in datasets:
        path = RAW / name / f"{stamp}.csv"
        if path.exists():
            print(f"  {name}: already have {stamp}, skipping")
            continue
        try:
            df = fetch()
            write_snapshot(df, path, min_rows)
            print(f"  {name}: wrote {len(df)} rows")
        except Exception as e:  # noqa: BLE001 - one dataset failing shouldn't kill the rest
            failures += 1
            print(f"  {name}: FAILED — {e}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
