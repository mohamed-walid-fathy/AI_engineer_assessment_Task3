# Engineering Handover — Operations Intelligence Assistant

Audience: the engineering team evaluating whether this system could responsibly move toward production. This document describes what exists, what it does, and what would still be needed.

## 1. System Architecture

```
User question (Streamlit)
  -> app/intent.py: route()  ->  Gemini strict-JSON intent  OR  deterministic rule fallback
  -> app/tools.py: ONE of 5 deterministic analytics functions -> evidence JSON {answer_data, caveats, n_rows}
  -> app/narration.py: narrate() -> Gemini rephrase-only (optional) OR deterministic template
  -> app/app.py: Streamlit UI (answer + Data note + Evidence JSON + Technical details)
```

Key invariants:

- **Gemini never calculates metrics.** Only `app/tools.py` (via `pandas`) produces numbers. Gemini receives at most a small, already-aggregated `answer_data` JSON (≤12,000 characters) — never the full 64,619-row dataset.
- **No per-row LLM calls, no agents, no vector DB, no LangChain.** Two Gemini calls at most per question: one for intent (`app/intent.py:122`) and one for narration (`app/narration.py:422`). Both are optional and fail-safe.
- **Single client.** `app/gemini_client.py` creates the only `google.genai.Client` (dotenv, `GEMINI_API_KEY` / `GEMINI_MODEL`). Returns `None` when unconfigured; callers degrade gracefully.
- **Local NLP is separate.** `app/nlp_pipeline.py` (+ `app/nlp_prototypes.py`) labels comments locally with multilingual embeddings before any Gemini call. Its labels are aggregated deterministically in `app/tools.py`; Gemini never sees raw comments.

Component map:

| File | Responsibility |
|---|---|
| `app/data_layer.py` | Load `operations_data_anonymized.xlsx` (sheet `Data`), clean, derive `delivery_min`/`dispatch_min`/`pickup_min`, flags, `is_late`, `ASSUMPTIONS`, `MIN_VOLUME=20`, `OUTLIER_CAP_MINUTES=1440` |
| `app/nlp_pipeline.py` | Singleton `LocalNLPPipeline`: embedding backend (`paraphrase-multilingual-MiniLM-L12-v2`) + prototype-similarity layer, batch + unique-text cache, independent `sentiment`/`complaint_intent`/`late_order_complaint` signals, lexical fallback |
| `app/nlp_prototypes.py` | `MODEL_NAME`, `THRESHOLDS` (`late:0.45`, `intent:0.40`, `compliment:0.45`, `sentiment_margin:0.06`, `sentiment_min:0.15`), EN+AR prototype phrases |
| `app/tools.py` | 5 analytics functions → `TOOLS` dict. Only numbers source. Branch P90 late, outlier/negative handling, window logic, volume gate |
| `app/intent.py` | Gemini strict-JSON parser (`temperature=0`, `response_mime_type=application/json`), `validate_intent()`, `rule_based_intent()` fallback, `check_out_of_scope()`, `intent_to_tool_kwargs()`, safety override blocking driver→`anomaly_scan` |
| `app/narration.py` | `template_narration()` (always) + `narrate_with_gemini()` (rephrase-only). `data_note()`, plain-language rendering, anti-causation/anti-blame rules |
| `app/gemini_client.py` | `get_client()`, `model_name()`, `is_configured()` |
| `app/api_usage.py` | Assessment-only cost logging (isolated, removable per `docs/API_USAGE_REMOVAL.md`) |
| `app/app.py` | Streamlit entry point (`streamlit run app/app.py`), cached `load_clean`, question routing, answer + data note + evidence + technical details |
| `tests/` | 4 files, mocked Gemini, no live API |

## 2. Data Pipeline

**Input data.** `operations_data_anonymized.xlsx`, sheet `Data`, ~64,619 rows, 132 `BranchID`, 1,700+ `RiderID`. Columns used: `OrderID`, `CustomerID`, `CustomerComment`, `CustomerRatingAverage`, `BranchID`, `DeliveryZoneName`, `RiderID`, `Amount`, `CreatedDate`, `ShiftDate`, `DeliveryTime`, `AddedToTripTime`, `PickingUpTime`. The dataset appears to be a partial extract (see assumptions).

**Preprocessing — `app/data_layer.py:83`:**

1. Derive `delivery_min = (DeliveryTime - CreatedDate)`, `dispatch_min`, `pickup_min` in minutes (`_minutes()`).
2. Quality flags: `flag_negative_dispatch`, `flag_negative_pickup` (< 0), `flag_delivery_outlier` (> 1440), `flag_dispatch_outlier`/`flag_pickup_outlier` (|min| > 1440).
3. Clean columns: `delivery_min_clean`, `dispatch_min_clean`, `pickup_min_clean` — flagged values become `NaN` for statistics only; rows retained.
4. `order_month` (period M), `order_hour`, `order_dow`, `has_comment`, `comment_lang` (20% Arabic-character heuristic).

**Branch late threshold — `app/data_layer.py:126`:**

Per-branch 90th percentile of `delivery_min_clean` over that branch's full history in the dataset. Mapped back as `branch_p90_min`; `is_late = delivery_min_clean > branch_p90_min`.

**Reference date — `app/data_layer.py:150`:**

`data_reference_date() = max(CreatedDate)` — currently 2026-07-12. Window helper `_month_window()` in `app/tools.py:16` resolves "last month" as the most recent full calendar month before that date (June 2026) and "current month" as the reference date's partial month.

**Analytical processing — `app/tools.py`:**

- `branch_delivery_trend` — compares last full month vs prior month; per-branch median (`p50_min`), P90, late rate; min-volume inner join; sorted by P90 change.
- `branch_worsening_reasons` — for a given `branch_id`, compares segment means (dispatch/pickup/delivery/late rate/rating) between the two months; top 5 late-order riders/zones.
- `late_complaint_breakdown` — attaches cached local-NLP labels (`nlp_complaint_intent`, `nlp_late`), aggregates by zone/rider/branch/hour/DOW with per-100-orders rates (`METRIC_DEFINITIONS:151`), volume-gated; explicit `metric_definitions` shipped in evidence to prevent Gemini metric renaming.
- `anomaly_scan` — rule-based scan: branch late-rate jump > 5 pp, rider late rate > 2× dataset average, rating drop > 0.3. No statistical test.
- `rider_performance_ranking` — ranks by `late_rate` (never mean time) among riders with `n >= MIN_VOLUME`; supports `window` (`last_month`/`current_month`/`all_time`/`all_time`), `direction`, `top_n` (1–20), `rider_id` lookup.

**Outputs.** Each tool returns `{answer_data, caveats, n_rows}`. `answer_data` is JSON-serialisable evidence; `caveats` carry verbatim assumption strings; `n_rows` is row count used.

## 3. Analytics and Business Logic — Deterministic vs LLM

**Deterministic (the only source of numbers):** all cleaning, flagging, P90 computation, late flag, month windows, counts, rates, medians, volume gates, and syndications in `app/data_layer.py` and `app/tools.py`. These run identically regardless of Gemini availability.

**LLM-driven (presentation only):**

- Intent parsing in `app/intent.py:105` — maps free-text question to `{tool, window, direction, top_n, rider_id, branch_id}`. Strict JSON, validated by `validate_intent():75` (normalises window/direction/top_n/cases). Failures fall back to `rule_based_intent():194` (keyword/regex rules) with a safety override (`route():255`) that never lets driver keywords reach `anomaly_scan`.
- Narration in `app/narration.py:400` — `narrate_with_gemini()` receives only the already-aggregated evidence JSON (capped at 12,000 chars) and a `NARRATION_SYSTEM` prompt that forbids inventing numbers, causation, or technical jargon. On any failure or when `get_client() is None`, `template_narration():100` is used.

**Clear separation:** `NARRATION_SYSTEM:465` and tool docstrings state "Gemini NEVER calculates metrics." Tests assert `tools` exposes no keyword matcher (`test_metrics.py:78`) and narration never relabels metrics (`test_narration.py:35`).

## 4. LLM / Gemini Integration

**Where used:**

- Intent: `app/intent.py:117` — `client.models.generate_content(model=model_name(), contents=INTENT_SYSTEM + question, config={temperature:0, response_mime_type:application/json})`.
- Narration: `app/narration.py:422` — `client.models.generate_content(model=model_name(), contents=NARRATION_SYSTEM + evidence, config={temperature:0})`.

**What it receives:**

- Intent: the intent-system prompt plus the user's raw question.
- Narration: the narration-system prompt plus the small evidence JSON (`{"tool", "evidence": answer_data, "caveats"}`). Raw customer comments are never sent — `late_complaint_breakdown` aggregates local-NLP labels before Gemini sees anything (verified by `test_narration.py:177`).

**What it is responsible for:**

- Producing valid intent JSON within the schema.
- Rephrasing evidence into concise, plain-language business prose (max ~180 words, association language, no new numbers).

**What it is NOT responsible for:**

- No metric calculation, no branching logic, no data retrieval, no forecasting.

**Failure / uncertainty:**

- Missing key, empty `text`, exception, invalid JSON, or schema mismatch → deterministic fallback (`rule_based_intent`, `template_narration`).
- Narration validates nothing beyond non-empty text; templates are always available at zero cost.
- The app never retries or throws to the user on LLM failure.

**API / dependency considerations:**

- Dependency: `google-genai>=1.0`, `python-dotenv>=1.0` (see `requirements.txt`).
- Model name via `GEMINI_MODEL` env, defaulting to `gemini-2.5-flash-lite` in `app/gemini_client.py:17`; assessment used `gemini-3.5-flash-lite`.
- At most 2 calls per question; no streaming, no functions, no per-comment calls.

## 5. Reliability and Correctness

Already present:

- Explicit, documented business rules in `app/data_layer.py:19` `ASSUMPTIONS` — single source of truth for late definition, caps, gates, sampling note.
- Flags preserved as columns (not silently dropped), so downstream logic can exclude only from statistics.
- Clean-column pattern (`*_clean`) prevents outlier contamination of P90/means without losing row counts.
- Volume gate (`MIN_VOLUME=20`) prevents small-sample artefacts; disclosed in evidence and narration.
- Intent validation (`validate_intent:75`) normalises and rejects out-of-schema values; driver safety override (`route:255`).
- Metric separation (`METRIC_DEFINITIONS:151`, narration separation clauses) prevents complaint-rate/late-rate conflation.
- Count coercion (`_int()` in `app/narration.py:23`) prevents float artefacts in display.
- Deterministic templates are specification-enforced (lead-with-answer, single Data note, association language) and tested for banned terms/causation.

Not claimed:

- No guarantee against all misclassification; NLP thresholds are heuristic (see Limitations).
- No statistical significance testing in `anomaly_scan` (explicitly noted as rule-based leads).

## 6. Testing

Run: `pytest tests/ -v` from repo root.

Actual coverage (verifiable in `tests/`):

| File | What is checked |
|---|---|
| `tests/test_metrics.py` | Derived-minute arithmetic, outlier/negative flags, P90 uses clean values, late flag, local-NLP as source , breakdown counts/rates/denominators/volume gate, router for all 5 tools and driver variants, rider min-volume and late-rate-not-mean ranking, numbers-from-analytics, anomaly detail naming |
| `tests/test_intent.py` | Gemini-success path (mocked), Gemini-failure fallback, invalid-intent rejection/normalisation, driver safety override, narration fallback without key |
| `tests/test_narration.py` | Counts render as ints, metric-label separation (no late-rate relabelling, no rider blame), peak-hour/day ordering, no internals leak (`MIN_VOLUME`/`p90`/`pp`/etc.), single Data note + lead structure, no causation/blame, no keyword claim, no raw comments in evidence |
| `tests/test_nlp.py` | EN/AR late, negative-not-late, late-with-neutral wording, rider-not-late, food-quality-not-late, mixed language, empty/null safety, batch cache + confidence, thresholds configurable, lexical fallback parity |

Totals: ~43+ tests. No live API calls (key absent → fallback; Gemini paths mocked).

- Not tested: Streamlit UI, live Gemini integration, real-file value regression (the 64k-row extract is not committed — a snapshot/freeze of branch/rider aggregates would be a useful additive test).

## 7. Security

- **API key handling.** Read from `GEMINI_API_KEY` env (`.env` via dotenv) in `app/gemini_client.py:25`. No hard-coded key, no logging of the key in `app/gemini_client.py`, `app/intent.py`, `app/narration.py`, or `app/api_usage.py`. `.env` is gitignored; only `.env.example` (empty placeholders) is committed.
- **Secrets exposure scan.** Before final submission, verify no key appears in `docs/`, `README.md`, `tests/`, or `api_usage.txt` (the latter stores only tokens/cost, never keys or questions).
- **External API dependency.** Only `google-genai` calls to Gemini models. No other outbound calls. Disable entirely by unsetting `GEMINI_API_KEY` — app falls back deterministically.
- **Logging.** `app/api_usage.py:52` prints `API call N type=... in=... out=... cost=...` and appends `api_usage.txt` (gitignored). It never logs questions, evidence contents, or raw comments.
- **Input surface.** User question is a free-text string; no file upload, no code execution from input.

## 8. Privacy / Data Handling

- **Data processed.** The anonymised extract `operations_data_anonymized.xlsx` (~64,619 rows) including `CustomerComment` text (EN/AR) and `CustomerRatingAverage`. File is not committed — evaluator places it locally per `setup.md`.
- **What leaves the process.** Only aggregated evidence JSON reaches Gemini (intent question + narration evidence). Raw `CustomerComment` strings never leave the process — they are labelled locally by `app/nlp_pipeline.py` and only counts/rates are aggregated in `app/tools.py` (verified by `test_narration.py:177`).
- **No persistence.** The app holds the DataFrame in memory (`@st.cache_data` in `app/app.py:39`); no database, no user accounts, no comment storage beyond the process.
- **Retention.** No compliance claim is made. For production, a DPIA, retention policy, and data-processing agreement for Gemini usage would be needed (see Production Readiness).

## 9. Failure Modes and Limitations

- **Late is relative.** Without an SLA, branch P90 is a stand-in. Branches with unusually lenient or tight histories will distort cross-branch comparability.
- **Partial extract and uneven months.** See `sampling_caveat` — MoM moves may be sampling artefacts. April 2025 is empty; July 2025 has 843 rows.
- **Timestamp artefacts.** ~21% negative pickup, ~5% negative dispatch. Means are filtered but the underlying system clock issue is not resolved.
- **Comments are sparse and noisy (~29%).** Local-NLP labels are embedding-similarity heuristics with configured thresholds (`app/nlp_prototypes.py:13`). The conservative `late:0.45` threshold misses paraphrased delay reports; `sentiment`/`complaint_intent`/`late_order_complaint` are independent and can disagree. No ground-truth evaluation of the NLP pipeline on this dataset is asserted beyond the 9 tests in `tests/test_nlp.py`.
- **Lexical fallback drift.** If the embedding model cannot load (no internet, cache miss, missing deps), quality drops silently to `lexical-fallback` (keyword-overlap) — disclosed in `LocalNLPPipeline:166` `backend_name` but not in the UI beyond evidence JSON.
- **Gemini failure.** Falls back deterministically; no retry, no user-visible error. Intent fallback may misroute ambiguous questions (though safety override handles driver cases).
- **Out-of-scope questions.** Answered by `check_out_of_scope():47` refusal strings (forecasting, HR/discipline, revenue/pricing) — not by Gemini.

## 10. Production Readiness Considerations

**Already implemented:**

- Deterministic analytics as source of truth; LLM isolated to routing/phrasing.
- Explicit assumptions and volume gates; evidence JSON always inspectable.
- Graceful Gemini absence/failure with template narration.
- Raw comments never sent to Gemini; key never logged; documented aggregation pipeline.
- Test suite covering routing, metrics, NLP signals, and narration rendering without live API.
- Assessment-only usage tracking fully isolated in `app/api_usage.py` (removal doc at `docs/API_USAGE_REMOVAL.md`).

**Recommended before production (relevant to this system):**

- **Authentication/authorization.** No auth exists (Streamlit is open). Add SSO, role-gating, and session isolation if deployed internally.
- **Secret management.** Move `GEMINI_API_KEY` to a secrets manager (not `.env` on disk) with rotation and audit.
- **Model evaluation.** Add ground-truth-labelled evaluation of the local NLP pipeline (precision/recall for `late_order_complaint`) and of intent routing accuracy beyond current rule tests.
- **Regression/snapshot tests.** Freeze a snapshot of branch/rider aggregates on a reference data cut to catch silent data-layer changes.
- **Monitoring & observability.** Structured logs (route method, tool, latency, token usage), error alerting, and evidence-level audit trail beyond the toy `api_usage.txt`.
- **Rate limits & cost controls.** Guard Gemini calls (per-user quotas, debounce, max tokens) — currently at most 2 per question but no throttle.
- **Data validation.** On load, validate schema, expected branches/riders, date ranges, forbidden nulls, and sampling health before serving.
- **Error handling & data-quality surfacing.** Promote `data_quality_flags` in the UI more visibly; never swallow pipeline load failures silently.
- **Privacy review & retention.** Confirm processing of `CustomerComment` via Gemini is permitted; document retention and deletion for any logged evidence or comments; complete DPIA.
- **Performance/load testing.** Current in-memory `pandas` is fine for 64k rows; test at 1M+ rows and consider DuckDB/warehouse offload; profile first-run model download (470 MB).
- **Deployment hardening.** Container image, health checks, TLS, network egress restrictions (only Gemini), backup of the `.xlsx` or migration to a versioned data store, and CI running `pytest tests/ -v` on every change.

Do not consider the system production-ready merely because it works locally.
