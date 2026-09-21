"""Gemini intent/narration tests — all mocked, no live API, no key needed."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

from unittest.mock import patch, MagicMock
import intent


def test_gemini_success_routes_driver():
    fake = {"tool": "rider_performance", "window": "last_month", "direction": "worst",
            "top_n": 5, "rider_id": None, "branch_id": None}
    with patch.object(intent, "_gemini_intent", return_value=fake):
        tool, kwargs, method = intent.route("Who is the worst driver?")
        assert tool == "rider_performance"
        assert method == "gemini"
        assert kwargs["direction"] == "worst"


def test_gemini_failure_falls_back():
    with patch.object(intent, "_gemini_intent", return_value=None):
        tool, kwargs, method = intent.route("Who is the worst driver?")
        assert tool == "rider_performance"
        assert method == "rules"
        assert kwargs["direction"] == "worst"
        assert kwargs["window"] == "last_month"


def test_invalid_intent_rejected():
    assert intent.validate_intent({"tool": "nope"}) is None
    assert intent.validate_intent({"tool": "rider_performance", "window": "never",
                                   "direction": "sideways", "top_n": 999,
                                   "rider_id": "invented!", "branch_id": "XX"}) is not None
    v = intent.validate_intent({"tool": "rider_performance", "window": "never",
                                "direction": "sideways", "top_n": 999,
                                "rider_id": "invented!", "branch_id": "XX"})
    assert v["window"] == "last_month" and v["rider_id"] is None


def test_driver_safety_override():
    # Even if Gemini wrongly says anomaly_scan for a driver question, route() corrects it.
    fake = {"tool": "anomaly_scan", "window": "last_month", "direction": "worst",
            "top_n": 5, "rider_id": None, "branch_id": None}
    with patch.object(intent, "_gemini_intent", return_value=fake):
        tool, kwargs, method = intent.route("Who is the worst driver?")
        assert tool == "rider_performance"


def test_narration_falls_back_without_key():
    from narration import narrate
    import narration as narr
    with patch.object(narr, "narrate_with_gemini", return_value=(None, {})):
        res = {"answer_data": {"window": "June 2026", "overall_late_rate_pct": 10.0,
                               "direction_requested": "worst", "min_volume_gate": 20,
                               "riders_considered": 3,
                               "worst_riders": [{"RiderID": "r1", "late_rate_pct": 40.0,
                                                 "vs_avg_pp": 30.0, "avg_rating": 4.0,
                                                 "avg_delivery_min": 60.0, "n": 25}],
                               "best_riders": [], "single_rider": None},
               "n_rows": 100, "caveats": []}
        text, method = narrate("rider_performance", res, use_gemini=True)
        assert method == "template" and "r1" in text
