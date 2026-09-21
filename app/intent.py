"""
intent.py — Gemini intent parser -> STRICT STRUCTURED INTENT -> tool kwargs.

Architecture: USER QUESTION -> Gemini (JSON only) -> validation -> ONE tool.
Gemini NEVER calculates metrics and NEVER answers the question.

If Gemini is missing/fails/times out/invalid -> deterministic rule fallback.
Fallback MUST handle "Who is the worst driver?" -> rider_performance.
"""
from __future__ import annotations
import json
import re

TOOL_NAMES = [
    "branch_delivery_trend",
    "branch_worsening_reasons",
    "late_complaint_breakdown",
    "rider_performance",
    "anomaly_scan",
]

WINDOWS = {"last_month", "current_month", "all_time"}
DIRECTIONS = {"worst", "best"}

BRANCH_RE = re.compile(r"\bBR-\d{2,3}\b", re.IGNORECASE)
RIDER_RE = re.compile(r"\brider_[a-z0-9]+\b", re.IGNORECASE)
DRIVER_KEYWORDS = ["rider", "driver", "courier", "deliverer", "deliveryman", "delivery man"]
TOP_N_RE = re.compile(r"\btop\s+(\d{1,2})\b", re.IGNORECASE)

OUT_OF_SCOPE_PATTERNS = [
    (r"\b(will|forecast|predict|next (week|month|quarter|year)|going to)\b",
     "This assistant reports on what already happened in the data. It has no "
     "forecasting model, so it can't tell you what will happen next week, "
     "month, or quarter."),
    (r"\b(fire|terminate|discipline|fault of|whose fault|to blame)\b",
     "This assistant can show you patterns (e.g. a rider's late-order rate "
     "relative to others), but it has no context on individual circumstances, "
     "HR history, or root cause — that's not a decision the data alone can "
     "support. Use the numbers as a starting point for a conversation, not a verdict."),
    (r"\bwhy (did|does|is|are).*(revenue|sales|amount|price|cost)\b",
     "This dataset covers delivery operations (timing, ratings, comments) — "
     "it doesn't contain cost structure, pricing decisions, or the broader "
     "business context needed to explain revenue changes."),
]


def check_out_of_scope(question: str) -> str | None:
    q = question.lower()
    for pattern, message in OUT_OF_SCOPE_PATTERNS:
        if re.search(pattern, q):
            return message
    return None


INTENT_SYSTEM = """You are a strict intent parser for an operations assistant. Return STRICT JSON only, no other text.
Schema: {"tool": "branch_delivery_trend | branch_worsening_reasons | late_complaint_breakdown | rider_performance | anomaly_scan", "window": "last_month | current_month | all_time", "direction": "worst | best", "top_n": 5, "rider_id": null, "branch_id": null}
Rules:
- "driver", "rider", "courier" ALWAYS map to tool rider_performance. Never use anomaly_scan for a specific rider/driver question.
- "worst driver", "highest late rate driver", "most late orders driver" -> rider_performance direction worst.
- "best driver" -> rider_performance direction best.
- "Which branch got worse at delivery last month, and why?" -> branch_delivery_trend, window last_month.
- "Why did BR-101 get worse?" -> branch_worsening_reasons with branch_id BR-101.
- Complaints/reviews/comments/sentiment/satisfaction about lateness by area/time/rider/branch -> late_complaint_breakdown (the local NLP pipeline covers sentiment and complaint intent; no per-comment Gemini needed).
- "Anything worried / wrong / flag" overview -> anomaly_scan.
- If no time period specified, window is last_month. If no top N specified, top_n is 5.
- Copy rider_id ONLY if the user literally wrote a rider_xxx token; else null. Same for branch_id with BR-xxx; else null. Never invent IDs.
- Never calculate metrics. Never answer the question. JSON only."""


def _defaults() -> dict:
    return {"tool": "anomaly_scan", "window": "last_month", "direction": "worst",
            "top_n": 5, "rider_id": None, "branch_id": None}


def validate_intent(obj: dict) -> dict | None:
    try:
        if not isinstance(obj, dict):
            return None
        tool = obj.get("tool")
        if tool not in TOOL_NAMES:
            return None
        window = obj.get("window", "last_month")
        if window not in WINDOWS:
            window = "last_month"
        direction = obj.get("direction", "worst")
        if direction not in DIRECTIONS:
            direction = "worst"
        try:
            top_n = max(1, min(20, int(obj.get("top_n", 5))))
        except Exception:
            top_n = 5
        rider_id = obj.get("rider_id")
        if rider_id is not None and not (isinstance(rider_id, str) and RIDER_RE.fullmatch(rider_id.strip())):
            rider_id = None
        branch_id = obj.get("branch_id")
        if branch_id is not None:
            m = BRANCH_RE.search(str(branch_id)) if isinstance(branch_id, str) else None
            branch_id = m.group(0).upper() if m else None
        return {"tool": tool, "window": window, "direction": direction,
                "top_n": top_n, "rider_id": rider_id, "branch_id": branch_id}
    except Exception:
        return None


def _gemini_intent(question: str) -> dict | None:
    """Try one Gemini call. Returns validated intent or None. Logs usage."""
    try:
        from gemini_client import get_client, model_name
    except ImportError:
        try:
            from app.gemini_client import get_client, model_name
        except Exception:
            return None
    client = get_client()
    if client is None:
        return None
    prompt = INTENT_SYSTEM + f"\nUser question: {question}\nJSON:"
    raw_text = ""
    in_tok = out_tok = 0
    estimated = True
    try:
        resp = client.models.generate_content(
            model=model_name(),
            contents=prompt,
            config={"temperature": 0, "response_mime_type": "application/json"},
        )
        raw_text = getattr(resp, "text", "") or ""
        um = getattr(resp, "usage_metadata", None)
        if um is not None:
            in_tok = int(getattr(um, "prompt_token_count", 0) or 0)
            out_tok = int(getattr(um, "candidates_token_count", 0) or 0)
            if in_tok or out_tok:
                estimated = False
        if estimated:
            from api_usage import estimate_tokens_fallback
            in_tok = estimate_tokens_fallback(prompt)
            out_tok = estimate_tokens_fallback(raw_text)
    except Exception:
        return None
    finally:
        try:
            from api_usage import log_call
        except ImportError:
            try:
                from app.api_usage import log_call
            except Exception:
                log_call = None
        if log_call is not None:
            try:
                if not in_tok and not out_tok:
                    from api_usage import estimate_tokens_fallback as _est
                    in_tok, out_tok = _est(prompt), _est(raw_text)
                    estimated = True
                log_call("intent", in_tok, out_tok, estimated=estimated)
            except Exception:
                pass
    # Strip code fences, parse, validate
    try:
        t = raw_text.strip()
        if t.startswith("```"):
            t = re.sub(r"^```(?:json)?\s*", "", t)
            t = re.sub(r"\s*```$", "", t)
        return validate_intent(json.loads(t))
    except Exception:
        return None


def _fallback_kwargs(question: str, q: str) -> dict:
    kw: dict = {"window": "last_month", "direction": "worst", "top_n": 5,
                "rider_id": None, "branch_id": None}
    m = RIDER_RE.search(question)
    if m:
        kw["rider_id"] = m.group(0)
    b = BRANCH_RE.search(question)
    if b:
        kw["branch_id"] = b.group(0).upper()
    tm = TOP_N_RE.search(q)
    if tm:
        try:
            kw["top_n"] = max(1, min(20, int(tm.group(1))))
        except ValueError:
            pass
    if "best" in q and "worst" not in q:
        kw["direction"] = "best"
    if "current month" in q or "this month" in q:
        kw["window"] = "current_month"
    elif "all time" in q or "overall" in q or "whole dataset" in q:
        kw["window"] = "all_time"
    elif "last month" in q:
        kw["window"] = "last_month"
    return kw


def rule_based_intent(question: str) -> dict:
    """Deterministic fallback. Always returns a valid intent. Driver -> rider_performance."""
    q = question.lower()
    fb = _fallback_kwargs(question, q)
    branch_match = BRANCH_RE.search(question)
    if branch_match and any(k in q for k in ["why", "worse", "reason", "what happened"]):
        fb["tool"] = "branch_worsening_reasons"
        fb["branch_id"] = branch_match.group(0).upper()
        return fb
    if any(k in q for k in ["worry", "worried", "concern", "anything i should", "flag", "wrong"]):
        fb["tool"] = "anomaly_scan"
        return fb
    if any(k in q for k in ["complain", "review", "comment", "feedback",
                              "sentiment", "satisf", "unhappy", "happy with"]):
        fb["tool"] = "late_complaint_breakdown"
        return fb
    if (any(k in q for k in ["late order", "late deliver", "sentiment", "satisf"]) and
            any(k in q for k in ["area", "zone", "time", "hour", "where", "specific", "coming from",
                                 "branch", "rider", "driver"])):
        fb["tool"] = "late_complaint_breakdown"
        return fb
    if RIDER_RE.search(question):
        fb["tool"] = "rider_performance"
        return fb
    if any(k in q for k in DRIVER_KEYWORDS):
        fb["tool"] = "rider_performance"
        return fb
    if any(k in q for k in ["worse at delivery", "got worse", "trend", "which branch", "delivery time"]):
        fb["tool"] = "branch_delivery_trend"
        return fb
    fb["tool"] = "anomaly_scan"
    return fb


def intent_to_tool_kwargs(intent: dict) -> tuple[str, dict]:
    tool = intent["tool"]
    if tool == "rider_performance":
        kw: dict = {"window": intent.get("window", "last_month"),
                    "direction": intent.get("direction", "worst"),
                    "top_n": intent.get("top_n", 5)}
        if intent.get("rider_id"):
            kw["rider_id"] = intent["rider_id"]
        return tool, kw
    if tool == "branch_worsening_reasons":
        bid = intent.get("branch_id")
        if not bid:
            # No branch id -> cannot run reasons; fall back to trend overview.
            return "branch_delivery_trend", {}
        return tool, {"branch_id": bid}
    return tool, {}


def route(question: str) -> tuple[str | None, dict, str]:
    """Returns (tool_name, kwargs, method). None = out-of-scope refusal in kwargs['refusal']."""
    oos = check_out_of_scope(question)
    if oos:
        return None, {"refusal": oos}, "out_of_scope"
    intent = _gemini_intent(question)
    if intent is not None:
        tool, kwargs = intent_to_tool_kwargs(intent)
        # Safety: never let a driver question reach the generic scanner.
        if any(k in question.lower() for k in DRIVER_KEYWORDS) and tool == "anomaly_scan":
            fb = rule_based_intent(question)
            return intent_to_tool_kwargs(fb)[0], intent_to_tool_kwargs(fb)[1], "rules"
        return tool, kwargs, "gemini"
    fb = rule_based_intent(question)
    tool, kwargs = intent_to_tool_kwargs(fb)
    return tool, kwargs, "rules"
