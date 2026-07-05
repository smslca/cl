"""Backfill historical bhavcopy (OHLCV + delivery %) into data/raw/bhavcopy/.

Usage: python backfill.py [--days 750]

Idempotent: skips dates already on disk, skips weekends, treats 404 as a holiday.
Run it once to seed history; re-run any time to fill gaps.
"""

import argparse
import datetime
import pathlib
import time

from nse_client import NSEClient, NotFound, fetch_bhavcopy, write_snapshot

ROOT = pathlib.Path(__file__).resolve().parent
BHAV_DIR = ROOT / "data" / "raw" / "bhavcopy"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=750, help="calendar days to walk back")
    args = parser.parse_args()

    client = NSEClient()
    today = datetime.date.today()
    fetched = skipped = holidays = 0

    for offset in range(args.days):
        day = today - datetime.timedelta(days=offset)
        if day.weekday() >= 5:
            continue
        path = BHAV_DIR / f"{day.isoformat()}.csv"
        if path.exists():
            skipped += 1
            continue
        try:
            df = fetch_bhavcopy(client, day)
            write_snapshot(df, path, min_rows=1000)
            fetched += 1
            print(f"{day} ok ({len(df)} rows)")
        except NotFound:
            holidays += 1
            print(f"{day} holiday/unpublished")
        time.sleep(0.5)  # stay polite with the archive server

    print(f"\ndone: {fetched} fetched, {skipped} already present, {holidays} holidays")


if __name__ == "__main__":
    main()
