"""Evening Telegram push: weather, gradeworthy tickets, tracker, positions.

Sends one message per run — a heartbeat even on empty days, so a missing
message means the pipeline failed. Credentials come from env (GitHub secrets
in CI): TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID. Absent credentials = graceful
skip, so the workflow never fails on an unconfigured machine.

Setup helper:  TELEGRAM_BOT_TOKEN=<token> python notify.py --setup
prints your chat_id after you've sent the bot one message.
"""

import json
import os
import pathlib
import sys

import duckdb
import pandas as pd
import requests

from dashboard import regime_verdict
from metrics import FEATURES_SQL

ROOT = pathlib.Path(__file__).resolve().parent
API = "https://api.telegram.org/bot{token}/{method}"


def setup(token: str) -> None:
    r = requests.get(API.format(token=token, method="getUpdates"), timeout=30).json()
    chats = {u["message"]["chat"]["id"]: u["message"]["chat"].get("first_name", "?")
             for u in r.get("result", []) if "message" in u}
    if not chats:
        print("no messages yet — open Telegram, send your bot any message, rerun")
        return
    for cid, name in chats.items():
        print(f"chat_id: {cid}  ({name})")


def build_message() -> str:
    con = duckdb.connect()
    con.execute(f"CREATE TEMP VIEW f AS {FEATURES_SQL}")
    breadth = con.execute("""
        SELECT d,
            round(100.0 * sum(CASE WHEN close > sma20 THEN 1 ELSE 0 END) / count(*), 1) AS pct20,
            round(100.0 * sum(CASE WHEN close > sma50 THEN 1 ELSE 0 END) / count(*), 1) AS pct50,
            sum(CASE WHEN close > prev_close THEN 1 ELSE 0 END) AS advances,
            sum(CASE WHEN close < prev_close THEN 1 ELSE 0 END) AS declines
        FROM f WHERE history_days >= 50 GROUP BY d ORDER BY d
    """).df()
    verdict, _, vrule = regime_verdict(breadth)
    day = pd.Timestamp(breadth.iloc[-1].d).date()

    snap_path = ROOT / "data" / "shortlists" / f"{day}.csv"
    risk_cfg = json.loads((ROOT / "config" / "risk.json").read_text())
    risk_amt = risk_cfg["capital_inr"] * risk_cfg["risk_per_trade_pct"] / 100
    max_pos = risk_cfg["capital_inr"] * risk_cfg["max_position_pct"] / 100

    j = pd.read_csv(ROOT / "journal" / "trades.csv")
    n_open = int(j.exit_price.isna().sum())
    adher = 100.0 * (j.adherent.fillna("yes") == "yes").mean() if len(j) else 100.0

    lines = [f"📊 <b>{day:%a %d %b} — {verdict}</b>", vrule, ""]
    if n_open >= 3:
        lines += ["⛔ <b>Positions 3/3 — no slots.</b> Tickets below are watch-only.", ""]
    else:
        lines += [f"✅ {3 - n_open} of 3 slots free", ""]

    if snap_path.exists():
        sl = pd.read_csv(snap_path)
        top = sl[sl.grade.isin(["A+", "A"])]
        if len(top):
            lines.append(f"<b>Tickets ({len(top)}):</b>")
            for r in top.itertuples():
                risk_ps = r.close - r.sig_low
                qty = int(min(risk_amt / risk_ps, max_pos / r.close)) if risk_ps / r.close <= 0.08 else 0
                lines.append(f"<b>{r.grade} · {r.symbol}</b>")
                lines.append(f"<code>Entry {r.close} · Max {r.close * 1.03:.0f} · Ext {r.ext_pct:+.1f}%</code>")
                if qty >= 1:
                    lines.append(f"<code>Stop {r.sig_low} · Qty {qty} · "
                                 f"Risk ₹{risk_ps * qty:.0f} ({100 * risk_ps / r.close:.1f}%)</code>")
                else:
                    lines.append("<code>Skip — stop too wide / price too big</code>")
                lines.append("")
            b = len(sl) - len(top)
            if b:
                lines += [f"+{b} B-grade on the page", ""]
        else:
            lines += ["No A-grade tickets today. Do-nothing day.", ""]
    else:
        lines += ["No shortlist snapshot for today.", ""]

    lines += ["🌅 Gate: no entries if NIFTY opens &lt;−0.2% or &gt;+0.5%",
              f"📒 {len(j)}/20 trades · {adher:.0f}% adherence",
              '🔗 <a href="https://smslca.github.io/cl/">Dashboard</a>']
    return "\n".join(lines)


def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if "--setup" in sys.argv:
        setup(token)
        return
    chat = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat:
        print("telegram not configured (missing token/chat id) — skipping")
        return
    msg = build_message()
    r = requests.post(
        API.format(token=token, method="sendMessage"),
        json={"chat_id": chat, "text": msg, "parse_mode": "HTML", "disable_web_page_preview": True},
        timeout=30,
    )
    r.raise_for_status()
    print("telegram: sent")


if __name__ == "__main__":
    main()
