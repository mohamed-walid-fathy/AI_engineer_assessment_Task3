# Removing assessment-only API usage tracking

Tracking is isolated so production does not depend on it.

## Delete this file

- `app/api_usage.py` (entire file; marked BEGIN/END ASSESSMENT API USAGE TRACKING)

## Remove these imports

- `app/intent.py`: the `from api_usage import ...` / `from app.api_usage import ...` blocks inside `_gemini_intent` (import + `log_call("intent", ...)` call). Leave routing/validation untouched.
- `app/narration.py`: the `from api_usage import ...` blocks inside `narrate_with_gemini` (import + `log_call("narration", ...)` call). Leave templates untouched.

## Remove these calls

- `log_call("intent", ...)` in `app/intent.py`
- `log_call("narration", ...)` in `app/narration.py`
- Optional: `estimate_tokens_fallback` uses in those two files (only needed for tracking; safe to leave or remove with the blocks above).

## Requirements

- No requirement becomes strictly unnecessary for the app itself (google-genai + python-dotenv are still needed for Gemini). If you also remove Gemini entirely, you may drop `google-genai` and `python-dotenv` from `requirements.txt`.

## Docs / misc

- Delete this file (`docs/API_USAGE_REMOVAL.md`) if desired.
- If your `README.md` still contains an "Assessment-only API usage tracking" section, remove it (the current root `README.md` does not).
- Delete runtime `api_usage.txt` (gitignored).
- Keep `.gitignore` entries for `api_usage.txt` or remove them — your choice.

## Verify afterward

```bash
pip install -r requirements.txt
pytest tests/ -v
streamlit run app/app.py
```

Ask "Who is the worst driver?" — must still route to `rider_performance` via fallback with no key.
