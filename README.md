# Market history pipeline

Daily NSE data collection + derived metrics for positional equity trading.

**Design constraint: zero-cost everywhere.** Data lives as dated CSVs (git-friendly,
diffable, no database server). DuckDB queries the CSV globs directly. Scheduling is
launchd locally / GitHub Actions in the cloud — both free.

## Layout

```
config/watch_indices.csv      indices tracked for constituent snapshots
data/raw/bhavcopy/DATE.csv    full equity bhavcopy incl. delivery % (backfillable)
data/raw/indices/DATE.csv     all-indices snapshot (collect-forward only)
data/raw/constituents/DATE.csv  heatmap constituents for watched indices
data/raw/total_market/DATE.csv  NIFTY TOTAL MARKET constituent changes
out/                          derived outputs (gitignored, rebuildable)
```

## Scripts

| script | what | when |
|---|---|---|
| `fetch_daily.py` | pulls all four datasets for the latest trading day | daily, 19:15 IST |
| `backfill.py --days N` | seeds/repairs bhavcopy history | once, or to fill gaps |
| `metrics.py` | breadth regime + RS/RVOL/delivery shortlist | after fetch |

All scripts are idempotent — re-running never duplicates or overwrites good data.

## Metrics (out/)

- **breadth.csv** — daily advances/declines, % of stocks above their own 20/50-day
  SMA. This is the regime gauge: when breadth rots, cut exposure.
- **shortlist_DATE.csv** — stocks passing all of: top-quintile 30-day relative
  strength, volume ≥ 2× own 20-day average, close above 20-day SMA, delivery %
  above its own 20-day average (accumulation, not churn).

## Scheduling

Local (survives sleep — launchd fires missed runs on wake):

```sh
cp launchd/com.market.daily.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.market.daily.plist
```

Cloud: push this repo to GitHub — `.github/workflows/daily.yml` runs the fetch on
weekdays and commits the data back. Caveat: NSE sometimes blocks datacenter IPs on
`www.nseindia.com` API endpoints (the archives host is usually fine). If snapshot
steps fail from Actions, keep those on launchd and let Actions do bhavcopy only.

## NSE quirks handled

- `www.nseindia.com` APIs need cookies from the homepage; sessions go stale (401/403)
  and are transparently rebuilt.
- On holidays the archive sometimes serves the **previous day's bhavcopy instead of
  404** — every download is validated against the requested date.
- Archive CSVs pad headers and values with spaces — normalized on ingest.
- Row-count floors prevent writing truncated/error payloads into history.
