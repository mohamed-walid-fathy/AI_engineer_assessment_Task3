"""
gemini_client.py — single reusable Gemini client (official google-genai SDK).

- Reads GEMINI_API_KEY / GEMINI_MODEL from environment (.env supported).
- Never hard-codes the key, never prints it.
- Returns None when unconfigured so callers fail gracefully to deterministic paths.
"""
from __future__ import annotations
import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

_MODEL_DEFAULT = "gemini-2.5-flash-lite"  # overridden by GEMINI_MODEL env (assessment: 3.5 Flash Lite id)


def model_name() -> str:
    return os.environ.get("GEMINI_MODEL", _MODEL_DEFAULT)


def is_configured() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY"))


def get_client():
    """Return a google.genai Client or None if no key / no SDK."""
    if not is_configured():
        return None
    try:
        from google import genai
        return genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    except Exception:
        return None
