# Setup

Short, practical guide to run the Operations Intelligence Assistant on a fresh clone.

## 1. Clone the Repository

```bash
git clone <your-repo-url>
cd ops-assistant-no-api
```

## 2. Create a Python Environment

Python 3.10+ is required. Use a virtual environment.

**Windows (PowerShell):**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python --version
```

**macOS / Linux:**

```bash
python3 -m venv .venv
source .venv/bin/activate
python --version
```

## 3. Install Dependencies

From the repository root (where `requirements.txt` lives):

**Windows (PowerShell) and macOS/Linux:**

```bash
pip install -r requirements.txt
```

Dependencies are listed in `requirements.txt` — `pandas`, `openpyxl`, `streamlit`, `pytest`, `google-genai`, `python-dotenv`, `sentence-transformers==6.0.1`, `transformers==5.17.0`, `torchvision==0.29.0`, and their transitive dependencies. No other packages are required. The first run of the local NLP pipeline downloads the `paraphrase-multilingual-MiniLM-L12-v2` model (~470 MB) to the Hugging Face cache.

## 4. Configure Environment Variables / API Keys

The app reads `GEMINI_API_KEY` and `GEMINI_MODEL` from the environment (via `python-dotenv` from a `.env` file).

**Windows (PowerShell):**

```powershell
Copy-Item .env.example .env
# Edit .env and set your values
notepad .env
```

**macOS / Linux:**

```bash
cp .env.example .env
# Edit .env and set your values
nano .env
```

`.env` contents:

```
GEMINI_API_KEY=your_key_here
GEMINI_MODEL=gemini-2.5-flash-lite
```

- `GEMINI_API_KEY` — required only if you want Gemini intent parsing and narration. 
- `GEMINI_MODEL` — optional. Defaults to `gemini-2.5-flash-lite` in `app/gemini_client.py` if not set. The assessment environment used `gemini-3.5-flash-lite`.

Do not commit `.env` (it is gitignored). Never paste a real key into documentation.

Optional:

- `OPS_DATA_PATH` — absolute or relative path to `operations_data_anonymized.xlsx`. If not set, the app tries the candidates resolved in `app/app.py`.

## 5. Place / Configure Required Data

The app expects the assessment extract `operations_data_anonymized.xlsx` (~64,619 rows, sheet `Data`).

Place it in one of these locations (all resolved automatically):

- Repository parent directory: `../operations_data_anonymized.xlsx` (default `OPS_DATA_PATH` fallback in `app/app.py:14`)
- Repository root: `./operations_data_anonymized.xlsx`
- `data/` directory: `./data/operations_data_anonymized.xlsx`

Or set a custom location:

**Windows (PowerShell):**

```powershell
$env:OPS_DATA_PATH="C:\path\to\operations_data_anonymized.xlsx"
```

**macOS / Linux:**

```bash
export OPS_DATA_PATH="/path/to/operations_data_anonymized.xlsx"
```

The `.xlsx` file is not committed (see `.gitignore`). The `data/` directory ships with a `.gitkeep` placeholder.

## 6. Start the Application

From the repository root:

```bash
streamlit run app/app.py
```

Open the URL Streamlit prints (typically `http://localhost:8501`). Reference date, example questions, and the Ask flow appear on the landing page. No database setup is required — the app loads the `.xlsx` into memory with `pandas` on startup.

## 7. Run the Tests

No API key or data file is needed for most tests (they use synthetic DataFrames and mock Gemini).

```bash
pytest tests/ -v
```

Expected: 43+ tests pass (see `tests/`). Coverage includes arithmetic, load/clean flags, local NLP signals (EN/AR/mixed/empty/cache/thresholds, lexical parity), complaint breakdown counts/rates/aggregations/volume gates, routing for all five tools, Gemini-failure fallbacks, min-volume gates, late-rate ranking, and narration rendering. Live Gemini paths and the Streamlit UI are not exercised in tests by design.

---

Troubleshooting:

- `FileNotFoundError: Could not find data file` — verify the `.xlsx` location or `OPS_DATA_PATH`.
- `sentence-transformers` / `torchvision` version errors — reinstall exactly `requirements.txt` pinned versions.
- No Gemini responses — expected when `GEMINI_API_KEY` is unset; rule-based routing and template narration are used instead.
