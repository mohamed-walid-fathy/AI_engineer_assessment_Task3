# Operations Intelligence Assistant — Guide for the COO

This guide is written for a non-technical operations leader. It explains what the system does, how to get value from it, and where to be careful.

---

## What Did We Build?

We built a question-and-answer assistant that turns plain-language operations questions into short, evidence-backed answers drawn directly from your orders, deliveries, and reviews extract (around 64,000 orders across 132 branches and 1,700+ riders).

**The problem it helps with:** as an operator you need to know quickly — without waiting for an analyst — which branches or riders need attention, where customer complaints concentrate, and whether anything in the data looks worrying. The system gives you that first, trustworthy read.

 You ask in your own words; it returns the number, a plain-language explanation, and pointers on where to look next. All numbers come from fixed calculations over the data you provided.

---

## How Should You Use It?

### What kinds of questions can you ask?

The assistant handles five kinds of questions well:

1. **"Which branch got worse at delivery last month?"** — names the most-deteriorated branch and how much its late-delivery rate moved.
2. **"Why did that branch get worse?"** — breaks the change into dispatch (assignment), pickup, and overall delivery time, plus the riders and zones that appeared most in late orders.
3. **"Are complaints about late orders coming from specific areas, times, or riders?"** — shows where late-delivery complaints cluster by zone, branch, rider, hour of day, and day of week.
4. **"Who is the worst or best driver?"** — ranks riders by late-delivery rate among those with enough orders for a fair comparison (also supports "top 5" or a specific rider such as `rider_1234`).
5. **"Is there anything I should be worried about?"** — scans for branches with sharp late-rate jumps, riders with unusually high rates, rating drops, and data-quality flags worth noting.

You can use everyday phrasing. "Driver," "rider," and "courier" mean the same thing to the system. You can add "last month," "this month," or "top 5" when you want that scope; otherwise it uses last full month and the top five by default.

**A few examples to try:**

- "Which branch got worse at delivery last month, and why?"
- "Are complaints about late orders coming from specific areas, times, or drivers?"
- "Is there anything in this data I should be worried about?"
- "Who is the worst driver?"
- "Show me the top 5 worst drivers."

### What will you get back?

Each answer contains:

- **A direct answer in plain language** — the branch or rider name, the change in late-delivery rate, the peak hour or day for complaints, or the list of findings.
- **Supporting evidence you can inspect** — the numbers behind the answer are available in an expandable "Evidence" panel.
- **A short Data Note at the end** — one line that states the key limitation for that answer (for example, how "late" is defined or that some months have few orders).

### How to interpret the answers

- **Late means "unusually long for that branch."** There was no service promise (SLA) in the file, so the system calls an order late when it took longer than the slowest 10% of that same branch's history. Use the percentage to compare branches and months, not to count broken promises.
- **Rates are always explained with their denominator.** For complaints, "14%" means 14 out of every 100 *orders* produced a late complaint — not 14 out of 100 comments. Zones, branches, or riders with fewer than 20 orders are left out entirely to avoid a "1 order, 100%" mistake.
- **Spikes are signals, not verdicts.** A high late rate for a rider or branch tells you where to look. It does not prove cause and does not on its own justify action against a person. Routes, demand spikes, and dispatch delays can all produce the same pattern.

---

## What Can You Rely On It For?

Things the system is designed to support:

- **Pointing you toward where to look next** among many branches and riders, quickly and consistently.
- **Using the same calculation every time** so comparisons across questions and months are apples-to-apples. (given data for both months is complete)
- **Keeping the data private by design** — your customer comments are processed locally; only small, aggregated numbers are ever used to phrase the final answer.

Use it as **decision support** — a way to prioritise where your team digs deeper — not as an autonomous decision-maker.

## What Should You NOT Rely On It For?

Be cautious and verify independently when:

- **Making people decisions.** Never use a rider ranking alone to discipline or reward. Check routes, shift patterns, dispatch logs, and branch context before drawing conclusions about an individual.
- **Treating "late" as a broken promise.** Because late is branch-relative, a "41% late" reading does not mean 41% of orders missed a promise — it means 41% were unusually slow for those branches. Use it to prioritise investigation, not to report SLA breaches.
- **Assuming comments represent everyone.** Only about 29% of orders included a written comment, so complaint patterns reflect what customers who wrote in said, not the whole customer base.
- **Reading month-to-month moves as pure trend.** Some months in this extract have far fewer orders than others (for example, about 843 orders in July 2025 versus nearly 10,000 in April 2026; April 2025 is empty). Moves between months may partly reflect sampling, not real operational change.
- **Expecting forecasts or financial explanations.** The system reports what already happened in delivery operations. It does not predict next week or explain revenue, cost, or pricing — those require other data.
- **Treating every flagged item as confirmed.** The "worry scan" uses straightforward thresholds (for example, a late-rate jump above 5 points, a rating drop above 0.3). Findings are leads worth checking, not proven root causes.

When in doubt, treat the answer as a well-sourced starting point for a conversation with branch managers, dispatch, and the data team — not the final word.

---

*Technical detail, data cleaning rules, and known limitations are documented separately for the engineering team in `to_engineering_team.md` and `assumptions&notes.md`. Setup instructions are in `setup.md`.*
