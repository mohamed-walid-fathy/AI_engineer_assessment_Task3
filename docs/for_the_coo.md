# Your Operations Assistant — What It Is and How to Use It

## What it does

Type questions like "which branch got worse at delivery last month?" or "who is the worst driver?" and get a short answer with numbers, drawn from your orders/deliveries/reviews extract. No SQL or analyst needed.

It handles 5 kinds:
1. Which branch got worse last month (names the single most-deteriorated branch first).
2. Why a branch got worse (dispatch vs pickup vs delivery, riders, zones — as associated signals, never proven cause).
3. Whether late complaints cluster by area, time, or rider.
4. Who is the worst/best driver (highest/lowest late-order rate among riders with enough orders).
5. "Anything to worry about" overview scan.

Try: the 3 kickoff questions plus "Who is the worst driver?" / "Show me the top 5 worst drivers."

## How to ask

- Use driver/rider/courier interchangeably — all mean RiderID.
- Add "last month" or "top 5" when you want that window/count; otherwise it uses last full month and top 5.
- Read the short data note at the end of each answer — it states what could limit that number.

## What you can trust

- Where to look next among 132 branches / 1,700+ riders.
- Consistent definitions: same calculation every time.
- Rider ranking is by late-order rate with a 20-order minimum, median delivery shown, compared to dataset average.

## Limitations

- **Late is relative, not SLA-based.** The file has no SLA, so late = delivery longer than that branch's own slowest 10% (P90). A "41% late" rider means 41% above their branches' P90s, not 41% past a promise.
- **Comments are incomplete** (~29% of orders have one); complaint analysis uses a local multilingual NLP pipeline with a conservative threshold, so some paraphrased delay reports may be missed.
- **Timestamps have artifacts** (~21% pickup-before-assignment); excluded from timing stats, kept for counts.
- **Monthly volumes are uneven** (some months <1,000 orders); treat cross-month moves as directional.
- **Signals, not verdicts.** Never use a ranking alone to discipline; routes, dispatch delays, and branch mix confound rider numbers.
- No forecasting, no revenue/cost explanation.
