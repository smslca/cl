#!/bin/zsh
# Local failsafe, runs at 20:30 IST — after the 19:15 GitHub Actions fetch.
# Pulls whatever the cloud committed; fetch_daily then skips everything the
# cloud already got and only fills gaps (cloud outage, NSE blocking, etc.).
# Any gap-fill is pushed back so git stays the single source of truth.
# Finally regenerates the local dashboard.
set -e
cd /Users/praveenjana/Market/cl

# explicit refspec: immune to FETCH_HEAD pollution from concurrent fetches
/usr/bin/git pull --ff-only origin main
/Users/praveenjana/Market/.venv/bin/python fetch_daily.py
/Users/praveenjana/Market/.venv/bin/python dashboard.py

# on fallback days also publish the dashboard, or Pages serves a stale page
cp out/dashboard.html docs/index.html
/Users/praveenjana/Market/.venv/bin/python history.py
/Users/praveenjana/Market/.venv/bin/python journal_page.py

/usr/bin/git add data/ docs/
if ! /usr/bin/git diff --cached --quiet; then
    /usr/bin/git commit -m "data: local fallback $(date +%F)"
    /usr/bin/git push origin main
fi
