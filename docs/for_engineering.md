# Engineering Handover

> Note: The canonical engineering handover is now `to_engineering_team.md` at the repository root. This file is kept for reference and summarises the same system.

## Architecture

`question -> intent.route() -> ONE of 5 tools in tools.py -> evidence JSON -> narration.narrate() -> UI`

- `app/gemini_client.py`: single `google.genai.Client`, dotenv, `GEMINI_API_KEY` / `GEMINI_MODEL`, `None` when unconfigured. Key never logged.
- `app/intent.py`: Gemini strict-JSON parser (`temperature=0`, `response_mime_type=json`), schema `{tool, window, direction, top_n, rider_id, branch_id}`, `validate_intent()`, deterministic `rule_based_intent()` fallback, safety override blocking driver -> `anomaly_scan`. `route()` returns `(tool, kwargs, gemini|rules|out_of_scope)`.
- `app/nlp_pipeline.py` (+ config `app/nlp_prototypes.py`): local multilingual comment labels. Pretrained `paraphrase-multilingual-MiniLM-L12-v2` embeddings + prototype-similarity layer (no fine-tuning — no reliable labels). Independent `sentiment` / `complaint_intent` / `late_order_complaint` signals; singleton load, batch + unique-text cache, lexical fallback. Text in, labels out — never counts.
- `app/tools.py`: the only numbers source. Branch P90 late, 1440-minute outlier cap, negative-lag exclusion, `MIN_VOLUME=20`, last-complete-month windows. Comment aggregations group NLP labels with unchanged population/denominator logic (rates per 100 orders; explicit `metric_definitions` in evidence).
- `app/narration.py`: `template_narration()` always available; `narrate_with_gemini()` rephrases evidence only (max ~180 words, no new numbers, association language, no disciplinary advice). Falls back to template.
- `app/api_usage.py`: isolated assessment tracking (see `docs/API_USAGE_REMOVAL.md`). App works if deleted.
- `app/app.py`: Streamlit Ask flow, answer (closed by narration's single data note) + collapsed evidence JSON + Technical details expander. Raw technical caveats are intentionally not shown verbatim to the COO.

Never: full rows to LLM, per-row calls, agents, LangChain, vectors, or microservices.

## Fallback / Validation / Testing

- Missing key, timeout, invalid JSON, unknown tool -> rules. 43+ tests (`pytest tests/ -v`), mocked Gemini, no live calls. Covers NLP (EN/AR/mixed/empty/cache/thresholds), aggregations + volume gate, metric separation, narration labels, 5 routes, failure + invalid fallback, analytics-as-truth, no raw comments to Gemini.
- Not tested: Streamlit UI, live Gemini paths (by design), real-file value regression (add a snapshot test that freezes branch/rider aggregates).

## Security / Key Handling

`.env` is gitignored; `.env.example` contains only key names. No key appears in code, logs, or `api_usage.txt`. Raw comments never leave the process — only aggregate evidence reaches Gemini (2 calls per question at most: intent + narration; structurally guaranteed because per-comment classification is local).

## Observability / Cost

Per-call terminal line `API call N type=intent|narration in=X out=Y cost=$Z`, `TOTAL` line, plus `api_usage.txt` (gitignored). Pricing is centralised in `api_usage.py` (`INPUT/OUTPUT_PRICE_PER_MILLION`, `ESTIMATE` label). Uses `usage_metadata` when present, otherwise a `len/4` estimate labelled as such.

## Data Quality / Scale Gaps

No SLA (relative late); `0.0` rating ambiguous; 132 vs ~120 branches; uneven months; pickup truncation. 64k rows in-memory pandas is fine; move to DuckDB/warehouse past millions; add auth/rate-limit; resolve sampler vs source gap before month-over-month decisions.

See `assumptions&notes.md` for full assumptions and `setup.md` for run instructions.
