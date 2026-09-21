"""Local NLP pipeline tests — no Gemini, embedding backend + lexical parity."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

import pytest

from nlp_pipeline import LocalNLPPipeline, get_pipeline, reset_pipeline


def _pipe():
    pipe = get_pipeline()
    if pipe.backend_name != "embedding":
        pytest.skip("embedding backend unavailable; quality assertions need it")
    return pipe


def test_english_late_order_complaint():
    r = _pipe().analyze(["The order arrived two hours late."])[0]
    assert r.late_order_complaint is True
    assert r.complaint_intent == "delivery_delay"
    assert r.lang == "en"


def test_arabic_late_order_complaint():
    r = _pipe().analyze(["الطلب وصل متأخر جدا"])[0]
    assert r.late_order_complaint is True
    assert r.lang == "ar"


def test_negative_but_not_late():
    # Negative sentiment must NOT imply a late complaint.
    r = _pipe().analyze(["The food was terrible but arrived on time."])[0]
    assert r.sentiment == "negative"
    assert r.late_order_complaint is False


def test_late_with_neutral_wording():
    r = _pipe().analyze(["The order delivered after 2 hours"])[0]
    assert r.late_order_complaint is True
    assert r.sentiment == "neutral"


def test_unrelated_rider_complaint_not_late():
    r = _pipe().analyze(["The rider was rude but the food arrived quickly"])[0]
    assert r.late_order_complaint is False
    assert r.complaint_intent == "rider_issue"


def test_food_quality_complaint_not_late():
    r = _pipe().analyze(["The food was cold and tasteless"])[0]
    assert r.late_order_complaint is False
    assert r.complaint_intent == "product_issue"


def test_mixed_language_comment():
    r = _pipe().analyze(["الطلب late جدا"])[0]
    assert r.late_order_complaint is True


def test_empty_comments_safe():
    for t in [None, "", "   ", ".", "10/10"]:
        r = _pipe().analyze([t])[0]
        assert r.sentiment == "neutral"
        assert r.complaint_intent == "none"
        assert r.late_order_complaint is False


def test_batch_cache_and_confidence():
    p = LocalNLPPipeline()
    texts = ["Too late", "Too late", "ممتاز"]
    first = p.analyze(texts)
    stats1 = p.cache_stats()
    second = p.analyze(texts)
    stats2 = p.cache_stats()
    assert [r.late_order_complaint for r in first] == [True, True, False]
    assert second[0] == first[0]  # cached identical
    assert stats2["hits"] > stats1["hits"]
    assert all(0.0 <= r.confidence <= 1.0 for r in first)


def test_thresholds_configurable():
    try:
        strict = LocalNLPPipeline(thresholds={"late": 0.99})
    except Exception:
        pytest.skip("embedding backend unavailable")
        return
    if strict.backend_name != "embedding":
        pytest.skip("embedding backend unavailable")
        return
    assert strict.analyze(["The order arrived two hours late."])[0].late_order_complaint is False


def test_lexical_fallback_same_schema():
    p = LocalNLPPipeline(backend="lexical")
    rs = p.analyze(["Too late", "ممتاز", None])
    assert rs[0].late_order_complaint is True
    assert rs[1].late_order_complaint is False
    assert rs[2].complaint_intent == "none"
    assert all(r.backend == "lexical-fallback" for r in rs)
