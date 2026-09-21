"""
nlp_prototypes.py — configuration for the local multilingual NLP pipeline.

Single place for: model id, decision thresholds, and the EN+AR prototype
phrases behind each signal. Phrase lists are transparent heuristics for an
embedding-similarity layer, NOT a trained classifier. Tune thresholds here;
analytics code reads them via nlp_pipeline (never hardcodes its own).
"""
from __future__ import annotations

MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

THRESHOLDS = {
    # late_order_complaint = sim(text, LATE centroid) >= late
    "late": 0.45,
    # complaint_intent = argmax intent centroid sim, accepted only if >= intent
    "intent": 0.40,
    # compliment accepted if sim >= compliment (checked before negativity)
    "compliment": 0.45,
    # sentiment = sign(pos-neg); neutral if abs(margin) < sentiment_margin
    # or max(pos,neg) < sentiment_min
    "sentiment_margin": 0.06,
    "sentiment_min": 0.15,
}

# Explicit lateness expressions only (narrow). Kept separate from broad
# delay so late_order_complaint stays independent of sentiment/intent.
LATE_PROTOTYPES = [
    "the order arrived late",
    "delivery was two hours late",
    "very late delivery",
    "the order was delayed",
    "arrived after two hours",
    "late delivery, took hours",
    "الطلب وصل متأخر",
    "التوصيل اتأخر",
    "تأخير كبير في التوصيل",
    "الاوردر وصل متأخر",
    "وصل بعد ساعتين",
    "التوصيل متأخر جدا",
    # Egyptian-dialect phrasings observed in this dataset (transparent,
    # documented; they lift genuine dialectal late reports above threshold)
    "الاوردر اتأخر جدا",
    "الطلب بيتأخر جدا",
    "تاخير فى التوصيل",
    "اتأخر في التوصيل",
    "my orders have been delayed by two hours",
    "order delayed over the normal time",
    # Short canonical forms (also frequent verbatims in this dataset).
    # These keep the lexical fallback honest on terse comments.
    "too late",
    "very late",
    "متأخر",
    "تأخير",
]

# Broad slowness (no explicit lateness claim). Feeds delivery_delay intent.
DELAY_PROTOTYPES = [
    "delivery took too long",
    "slow delivery service",
    "I waited a very long time",
    "the delivery is slow",
    "التوصيل بطيء",
    "استنيت كتير",
    "الاوردر خد وقت كبير",
    "خدمة بطيئة",
    "استنيت الاوردر ساعتين",
    "I waited an hour for a reply",
]

POS_PROTOTYPES = [
    "excellent service",
    "great service thank you",
    "perfect fast delivery",
    "very good service",
    "ممتاز",
    "خدمة ممتازة",
    "شكرا جزيلا",
    "رائع جدا",
]

NEG_PROTOTYPES = [
    "very bad service",
    "terrible experience",
    "awful service",
    "worst experience ever",
    "سيئ جدا",
    "خدمة سيئة",
    "زفت",
    "أسوأ تجربة",
]

# Intent prototype sets. delivery_delay reuses LATE+DELAY (explicit+implicit).
# Only intents useful for this app's analytics are listed.
INTENT_PROTOTYPES: dict[str, list[str]] = {
    "delivery_delay": LATE_PROTOTYPES + DELAY_PROTOTYPES,
    "product_issue": [
        "the food was cold and tasteless",
        "the product quality was bad",
        "expired product",
        "the medicine was damaged",
        "الأكل كان بارد",
        "جودة سيئة",
        "منتج منتهي الصلاحية",
        "الدواء تالف",
    ],
    "missing_wrong_item": [
        "items were missing from my order",
        "received the wrong item",
        "incomplete order",
        "الطلب ناقص",
        "وصلني صنف غلط",
        "في أصناف ناقصة",
    ],
    "rider_issue": [
        "the rider was rude",
        "the delivery man refused to come up",
        "rude courier behavior",
        "الدليفري اسلوبه سيء",
        "الطيار كان سيئا",
        "مندوب التوصيل رفض",
    ],
    "service_issue": [
        "customer service never answers",
        "no one follows up on complaints",
        "bad customer service",
        "خدمة العملاء لا ترد",
        "محدش بيرد",
        "عدم اهتمام بالشكوى",
    ],
    "compliment": [
        "thank you excellent service",
        "perfect service highly recommended",
        "شكرا خدمة ممتازة",
        "ممتاز جدا",
    ] + POS_PROTOTYPES,
}
