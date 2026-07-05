#!/bin/zsh
# Local failsafe, runs at 20:30 IST — after the 19:15 GitHub Actions fetch.
# Pulls whatever the cloud committed; fetch_daily then skips everything the
# cloud already got and only fills gaps (cloud outage, NSE blocking, etc.).
# Any gap-fill is pushed back so git stays the single source of truth.
# Finally regenerates the local dashboard.
set -e
cd /Users/praveenjana/Market/cl

/usr/bin/git pull --ff-only
/Users/praveenjana/Market/.venv/bin/python fetch_daily.py

/usr/bin/git add data/
if ! /usr/bin/git diff --cached --quiet; then
    /usr/bin/git commit -m "data: local fallback $(date +%F)"
    /usr/bin/git push
fi

/Users/praveenjana/Market/.venv/bin/python dashboard.py
