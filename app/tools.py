"""
tools.py
Every function here returns a plain dict: {answer_data, caveats, n_rows}.
No function calls an LLM. These are the ONLY source of numbers in the app.
Gemini (intent/narration) never calculates business metrics.
"""
from __future__ import annotations
import pandas as pd
import numpy as np
try:
    from data_layer import MIN_VOLUME, ASSUMPTIONS, data_reference_date
except ImportError:  # `streamlit run app/app.py` from repo root
    from app.data_layer import MIN_VOLUME, ASSUMPTIONS, data_reference_date


def _month_window(df, months_back=1, ref=None):
    """Return (start, end, label) for the Nth full month before ref's month."""
    ref = ref or data_reference_date(df)
    first_of_ref_month = ref.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end = first_of_ref_month
    for _ in range(months_back - 1):
        end = end - pd.Timedelta(days=1)
        end = end.replace(day=1)
    start = (end - pd.Timedelta(days=1)).replace(day=1)
    label = start.strftime("%B %Y")
    return start, end, label


# ---------------------------------------------------------------------------
# Q1: "Which branch got worse at delivery last month, and why?"
# ---------------------------------------------------------------------------
def branch_delivery_trend(df: pd.DataFrame, min_volume: int = MIN_VOLUME) -> dict:
    ref = data_reference_date(df)
    last_start, last_end, last_label = _month_window(df, months_back=1, ref=ref)
    prev_start, prev_end, prev_label = _month_window(df, months_back=2, ref=ref)

    last = df[(df.CreatedDate >= last_start) & (df.CreatedDate < last_end)]
    prev = df[(df.CreatedDate >= prev_start) & (df.CreatedDate < prev_end)]

    def branch_stats(d):
        g = d.groupby("BranchID")
        out = g.agg(
            n=("OrderID", "count"),
            p50_min=("delivery_min_clean", "median"),
            p90_min=("delivery_min_clean", lambda s: s.quantile(0.9)),
            late_rate=("is_late", "mean"),
        )
        return out[out.n >= min_volume]

    last_stats = branch_stats(last)
    prev_stats = branch_stats(prev)

    merged = last_stats.join(prev_stats, lsuffix="_last", rsuffix="_prev", how="inner")
    if merged.empty:
        return {
            "answer_data": None,
            "n_rows": int(len(last) + len(prev)),
            "caveats": [
                f"No branch had at least {min_volume} orders in BOTH {prev_label} "
                f"and {last_label}, so no reliable month-over-month comparison "
                f"can be made at this volume threshold.",
                ASSUMPTIONS["sampling_caveat"],
            ],
        }

    merged["p90_change_min"] = merged["p90_min_last"] - merged["p90_min_prev"]
    merged["late_rate_change_pp"] = (merged["late_rate_last"] - merged["late_rate_prev"]) * 100
    merged = merged.sort_values("p90_change_min", ascending=False)

    worsened = merged[merged["p90_change_min"] > 0].head(10)
    improved = merged[merged["p90_change_min"] < 0].sort_values("p90_change_min").head(5)

    return {
        "answer_data": {
            "compared_months": [prev_label, last_label],
            "reference_date_used": str(ref.date()),
            "min_volume_gate": min_volume,
            "branches_worsened": worsened.reset_index().round(1).to_dict(orient="records"),
            "branches_improved": improved.reset_index().round(1).to_dict(orient="records"),
        },
        "n_rows": int(len(last) + len(prev)),
        "caveats": [
            f"Only branches with >= {min_volume} orders in both months are shown; "
            f"{len(last_stats)} branches met that bar in {last_label} out of "
            f"{df.BranchID.nunique()} total branches in the dataset.",
            ASSUMPTIONS["sampling_caveat"],
            ASSUMPTIONS["late_definition"],
        ],
    }


def branch_worsening_reasons(df: pd.DataFrame, branch_id: str, min_volume: int = MIN_VOLUME) -> dict:
    """Break down WHY a specific branch's delivery got worse: dispatch lag vs
    pickup lag vs everything-else (in-transit) contribution."""
    ref = data_reference_date(df)
    last_start, last_end, last_label = _month_window(df, months_back=1, ref=ref)
    prev_start, prev_end, prev_label = _month_window(df, months_back=2, ref=ref)

    b = df[df.BranchID == branch_id]
    last = b[(b.CreatedDate >= last_start) & (b.CreatedDate < last_end)]
    prev = b[(b.CreatedDate >= prev_start) & (b.CreatedDate < prev_end)]

    if len(last) < min_volume or len(prev) < min_volume:
        return {
            "answer_data": None,
            "n_rows": int(len(last) + len(prev)),
            "caveats": [f"Branch {branch_id} has fewer than {min_volume} orders in "
                        f"one of the two months being compared — breakdown suppressed."],
        }

    def seg_means(d):
        return {
            "dispatch_min": round(d["dispatch_min_clean"].mean(), 1),
            "pickup_min": round(d["pickup_min_clean"].mean(), 1),
            "delivery_min": round(d["delivery_min_clean"].mean(), 1),
            "late_rate_pct": round(d["is_late"].mean() * 100, 1),
            "avg_rating": round(d["CustomerRatingAverage"].mean(), 2),
            "n": len(d),
        }

    last_seg, prev_seg = seg_means(last), seg_means(prev)
    top_riders = (
        last[last.is_late]["RiderID"].value_counts().head(5).to_dict()
    )
    top_zones = (
        last[last.is_late]["DeliveryZoneName"].value_counts().head(5).to_dict()
    )

    return {
        "answer_data": {
            "branch": branch_id,
            "months": [prev_label, last_label],
            "prev": prev_seg,
            "last": last_seg,
            "top_riders_in_late_orders": top_riders,
            "top_zones_in_late_orders": top_zones,
        },
        "n_rows": int(len(last) + len(prev)),
        "caveats": [ASSUMPTIONS["late_definition"], ASSUMPTIONS["sampling_caveat"]],
    }


# ---------------------------------------------------------------------------
# Q2: "Are complaints about late orders coming from specific areas, times, riders?"
#
# Comment signals come from the LOCAL multilingual NLP pipeline
# (app/nlp_pipeline.py): sentiment, complaint_intent, late_order_complaint
# are three independent per-comment labels. This function ONLY aggregates
# them with deterministic pandas logic — it never classifies text itself.
# ---------------------------------------------------------------------------
METRIC_DEFINITIONS = {
    # Explicit denominators. Rates below are per 100 ORDERS (all orders in the
    # group), NOT per 100 comments — stated so Gemini/narration cannot rename
    # or interchange them.
    "order_count": "All orders in the analyzed set (with or without comments).",
    "comment_count": "Orders that include a non-empty customer comment.",
    "no_comment_pct": "Share of orders without any comment.",
    "complaint_count": "Comments whose complaint_intent is a complaint "
                       "(any intent except none/compliment), any topic.",
    "complaint_rate": "complaint_count per 100 orders (denominator: all orders).",
    "late_order_complaint_count": "Comments flagged late_order_complaint=True "
                                  "by the local NLP pipeline (explicit lateness).",
    "late_order_rate": "late_order_complaint_count per 100 orders "
                       "(denominator: all orders). Distinct from complaint_rate "
                       "and from timing-based late rate (branch P90); never interchange.",
}


def _nlp_labels(df: pd.DataFrame) -> pd.DataFrame:
    """Attach cached local-NLP labels. Model loads once per process; unique
    comments are embedded once (see nlp_pipeline cache stats)."""
    try:
        from nlp_pipeline import get_pipeline
    except ImportError:  # `streamlit run app/app.py` from repo root
        from app.nlp_pipeline import get_pipeline
    labels = get_pipeline().analyze_series(df["CustomerComment"])
    return labels


def late_complaint_breakdown(df: pd.DataFrame, min_volume: int = MIN_VOLUME) -> dict:
    d = df.copy()
    labels = _nlp_labels(d)
    d["is_complaint"] = (labels["nlp_complaint_intent"] != "none") & (
        labels["nlp_complaint_intent"] != "compliment")
    d["is_late_complaint"] = labels["nlp_late"]
    complaints = d[d["is_late_complaint"]]

    order_count = int(len(d))
    comment_count = int(d["has_comment"].sum())
    no_comment_pct = round((1 - comment_count / order_count) * 100, 1) if order_count else 0.0
    complaint_count = int(d["is_complaint"].sum())
    late_count = int(len(complaints))

    if complaints.empty:
        return {"answer_data": None, "n_rows": 0,
                "caveats": ["No comments were flagged as late-order complaints "
                            "by the local NLP pipeline."]}

    def top_with_rate(col):
        counts = complaints[col].value_counts()
        totals = d.groupby(col).size()
        rate = (counts / totals * 100).round(1)
        volume_ok = totals[totals >= min_volume].index
        out = pd.DataFrame({"complaints": counts, "complaint_rate_pct": rate, "total_orders": totals})
        out = out.loc[out.index.intersection(volume_ok)]
        # Counts are integers by definition; NaN alignment in the join above
        # would otherwise leak floats (53.0) into the evidence Gemini sees.
        out["complaints"] = out["complaints"].fillna(0).astype(int)
        out["total_orders"] = out["total_orders"].astype(int)
        return out.sort_values("complaints", ascending=False).head(10).reset_index().to_dict(orient="records")

    by_zone = top_with_rate("DeliveryZoneName")
    by_rider = top_with_rate("RiderID")
    by_branch = top_with_rate("BranchID")
    by_hour = (
        complaints.groupby("order_hour").size().reindex(range(24), fill_value=0)
        .to_dict()
    )
    by_dow = complaints.groupby("order_dow").size().to_dict()

    try:
        from nlp_pipeline import get_pipeline
    except ImportError:
        from app.nlp_pipeline import get_pipeline
    pipe = get_pipeline()

    return {
        "answer_data": {
            # Legacy keys (same semantics as before; narration/tests use them).
            "total_comments": comment_count,
            "late_complaints_found": late_count,
            "pct_of_all_comments": round(late_count / comment_count * 100, 1) if comment_count else 0.0,
            "top_zones_by_complaint_volume": by_zone,
            "top_riders_by_complaint_volume": by_rider,
            "top_branches_by_complaint_volume": by_branch,
            "complaints_by_hour_of_day": by_hour,
            "complaints_by_day_of_week": by_dow,
            # Explicit metric names + denominators (for Gemini evidence).
            "order_count": order_count,
            "comment_count": comment_count,
            "no_comment_pct": no_comment_pct,
            "complaint_count": complaint_count,
            "complaint_rate": round(complaint_count / order_count * 100, 1) if order_count else 0.0,
            "late_order_complaint_count": late_count,
            "late_order_rate": round(late_count / order_count * 100, 1) if order_count else 0.0,
            "metric_definitions": dict(METRIC_DEFINITIONS),
            "nlp_backend": pipe.backend_name,
        },
        "n_rows": late_count,
        "caveats": [
            "Late-order complaints are flagged by a local multilingual NLP pipeline "
            "(embeddings + transparent similarity layer, EN+AR), not keyword matching. "
            "The threshold is deliberately conservative: some paraphrased delay reports "
            "are missed, and sentiment/complaint-intent/late labels are independent "
            "(a negative comment is not automatically a late complaint).",
            f"{no_comment_pct}% of orders have no comment at all; rates are per 100 "
            f"orders (denominator: all {order_count:,} orders), not per 100 comments.",
            f"Zones/riders/branches with fewer than {min_volume} total orders "
            f"are excluded even if all of them complained, to avoid a '1 order, "
            f"1 complaint = 100%' artifact.",
        ],
    }


# ---------------------------------------------------------------------------
# Q3: "Is there anything in this data I should be worried about?"
# ---------------------------------------------------------------------------
def anomaly_scan(df: pd.DataFrame, min_volume: int = MIN_VOLUME) -> dict:
    ref = data_reference_date(df)
    last_start, last_end, last_label = _month_window(df, months_back=1, ref=ref)
    prev_start, prev_end, prev_label = _month_window(df, months_back=2, ref=ref)
    last = df[(df.CreatedDate >= last_start) & (df.CreatedDate < last_end)]
    prev = df[(df.CreatedDate >= prev_start) & (df.CreatedDate < prev_end)]

    findings = []

    # 1. Branches with big late-rate jumps
    def rate_by(d, key):
        g = d.groupby(key)
        out = g.agg(n=("OrderID", "count"), late_rate=("is_late", "mean"),
                     avg_rating=("CustomerRatingAverage", "mean"))
        return out[out.n >= min_volume]

    lb, pb = rate_by(last, "BranchID"), rate_by(prev, "BranchID")
    joined = lb.join(pb, lsuffix="_last", rsuffix="_prev", how="inner")
    joined["late_rate_jump_pp"] = (joined.late_rate_last - joined.late_rate_prev) * 100
    worst_branches = joined.sort_values("late_rate_jump_pp", ascending=False).head(5)
    for bid, row in worst_branches.iterrows():
        if row.late_rate_jump_pp > 5:
            findings.append({
                "type": "branch_late_rate_jump",
                "branch": bid,
                "detail": f"Branch {bid}: late-order rate rose {row.late_rate_jump_pp:.1f} points "
                          f"({row.late_rate_prev*100:.1f}% -> {row.late_rate_last*100:.1f}%) "
                          f"between {prev_label} and {last_label}, n={int(row.n_last)}.",
            })

    # 2. Riders with high late rate at adequate volume (whole-dataset, not just last month)
    rr = df.groupby("RiderID").agg(n=("OrderID", "count"), late_rate=("is_late", "mean"))
    rr = rr[rr.n >= min_volume]
    overall_late_rate = df["is_late"].mean()
    bad_riders = rr[rr.late_rate > overall_late_rate * 2].sort_values("late_rate", ascending=False).head(5)
    for rid, row in bad_riders.iterrows():
        findings.append({
            "type": "rider_high_late_rate",
            "rider": rid,
            "detail": f"Rider {rid}: late-order rate {row.late_rate*100:.1f}% vs a {overall_late_rate*100:.1f}% "
                      f"dataset average, over {int(row.n)} orders.",
        })

    # 3. Rating drops by branch
    lr = last.groupby("BranchID").agg(n=("OrderID", "count"), rating=("CustomerRatingAverage", "mean"))
    pr = prev.groupby("BranchID").agg(n=("OrderID", "count"), rating=("CustomerRatingAverage", "mean"))
    lr, pr = lr[lr.n >= min_volume], pr[pr.n >= min_volume]
    rj = lr.join(pr, lsuffix="_last", rsuffix="_prev", how="inner")
    rj["rating_drop"] = rj.rating_prev - rj.rating_last
    drops = rj.sort_values("rating_drop", ascending=False).head(5)
    for bid, row in drops.iterrows():
        if row.rating_drop > 0.3:
            findings.append({
                "type": "branch_rating_drop",
                "branch": bid,
                "detail": f"Branch {bid}: average rating fell from {row.rating_prev:.2f} to "
                          f"{row.rating_last:.2f} ({prev_label} -> {last_label}), n={int(row.n_last)}.",
            })

    # 4. Data-quality flags worth surfacing regardless
    dq = {
        "pct_negative_pickup_lag": round(df["flag_negative_pickup"].mean() * 100, 1),
        "pct_negative_dispatch_lag": round(df["flag_negative_dispatch"].mean() * 100, 1),
        "pct_delivery_outliers_excluded": round(df["flag_delivery_outlier"].mean() * 100, 1),
        "months_with_under_1000_orders": [
            str(p) for p, n in df.groupby("order_month").size().items() if n < 1000
        ],
        "zero_rating_orders": int((df.CustomerRatingAverage == 0).sum()),
    }

    return {
        "answer_data": {
            "operational_findings": findings,
            "data_quality_flags": dq,
            "compared_months": [prev_label, last_label],
        },
        "n_rows": int(len(df)),
        "caveats": [
            "This is a rule-based scan (thresholds: late-rate jump > 5pp, rider "
            "late-rate > 2x average, rating drop > 0.3), not a statistical "
            "significance test — treat findings as leads to investigate, not "
            "confirmed root causes.",
            ASSUMPTIONS["sampling_caveat"],
            ASSUMPTIONS["min_volume_gate"],
        ],
    }


# ---------------------------------------------------------------------------
# Q: "Who is the worst driver / rider?" (also best / top-N / specific rider)
# ---------------------------------------------------------------------------
def rider_performance_ranking(
    df: pd.DataFrame,
    min_volume: int = MIN_VOLUME,
    top_n: int = 5,
    window: str | None = None,
    rider_id: str | None = None,
    direction: str = "worst",
) -> dict:
    """Rank riders (drivers/couriers = RiderID in the data) by late-order rate.

    window: None/"all_time" -> whole dataset; "last_month" -> last full
        calendar month before the reference date; "current_month" -> the
        reference date's (partial) calendar month.
    rider_id: if given, return that rider's card plus its rank.
    direction: "worst" (highest late rate first) or "best" (lowest first).
        Both ends are always computed so the answer can show context.
    """
    ref = data_reference_date(df)
    label = "whole dataset"
    d = df
    if window == "last_month":
        last_start, last_end, last_label = _month_window(df, months_back=1, ref=ref)
        d = df[(df.CreatedDate >= last_start) & (df.CreatedDate < last_end)]
        label = last_label
    elif window == "current_month":
        start = ref.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        d = df[(df.CreatedDate >= start) & (df.CreatedDate <= ref)]
        label = start.strftime("%B %Y") + " (partial)"
    elif window in (None, "all_time"):
        d = df
        label = "whole dataset" if window is None else "all time"

    if d.empty:
        return {
            "answer_data": None,
            "n_rows": 0,
            "caveats": [f"No orders found in window '{label}'."],
        }

    g = d.groupby("RiderID")
    stats = g.agg(
        n=("OrderID", "count"),
        late_rate=("is_late", "mean"),
        avg_rating=("CustomerRatingAverage", "mean"),
        # median, not mean: delivery times have a long right tail (up to the
        # 24h outlier cap), so the mean overstates the typical trip.
        avg_delivery_min=("delivery_min_clean", "median"),
    )
    overall_late_rate = float(d["is_late"].mean())
    eligible = stats[stats.n >= min_volume].copy()
    if eligible.empty:
        return {
            "answer_data": None,
            "n_rows": int(len(d)),
            "caveats": [
                f"No rider had at least {min_volume} orders in '{label}' — "
                f"ranking suppressed to avoid small-sample artifacts. "
                f"{int(stats.shape[0])} riders seen in window, "
                f"max orders for one rider: {int(stats.n.max()) if len(stats) else 0}."
            ],
        }

    eligible["late_rate_pct"] = (eligible["late_rate"] * 100).round(1)
    eligible["vs_avg_pp"] = ((eligible["late_rate"] - overall_late_rate) * 100).round(1)
    eligible["avg_rating"] = eligible["avg_rating"].round(2)
    eligible["avg_delivery_min"] = eligible["avg_delivery_min"].round(1)
    ranked_worst = eligible.sort_values("late_rate", ascending=False)
    ranked_best = eligible.sort_values("late_rate", ascending=True)

    def _row(rid, row):
        return {
            "RiderID": rid,
            "n": int(row["n"]),
            "late_rate_pct": float(row["late_rate_pct"]),
            "vs_avg_pp": float(row["vs_avg_pp"]),
            "avg_rating": float(row["avg_rating"]),
            "avg_delivery_min": float(row["avg_delivery_min"]),
        }

    worst = [_row(rid, r) for rid, r in ranked_worst.head(top_n).iterrows()]
    best = [_row(rid, r) for rid, r in ranked_best.head(top_n).iterrows()]

    single = None
    if rider_id is not None:
        # case-insensitive lookup; RiderIDs are like rider_xxxx
        match = [r for r in eligible.index if str(r).lower() == str(rider_id).lower()]
        if match:
            rid = match[0]
            row = eligible.loc[rid]
            # 1-based rank by late rate (1 = worst)
            rank = int((ranked_worst.index == rid).argmax() + 1) if rid in ranked_worst.index else None
            single = _row(rid, row)
            single["rank_by_late_rate"] = rank
            single["rank_out_of"] = int(len(eligible))
        else:
            n_all = int(stats.loc[stats.index.str.lower() == str(rider_id).lower(), "n"].sum()) \
                if len(stats) else 0
            return {
                "answer_data": None,
                "n_rows": int(len(d)),
                "caveats": [
                    f"Rider '{rider_id}' "
                    + (f"has only {n_all} orders in '{label}' — below the "
                       f"{min_volume}-order gate, so no reliable rate can be shown."
                       if n_all else f"was not found in '{label}'.")
                ],
            }

    return {
        "answer_data": {
            "window": label,
            "reference_date_used": str(ref.date()),
            "min_volume_gate": min_volume,
            "overall_late_rate_pct": round(overall_late_rate * 100, 1),
            "riders_considered": int(len(eligible)),
            "riders_seen_in_window": int(len(stats)),
            "direction_requested": direction,
            "worst_riders": worst,
            "best_riders": best,
            "single_rider": single,
        },
        "n_rows": int(len(d)),
        "caveats": [
            f"'Driver' means RiderID in this data. 'Worst' means highest "
            f"late-order rate among riders with >= {min_volume} orders in {label}.",
            ASSUMPTIONS["late_definition"],
            "A high late rate can reflect a harder route/zone or dispatch "
            "delays, not just rider behavior — use this to know where to ask, "
            "not as a verdict on a person.",
        ],
    }


TOOLS = {
    "branch_delivery_trend": branch_delivery_trend,
    "branch_worsening_reasons": branch_worsening_reasons,
    "late_complaint_breakdown": late_complaint_breakdown,
    "anomaly_scan": anomaly_scan,
    "rider_performance": rider_performance_ranking,
}
