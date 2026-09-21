# Assumptions & Notes

This document collects the important assumptions, data caveats, and interpretation notes that apply to the Operations Intelligence Assistant. No assumption here is changed from the implementation — the app's cleaning and metric logic follows exactly what is stated below.

## 1. How "Late" Is Defined

> **Assumption — `late_definition` (`app/data_layer.py:19`)**
> An order is "late" if its delivery duration (`DeliveryTime - CreatedDate`) exceeds the 90th percentile duration for its own branch, computed over that branch's full history in the dataset. This is a relative, self-referential threshold, not a fixed SLA in minutes, because no SLA was provided in the data.

- There is no SLA column in `operations_data_anonymized.xlsx`. The app cannot know a contractual promise time.
- Branch P90 is computed on `delivery_min_clean` only (outlier-capped; see below).
- A reported figure such as "29.4% late" means 29.4% of that branch's orders were slower than its own historical P90 — not 29.4% past a service promise.
- If the business has a real SLA (for example "45 minutes"), the correct change is to replace `LATE_THRESHOLD_FN` / `branch_late_thresholds()` in `app/data_layer.py` with that constant. All five tools would then pick up the new definition automatically.

## 2. Outlier Cap

> **Assumption — `outlier_cap` (`app/data_layer.py:28`)**
> Delivery, dispatch, and pickup durations longer than 24 hours (1440 minutes) are treated as data or timestamp errors, not real operational events, and are excluded from duration statistics. The order itself is retained for counts and ratings.

- Implemented in `app/data_layer.py:92-106` as `flag_delivery_outlier`, `flag_dispatch_outlier`, `flag_pickup_outlier` and the `*_clean` columns.
- Affected values become `NaN` for statistics but the row still contributes to order counts, ratings, and comment aggregations.

## 3. Negative Durations / Timestamp Artifacts

> **Assumption — `negative_durations` (`app/data_layer.py:34`)**
> Approximately 21% of `PickingUpTime` values fall before `AddedToTripTime`, and approximately 5% of `AddedToTripTime` values fall before `CreatedDate`. These are treated as clock-sync or system-logging artifacts. Rows with a negative dispatch or pickup lag are excluded from lag statistics only (not from order counts or ratings).

- Flagged as `flag_negative_dispatch` and `flag_negative_pickup` in `app/data_layer.py:92-93`.
- A substantial negative-lag share means dispatch and pickup means should be interpreted with caution even after filtering.

## 4. Minimum Volume Gate

> **Assumption — `min_volume_gate` (`app/data_layer.py:41`)**
> Any branch, rider, or zone comparison suppresses entities with fewer than `MIN_VOLUME` orders in the relevant window. `MIN_VOLUME` is 20 (`app/data_layer.py:70`). Branch order counts in the dataset range from 1 to 1,924 — small-sample entities are hidden from rankings rather than shown with misleadingly precise statistics.

- Applied in `app/tools.py` (`branch_delivery_trend`, `late_complaint_breakdown`, `anomaly_scan`, `rider_performance_ranking`).
- Reported explicitly in answers ("Only branches with >= 20 orders in both months are shown") and in evidence JSON (`min_volume_gate`).
- Rider ranking: "worst" means highest `is_late` rate among eligible riders (never mean delivery time).

## 5. Reference Date and "Last Month"

> **Assumption — `reference_date` (`app/data_layer.py:47`)**
> "Last month" and "this month" are resolved against the maximum `CreatedDate` actually present in the data (2026-07-12), not against today's real-world date. The most recent calendar month (July 2026) is therefore partial.

- Implemented as `data_reference_date()` in `app/data_layer.py:150`.
- Displayed in the UI as "Answering relative to latest data date **2026-07-12**. 'Last month' = most recent full calendar month before that date." and included in evidence (`reference_date_used`, `compared_months`).

## 6. Sampling Caveat — Partial Extract

> **Assumption — `sampling_caveat` (`app/data_layer.py:53`)**
> Monthly order volumes in the dataset are highly uneven (for example, 843 orders in July 2025 versus 9,953 in April 2026) and April 2025 has zero rows. This looks like a sample extract, not a complete transaction log. Month-over-month comparisons may reflect sampling differences, not real operational change. Every answer that makes a month-over-month comparison flags this caveat.

- Concretely: uneven volumes affect `branch_delivery_trend`, `branch_worsening_reasons`, and `anomaly_scan`.
- The system cannot rule sampling effects out from the data alone — treat MoM moves as directional leads.

## 7. Zero Rating

> **Assumption — `zero_rating` (`app/data_layer.py:62`)**
> `0.0` in `CustomerRatingAverage` is treated as a real (very negative) rating, not as a null or "not rated" code, because the data dictionary does not indicate otherwise.

- Should be confirmed with the owner of the rating system before production use. If `0.0` means "unrated," averages would shift materially (1,339 orders carry `0.0` in the full extract).

## 8. Additional Operational and Data Notes

These are not separate ASSUMPTIONS keys but are important for correct interpretation:

- **Dataset scale and structure.** Approximately 64,619 orders, 132 distinct `BranchID` values (versus a ~120-branch expectation), 1,700+ `RiderID` values.
- **Comments are incomplete.** Roughly 29% of orders include a `CustomerComment`. Late-complaint analysis (via `app/nlp_pipeline.py`) therefore reflects only orders where customers wrote something. Rates in `late_complaint_breakdown` are per 100 orders with explicit denominators (see `app/tools.py:151` `METRIC_DEFINITIONS`), not per 100 comments.
- **Language.** Customer comments are English and Arabic (including Egyptian dialect). The local NLP pipeline (`paraphrase-multilingual-MiniLM-L12-v2`) handles both; a crude `comment_lang` tag (`ar` vs `en`) is derived in `app/data_layer.py:115` for bucketing only, not for classification.
- **Local NLP scope.** Three independent signals per comment — `sentiment`, `complaint_intent`, `late_order_complaint` — from `app/nlp_pipeline.py` and thresholds/phrases in `app/nlp_prototypes.py`. Batch inference with unique-text caching; lexical fallback if the embedding model cannot load. The pipeline only labels text; `app/tools.py` owns all counts and rates.
- **No forecasting or financial explanation.** The app reports what already happened. Patterns mentioning `will`, `forecast`, `predict`, `next week/month/quarter`, `revenue`, or disciplinary asks are answered with scoped refusals in `app/intent.py:30`.
- **Rider ranking uses median.** `avg_delivery_min` in `rider_performance_ranking` is the median of `delivery_min_clean` (not the mean) because delivery times have a long right tail up to the 24-hour cap.

## 9. Known Limitations and Caveats to Keep in Mind

- Late is branch-relative; do not read it as an SLA breach count.
- Comment-bearing orders are a minority; avoid generalising complaint shares to the full order population.
- Dispatch/pickup lag means are filtered but still sit on imperfect timestamp data.
- Small entities (< 20 orders) are intentionally invisible — absence from a ranking does not mean good performance.
- "Last month" is June 2026 (last full month before 2026-07-12); July 2026 is partial and is not used as a full comparison month.
- Monthly volume unevenness means some branches fail the 20-order gate in one month but not the other.

All of the above accurately reflects the frozen implementation. For how the system is intended to be used, see `COO_doc.md`; for engineering detail, see `to_engineering_team.md`.
