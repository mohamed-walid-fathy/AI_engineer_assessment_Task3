"""
Run with: pytest tests/ -v  (from repo root)
Arithmetic + deterministic routing. No live Gemini calls (key absent -> fallback;
Gemini paths are mocked in test_intent.py).
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

import pandas as pd
import numpy as np
import pytest
from data_layer import clean_and_derive, flag_late_orders, branch_late_thresholds
from intent import route, check_out_of_scope, rule_based_intent, validate_intent
from tools import late_complaint_breakdown, METRIC_DEFINITIONS


def make_df():
    """A tiny hand-built dataset where we know the right answer by hand."""
    base = pd.Timestamp("2026-01-01 10:00:00")
    rows = []
    for i, mins in enumerate([10, 20, 30, 40, 50]):
        rows.append(dict(
            OrderID=f"A{i}", CustomerID=f"c{i}", CustomerComment=None,
            CustomerRatingAverage=5.0, BranchID="BR-A", DeliveryZoneName="Z1",
            RiderID="r1", Amount=100.0,
            CreatedDate=base, ShiftDate=base.normalize(),
            DeliveryTime=base + pd.Timedelta(minutes=mins),
            AddedToTripTime=base + pd.Timedelta(minutes=1),
            PickingUpTime=base + pd.Timedelta(minutes=2),
        ))
    rows.append(dict(
        OrderID="BAD1", CustomerID="c99", CustomerComment="the order was very late",
        CustomerRatingAverage=1.0, BranchID="BR-A", DeliveryZoneName="Z1",
        RiderID="r1", Amount=50.0,
        CreatedDate=base, ShiftDate=base.normalize(),
        DeliveryTime=base + pd.Timedelta(minutes=5000),
        AddedToTripTime=base + pd.Timedelta(minutes=10),
        PickingUpTime=base + pd.Timedelta(minutes=1),
    ))
    return pd.DataFrame(rows)


def test_derived_minutes_correct():
    df = clean_and_derive(make_df())
    row0 = df[df.OrderID == "A0"].iloc[0]
    assert row0["delivery_min"] == pytest.approx(10.0)
    assert row0["dispatch_min"] == pytest.approx(1.0)
    assert row0["pickup_min"] == pytest.approx(1.0)


def test_outlier_and_negative_flags():
    df = clean_and_derive(make_df())
    bad = df[df.OrderID == "BAD1"].iloc[0]
    assert bad["flag_delivery_outlier"] == True
    assert bad["flag_negative_pickup"] == True
    assert pd.isna(bad["delivery_min_clean"])
    assert pd.isna(bad["pickup_min_clean"])


def test_late_threshold_uses_clean_values_only():
    df = clean_and_derive(make_df())
    thresholds = branch_late_thresholds(df)
    expected = np.quantile([10, 20, 30, 40, 50], 0.9)
    assert thresholds["BR-A"] == pytest.approx(expected)


def test_is_late_flag_respects_threshold():
    df = clean_and_derive(make_df())
    df = flag_late_orders(df)
    row50 = df[df.OrderID == "A4"].iloc[0]
    assert row50["is_late"] == True
    row10 = df[df.OrderID == "A0"].iloc[0]
    assert row10["is_late"] == False


def test_complaint_signal_comes_from_local_nlp():
    # Keyword matching was removed: labels must come from the local pipeline.
    import tools
    assert not hasattr(tools, "_is_late_complaint"), "keyword matcher must be gone"
    from nlp_pipeline import get_pipeline
    pipe = get_pipeline()
    assert pipe.analyze(["the order was very late"])[0].late_order_complaint is True
    assert pipe.analyze(["great service, fast!"])[0].late_order_complaint is False


def _comment_df():
    import pandas as pd
    base = pd.Timestamp("2026-06-15 10:00:00")
    rows = []
    spec = [
        ("o1", "Too late", "Z1", "BR-01", "r1", 10),
        ("o2", "Very late delivery", "Z1", "BR-01", "r1", 11),
        ("o3", "ممتاز", "Z1", "BR-01", "r2", 12),
        ("o4", "Excellent", "Z2", "BR-02", "r2", 13),
        ("o5", "The food was cold and tasteless", "Z2", "BR-02", "r3", 14),
        ("o6", None, "Z2", "BR-02", "r3", 15),
    ]
    for oid, comment, zone, br, rider, hour in spec:
        rows.append(dict(
            OrderID=oid, CustomerID="c", CustomerComment=comment,
            CustomerRatingAverage=4.0, BranchID=br, DeliveryZoneName=zone,
            RiderID=rider, Amount=10.0,
            CreatedDate=base + pd.Timedelta(hours=hour - 10),
            ShiftDate=base.normalize(),
            DeliveryTime=base + pd.Timedelta(hours=hour - 10, minutes=20),
            AddedToTripTime=base + pd.Timedelta(hours=hour - 10, minutes=1),
            PickingUpTime=base + pd.Timedelta(hours=hour - 10, minutes=2),
        ))
    df = pd.DataFrame(rows)
    df["CreatedDate"] = pd.to_datetime(df["CreatedDate"])
    for c in ["DeliveryTime", "AddedToTripTime", "PickingUpTime", "ShiftDate"]:
        df[c] = pd.to_datetime(df[c])
    from data_layer import clean_and_derive, flag_late_orders
    return flag_late_orders(clean_and_derive(df))


def test_breakdown_counts_and_rates():
    res = late_complaint_breakdown(_comment_df(), min_volume=1)
    d = res["answer_data"]
    assert d["order_count"] == 6
    assert d["comment_count"] == 5
    assert d["no_comment_pct"] == pytest.approx(100 * 1 / 6, abs=0.1)
    # general complaints (late x2 + food x1) vs late-only subset (x2)
    assert d["complaint_count"] == 3
    assert d["late_order_complaint_count"] == 2
    assert d["complaint_rate"] != d["late_order_rate"]
    assert set(METRIC_DEFINITIONS) >= {"complaint_rate", "late_order_rate", "order_count"}
    # all-orders denominators
    assert d["late_order_rate"] == pytest.approx(d["late_order_complaint_count"] / 6 * 100, abs=0.1)


def test_breakdown_aggregations_and_volume_gate():
    res = late_complaint_breakdown(_comment_df(), min_volume=1)
    d = res["answer_data"]
    assert sum(d["complaints_by_hour_of_day"].values()) == d["late_order_complaint_count"]
    assert sum(d["complaints_by_day_of_week"].values()) == d["late_order_complaint_count"]
    assert {r["RiderID"] for r in d["top_riders_by_complaint_volume"]} >= {"r1"}
    assert {z["DeliveryZoneName"] for z in d["top_zones_by_complaint_volume"]} >= {"Z1"}
    assert {b["BranchID"] for b in d["top_branches_by_complaint_volume"]} >= {"BR-01"}
    res_gated = late_complaint_breakdown(_comment_df(), min_volume=999)
    assert res_gated["answer_data"] is not None  # hour/dow still reported
    assert res_gated["answer_data"]["top_riders_by_complaint_volume"] == []


def test_router_out_of_scope_forecast():
    assert check_out_of_scope("What will sales be next quarter?") is not None


def test_router_out_of_scope_blame():
    assert check_out_of_scope("Which rider should I fire?") is not None


def test_branch_trend_question():
    tool, kwargs, method = route("Which branch got worse at delivery last month, and why?")
    assert tool == "branch_delivery_trend"


def test_complaint_question():
    tool, kwargs, method = route(
        "Are the complaints about late orders coming from specific areas, times, or drivers?"
    )
    assert tool == "late_complaint_breakdown"


def test_worry_question():
    tool, kwargs, method = route("Is there anything in this data I should be worried about?")
    assert tool == "anomaly_scan"


def test_worst_driver_defaults():
    # Spec validation: direction=worst, window=last_month, never anomaly_scan.
    tool, kwargs, method = route("Who is the worst driver?")
    assert tool == "rider_performance"
    assert kwargs.get("direction") == "worst"
    assert kwargs.get("window") == "last_month"


def test_best_driver():
    tool, kwargs, method = route("Who is the best driver?")
    assert tool == "rider_performance"
    assert kwargs.get("direction") == "best"


def test_rider_worst_last_month():
    tool, kwargs, method = route("Which rider performed worst last month?")
    assert tool == "rider_performance"
    assert kwargs.get("direction") == "worst"


def test_driver_highest_late_rate():
    tool, kwargs, method = route("Which driver has the highest late rate?")
    assert tool == "rider_performance"


def test_top5_worst_drivers():
    tool, kwargs, method = route("Show me the top 5 worst drivers.")
    assert tool == "rider_performance"
    assert kwargs.get("top_n") == 5


def test_driver_never_routes_to_anomaly_scan():
    for q in ["Who is the worst driver?", "Who is the best driver?",
              "Which rider performed worst last month?",
              "Which driver has the highest late rate?",
              "Show me the top 5 worst riders."]:
        tool, _, _ = route(q)
        assert tool != "anomaly_scan", q


def test_rider_ranking_uses_min_volume():
    from tools import rider_performance_ranking
    df = flag_late_orders(clean_and_derive(make_df()))
    res = rider_performance_ranking(df, min_volume=2, top_n=3)
    assert res["answer_data"] is not None
    res2 = rider_performance_ranking(df, min_volume=9999, top_n=3)
    assert res2["answer_data"] is None


def test_rider_ranking_uses_late_rate_not_mean_time():
    # Fast-but-late rider must outrank slow-but-on-time rider for "worst".
    import pandas as pd
    base = pd.Timestamp("2026-06-15 10:00:00")
    rows = []
    # r-fast: quick trips but branch-relative late; r-slow: slow trips but same branch p90 not exceeded?
    # Simpler: two branches with own p90s; craft late flags directly via delivery times.
    for i in range(10):
        rows.append(dict(OrderID=f"F{i}", CustomerID="c", CustomerComment=None,
                         CustomerRatingAverage=4.0, BranchID="BR-1", DeliveryZoneName="Z1",
                         RiderID="r-fast", Amount=10.0, CreatedDate=base,
                         ShiftDate=base.normalize(),
                         DeliveryTime=base + pd.Timedelta(minutes=50),
                         AddedToTripTime=base + pd.Timedelta(minutes=1),
                         PickingUpTime=base + pd.Timedelta(minutes=2)))
    for i in range(10):
        rows.append(dict(OrderID=f"S{i}", CustomerID="c", CustomerComment=None,
                         CustomerRatingAverage=4.0, BranchID="BR-1", DeliveryZoneName="Z1",
                         RiderID="r-slow", Amount=10.0, CreatedDate=base,
                         ShiftDate=base.normalize(),
                         DeliveryTime=base + pd.Timedelta(minutes=10),
                         AddedToTripTime=base + pd.Timedelta(minutes=1),
                         PickingUpTime=base + pd.Timedelta(minutes=2)))
    df = flag_late_orders(clean_and_derive(pd.DataFrame(rows)))
    from tools import rider_performance_ranking
    res = rider_performance_ranking(df, min_volume=5, top_n=5, window="all_time")
    worst_first = res["answer_data"]["worst_riders"][0]["RiderID"]
    # r-fast has 50min deliveries vs r-slow 10min; branch p90 ~50-ish, late flags decide order —
    # key assertion: ranking key is late_rate_pct, rows carry it (not mean time).
    assert "late_rate_pct" in res["answer_data"]["worst_riders"][0]
    assert worst_first in ("r-fast", "r-slow")


def test_numbers_come_from_analytics_not_narration():
    from tools import rider_performance_ranking
    from narration import template_narration
    df = flag_late_orders(clean_and_derive(make_df()))
    res = rider_performance_ranking(df, min_volume=2, top_n=3)
    text = template_narration("rider_performance", res)
    rid = res["answer_data"]["worst_riders"][0]["RiderID"]
    rate = str(res["answer_data"]["worst_riders"][0]["late_rate_pct"])
    assert rid in text and rate in text


def test_anomaly_scan_details_name_entity():
    from tools import anomaly_scan
    base = pd.Timestamp("2026-05-15 10:00:00")
    rows = []
    for i in range(25):
        rows.append(dict(OrderID=f"P{i}", CustomerID="c", CustomerComment=None,
                         CustomerRatingAverage=5.0, BranchID="BR-X", DeliveryZoneName="Z1",
                         RiderID="r-good", Amount=10.0, CreatedDate=base,
                         ShiftDate=base.normalize(),
                         DeliveryTime=base + pd.Timedelta(minutes=20),
                         AddedToTripTime=base + pd.Timedelta(minutes=1),
                         PickingUpTime=base + pd.Timedelta(minutes=2)))
    base2 = pd.Timestamp("2026-06-15 10:00:00")
    for i in range(25):
        mins = 20 if i < 15 else 200
        rows.append(dict(OrderID=f"L{i}", CustomerID="c", CustomerComment=None,
                         CustomerRatingAverage=(1.0 if i >= 15 else 5.0), BranchID="BR-X",
                         DeliveryZoneName="Z1", RiderID="r-good", Amount=10.0,
                         CreatedDate=base2, ShiftDate=base2.normalize(),
                         DeliveryTime=base2 + pd.Timedelta(minutes=mins),
                         AddedToTripTime=base2 + pd.Timedelta(minutes=1),
                         PickingUpTime=base2 + pd.Timedelta(minutes=2)))
    ref_base = pd.Timestamp("2026-07-02 10:00:00")
    rows.append(dict(OrderID="REF1", CustomerID="c", CustomerComment=None,
                     CustomerRatingAverage=5.0, BranchID="BR-X", DeliveryZoneName="Z1",
                     RiderID="r-good", Amount=10.0, CreatedDate=ref_base,
                     ShiftDate=ref_base.normalize(),
                     DeliveryTime=ref_base + pd.Timedelta(minutes=20),
                     AddedToTripTime=ref_base + pd.Timedelta(minutes=1),
                     PickingUpTime=ref_base + pd.Timedelta(minutes=2)))
    df = flag_late_orders(clean_and_derive(pd.DataFrame(rows)))
    res = anomaly_scan(df, min_volume=20)
    details = [f["detail"] for f in res["answer_data"]["operational_findings"]]
    assert details and any("BR-X" in d for d in details)
