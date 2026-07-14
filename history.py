"""Build the historical report browser: out/history/index.html.

One report per day the screen ran (dated by shortlist snapshots), regenerated
as-of that date, plus a viewer with a calendar picker. Reports are frozen
once rendered (skipped on rebuild; --force regenerates). The live dashboard
is untouched — this is a separate audit surface for "what did the system say
on day X".
"""

import argparse
import json
import pathlib

from dashboard import generate

ROOT = pathlib.Path(__file__).resolve().parent
# lives under docs/ (tracked, Pages-published) so cloud checkouts see prior
# reports and only render the new day
HISTORY = ROOT / "docs" / "history"

VIEWER = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Market story — archive</title>
<style>
 body {{ font-family: -apple-system, sans-serif; margin: 0; height: 100vh; display: flex; flex-direction: column; }}
 header {{ padding: 10px 16px; border-bottom: 1px solid #e5e5e5; display: flex; gap: 14px; align-items: center; position: relative; }}
 header b {{ font-size: 15px; }}
 .muted {{ color: #777; font-size: 12px; }}
 iframe {{ flex: 1; border: 0; width: 100%; }}
 #daybtn {{ font-size: 14px; padding: 5px 12px; border: 1px solid #ccc; border-radius: 8px; background: #fff; cursor: pointer; }}
 #cal {{ display: none; position: absolute; top: 46px; left: 140px; background: #fff; border: 1px solid #ddd;
         border-radius: 10px; box-shadow: 0 4px 16px rgba(0,0,0,.12); padding: 10px 12px; z-index: 5; }}
 #cal.open {{ display: block; }}
 #cal .nav {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; font-size: 13px; font-weight: 600; }}
 #cal .nav button {{ border: 0; background: none; font-size: 15px; cursor: pointer; padding: 2px 8px; }}
 #cal table {{ border-collapse: collapse; }}
 #cal th {{ font-size: 10px; color: #999; padding: 2px; font-weight: 500; }}
 #cal td {{ width: 30px; height: 28px; text-align: center; font-size: 12px; border-radius: 6px; color: #ccc; }}
 #cal td.has {{ color: #1a1a1a; cursor: pointer; background: #E1F5EE; font-weight: 500; }}
 #cal td.has:hover {{ background: #9FE1CB; }}
 #cal td.sel {{ background: #1D9E75; color: #fff; }}
</style></head><body>
<header>
 <b>Market story — archive</b>
 <button id="daybtn" onclick="document.getElementById('cal').classList.toggle('open')">{latest} ▾</button>
 <div id="cal"></div>
 <span class="muted">green = report exists · regenerated as-of that date (history-length gates count later days too;
 the true as-shown record is data/shortlists/)</span>
</header>
<iframe id="r" src="report_{latest}.html"></iframe>
<script>
const DATES = {dates_json};
const avail = new Set(DATES);
let selected = DATES[DATES.length - 1];
let view = new Date(selected + "T00:00:00");

function pick(d) {{
  selected = d;
  document.getElementById("r").src = "report_" + d + ".html";
  document.getElementById("daybtn").textContent = d + " ▾";
  document.getElementById("cal").classList.remove("open");
  draw();
}}

function draw() {{
  const y = view.getFullYear(), m = view.getMonth();
  const first = new Date(y, m, 1), start = (first.getDay() + 6) % 7;
  const days = new Date(y, m + 1, 0).getDate();
  const min = new Date(DATES[0] + "T00:00:00"), max = new Date(DATES[DATES.length-1] + "T00:00:00");
  let h = `<div class="nav">
    <button onclick="view.setMonth(view.getMonth()-1);draw()" ${{(y === min.getFullYear() && m === min.getMonth()) ? "disabled" : ""}}>‹</button>
    <span>${{first.toLocaleString("en", {{month: "long"}})}} ${{y}}</span>
    <button onclick="view.setMonth(view.getMonth()+1);draw()" ${{(y === max.getFullYear() && m === max.getMonth()) ? "disabled" : ""}}>›</button>
  </div><table><tr>` + ["Mo","Tu","We","Th","Fr","Sa","Su"].map(d => `<th>${{d}}</th>`).join("") + "</tr><tr>";
  for (let i = 0; i < start; i++) h += "<td></td>";
  for (let d = 1; d <= days; d++) {{
    const iso = `${{y}}-${{String(m+1).padStart(2,"0")}}-${{String(d).padStart(2,"0")}}`;
    const cls = iso === selected ? "has sel" : (avail.has(iso) ? "has" : "");
    h += `<td class="${{cls}}" ${{avail.has(iso) ? `onclick="pick('${{iso}}')"` : ""}}>${{d}}</td>`;
    if ((start + d) % 7 === 0 && d < days) h += "</tr><tr>";
  }}
  document.getElementById("cal").innerHTML = h + "</tr></table>";
}}
draw();
document.addEventListener("click", e => {{
  if (!e.target.closest("#cal") && !e.target.closest("#daybtn"))
    document.getElementById("cal").classList.remove("open");
}});
</script>
</body></html>
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="regenerate reports that already exist")
    args = parser.parse_args()

    dates = sorted(p.stem for p in (ROOT / "data" / "shortlists").glob("*.csv"))
    HISTORY.mkdir(parents=True, exist_ok=True)

    for d in dates:
        out = HISTORY / f"report_{d}.html"
        if out.exists() and not args.force:
            continue
        generate(as_of=d, out_path=out)

    (HISTORY / "index.html").write_text(
        VIEWER.format(dates_json=json.dumps(dates), latest=dates[-1])
    )
    print(f"viewer: {HISTORY / 'index.html'} ({len(dates)} reports)")


if __name__ == "__main__":
    main()
