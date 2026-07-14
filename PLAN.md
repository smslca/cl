# The plan — how this gets big

Wealth = Capital × Edge × Time × Survival. Tooling is not a lever; closed
feedback loops are. Stages advance through gates, never through feelings.
Gate numbers are amendable by editing this file — with a git commit as witness.

## Stage 0 — prove the trader (now → ~3 months)

**Question:** can I execute my own system for 20 consecutive trades?

| what | rule |
|---|---|
| Capital | ₹50,000 — frozen |
| Risk | 1% per trade, 20% max position, **3 positions max** (total open risk ≤ 3%) — amended from 2 on 2026-07-14: learning phase needs samples; hard ceiling, enforced by the trade logger |
| Metric | trades logged, adherence % (corridor + printed qty + GTT + journaled) |
| **Gate to Stage 1** | **20 trades with ≥90% adherence** |
| Reset clause | an unlogged trade or an overridden stop resets the count |
| Builds allowed | journal plumbing only (auto-exits, 60d-after column, monthly review report) |

## Stage 1 — prove the edge lives (3–9 months)

**Question:** does the live R-multiple distribution match the backtest (+7.1% median 60d excess, 61% win)?

| what | rule |
|---|---|
| Capital | ₹50k → 1L at gate, → 2L at 40 trades ≥90% — plus monthly savings contributions (contribution > compounding at this size) |
| Close the loop | score every snapshot signal forward (5/20/60d); A+ vs A vs B live; my picks vs blind row-1 |
| Metric | live expectancy (R), win rate, offered-vs-taken gap |
| **Gate to Stage 2** | **50 trades, positive live expectancy, no adherence resets in final 20** |

## Stage 2 — scale size before it scales me (year 1–2)

**Question:** what breaks at 4–5 positions and ₹2–5L?

Build BEFORE it hurts: liquidity floor (median turnover rule — the winners are
sub-microcaps), aggregate open-risk cap (portfolio heat), sector concentration
limit (MOREALTY + PHOENIXLTD were one bet), then order-placement automation
(execution only — selection stays human). Gate defined from Stage 1 data.

## Stage 3 — the horizon (year 2+)

Two years of timestamped, unfalsifiable personal statistics on proven
infrastructure. Decide then what "big" means. Not before.

## Parking lot — ideas that wait their turn

- **Telegram notifications** — ✅ BUILT 2026-07-14 (notify.py, nightly workflow
  step; heartbeat design: silence = pipeline failure).
- **Morning gate notification** (approved, later): ~9:20 IST job fetches the
  NIFTY open, applies the tested gate [−0.2%, +0.5%], pushes "GATE OPEN /
  CLOSED today" so the 9:15 glance becomes a buzz. Moving parts to solve when
  built: a second workflow cron at 03:50 UTC (GitHub cron jitter matters more
  at a precise hour), NSE snapshot API from datacenter IPs in the morning
  session. Rule itself is already tested — this is delivery only.
- **Morning conditions check** — PROMOTED TO TESTED RULE 2026-07-14. Trial
  (exp_morning_gate.py, 982 corridor-valid entries): market-open gap outside
  [−0.2%, +0.5%] → 27–46% win, negative mean, on BOTH sides — euphoric opens
  as toxic as fearful ones. In-window: 63% win, +2.1% median. Gate closes
  ~22% of mornings (mostly green ones; longest historical lockout 9 sessions).
  The rule: one glance at NIFTY's open at 9:15 — outside the window, no
  entries that day. Entries only; holdings and exits unaffected. No
  infrastructure needed; on the process card.

## Standing rules (all stages)

1. No new signal logic without a backtest; no new thresholds without evidence.
2. The journal is the referee of every open question.
3. Confidence is not a gate. Streaks are not a gate. Only counts are gates.
4. The plan survives motivation. That is its entire job.
