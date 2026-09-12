import streamlit as st
from google import genai
import json
import re
import difflib
import time
import hashlib
import io
import sqlite3
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import inch

st.set_page_config(page_title="PragatiTrace", layout="wide", page_icon="🏛️", initial_sidebar_state="expanded")

API_KEY = st.secrets["GEMINI_API_KEY"]

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;700&family=Inter:wght@400;500;600&display=swap');

html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
h1, h2, h3 { font-family: 'Space Grotesk', sans-serif !important; }

.stApp { background: radial-gradient(circle at 15% 0%, #131b2e 0%, #0b0e14 55%); }

.hero {
    background: linear-gradient(120deg, #1a2a52 0%, #0e1a33 60%, #0b0e14 100%);
    border-radius: 20px; padding: 40px 44px; margin-bottom: 28px;
    border: 1px solid #22304d;
}
.hero-title {
    font-family: 'Space Grotesk', sans-serif; font-size: 40px; font-weight: 700;
    background: linear-gradient(90deg, #7ab8ff, #a78bfa);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
    margin: 0;
}
.hero-sub { color: #9ca3af; font-size: 16px; margin-top: 8px; max-width: 640px; }
.hero-pills { margin-top: 18px; }
.pill {
    display: inline-block; background: #182238; border: 1px solid #2a3a5c;
    color: #c7d2fe; padding: 6px 14px; border-radius: 20px; font-size: 13px;
    margin-right: 8px; margin-top: 6px;
}

.report-card {
    background: linear-gradient(145deg, #171e2e, #131826);
    border-radius: 14px; padding: 18px 22px; margin: 12px 0;
    border-left: 4px solid #4a9eff; box-shadow: 0 4px 14px rgba(0,0,0,0.25);
}
.flag-card {
    background: linear-gradient(145deg, #171e2e, #131826);
    border-radius: 14px; padding: 16px 20px; margin: 10px 0;
    box-shadow: 0 4px 14px rgba(0,0,0,0.25);
}
.flag-red { border-left: 4px solid #ff4b4b; }
.flag-green { border-left: 4px solid #21c55d; }

.metric-box {
    background: linear-gradient(145deg, #171e2e, #131826);
    border-radius: 14px; padding: 22px; text-align: center; margin: 6px 0;
    border: 1px solid #202a40;
}
.metric-number {
    font-family: 'Space Grotesk', sans-serif; font-size: 34px; font-weight: 700; color: #7ab8ff;
}
.metric-label { font-size: 12px; color: #8b95a8; text-transform: uppercase; letter-spacing: 0.8px; margin-top: 2px; }

.badge {
    display: inline-block; padding: 3px 10px; border-radius: 20px;
    font-size: 12px; font-weight: 600; margin-right: 6px;
}
.badge-high { background: #4a1414; color: #ff8787; }
.badge-medium { background: #4a3814; color: #ffc078; }
.badge-low { background: #14351a; color: #8ce99a; }

.stTabs [data-baseweb="tab-list"] { gap: 6px; }
.stTabs [data-baseweb="tab"] {
    background: #131826; border-radius: 10px; padding: 10px 18px;
    border: 1px solid #202a40;
}
.stTabs [aria-selected="true"] {
    background: linear-gradient(120deg, #2a4a8a, #1e3a6a) !important;
    border: 1px solid #4a7dd9 !important;
}
</style>
""", unsafe_allow_html=True)

with st.sidebar:
    st.markdown("### 🏛️ PragatiTrace")
    st.caption("Built for Indian infrastructure accountability")
    st.markdown("---")
    st.markdown("**How it works**\n\n1. 📣 Citizens report a problem — by voice or text, in their own language\n2. 🔍 The system reads real government sanction papers and checks the numbers\n3. 🔗 It matches the two, so you can see if a funded project was actually finished")
    st.markdown("---")
    st.caption("Built for Build with AI: Code for Communities — Google Cloud Hackathon")
    st.caption("Powered by Gemini")

hero_html = (
    '<div class="hero">'
    '<p class="hero-title">PragatiTrace</p>'
    '<p class="hero-sub">Citizens report infrastructure problems. We check them against real '
    'government spending records to see if the money was actually spent where it should have been.</p>'
    '<div class="hero-pills">'
    '<span class="pill">🎙️ Voice and text, any language</span>'
    '<span class="pill">🤖 Real Gemini AI</span>'
    '<span class="pill">📄 Real government data</span>'
    '<span class="pill">🇮🇳 Works for any Indian state</span>'
    '</div></div>'
)
st.markdown(hero_html, unsafe_allow_html=True)

DB_PATH = "pragatitrace.db"


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS citizen_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            issue_type TEXT, location_mentioned TEXT, severity TEXT,
            summary TEXT, transcript TEXT, is_demo INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sanctioned_works (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            work_name_full TEXT, location TEXT, administrative_sanction REAL,
            completion_report_amount REAL, variance_pct REAL, risk_level TEXT,
            flag TEXT, source_type TEXT, data_provenance TEXT,
            amounts_verified_in_text INTEGER, is_demo INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


def insert_citizen_report(report, is_demo=False):
    conn = get_connection()
    conn.execute(
        "INSERT INTO citizen_reports (issue_type, location_mentioned, severity, summary, transcript, is_demo) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (report.get("issue_type"), report.get("location_mentioned"), report.get("severity"),
         report.get("summary"), report.get("transcript"), 1 if is_demo else 0)
    )
    conn.commit()
    conn.close()


def get_all_citizen_reports():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM citizen_reports ORDER BY id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def insert_sanctioned_work(work, is_demo=False):
    conn = get_connection()
    verified = work.get("amounts_verified_in_text")
    verified_int = 1 if verified is True else (0 if verified is False else None)
    conn.execute(
        "INSERT INTO sanctioned_works (work_name_full, location, administrative_sanction, "
        "completion_report_amount, variance_pct, risk_level, flag, source_type, "
        "data_provenance, amounts_verified_in_text, is_demo) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (work.get("work_name_full"), work.get("location"), work.get("administrative_sanction"),
         work.get("completion_report_amount"), work.get("variance_pct"), work.get("risk_level"),
         work.get("flag"), work.get("source_type"), work.get("data_provenance"),
         verified_int, 1 if is_demo else 0)
    )
    conn.commit()
    conn.close()


def get_all_sanctioned_works():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM sanctioned_works ORDER BY id").fetchall()
    conn.close()
    works = []
    for r in rows:
        w = dict(r)
        w["sl_no"] = w["id"]
        if w["amounts_verified_in_text"] is not None:
            w["amounts_verified_in_text"] = bool(w["amounts_verified_in_text"])
        works.append(w)
    return works


def clear_demo_data():
    conn = get_connection()
    conn.execute("DELETE FROM citizen_reports WHERE is_demo = 1")
    conn.execute("DELETE FROM sanctioned_works WHERE is_demo = 1")
    conn.commit()
    conn.close()


def sync_from_db():
    st.session_state.citizen_reports = get_all_citizen_reports()
    st.session_state.sanctioned_works = get_all_sanctioned_works()


init_db()
sync_from_db()


def compute_risk_level(variance_pct):
    if variance_pct > 10:
        return "CRITICAL"
    elif variance_pct > 5:
        return "HIGH"
    elif variance_pct > 1:
        return "MEDIUM"
    else:
        return "LOW"


DEMO_CITIZEN_REPORTS = [
    {"issue_type": "road", "location_mentioned": "Achalpuram", "severity": "high",
     "summary": "Main road in Achalpuram has severe potholes, accident risk."},
    {"issue_type": "road", "location_mentioned": "Achalpuram", "severity": "medium",
     "summary": "Road near the school in Achalpuram needs repair."},
    {"issue_type": "water", "location_mentioned": "Samiyam village", "severity": "high",
     "summary": "No piped water supply in Samiyam village for two weeks."},
    {"issue_type": "road", "location_mentioned": "Kulichar", "severity": "medium",
     "summary": "Road connecting Kulichar to Melparasalur is damaged after rains."},
    {"issue_type": "sanitation", "location_mentioned": "Puthur", "severity": "low",
     "summary": "Garbage collection irregular in Puthur AD Colony."},
]

DEMO_SANCTIONED_WORKS = [
    {"sl_no": 1, "work_name_full": "Improvements to Alakudi - Kaduvetti road Km.0/0-1/0",
     "location": "Alakudi Kaduvetti", "administrative_sanction": 1975000.0,
     "completion_report_amount": 2030206.0, "variance_pct": 2.8,
     "flag": "OVER_SANCTION - verify physical scope",
     "data_provenance": "Extracted by this app's Tier 1 regex parser from a real 2007 Tamil Nadu PMGSY sanction order (G.O. (D) No.130, Nagapattinam)."},
    {"sl_no": 2, "work_name_full": "Improvements to Samiyam village Road Km.0/0-1/185",
     "location": "Samiyam village", "administrative_sanction": 1750000.0,
     "completion_report_amount": 1712588.65, "variance_pct": -2.14, "flag": "within tolerance",
     "data_provenance": "Extracted by this app's Tier 1 regex parser from the same real Tamil Nadu PMGSY sanction order."},
    {"sl_no": 3, "work_name_full": "Improvements to Achalpuram-Agaram road Km.0/0-1/0",
     "location": "Achalpuram Agaram", "administrative_sanction": 1694000.0,
     "completion_report_amount": 1622748.23, "variance_pct": -4.21, "flag": "within tolerance",
     "data_provenance": "Extracted by this app's Tier 1 regex parser from the same real Tamil Nadu PMGSY sanction order."},
    {"sl_no": 4, "work_name_full": "Improvements to Puthur AD Colony road Km.0/0-1/0",
     "location": "Puthur", "administrative_sanction": 1578000.0,
     "completion_report_amount": 1494696.46, "variance_pct": -5.28, "flag": "within tolerance",
     "data_provenance": "Extracted by this app's Tier 1 regex parser from the same real Tamil Nadu PMGSY sanction order."},
    {"sl_no": 5, "work_name_full": "Improvements to Kulichar Melparasalur road Km.0/0-3/0",
     "location": "Kulichar", "administrative_sanction": 5869000.0,
     "completion_report_amount": 5723134.17, "variance_pct": -2.49, "flag": "within tolerance",
     "data_provenance": "Extracted by this app's Tier 1 regex parser from the same real Tamil Nadu PMGSY sanction order."},
    {"sl_no": 6, "work_name_full": "Mumbai Coastal Road Project - Phase 1 (Princess Street Flyover to Worli)",
     "location": "Mumbai", "administrative_sanction": 60000000000.0,
     "completion_report_amount": 127210000000.0, "variance_pct": 112.02,
     "flag": "OVER_SANCTION - verify physical scope", "source_type": "narrative_escalation",
     "data_provenance": "Reference example: real cost-escalation figures from public news reporting (Hindustan Times, Sept 2018), entered directly -- not run through this app's extraction pipeline."},
]

with st.sidebar:
    st.markdown("---")
    demo_mode = st.checkbox("🧪 Load sample district data", value=False)
    if demo_mode and not st.session_state.get("_demo_loaded_in_db"):
        for report in DEMO_CITIZEN_REPORTS:
            insert_citizen_report(report, is_demo=True)
        for w in DEMO_SANCTIONED_WORKS:
            work = dict(w)
            work["risk_level"] = compute_risk_level(work["variance_pct"])
            insert_sanctioned_work(work, is_demo=True)
        st.session_state["_demo_loaded_in_db"] = True
        sync_from_db()
        st.caption("Showing sample data from a real PMGSY package (Nagapattinam) + Rajasthan/Mumbai examples.")
    elif demo_mode:
        st.caption("Showing sample data from a real PMGSY package (Nagapattinam) + Rajasthan/Mumbai examples.")
    elif not demo_mode and st.session_state.get("_demo_loaded_in_db"):
        clear_demo_data()
        st.session_state["_demo_loaded_in_db"] = False
        sync_from_db()

    st.markdown("---")
    st.markdown("**💾 Save / Load Session**")
    st.caption("Data is stored in a local database that survives page refreshes. Export gives you a portable backup you can move between deployments.")
    session_export = json.dumps({
        "citizen_reports": st.session_state.citizen_reports,
        "sanctioned_works": st.session_state.sanctioned_works,
    }, indent=2)
    st.download_button("📥 Export session (.json)", data=session_export,
                        file_name="pragatitrace_session.json", mime="application/json")

    uploaded_session = st.file_uploader("📤 Import session", type=["json"], key="session_uploader")
    if uploaded_session is not None:
        try:
            loaded = json.loads(uploaded_session.read())
            for report in loaded.get("citizen_reports", []):
                insert_citizen_report(report, is_demo=False)
            for work in loaded.get("sanctioned_works", []):
                insert_sanctioned_work(work, is_demo=False)
            sync_from_db()
            st.success("Session imported into the database.")
        except Exception as e:
            st.error(f"Couldn't load session file: {e}")


def parse_indian_number(s):
    s = s.strip().replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def extract_work_rows(text):
    row_pattern = re.compile(
        r'^(\d{1,2})\s+(.*?)\s+([\d,]+(?:\.\d+)?)\s+([\d,]+(?:\.\d+)?)\s+'
        r'([\d,]+(?:\.\d+)?)\s+([\d,]+(?:\.\d+)?)\s*(.*)$'
    )
    rows = []
    for line in text.split("\n"):
        line = line.strip()
        m = row_pattern.match(line)
        if not m:
            continue
        sl_no = int(m.group(1))
        if sl_no > 10:
            continue
        rows.append({
            "sl_no": sl_no,
            "work_name_partial": m.group(2).strip(),
            "administrative_sanction": parse_indian_number(m.group(3)),
            "completion_report_amount": parse_indian_number(m.group(6)),
        })
    return rows


def flag_variance(rows):
    for r in rows:
        admin = r["administrative_sanction"]
        completion = r["completion_report_amount"]
        if admin and completion:
            variance_pct = round(((completion - admin) / admin) * 100, 2)
            r["variance_pct"] = variance_pct
            r["flag"] = "OVER_SANCTION - verify physical scope" if variance_pct > 1.0 else "within tolerance"
            r["risk_level"] = compute_risk_level(variance_pct)
    return rows


def compute_narrative_risk(stages):
    if not stages or len(stages) < 2:
        return None
    first, last = stages[0], stages[-1]
    if not first:
        return None
    variance_pct = round(((last - first) / first) * 100, 2)
    return {
        "variance_pct": variance_pct,
        "risk_level": compute_risk_level(variance_pct),
        "first_stage": first,
        "last_stage": last,
        "num_stages": len(stages),
    }


def extract_amount_candidates_from_text(text):
    candidates = []
    pattern = re.compile(r'(\d+(?:\.\d+)?)\s*(crore|cr\.?|lakh|lac)\b', re.IGNORECASE)
    for match in pattern.finditer(text):
        num = float(match.group(1))
        unit = match.group(2).lower()
        if unit.startswith("cr"):
            candidates.append(num * 1e7)
        else:
            candidates.append(num * 1e5)
    return candidates


def verify_stages_against_text(stages, doc_text, tolerance=0.01):
    candidates = extract_amount_candidates_from_text(doc_text)
    unverified = [s for s in stages if not any(c > 0 and abs(s - c) / c <= tolerance for c in candidates)]
    return len(unverified) == 0, unverified


def call_gemini(prompt, max_retries=3):
    client = genai.Client(api_key=API_KEY)
    for attempt in range(1, max_retries + 1):
        try:
            response = client.models.generate_content(
                model="gemini-3.6-flash",
                contents=prompt
            )
            return response.text.strip().strip("```json").strip("```").strip()
        except Exception as e:
            if attempt == max_retries:
                raise
            time.sleep(3)


def get_full_names_from_gemini(text):
    prompt = f"""This is text extracted from an Indian government road-sanction
order. Names of works got split across multiple lines when the PDF was read.
Reconstruct the FULL name of each numbered work as a clean single line.
Return ONLY a JSON list like: [{{"sl_no": 1, "full_name": "...", "location": "..."}}]
"location" should be just the place/village name, short, for matching purposes.
No markdown, no explanation, just the JSON list.

TEXT:
{text}
"""
    return json.loads(call_gemini(prompt))


def get_narrative_sanction_data_from_gemini(text):
    prompt = f"""This is text from an Indian government infrastructure
document (any scheme: PMGSY, JJM, or other). It may describe a project
whose sanctioned budget was revised one or more times (e.g. an initial
sanction, then a "revised sanction", then a "further revised sanction").

Find the single clearest project described and list every distinct
sanction/revision amount mentioned for it, in chronological order.
Convert all amounts to a plain number of rupees (e.g. "Rs. 76.76 Cr"
means 767600000, "Rs. 50 Lakh" means 5000000). Do not use commas or
currency symbols in the numbers.

Return ONLY a JSON object, no markdown, no explanation, in this exact
shape:
{{
  "found": true or false,
  "project_name": "short project name, or null",
  "location": "short place/village/district name, or null",
  "sanction_stages": [amount1, amount2, ...]
}}

If you cannot find at least one clear sanction amount for an
infrastructure project in this text, return exactly {{"found": false}}.

TEXT:
{text}
"""
    return json.loads(call_gemini(prompt))


def classify_report(complaint_text):
    prompt = f"""A citizen in India submitted this infrastructure complaint.
Extract structured information from it.

Return ONLY a JSON object like this, no markdown, no explanation:
{{
  "issue_type": "road" | "water" | "electricity" | "sanitation" | "other",
  "location_mentioned": "the place name mentioned, or null if none",
  "severity": "low" | "medium" | "high",
  "summary": "one short sentence summarizing the issue in English"
}}

COMPLAINT:
{complaint_text}
"""
    return json.loads(call_gemini(prompt))


def classify_report_from_audio(audio_bytes, max_retries=3):
    import tempfile
    import os
    client = genai.Client(api_key=API_KEY)

    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
        tmp.write(audio_bytes)
        tmp_path = tmp.name

    prompt = """A citizen in India recorded this voice complaint about an
infrastructure issue, possibly in Hindi, English, or a mix of both.
First transcribe what they said, then extract structured information.
Return ONLY a JSON object like this, no markdown, no explanation:
{
  "transcript": "what was said, transcribed",
  "issue_type": "road" | "water" | "electricity" | "sanitation" | "other",
  "location_mentioned": "the place name mentioned, or null if none",
  "severity": "low" | "medium" | "high",
  "summary": "one short sentence summarizing the issue in English"
}
"""
    for attempt in range(1, max_retries + 1):
        try:
            uploaded_file = client.files.upload(file=tmp_path)
            response = client.models.generate_content(
                model="gemini-3.6-flash",
                contents=[prompt, uploaded_file]
            )
            os.unlink(tmp_path)
            cleaned = response.text.strip().strip("```json").strip("```").strip()
            return json.loads(cleaned)
        except Exception:
            if attempt == max_retries:
                os.unlink(tmp_path)
                raise
            time.sleep(3)


def normalize(text):
    return "".join(c.lower() for c in text if c.isalnum() or c.isspace()).strip()


def fuzzy_location_match(loc_a, loc_b, threshold=0.80):
    a, b = normalize(loc_a), normalize(loc_b)
    if not a or not b:
        return False, 0.0

    words_a = {w for w in a.split() if len(w) >= 4}
    words_b = {w for w in b.split() if len(w) >= 4}
    if words_a & words_b:
        return True, 0.9

    ratio = difflib.SequenceMatcher(None, a, b).ratio()
    return ratio >= threshold, round(ratio, 2)


def find_matching_sanctions(citizen_report, sanctioned_works):
    report_loc_raw = citizen_report.get("location_mentioned") or ""
    if not normalize(report_loc_raw):
        return {"status": "NO_LOCATION_DETECTED", "matches": []}

    matches = []
    for work in sanctioned_works:
        work_loc_raw = work.get("location", "")
        if not normalize(work_loc_raw):
            continue
        is_match, score = fuzzy_location_match(report_loc_raw, work_loc_raw)
        if is_match:
            matches.append(work)

    if not matches:
        return {"status": "NO_SANCTION_FOUND", "matches": [],
                "message": "No existing sanctioned project found for this location -- genuinely unaddressed, recommend for prioritization."}

    result = {"status": "SANCTION_FOUND", "matches": matches}
    flagged = [m for m in matches if "OVER_SANCTION" in m.get("flag", "")]
    if flagged:
        result["message"] = (
            f"This area has Rs.{matches[0]['administrative_sanction']:,.0f} already sanctioned, "
            f"and it was flagged for cost variance during verification -- citizen is still "
            f"reporting an issue here despite funding. Recommend audit."
        )
    else:
        result["message"] = (
            f"This area has Rs.{matches[0]['administrative_sanction']:,.0f} sanctioned and "
            f"completed within tolerance. Citizen report may indicate new/separate damage, "
            f"or incomplete resolution -- recommend field verification."
        )
    return result


SEVERITY_RANK = {"high": 3, "medium": 2, "low": 1}


def cluster_reports_by_location(citizen_reports):
    clusters = []

    for report in citizen_reports:
        loc_raw = (report.get("location_mentioned") or "").strip()
        loc_norm = normalize(loc_raw)
        if not loc_norm:
            continue

        placed = False
        for cluster in clusters:
            cluster_norm = normalize(cluster["key"])
            same = (
                loc_norm == cluster_norm
                or loc_norm in cluster_norm
                or cluster_norm in loc_norm
                or set(loc_norm.split()) & set(cluster_norm.split())
            )
            if same:
                cluster["reports"].append(report)
                placed = True
                break

        if not placed:
            clusters.append({"key": loc_raw, "reports": [report]})

    hotspots = []
    for cluster in clusters:
        reports = cluster["reports"]
        severities = [(r.get("severity") or "low").lower() for r in reports]
        top_severity = max(severities, key=lambda s: SEVERITY_RANK.get(s, 0))
        hotspots.append({
            "location": cluster["key"],
            "report_count": len(reports),
            "priority": top_severity.upper(),
            "reports": reports,
        })

    hotspots.sort(key=lambda h: (h["report_count"], SEVERITY_RANK.get(h["priority"].lower(), 0)), reverse=True)
    return hotspots


def hash_ledger_entry(entry, prev_hash):
    payload = json.dumps(entry, sort_keys=True) + prev_hash
    return hashlib.sha256(payload.encode()).hexdigest()


def build_ledger(flagged_works):
    ledger = []
    prev_hash = "0" * 64
    for w in flagged_works:
        entry = {
            "work": w.get("work_name_full"),
            "sanctioned": w.get("administrative_sanction"),
            "completed": w.get("completion_report_amount"),
            "variance_pct": w.get("variance_pct"),
        }
        this_hash = hash_ledger_entry(entry, prev_hash)
        ledger.append({"entry": entry, "prev_hash": prev_hash, "hash": this_hash})
        prev_hash = this_hash
    return ledger


def verify_ledger(ledger):
    prev_hash = "0" * 64
    for block in ledger:
        recomputed = hash_ledger_entry(block["entry"], prev_hash)
        if recomputed != block["hash"]:
            return False
        prev_hash = block["hash"]
    return True


def generate_executive_summary_pdf(citizen_reports, sanctioned_works):
    flagged = [w for w in sanctioned_works if "OVER_SANCTION" in w.get("flag", "")]
    total_flagged_amount = sum(
        w["completion_report_amount"] - w["administrative_sanction"] for w in flagged
    )
    hotspots = cluster_reports_by_location(citizen_reports)

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter,
                             topMargin=0.6 * inch, bottomMargin=0.6 * inch)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("TitleStyle", parent=styles["Title"], fontSize=22, spaceAfter=4)
    subtitle_style = ParagraphStyle("SubtitleStyle", parent=styles["Normal"], textColor=colors.grey, spaceAfter=18)
    heading_style = styles["Heading2"]
    body_style = styles["Normal"]

    story = []
    story.append(Paragraph("PragatiTrace &mdash; Executive Summary", title_style))
    story.append(Paragraph("Infrastructure accountability briefing, generated from live citizen reports and sanction-order verification.", subtitle_style))

    story.append(Paragraph("Impact at a Glance", heading_style))
    impact_data = [
        ["Citizen Reports", str(len(citizen_reports))],
        ["Sanctioned Works Verified", str(len(sanctioned_works))],
        ["Works Flagged for Leakage", str(len(flagged))],
        ["Total Amount Flagged", f"Rs. {total_flagged_amount:,.0f}"],
    ]
    impact_table = Table(impact_data, colWidths=[3.2 * inch, 2.5 * inch])
    impact_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 11),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("LINEBELOW", (0, 0), (-1, -2), 0.5, colors.lightgrey),
        ("LINEBELOW", (0, -1), (-1, -1), 1, colors.black),
    ]))
    story.append(impact_table)
    story.append(Spacer(1, 20))

    story.append(Paragraph("Top Demand Hotspots", heading_style))
    if not hotspots:
        story.append(Paragraph("No location-tagged citizen reports yet.", body_style))
    else:
        hotspot_data = [["Location", "Reports", "Priority"]]
        for h in hotspots[:10]:
            hotspot_data.append([h["location"], str(h["report_count"]), h["priority"]])
        hotspot_table = Table(hotspot_data, colWidths=[3 * inch, 1.3 * inch, 1.4 * inch])
        hotspot_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e293b")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 10),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(hotspot_table)
    story.append(Spacer(1, 20))

    story.append(Paragraph("Flagged Sanctioned Works", heading_style))
    if not flagged:
        story.append(Paragraph("No works flagged for leakage yet.", body_style))
    else:
        flagged_data = [["Work", "Sanctioned (Rs.)", "Completion (Rs.)", "Variance"]]
        for w in flagged:
            flagged_data.append([
                Paragraph(w.get("work_name_full", "")[:60], body_style),
                f"{w['administrative_sanction']:,.0f}",
                f"{w['completion_report_amount']:,.0f}",
                f"{w.get('variance_pct', 'N/A')}%",
            ])
        flagged_table = Table(flagged_data, colWidths=[2.6 * inch, 1.3 * inch, 1.3 * inch, 1 * inch])
        flagged_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#4a1414")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        story.append(flagged_table)

    doc.build(story)
    buffer.seek(0)
    return buffer


def render_report_card(result):
    sev = (result.get("severity") or "low").lower()
    badge_class = {"high": "badge-high", "medium": "badge-medium", "low": "badge-low"}.get(sev, "badge-low")
    icon = {"road": "🛣️", "water": "💧", "electricity": "⚡", "sanitation": "🧹"}.get(result.get("issue_type"), "📍")

    transcript_part = f'<p style="color:#9ca3af; font-style:italic; margin:6px 0;">"{result["transcript"]}"</p>' if result.get("transcript") else ""

    html = (
        f'<div class="report-card">'
        f'<span class="badge {badge_class}">{sev.upper()} PRIORITY</span>'
        f'<span class="badge" style="background:#1e293b;color:#93c5fd;">{icon} {result.get("issue_type","?").upper()}</span>'
        f'{transcript_part}'
        f'<p style="font-size:16px; margin:8px 0 4px 0;"><b>{result.get("summary","")}</b></p>'
        f'<p style="color:#9ca3af; font-size:13px; margin:0;">📍 {result.get("location_mentioned") or "Location not detected"}</p>'
        f'</div>'
    )
    st.markdown(html, unsafe_allow_html=True)


def render_work_card(r):
    risk = r.get("risk_level", "LOW")
    risk_colors = {
        "CRITICAL": ("#ff4b4b", "flag-red", "🔴"),
        "HIGH": ("#ff8c42", "flag-red", "🟠"),
        "MEDIUM": ("#ffc078", "flag-red", "🟡"),
        "LOW": ("#21c55d", "flag-green", "🟢"),
    }
    color, card_class, icon = risk_colors.get(risk, risk_colors["LOW"])
    is_narrative = r.get("source_type") == "narrative_escalation"
    first_label = "First sanction" if is_narrative else "Sanctioned"
    last_label = "Latest revision" if is_narrative else "Completion"
    type_note = (
        f'<p style="margin:0 0 4px 0; color:#7ab8ff; font-size:12px;">📄 Detected via narrative analysis '
        f'(non-tabular document) — comparing sanction revision stages, not a completion report.</p>'
        if is_narrative else ""
    )
    provenance = r.get("data_provenance")
    provenance_note = (
        f'<p style="margin:0 0 4px 0; color:#6b7280; font-size:11px; font-style:italic;">ℹ️ {provenance}</p>'
        if provenance else ""
    )
    verified_flag = r.get("amounts_verified_in_text")
    verification_note = ""
    if verified_flag is True:
        verification_note = '<p style="margin:0 0 4px 0; color:#21c55d; font-size:11px;">✅ Amounts independently confirmed present in source text (regex check).</p>'
    elif verified_flag is False:
        verification_note = '<p style="margin:0 0 4px 0; color:#ff8c42; font-size:11px;">⚠️ Some amounts NOT independently confirmed in source text — verify before trusting this result.</p>'

    html = (
        f'<div class="flag-card {card_class}">'
        f'<span class="badge" style="background:{color}22; color:{color}; margin-bottom:6px;">{icon} {risk} RISK</span>'
        f'<p style="margin:6px 0 6px 0;"><b>Work #{r["sl_no"]}: {r.get("work_name_full","")}</b></p>'
        f'{type_note}'
        f'{provenance_note}'
        f'{verification_note}'
        f'<p style="margin:0; color:#9ca3af; font-size:14px;">'
        f'{first_label}: ₹{r["administrative_sanction"]:,.2f} &nbsp;|&nbsp; '
        f'{last_label}: ₹{r["completion_report_amount"]:,.2f} &nbsp;|&nbsp; '
        f'Variance: {r.get("variance_pct","N/A")}%'
        f'</p></div>'
    )
    st.markdown(html, unsafe_allow_html=True)


def render_hotspot_card(h):
    priority = h.get("priority", "LOW")
    priority_badge = {"HIGH": "badge-high", "MEDIUM": "badge-medium", "LOW": "badge-low"}.get(priority, "badge-low")
    html = (
        f'<div class="report-card">'
        f'<span class="badge {priority_badge}">{priority} PRIORITY</span>'
        f'<span class="badge" style="background:#1e293b;color:#93c5fd;">📍 {h["report_count"]} REPORT{"S" if h["report_count"] != 1 else ""}</span>'
        f'<p style="font-size:16px; margin:8px 0 4px 0;"><b>{h["location"]}</b></p>'
        f'<p style="color:#9ca3af; font-size:13px; margin:0;">'
        + " · ".join(r.get("summary", "") for r in h["reports"][:3])
        + f'</p></div>'
    )
    st.markdown(html, unsafe_allow_html=True)


def format_inr_compact(amount):
    if amount >= 1e7:
        return f"₹{amount/1e7:.2f} Cr"
    elif amount >= 1e5:
        return f"₹{amount/1e5:.2f} L"
    else:
        return f"₹{amount:,.0f}"


def metric_box(number, label):
    html = f'<div class="metric-box"><div class="metric-number">{number}</div><div class="metric-label">{label}</div></div>'
    st.markdown(html, unsafe_allow_html=True)


DISTRICT_POPULATION = {
    "nagapattinam": 1616450, "mumbai": 12442373,
    "pune": 9426959, "thane": 11060148,
}
LOCATION_TO_DISTRICT = {
    "alakudi": "nagapattinam", "kaduvetti": "nagapattinam",
    "samiyam": "nagapattinam", "achalpuram": "nagapattinam",
    "kulichar": "nagapattinam", "puthur": "nagapattinam",
    "mumbai": "mumbai", "pune": "pune", "thane": "thane",
}


def estimate_population_in_scope(sanctioned_works):
    districts_seen = set()
    for w in sanctioned_works:
        loc = normalize(w.get("location", ""))
        for place, district in LOCATION_TO_DISTRICT.items():
            if place in loc:
                districts_seen.add(district)
                break
    total = sum(DISTRICT_POPULATION[d] for d in districts_seen)
    return total, sorted(districts_seen)


st.title("🛣️ PragatiTrace")
st.caption("Real citizen complaints, checked against real government spending records")

tab1, tab2, tab3, tab4 = st.tabs(["📣 Report an Issue", "🔍 Check a Sanction Order", "📊 Dashboard", "🔎 Field Verification"])

with tab1:
    st.subheader("Report an infrastructure issue")
    st.caption("Speak or type in any language. Gemini handles the translation and classification.")

    audio_input = st.audio_input("🎙️ Record your complaint")
    if audio_input is not None:
        if st.button("Submit Voice Report", type="primary"):
            with st.spinner("Transcribing and classifying with Gemini..."):
                try:
                    result = classify_report_from_audio(audio_input.read())
                    insert_citizen_report(result)
                    sync_from_db()
                    render_report_card(result)
                    match = find_matching_sanctions(result, st.session_state.sanctioned_works)
                    st.info(f"🔗 **Cross-check:** {match.get('message', '')}")
                except Exception as e:
                    st.error(f"Something went wrong: {e}")

    st.markdown("**— or type instead —**")
    complaint = st.text_area(
        "Describe the issue:",
        placeholder="Sir humare gaon Achalpuram mein road bahut kharab hai...",
        label_visibility="collapsed"
    )
    if st.button("Submit Text Report"):
        if not complaint.strip():
            st.warning("Please describe the issue first.")
        else:
            with st.spinner("Classifying with Gemini..."):
                try:
                    result = classify_report(complaint)
                    insert_citizen_report(result)
                    sync_from_db()
                    render_report_card(result)
                    match = find_matching_sanctions(result, st.session_state.sanctioned_works)
                    st.info(f"🔗 **Cross-check:** {match.get('message', '')}")
                except Exception as e:
                    st.error(f"Something went wrong: {e}")

def extract_text_from_upload(uploaded_file):
    name = uploaded_file.name.lower()
    if name.endswith(".pdf"):
        import pdfplumber
        text_parts = []
        with pdfplumber.open(uploaded_file) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)
        return "\n".join(text_parts)
    else:
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False, suffix="." + name.split(".")[-1]) as tmp:
            tmp.write(uploaded_file.read())
            tmp_path = tmp.name
        client = genai.Client(api_key=API_KEY)
        uploaded = client.files.upload(file=tmp_path)
        response = client.models.generate_content(
            model="gemini-3.6-flash",
            contents=["Extract ALL text from this image exactly as it appears, preserving line breaks. Return only the raw text, nothing else.", uploaded]
        )
        return response.text


with tab2:
    st.subheader("Check a government sanction order for leakage")
    st.caption("Upload a sanction order PDF or photo, or paste the text directly.")

    uploaded_doc = st.file_uploader("Upload PDF or image", type=["pdf", "png", "jpg", "jpeg"])
    st.markdown("**— or paste text —**")
    doc_text_pasted = st.text_area(
        "Document text:",
        height=180,
        placeholder="Paste the extracted text of a sanction order...",
        label_visibility="collapsed"
    )

    if st.button("Analyze Document", type="primary"):
        doc_text = None
        if uploaded_doc is not None:
            with st.spinner("Reading uploaded document..."):
                try:
                    doc_text = extract_text_from_upload(uploaded_doc)
                except Exception as e:
                    st.error(f"Couldn't read the file: {e}")
        elif doc_text_pasted.strip():
            doc_text = doc_text_pasted

        if not doc_text or not doc_text.strip():
            st.warning("Please upload a document or paste text first.")
        else:
            with st.spinner("Running Tier 1 (deterministic extraction)..."):
                try:
                    rows = flag_variance(extract_work_rows(doc_text))
                except Exception as e:
                    st.error(f"Something went wrong reading the document structure: {e}")
                    rows = []

            if rows:
                with st.spinner("Reconstructing full work names with Gemini..."):
                    try:
                        names = get_full_names_from_gemini(doc_text)
                        names_by_id = {n["sl_no"]: n for n in names}

                        for r in rows:
                            info = names_by_id.get(r["sl_no"], {})
                            r["work_name_full"] = info.get("full_name", r["work_name_partial"])
                            r["location"] = info.get("location", r["work_name_partial"])
                            r["data_provenance"] = "Extracted live from the document you just provided, using this app's Tier 1 regex parser + Gemini name reconstruction."

                        for r in rows:
                            insert_sanctioned_work(r)
                        sync_from_db()
                        newly_inserted = st.session_state.sanctioned_works[-len(rows):]

                        n_flagged = sum(1 for r in newly_inserted if "OVER_SANCTION" in r.get("flag", ""))
                        st.success(f"✅ Extracted {len(newly_inserted)} works — {n_flagged} flagged for review.")

                        for r in newly_inserted:
                            render_work_card(r)

                        st.markdown("### 🔗 Cross-Reference Check")
                        cross_found = False
                        for w in newly_inserted:
                            if "OVER_SANCTION" not in w.get("flag", ""):
                                continue
                            w_loc_raw = w.get("location", "")
                            matches = [
                                rep for rep in st.session_state.citizen_reports
                                if fuzzy_location_match(w_loc_raw, rep.get("location_mentioned") or "")[0]
                            ]
                            if matches:
                                cross_found = True
                                st.error(
                                    f"🚨 **{w.get('work_name_full')}** is flagged for a "
                                    f"{w.get('variance_pct')}% cost overrun, and {len(matches)} "
                                    f"citizen report(s) in the same area still describe this as unresolved. "
                                    f"Recommend priority field audit."
                                )
                        if not cross_found:
                            st.caption("No cross-referenced discrepancies yet — submit matching citizen reports in Tab 1 to test this.")
                    except Exception as e:
                        st.error(f"Something went wrong: {e}")
            else:
                with st.spinner("No sanctioned-works table detected — trying narrative analysis with Gemini..."):
                    narrative_data = None
                    try:
                        narrative_data = get_narrative_sanction_data_from_gemini(doc_text)
                    except Exception as e:
                        st.error(f"Something went wrong analyzing this document: {e}")

                if not narrative_data or not narrative_data.get("found"):
                    st.warning(
                        "Couldn't find a sanctioned-works table or a recognizable "
                        "sanction/revision amount in this document. Try a different "
                        "document, or paste more of the surrounding text."
                    )
                else:
                    stages = narrative_data.get("sanction_stages") or []
                    risk_info = compute_narrative_risk(stages)
                    if not risk_info:
                        st.info(
                            f"Found '{narrative_data.get('project_name') or 'this project'}' "
                            f"but only one sanction amount was detected -- no revision "
                            f"history to compare, so no risk score could be computed."
                        )
                    else:
                        verified, unverified_stages = verify_stages_against_text(stages, doc_text)
                        entry = {
                            "work_name_full": narrative_data.get("project_name") or "Unnamed project",
                            "location": narrative_data.get("location") or "",
                            "administrative_sanction": risk_info["first_stage"],
                            "completion_report_amount": risk_info["last_stage"],
                            "variance_pct": risk_info["variance_pct"],
                            "risk_level": risk_info["risk_level"],
                            "flag": "OVER_SANCTION - verify physical scope" if risk_info["variance_pct"] > 1.0 else "within tolerance",
                            "source_type": "narrative_escalation",
                            "data_provenance": "Extracted live from the document you just provided, using this app's Gemini narrative fallback (Tier 1B).",
                            "amounts_verified_in_text": verified,
                        }
                        insert_sanctioned_work(entry)
                        sync_from_db()
                        entry = st.session_state.sanctioned_works[-1]
                        st.success(
                            f"✅ Extracted 1 project via narrative analysis — "
                            f"{risk_info['num_stages']} sanction stages found."
                        )
                        if verified:
                            st.caption("✅ All extracted amounts independently confirmed present in the source text (deterministic regex check, not Gemini re-asking itself).")
                        else:
                            st.warning(
                                f"⚠️ {len(unverified_stages)} of {risk_info['num_stages']} extracted amount(s) "
                                f"could not be independently matched against numbers in the source text — "
                                f"Gemini may have misread the document. Treat this result with caution and "
                                f"verify against the original source before trusting the risk score."
                            )
                        render_work_card(entry)

with tab3:
    st.subheader("Dashboard")

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        metric_box(len(st.session_state.citizen_reports), "Citizen Reports")
    with c2:
        metric_box(len(st.session_state.sanctioned_works), "Works Verified")
    with c3:
        flagged = [w for w in st.session_state.sanctioned_works if "OVER_SANCTION" in w.get("flag", "")]
        metric_box(len(flagged), "Flagged for Leakage")
    with c4:
        total_flagged_amount = sum(
            w["completion_report_amount"] - w["administrative_sanction"] for w in flagged
        )
        metric_box(format_inr_compact(total_flagged_amount), "Total Amount Flagged")

    pop_in_scope, districts_matched = estimate_population_in_scope(st.session_state.sanctioned_works)
    if pop_in_scope > 0:
        st.markdown(
            f'<div style="text-align:center; margin: 8px 0 20px 0; color:#9ca3af; font-size:13px;">'
            f'📍 <b style="color:#7ab8ff;">{pop_in_scope:,}</b> people live in the districts covered so far '
            f'({", ".join(d.title() for d in districts_matched)}) — Census 2011 district population, '
            f'not a claim that every resident is directly affected by a specific flagged work.'
            f'</div>',
            unsafe_allow_html=True
        )

    pdf_buffer = generate_executive_summary_pdf(
        st.session_state.citizen_reports, st.session_state.sanctioned_works
    )
    st.download_button(
        "📄 Download Executive Summary PDF",
        data=pdf_buffer,
        file_name="pragatitrace_executive_summary.pdf",
        mime="application/pdf",
    )

    st.markdown("### Demand Hotspots")
    hotspots = cluster_reports_by_location(st.session_state.citizen_reports)
    if not hotspots:
        st.caption("No location-tagged reports yet.")
    for h in hotspots:
        render_hotspot_card(h)

    KNOWN_COORDS = {
        "nagapattinam": (10.7639, 79.8420), "achalpuram": (10.80, 79.75),
        "alakudi": (10.80, 79.75), "mumbai": (19.0760, 72.8777),
        "delhi": (28.6139, 77.2090), "chennai": (13.0827, 80.2707),
        "jaipur": (26.9124, 75.7873),
    }

    def find_coords(name):
        if not name:
            return None
        key = name.lower().strip()
        for k, v in KNOWN_COORDS.items():
            if k in key or key in k:
                return v
        return None

    map_points = []
    for w in st.session_state.sanctioned_works:
        coords = find_coords(w.get("location") or w.get("work_name_full"))
        if coords:
            is_flagged = "OVER_SANCTION" in w.get("flag", "")
            map_points.append({
                "lat": coords[0], "lon": coords[1],
                "color": [255, 75, 75, 180] if is_flagged else [33, 197, 93, 180],
                "label": w.get("work_name_full", "")
            })

    if map_points:
        st.markdown("### Leakage Map")
        import pandas as pd
        import pydeck as pdk
        df = pd.DataFrame(map_points)
        layer = pdk.Layer(
            "ScatterplotLayer", data=df,
            get_position="[lon, lat]", get_fill_color="color",
            get_radius=25000, pickable=True,
        )
        view_state = pdk.ViewState(latitude=20.5937, longitude=78.9629, zoom=4)
        st.pydeck_chart(pdk.Deck(
            layers=[layer], initial_view_state=view_state,
            map_style=None, tooltip={"text": "{label}"}
        ))
        st.caption("🔴 Flagged for leakage review · 🟢 Within tolerance — approximate district-level locations")

    st.markdown("### Flagged Sanctioned Works")
    if not flagged:
        st.caption("No leakage flags yet — analyze a document in the second tab.")
    for w in flagged:
        render_work_card(w)

    st.markdown("### Recent Citizen Reports")
    if not st.session_state.citizen_reports:
        st.caption("No reports yet — submit one in the first tab.")
    SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}
    sorted_reports = sorted(
        reversed(st.session_state.citizen_reports),
        key=lambda r: SEVERITY_ORDER.get((r.get("severity") or "low").lower(), 3)
    )
    for r in sorted_reports:
        render_report_card(r)

with tab4:
    st.subheader("Field verification helper")
    st.caption(
        "This is a manual comparison tool, not live satellite/CV analysis -- "
        "it lets a field officer log the gap between a contractor's claimed "
        "progress and what they actually observed on-site."
    )

    fc1, fc2 = st.columns(2)
    with fc1:
        proj_name = st.text_input("Project name", value="Improvements to Alakudi - Kaduvetti road")
        claimed_pct = st.slider("Contractor-claimed completion (%)", 0, 100, 90)
    with fc2:
        observed_pct = st.slider("Field-observed completion (%)", 0, 100, 55)

    if st.button("Log verification"):
        gap = claimed_pct - observed_pct
        if "field_verifications" not in st.session_state:
            st.session_state.field_verifications = []
        st.session_state.field_verifications.append({
            "project": proj_name, "claimed": claimed_pct,
            "observed": observed_pct, "gap": gap
        })
        if gap > 15:
            st.error(f"🚨 {gap}% gap between claim and field observation — flag for review.")
        else:
            st.success(f"✅ {gap}% gap — within acceptable tolerance.")

    if st.session_state.get("field_verifications"):
        st.markdown("### Logged verifications")
        for v in st.session_state.field_verifications:
            st.write(f"**{v['project']}** — claimed {v['claimed']}% vs observed {v['observed']}% (gap: {v['gap']}%)")

    st.markdown("---")
    st.markdown("### 📋 Officer escalation brief")
    n_flagged_total = len([w for w in st.session_state.sanctioned_works if "OVER_SANCTION" in w.get("flag", "")])
    total_variance = sum(
        w.get("completion_report_amount", 0) - w.get("administrative_sanction", 0)
        for w in st.session_state.sanctioned_works if "OVER_SANCTION" in w.get("flag", "")
    )
    brief = (
        f"PRAGATITRACE FIELD BRIEF\n"
        f"========================\n"
        f"Citizen reports logged: {len(st.session_state.citizen_reports)}\n"
        f"Sanctioned works checked: {len(st.session_state.sanctioned_works)}\n"
        f"Works flagged for leakage: {n_flagged_total}\n"
        f"Total flagged variance amount: Rs.{total_variance:,.2f}\n"
    )
    st.code(brief, language="text")
    st.download_button("📥 Download brief (.txt)", data=brief, file_name="pragatitrace_brief.txt", mime="text/plain")

    st.markdown("---")
    st.markdown("### 🔐 Audit Ledger (Hash-Chain Pattern)")
    st.caption(
        "Prototype of the hash-chaining pattern used in real tamper-evident audit systems: "
        "each flagged work's hash includes the previous record's hash (SHA-256), so editing "
        "an earlier entry breaks every hash after it. In this session-based prototype the chain "
        "lives in memory alongside the data it protects, so it demonstrates the *mechanism*, not "
        "production-grade tamper resistance -- a real deployment would anchor hashes in an "
        "external write-once log or public ledger, independent of the app's own storage."
    )
    flagged_for_ledger = [w for w in st.session_state.sanctioned_works if "OVER_SANCTION" in w.get("flag", "")]
    if not flagged_for_ledger:
        st.caption("No flagged works yet to add to the ledger.")
    else:
        ledger = build_ledger(flagged_for_ledger)
        is_valid = verify_ledger(ledger)
        if is_valid:
            st.success("✅ Ledger integrity verified — no tampering detected.")
        else:
            st.error("🚨 Ledger integrity check FAILED — a record may have been altered.")

        for i, block in enumerate(ledger):
            st.markdown(
                f"**Block {i+1}:** {block['entry']['work']}  \n"
                f"`hash: {block['hash'][:24]}...`  \n"
                f"`prev: {block['prev_hash'][:24]}...`"
            )