# The plan — how this gets big

Wealth = Capital × Edge × Time × Survival. Tooling is not a lever; closed
feedback loops are. Stages advance through gates, never through feelings.
Gate numbers are amendable by editing this file — with a git commit as witness.

## Stage 0 — prove the trader (now → ~3 months)

**Question:** can I execute my own system for 20 consecutive trades?

| what | rule |
|---|---|
| Capital | ₹50,000 — frozen |
| Risk | 1% per trade, 20% max position, 2 positions max |
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

- **Telegram notifications** (approved, next build): evening push of gradeworthy
  tickets + daily heartbeat line; missing message = pipeline failure alarm.
- **Morning conditions check** (idea, unevaluated): a post-open job that reads
  market conditions and gates the day's entries. Rules for when we revisit:
  it must be *mechanical and backtestable* (e.g. "skip entries if NIFTY gaps
  down >X%") — never a vibe check, because a morning gut-veto is fear wearing
  a process costume. Note before building: the corridor already handles
  per-stock gaps mechanically, and the backtest found signals in *weak* tape
  performed fine — the burden of proof is on the filter, tested on the 4,628
  historical signals like everything else.

## Standing rules (all stages)

1. No new signal logic without a backtest; no new thresholds without evidence.
2. The journal is the referee of every open question.
3. Confidence is not a gate. Streaks are not a gate. Only counts are gates.
4. The plan survives motivation. That is its entire job.
