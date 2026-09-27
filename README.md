# PragatiTrace

**Citizen complaints, checked against the government's own sanction orders.**

Built for **Build with AI: Code for Communities - Google Cloud Hackathon**
Track: *Constituency Development Planning*

प्रगति (*pragati*) means progress.

---

## The problem

India's rural works schemes move enormous sums through thousands of small,
local sanction orders and almost none of them are ever checked against
what a citizen actually sees on the ground. A villager can see a pothole.
A district officer has a filing cabinet of sanction orders. Nobody
routinely puts the two side by side.

## What PragatiTrace does

1. **Hear** - A citizen reports a problem by voice or text, in any Indian
   language. Gemini transcribes and classifies it into a structured
   complaint (issue type, location, severity).
2. **Read** - The app ingests real government sanction/completion
   documents (PMGSY, JJM, or similar) — typed tables, scanned PDFs, or
   narrative text - and extracts the numbers.
3. **Connect** - Complaints are matched to the sanctioned work for that
   village, and any work whose completion amount deviates from its
   sanction is flagged for audit with every number checked back against
   the source text before it's trusted.

The result is a single dashboard a district officer can use to see which
complaints correspond to real, funded work — and which of that work looks
worth a second look.

## Why this is hard (and how we handled it)

Government documents don't come in one shape. `universal_ingest.py` gives
every document a verdict instead of silently failing:

| Status | Meaning |
|---|---|
| `variance_pair` | Classic sanctioned-vs-completed pair found risk score computed |
| `narrative_anomaly` | No clean numeric pair, but the text itself names an irregularity (cost inflation, delay, action ordered) |
| `batch_aggregate` | A real sanction, but batch-level with no completion data logged as coverage, not scored |
| `unreadable` | OCR/text extraction failed or text too sparse to say anything flagged for manual review |
| `no_findings` | Readable, but nothing matches a known pattern flagged for manual review, not discarded |
| `quota_exceeded` | Gemini's API quota is exhausted distinct from a document problem |

Nothing in the pipeline ever raises an unhandled exception out to the UI 
every path returns a result the app can render.

### What Gemini does vs. what deterministic code does

- **Gemini**: transcribes voice complaints and classifies them; reads
  scanned sanction orders; rebuilds work names that break across lines;
  finds revision history in narrative documents; writes the short
  district-officer briefing.
- **Code**: parses table rows; computes every variance and risk level;
  checks each extracted amount against the source text; matches
  complaints to sanctions by place and issue; caches OCR results by file
  hash so a document is never re-processed unnecessarily.

Built to keep running: automatic model fallback across Gemini model
variants, timeouts on every call, and retries only for transient errors 
with a hard per-session call budget so one runaway session can't exhaust
the API key.

## Tech stack

- **Streamlit** - UI and app framework
- **Google Gemini API** (`google-genai`) - transcription, classification,
  document understanding, narrative synthesis
- **pdfplumber / pypdf** - PDF text extraction
- **SQLite** - local persistence for citizen reports, sanctioned works,
  document coverage, and field verifications
- **ReportLab** - generates the one-click PDF briefing for a collector/MP's
  office
- **pandas / pydeck** - map view of flagged works by location

## Demo data

The app ships with a **"Load sample district data"** toggle that loads:

- Five citizen reports (road, water, sanitation) across a sample district
- Six sanctioned works extracted from a **real 2007 Tamil Nadu PMGSY
  sanction order** (G.O. (D) No.130, Nagapattinam)
- One reference example (Mumbai Coastal Road cost escalation) sourced from
  public news reporting, entered directly rather than through the
  extraction pipeline, to illustrate the "revision history" document shape

This is sample data for demonstration, clearly marked as such in the UI
and in the data provenance field of every record.

## Getting started

### 1. Clone and install

```bash
git clone https://github.com/vedant248/pragatitrace.git
cd pragatitrace
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Add your Gemini API key

Get a free key from [Google AI Studio](https://aistudio.google.com/apikey),
then create `.streamlit/secrets.toml` (already git-ignored):

```toml
GEMINI_API_KEY = "your-key-here"
```

A template is provided at `.streamlit/secrets.toml.example` — copy it and
fill in your key:

```bash
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
```

### 3. Run it

```bash
streamlit run app.py
```

### 4. (Optional) Verify your API key/model access

```bash
python check_gemini.py
```

This checks which Gemini model variants your key currently has access to
and gives a plain-English reason (bad key, quota exhausted, model not
available) for any that fail.

## Project structure

```
pragatitrace/
├── app.py                       # Streamlit app: UI, DB layer, Gemini calls, risk scoring
├── universal_ingest.py          # Multi-tier document classifier/extractor with graceful fallback
├── check_gemini.py              # Standalone script to verify API key + model availability
├── requirements.txt
├── .streamlit/
│   ├── config.toml
│   └── secrets.toml.example     # Template — copy to secrets.toml and add your key
└── .gitignore
```

## Known limitations

Being upfront about what this is (a hackathon prototype) and isn't
(production-ready):

- **Risk thresholds are a starting heuristic**, not calibrated per scheme
  or state.
- **Tested on real documents from two states** (Tamil Nadu, Himachal
  Pradesh) — not yet validated at national scale.
- **Single-user prototype**: no login, and no consent flow for citizen
  data yet. Voice recordings and documents are sent to Google's Gemini
  API for processing; reports are stored in a local SQLite database with
  no retention policy. A real deployment handling citizen complaints
  against officials would need both.
- **Field verification is a manual log**, not satellite imagery or
  independent site visits.
- Not affiliated with or endorsed by any government body. Sanction data
  used is public-record PMGSY documentation, used here to demonstrate the
  matching pipeline.

## Roadmap

- Calibrate risk thresholds per scheme and state
- Add more states and document formats
- Deploy securely on Google Cloud, with login and citizen consent
- Check completed roads against satellite imagery

## Demo video

https://drive.google.com/file/d/18MyoMQNXLfgWJ2WjmAikZjrzFsizg4dc/view?usp=drivesdk

## License

MIT [LICENSE](LICENSE).

## Team

Team PragatiTrace - *Build with AI: Code for Communities, Google Cloud
Hackathon*
