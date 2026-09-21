"""Narration-layer regression tests — no analytics/routing changes, no live API."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

from narration import template_narration


def _complaint_result():
    return {"answer_data": {
        "late_complaints_found": 12.0,  # float on purpose: must render as int
        "total_comments": 100.0,
        "pct_of_all_comments": 12.0,
        "top_zones_by_complaint_volume": [
            {"DeliveryZoneName": "Z1", "complaints": 7.0, "total_orders": 50.0,
             "complaint_rate_pct": 14.0}],
        "top_branches_by_complaint_volume": [
            {"BranchID": "BR-1", "complaints": 5.0, "total_orders": 40.0,
             "complaint_rate_pct": 12.5}],
        "top_riders_by_complaint_volume": [
            {"RiderID": "r1", "complaints": 4.0, "total_orders": 30.0,
             "complaint_rate_pct": 13.3}],
        "complaints_by_hour_of_day": {"9": 1, "18": 9, "19": 2},
        "complaints_by_day_of_week": {"Monday": 2, "Friday": 8},
    }, "n_rows": 12, "caveats": []}


def test_complaint_counts_render_as_ints():
    t = template_narration("late_complaint_breakdown", _complaint_result())
    assert "7.0 complaints" not in t
    assert "50.0 orders" not in t
    assert "12 late-delivery complaints in 100 comments" in t
    assert "7 complaints" in t and "50 orders" in t


def test_complaint_rate_never_relabeled_as_late_order_rate():
    t = template_narration("late_complaint_breakdown", _complaint_result()).lower()
    # Complaint shares may be described, but never as a delivery-lateness rate,
    # and never attributed as rider fault.
    assert "late-delivery complaint" in t
    assert "late-order rate" not in t
    assert "late-delivery rate" not in t
    rider_lines = [ln for ln in t.splitlines() if "r1" in ln]
    assert rider_lines and all("late-delivery rate" not in ln for ln in rider_lines)


def test_complaint_answer_leads_with_peak_hour_and_day():
    t = template_narration("late_complaint_breakdown", _complaint_result())
    tl = t.lower()
    assert "18:00" in tl and "friday" in tl
    # direct answer (peak hour/day) comes before supporting zone/branch/rider findings
    assert tl.index("18:00") < tl.index("top zones")
    assert tl.index("friday") < tl.index("top riders")


def _trend_result():
    return {"answer_data": {
        "compared_months": ["May 2026", "June 2026"],
        "reference_date_used": "2026-07-12",
        "min_volume_gate": 20,
        "branches_worsened": [
            {"BranchID": "BR-106", "p90_min_prev": 50.0, "p90_min_last": 80.0,
             "p90_change_min": 30.0, "late_rate_prev": 0.072, "late_rate_last": 0.294,
             "n_last": 51, "n_prev": 60},
            {"BranchID": "BR-025", "p90_min_prev": 40.0, "p90_min_last": 55.0,
             "p90_change_min": 15.0, "late_rate_prev": 0.077, "late_rate_last": 0.273,
             "n_last": 22, "n_prev": 25},
        ],
        "branches_improved": [],
    }, "n_rows": 100, "caveats": []}


def _reasons_result():
    return {"answer_data": {
        "branch": "BR-106",
        "months": ["May 2026", "June 2026"],
        "prev": {"dispatch_min": 10.0, "pickup_min": 5.0, "delivery_min": 40.0,
                 "late_rate_pct": 7.2, "avg_rating": 4.2, "n": 60},
        "last": {"dispatch_min": 25.0, "pickup_min": 6.0, "delivery_min": 55.0,
                 "late_rate_pct": 29.4, "avg_rating": 3.1, "n": 51},
        "top_riders_in_late_orders": {"r1": 5},
        "top_zones_in_late_orders": {"Z1": 8},
    }, "n_rows": 111, "caveats": []}


def _rider_result():
    return {"answer_data": {
        "window": "June 2026", "overall_late_rate_pct": 10.0,
        "direction_requested": "worst", "min_volume_gate": 20,
        "riders_considered": 3,
        "worst_riders": [{"RiderID": "r1", "late_rate_pct": 41.4,
                          "vs_avg_pp": 31.4, "avg_rating": 4.0,
                          "avg_delivery_min": 58.4, "n": 29}],
        "best_riders": [{"RiderID": "r9", "late_rate_pct": 0.0,
                         "vs_avg_pp": -10.0, "avg_rating": 4.5,
                         "avg_delivery_min": 30.0, "n": 40}],
        "single_rider": None},
        "n_rows": 100, "caveats": []}


def _anomaly_result():
    return {"answer_data": {
        "operational_findings": [
            {"type": "branch_late_rate_jump", "branch": "BR-106",
             "detail": "Branch BR-106: late-order rate rose 22.2 points (7.2% -> 29.4%) "
                       "between May 2026 and June 2026, n=51."},
            {"type": "rider_high_late_rate", "rider": "rider_abc",
             "detail": "Rider rider_abc: late-order rate 41.4% vs a 10.0% dataset average, "
                       "over 29 orders."},
            {"type": "branch_rating_drop", "branch": "BR-081",
             "detail": "Branch BR-081: average rating fell from 4.24 to 1.74 "
                       "(May 2026 -> June 2026), n=27."},
        ],
        "data_quality_flags": {"pct_negative_pickup_lag": 21.5,
                               "pct_negative_dispatch_lag": 5.0,
                               "pct_delivery_outliers_excluded": 0.4,
                               "months_with_under_1000_orders": ["2025-07"],
                               "zero_rating_orders": 1339},
        "compared_months": ["May 2026", "June 2026"],
    }, "n_rows": 64619, "caveats": []}


BANNED = ["MIN_VOLUME", "n_last", "late_rate_", "vs_avg", "n=", " p90", "P90",
          "SLA", "threshold", "statistical significance", "rule-based scan",
          "DataFrame", "entity", "late_complaint_breakdown"]


def _all_template_texts():
    from narration import template_narration as _t
    return {
        "branch_delivery_trend": _t("branch_delivery_trend", _trend_result()),
        "branch_worsening_reasons": _t("branch_worsening_reasons", _reasons_result()),
        "late_complaint_breakdown": _t("late_complaint_breakdown", _complaint_result()),
        "rider_performance": _t("rider_performance", _rider_result()),
        "anomaly_scan": _t("anomaly_scan", _anomaly_result()),
    }


def test_no_technical_jargon_or_internals_leak():
    for tool, t in _all_template_texts().items():
        for banned in BANNED:
            assert banned not in t, f"{tool} leaks {banned!r}: {t[:200]}"
        # "pp" as a standalone abbreviation must not appear ("percentage points" is fine)
        import re
        assert not re.search(r"\bpp\b", t), f"{tool} uses 'pp': {t[:200]}"


def test_answers_lead_and_close_with_single_data_note():
    for tool, t in _all_template_texts().items():
        assert t.count("Data note") == 1, f"{tool} must state its data note exactly once"
    # Anomaly scan leads with the bottom line, not methodology
    first = _all_template_texts()["anomaly_scan"].splitlines()
    body = [ln for ln in first if ln.strip() and not ln.startswith("###")][0]
    assert body.startswith("Yes."), body
    # Trend leads with the worst branch and plain percentages
    trend = _all_template_texts()["branch_delivery_trend"]
    assert trend.startswith("BR-106") and "7%" in trend and "29%" in trend


def test_no_causation_or_blame_claims():
    import re
    for tool, t in _all_template_texts().items():
        tl = t.lower()
        assert "the reason is" not in tl
        assert "caused the delays" not in tl
        assert "underperforming because" not in tl
        assert not re.search(r"rider (is|was) (responsible|at fault|to blame)", tl)


def test_no_keyword_matching_claim_remains():
    import tools
    from narration import template_narration as _t
    t = (_t("late_complaint_breakdown", _complaint_result()) + " "
         + " ".join(tools.late_complaint_breakdown.__doc__ or "")).lower()
    assert "keyword" not in t


def test_gemini_evidence_contains_no_raw_comments():
    # Breakdown must aggregate locally: raw comment strings must never reach
    # the narration evidence (and hence never reach Gemini per-comment).
    import json
    from unittest.mock import patch
    import narration as narr
    import tools
    marker = "UNIQUE_MARKER_XYZ_123"
    import pandas as pd
    base = pd.Timestamp("2026-06-15 10:00:00")
    df = pd.DataFrame([dict(
        OrderID="m1", CustomerID="c", CustomerComment=f"Too late {marker}",
        CustomerRatingAverage=2.0, BranchID="BR-01", DeliveryZoneName="Z1",
        RiderID="r1", Amount=10.0, CreatedDate=base, ShiftDate=base.normalize(),
        DeliveryTime=base + pd.Timedelta(minutes=90),
        AddedToTripTime=base + pd.Timedelta(minutes=1),
        PickingUpTime=base + pd.Timedelta(minutes=2))])
    df["CreatedDate"] = pd.to_datetime(df["CreatedDate"])
    for c in ["DeliveryTime", "AddedToTripTime", "PickingUpTime", "ShiftDate"]:
        df[c] = pd.to_datetime(df[c])
    from data_layer import clean_and_derive, flag_late_orders
    df = flag_late_orders(clean_and_derive(df))
    with patch.object(narr, "narrate_with_gemini",
                      side_effect=AssertionError("no Gemini during analytics")):
        res = tools.late_complaint_breakdown(df, min_volume=1)
    assert marker not in json.dumps(res["answer_data"], default=str)
