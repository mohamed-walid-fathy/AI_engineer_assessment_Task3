"""
nlp_pipeline.py — reusable local multilingual NLP pipeline for customer text.

Produces three INDEPENDENT signals per comment (never derived from each other):
  sentiment            positive | negative | neutral   (+ sentiment_score)
  complaint_intent     delivery_delay | product_issue | missing_wrong_item |
                       rider_issue | service_issue | compliment |
                       general_complaint | none       (+ intent_score)
  late_order_complaint True | False                    (+ late_score, confidence)

Backend: pretrained multilingual sentence embeddings
(paraphrase-multilingual-MiniLM-L12-v2, EN+AR) + transparent prototype-
similarity layer. No fine-tuning: the dataset has no reliable labels, so a
supervised claim would be dishonest. One model load per process (singleton),
batch inference, per-unique-text cache, empty/null safe, graceful
lexical fallback if the embedding model cannot load.

Analytics owns all numbers; this module only labels text.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, asdict

try:
    from nlp_prototypes import (
        MODEL_NAME, THRESHOLDS, LATE_PROTOTYPES, POS_PROTOTYPES,
        NEG_PROTOTYPES, INTENT_PROTOTYPES,
    )
except ImportError:  # `streamlit run app/app.py` from repo root
    from app.nlp_prototypes import (
        MODEL_NAME, THRESHOLDS, LATE_PROTOTYPES, POS_PROTOTYPES,
        NEG_PROTOTYPES, INTENT_PROTOTYPES,
    )


@dataclass
class NLPResult:
    text: str
    lang: str | None
    sentiment: str
    sentiment_score: float
    complaint_intent: str
    intent_score: float
    late_order_complaint: bool
    late_score: float
    confidence: float
    backend: str

    def to_dict(self) -> dict:
        return asdict(self)


def detect_lang(s: str | None) -> str | None:
    if not isinstance(s, str) or not s.strip():
        return None
    arabic = sum("\u0600" <= ch <= "\u06FF" for ch in s)
    return "ar" if arabic > len(s) * 0.2 else "en"


_WORD_RE = re.compile(r"[\w\u0600-\u06FF]+", re.UNICODE)
_LETTER_RE = re.compile(r"[A-Za-z\u0600-\u06FF]")


def _has_letters(text: str) -> bool:
    """Digit/punctuation-only comments (".", "10/10") carry no signal."""
    return bool(_LETTER_RE.search(text))


class _EmbeddingBackend:
    """Prototype-similarity over multilingual sentence embeddings."""

    name = "embedding"

    def __init__(self, model_name: str = MODEL_NAME, device: str | None = None):
        from sentence_transformers import SentenceTransformer
        import torch

        self.torch = torch
        self.model = SentenceTransformer(model_name, device=device)
        self.model.max_seq_length = min(getattr(self.model, "max_seq_length", 128), 256)
        with torch.inference_mode():
            self._late = self._centroid(LATE_PROTOTYPES)
            self._pos = self._centroid(POS_PROTOTYPES)
            self._neg = self._centroid(NEG_PROTOTYPES)
            self._intents = {k: self._centroid(v) for k, v in INTENT_PROTOTYPES.items()}

    def _centroid(self, phrases: list[str]):
        import torch.nn.functional as F
        e = self.model.encode(phrases, convert_to_tensor=True, show_progress_bar=False)
        e = F.normalize(e, dim=1)
        return F.normalize(e.mean(dim=0), dim=0)

    def score(self, texts: list[str]) -> list[dict]:
        import torch.nn.functional as F
        e = self.model.encode(texts, convert_to_tensor=True, show_progress_bar=False,
                              batch_size=128)
        e = F.normalize(e, dim=0 if e.dim() == 1 else 1)
        if e.dim() == 1:
            e = e.unsqueeze(0)
        out = []
        for i in range(e.shape[0]):
            v = e[i]
            late = float(v @ self._late)
            pos = float(v @ self._pos)
            neg = float(v @ self._neg)
            intents = {k: float(v @ c) for k, c in self._intents.items()}
            out.append({"late": late, "pos": pos, "neg": neg, "intents": intents})
        return out


class _LexicalFallback:
    """Clearly-labeled fallback: normalized phrase matching. Used only when the
    embedding model cannot load. Same interface, lower quality."""

    name = "lexical-fallback"

    def __init__(self, *a, **k):
        self._late = LATE_PROTOTYPES
        self._pos = POS_PROTOTYPES
        self._neg = NEG_PROTOTYPES
        self._intents = INTENT_PROTOTYPES

    @staticmethod
    def _norm(s: str) -> str:
        return " ".join(_WORD_RE.findall(s.lower()))

    def _hit(self, norm: str, phrases: list[str]) -> float:
        if not norm:
            return 0.0
        hits = sum(1 for p in phrases if self._norm(p) and self._norm(p) in norm)
        return min(1.0, hits / 2.0 + (0.5 if hits else 0.0))

    def score(self, texts: list[str]) -> list[dict]:
        out = []
        for t in texts:
            n = self._norm(t if isinstance(t, str) else "")
            out.append({
                "late": self._hit(n, self._late),
                "pos": self._hit(n, self._pos),
                "neg": self._hit(n, self._neg),
                "intents": {k: self._hit(n, v) for k, v in self._intents.items()},
            })
        return out


class LocalNLPPipeline:
    """Batch + cached multilingual comment classifier. Load once, reuse."""

    def __init__(self, thresholds: dict | None = None, backend: str = "auto"):
        self.thresholds = dict(THRESHOLDS)
        if thresholds:
            self.thresholds.update(thresholds)
        self._cache: dict[str, NLPResult] = {}
        self.cache_hits = 0
        self.cache_misses = 0
        if backend == "lexical":
            self.backend = _LexicalFallback()
        elif backend == "embedding":
            self.backend = _EmbeddingBackend()
        else:  # auto: embedding preferred, lexical on failure
            try:
                self.backend = _EmbeddingBackend()
            except Exception as e:
                import sys
                print(f"[nlp_pipeline] WARNING: embedding backend failed ({e}); "
                      f"using lexical fallback with reduced quality.",
                      file=sys.stderr)
                self.backend = _LexicalFallback()

    @property
    def backend_name(self) -> str:
        return self.backend.name

    @staticmethod
    def _key(text) -> str | None:
        if not isinstance(text, str) or not text.strip():
            return None
        return text.strip()[:1000]

    def _decide(self, text: str, s: dict) -> NLPResult:
        th = self.thresholds
        pos, neg = s["pos"], s["neg"]
        margin = pos - neg
        if abs(margin) < th["sentiment_margin"] or max(pos, neg) < th["sentiment_min"]:
            sentiment, s_score = "neutral", 0.0
        elif margin > 0:
            sentiment, s_score = "positive", round(min(1.0, margin + 0.5), 3)
        else:
            sentiment, s_score = "negative", round(min(1.0, -margin + 0.5), 3)

        ranked = sorted(s["intents"].items(), key=lambda kv: kv[1], reverse=True)
        top_intent, top_score = ranked[0]
        if top_score >= th["compliment"] and top_intent == "compliment":
            intent, i_score = "compliment", round(top_score, 3)
        elif top_score >= th["intent"] and top_intent != "compliment":
            intent, i_score = top_intent, round(top_score, 3)
        elif top_intent == "compliment" and top_score >= th["intent"]:
            intent, i_score = "compliment", round(top_score, 3)
        elif sentiment == "negative":
            intent, i_score = "general_complaint", round(s["neg"], 3)
        elif sentiment == "positive":
            intent, i_score = "compliment", round(s["pos"], 3)
        else:
            intent, i_score = "none", 0.0

        late = bool(s["late"] >= th["late"])
        late_score = round(float(s["late"]), 3)
        confidence = round(late_score if late else (i_score if intent not in ("none",) else s_score), 3)
        return NLPResult(
            text=text if isinstance(text, str) else "",
            lang=detect_lang(text),
            sentiment=sentiment,
            sentiment_score=s_score,
            complaint_intent=intent,
            intent_score=i_score,
            late_order_complaint=late,
            late_score=late_score,
            confidence=confidence,
            backend=self.backend.name,
        )

    def analyze(self, texts: list) -> list[NLPResult]:
        results: list[NLPResult | None] = [None] * len(texts)
        # Deduplicate within this batch too: identical comments are scored once.
        uniq_keys: list[str] = []
        uniq_pos: dict[str, int] = {}
        key_of: list[str | None] = [None] * len(texts)
        for i, t in enumerate(texts):
            key = self._key(t)
            if key is None or not _has_letters(key):
                results[i] = NLPResult("", None, "neutral", 0.0, "none", 0.0,
                                       False, 0.0, 0.0, self.backend.name)
            elif key in self._cache:
                self.cache_hits += 1
                results[i] = self._cache[key]
            else:
                key_of[i] = key
                if key not in uniq_pos:
                    uniq_pos[key] = len(uniq_keys)
                    uniq_keys.append(key)
        if uniq_keys:
            for key, s in zip(uniq_keys, self.backend.score(uniq_keys)):
                self.cache_misses += 1
                self._cache[key] = self._decide(key, s)
            for i, key in enumerate(key_of):
                if results[i] is None and key is not None:
                    results[i] = self._cache[key]
        return results  # type: ignore[return-value]

    def analyze_series(self, series):
        """Label a pandas Series; returns DataFrame aligned to input index."""
        import pandas as pd

        res = self.analyze(list(series))
        return pd.DataFrame([{
            "nlp_sentiment": r.sentiment,
            "nlp_sentiment_score": r.sentiment_score,
            "nlp_complaint_intent": r.complaint_intent,
            "nlp_intent_score": r.intent_score,
            "nlp_late": r.late_order_complaint,
            "nlp_late_score": r.late_score,
            "nlp_confidence": r.confidence,
            "nlp_backend": r.backend,
        } for r in res], index=series.index)

    def cache_stats(self) -> dict:
        total = self.cache_hits + self.cache_misses
        return {"hits": self.cache_hits, "misses": self.cache_misses,
                "unique_cached": len(self._cache),
                "hit_rate": round(self.cache_hits / total, 3) if total else 0.0}


_pipeline: LocalNLPPipeline | None = None


def get_pipeline(**kwargs) -> LocalNLPPipeline:
    """Process-wide singleton: model loads once, reused everywhere."""
    global _pipeline
    if _pipeline is None:
        _pipeline = LocalNLPPipeline(**kwargs)
    return _pipeline


def reset_pipeline() -> None:
    global _pipeline
    _pipeline = None
