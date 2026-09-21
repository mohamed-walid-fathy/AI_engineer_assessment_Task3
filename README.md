# Operations Intelligence Assistant

COO-facing question-answering assistant for delivery operations — built for **Task 3**. Ask in plain language; get trustworthy, numbers-first answers from your `operations_data_anonymized.xlsx` extract (~64,619 orders, 132 branches, 1,700+ riders).

## What Task 3 Is

Task 3 delivers a decision-support assistant that routes free-text operations questions through strict intent parsing to a single deterministic analytics tool, then narrates the evidence in plain business language. No per-row language-model calls, no invented numbers.

## What Problem It Addresses

Operations leaders need fast, consistent answers to questions like "which branch got worse at delivery last month, and why?", "where do late-delivery complaints cluster?", and "should I be worried about anything?" — without waiting for ad-hoc analysis. The system provides that first reliable read and points to where deeper investigation is warranted.

## How It Works (High Level)

```
Question → Gemini intent parser → strict intent JSON → one pandas tool
  → evidence JSON → Gemini narration (rephrase-only) or deterministic template → answer
```

- Intent parsing and narration are the only places Gemini is used. Both are optional — without a key the app falls back deterministically.
- All numbers come from five fixed analytics functions over the loaded extract.
- Raw customer comments are labelled locally; only small, aggregated evidence ever reaches Gemini.

## Major Components

- **Data layer** — load, clean, flag outliers/negative lags, derive delivery/dispatch/pickup times, branch-relative P90 late definition.
- **Local NLP pipeline** — multilingual embeddings (`paraphrase-multilingual-MiniLM-L12-v2`) + prototype-similarity layer for `sentiment` / `complaint_intent` / `late_order_complaint` (EN + AR, batch + cache, lexical fallback).
- **Five analytics tools** — `branch_delivery_trend`, `branch_worsening_reasons`, `late_complaint_breakdown`, `rider_performance`, `anomaly_scan`.
- **Intent router** — strict-JSON Gemini parser with validation and deterministic rule fallback (driver questions can never reach the generic scan).
- **Narration** — deterministic templates with an optional Gemini rephrase-only pass; single plain-language Data Note per answer.
- **Streamlit app** — Ask button, answer, evidence panel, and technical details.

## Technologies

Python, pandas, Streamlit, `sentence-transformers` / `transformers` / `torchvision`, `google-genai` (Gemini), `python-dotenv`, `openpyxl`, pytest.

## Repository Structure

```
app/
  app.py               Streamlit entry point (streamlit run app/app.py)
  data_layer.py        Load/clean, ASSUMPTIONS, branch P90 late
  nlp_pipeline.py      Local comment labels (singleton, batch, cache)
  nlp_prototypes.py    Model id, thresholds, EN+AR prototype phrases
  tools.py             5 deterministic analytics functions (numbers only)
  gemini_client.py     Single google-genai client, dotenv, no hard-coded key
  intent.py            Gemini JSON parser + validation + rule fallback + route()
  narration.py         Gemini rephrase-only + deterministic templates
  api_usage.py         Assessment-only cost log (removable; see docs/API_USAGE_REMOVAL.md)
data/
  .gitkeep             Place operations_data_anonymized.xlsx here (or set OPS_DATA_PATH)
tests/
  test_metrics.py | test_intent.py | test_narration.py | test_nlp.py
docs/
  API_USAGE_REMOVAL.md   How to strip assessment tracking
```

## Documentation

| Document | For | Content |
|---|---|---|
| `setup.md` | Anyone cloning the repo | Clone, env, install, keys, data placement, run, tests (Windows + macOS/Linux) |
| `assumptions&notes.md` | Evaluators, analysts | All material assumptions, data caveats, and interpretation notes |
| `COO_doc.md` | COO / non-technical leader | What it does, how to ask, what to trust, what not to use it for |
| `to_engineering_team.md` | Engineering | Architecture, data pipeline, deterministic vs LLM split, Gemini integration, reliability, testing, security, privacy, failure modes, production readiness |
| `docs/API_USAGE_REMOVAL.md` | Engineering | Remove the assessment-only `api_usage.py` tracking |
| `docs/for_the_coo.md`, `docs/for_engineering.md` | Reference | Earlier handover notes (superseded by root docs but kept for context) |

## Current Status

Task 3 is functionally complete and tested. The application runs locally via `streamlit run app/app.py`, routes all five question classes, and passes the test suite (`pytest tests/ -v`) without live API calls. It is a working decision-support prototype, not yet production-hardened — see `to_engineering_team.md` for what remains before a real deployment.
