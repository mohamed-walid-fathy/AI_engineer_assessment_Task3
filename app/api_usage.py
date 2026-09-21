# BEGIN ASSESSMENT API USAGE TRACKING
"""
api_usage.py — ISOLATED assessment-only Gemini API usage/cost tracking.

All pricing and logging lives HERE and nowhere else. The production app
must not depend on this module for correctness: every function fails safe
and callers guard imports with try/except.

To remove tracking before submission, see docs/API_USAGE_REMOVAL.md
(delete this file + listed imports/calls).
"""
from __future__ import annotations
import os
import threading
from datetime import datetime, timezone

# --- Central pricing: ONE place in the whole repo. ---
# Gemini 3.5 Flash Lite pricing. The google-genai SDK does not expose live
# pricing, so these are clearly-marked ESTIMATES. Update them here only.
# Units: USD per 1M tokens.
INPUT_PRICE_PER_MILLION = 0.3   # ESTIMATE for Gemini 3.5 Flash Lite input
OUTPUT_PRICE_PER_MILLION = 2.50  # ESTIMATE for Gemini 3.5 Flash Lite output
PRICING_LABEL = "estimate"
MODEL_FOR_PRICING = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite (estimate)")

_lock = threading.Lock()
_calls: list[dict] = []
_cum_in = 0
_cum_out = 0
_cum_cost = 0.0


def _usage_path() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(here), "api_usage.txt")


def estimate_tokens_fallback(text: str) -> int:
    # Rough fallback ONLY when the SDK gives no usage_metadata.
    # ~4 chars per token. Callers must label this as estimate.
    if not text:
        return 0
    return max(1, len(text) // 4)


def calc_cost(in_tokens: int, out_tokens: int) -> float:
    return (in_tokens / 1_000_000 * INPUT_PRICE_PER_MILLION) + (
        out_tokens / 1_000_000 * OUTPUT_PRICE_PER_MILLION
    )


def log_call(call_type: str, in_tokens: int, out_tokens: int, estimated: bool = False) -> dict:
    """Record one Gemini call. Returns the entry. Also prints + appends to api_usage.txt."""
    global _cum_in, _cum_out, _cum_cost
    cost = calc_cost(in_tokens, out_tokens)
    with _lock:
        _cum_in += in_tokens
        _cum_out += out_tokens
        _cum_cost += cost
        n = len(_calls) + 1
        entry = {
            "n": n,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": call_type,
            "input_tokens": int(in_tokens),
            "output_tokens": int(out_tokens),
            "estimated_cost": round(cost, 6),
            "estimated_tokens": bool(estimated),
            "cum_calls": n,
            "cum_in": _cum_in,
            "cum_out": _cum_out,
            "cum_cost": round(_cum_cost, 6),
        }
        _calls.append(entry)
        tag = " (tokens estimated)" if estimated else ""
        print(
            f"API call {n}  type={call_type:<9} in={in_tokens}  out={out_tokens}  "
            f"cost=${cost:.4f}{tag}",
            flush=True,
        )
        try:
            _rewrite_file_locked()
        except Exception:
            pass
        return entry


def _rewrite_file_locked() -> None:
    path = _usage_path()
    lines = ["Operations Intelligence Assistant - Gemini API Usage", ""]
    for e in _calls:
        lines += [
            f"API call {e['n']}",
            f"type={e['type']}",
            f"timestamp={e['timestamp']}",
            f"input_tokens={e['input_tokens']}",
            f"output_tokens={e['output_tokens']}",
            f"estimated_cost=${e['estimated_cost']:.6f}",
            f"tokens_estimated={e['estimated_tokens']}",
            f"pricing={PRICING_LABEL} (model: {MODEL_FOR_PRICING})",
            "",
        ]
    lines += [
        "TOTAL",
        f"calls={len(_calls)}",
        f"input_tokens={_cum_in}",
        f"output_tokens={_cum_out}",
        f"estimated_cost=${_cum_cost:.6f}",
    ]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def summary_line() -> str:
    with _lock:
        return (
            f"TOTAL       calls={len(_calls)}         "
            f"in={_cum_in}  out={_cum_out}  cost=${_cum_cost:.4f}"
        )


def reset() -> None:
    global _calls, _cum_in, _cum_out, _cum_cost
    with _lock:
        _calls = []
        _cum_in = 0
        _cum_out = 0
        _cum_cost = 0.0
# END ASSESSMENT API USAGE TRACKING
