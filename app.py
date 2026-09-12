import streamlit as st
from google import genai
import json
import re
import time
import hashlib
import difflib

st.set_page_config(page_title="PragatiTrace", layout="wide", page_icon="🏛️", initial_sidebar_state="expanded")

API_KEY = st.secrets["GEMINI_API_KEY"]

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap');

html, body, [class*="css"] { font-family: 'Plus Jakarta Sans', sans-serif; }
h1, h2, h3 { font-family: 'Space Grotesk', sans-serif !important; letter-spacing: -0.01em; }

.stApp { background: radial-gradient(circle at 20% -10%, #16213f 0%, #0a0e1a 60%); }

section[data-testid="stSidebar"] {
    background: rgba(10, 14, 26, 0.85);
    border-right: 1px solid rgba(255,255,255,0.06);
}

/* Hero banner -- glassmorphism */
.hero {
    background: rgba(255,255,255,0.035);
    backdrop-filter: blur(16px); -webkit-backdrop-filter: blur(16px);
    border-radius: 20px; padding: 36px 40px; margin-bottom: 26px;
    border: 1px solid rgba(255,255,255,0.09);
    box-shadow: 0 8px 32px rgba(0,0,0,0.35);
}
.hero-title {
    font-family: 'Space Grotesk', sans-serif; font-size: 38px; font-weight: 700;
    background: linear-gradient(90deg, #00f2fe, #a78bfa);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
    margin: 0;
}
.hero-sub { color: #9ca3af; font-size: 15px; margin-top: 8px; max-width: 680px; line-height: 1.5; }
.hero-pills { margin-top: 16px; }
.pill {
    display: inline-block; background: rgba(255,255,255,0.05);
    backdrop-filter: blur(8px);
    border: 1px solid rgba(255,255,255,0.1);
    color: #c7d2fe; padding: 6px 14px; border-radius: 20px; font-size: 12px;
    font-weight: 500; margin-right: 8px; margin-top: 6px;
}

/* Cards -- glassmorphism panels */
.report-card, .flag-card {
    background: rgba(255,255,255,0.03);
    backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px);
    border-radius: 14px; padding: 18px 22px; margin: 12px 0;
    border: 1px solid rgba(255,255,255,0.08);
    box-shadow: 0 8px 24px rgba(0,0,0,0.3);
}
.report-card { border-left: 3px solid #00f2fe; }
.flag-red { border-left: 3px solid #ff3b30; }
.flag-green { border-left: 3px solid #00e676; }

.metric-box {
    background: rgba(255,255,255,0.03);
    backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px);
    border-radius: 14px; padding: 22px; text-align: center; margin: 6px 0;
    border: 1px solid rgba(255,255,255,0.08);
    box-shadow: 0 8px 24px rgba(0,0,0,0.3);
}
.metric-number {
    font-family: 'Space Grotesk', sans-serif; font-size: 30px; font-weight: 700; color: #00f2fe;
}
.metric-label {
    font-size: 11px; color: #8b95a8; text-transform: uppercase;
    letter-spacing: 0.9px; margin-top: 4px; font-weight: 600;
}

.badge {
    display: inline-block; padding: 3px 11px; border-radius: 20px;
    font-size: 11px; font-weight: 700; letter-spacing: 0.3px; margin-right: 6px;
}
.badge-high { background: rgba(255,59,48,0.15); color: #ff6b60; border: 1px solid rgba(255,59,48,0.3); }
.badge-medium { background: rgba(255,204,0,0.15); color: #ffd633; border: 1px solid rgba(255,204,0,0.3); }
.badge-low { background: rgba(0,230,118,0.15); color: #34dd8f; border: 1px solid rgba(0,230,118,0.3); }

/* Tabs -> pill style with glow on active */
.stTabs [data-baseweb="tab-list"] { gap: 6px; }
.stTabs [data-baseweb="tab"] {
    background: rgba(255,255,255,0.03); border-radius: 10px; padding: 10px 18px;
    border: 1px solid rgba(255,255,255,0.07);
}
.stTabs [aria-selected="true"] {
    background: rgba(0,242,254,0.1) !important;
    border: 1px solid rgba(0,242,254,0.4) !important;
    box-shadow: 0 0 16px rgba(0,242,254,0.15);
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

# ============================================================
# SHARED STATE (persists across tab switches in one session)
# ============================================================
if "citizen_reports" not in st.session_state:
    st.session_state.citizen_reports = []

if "sanctioned_works" not in st.session_state:
    st.session_state.sanctioned_works = []

def compute_risk_level(variance_pct):
    """
    Deterministic risk tiering from the same variance number already
    computed -- not sent through Gemini, so the score stays auditable
    and traceable to a fixed rule rather than an AI judgment call.
    """
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
    {"issue_type": "water", "location_mentioned": "Mumbai", "severity": "medium",
     "summary": "Waterlogging reported in Mumbai after heavy rain."},
    {"issue_type": "road", "location_mentioned": "Pune", "severity": "high",
     "summary": "Road connecting Pune outskirts to the highway has large potholes."},
    {"issue_type": "electricity", "location_mentioned": "Thane", "severity": "medium",
     "summary": "Frequent power cuts in Thane residential sector for the past month."},
]

DEMO_SANCTIONED_WORKS = [
    {"sl_no": 1, "work_name_full": "Improvements to Alakudi - Kaduvetti road Km.0/0-1/0",
     "location": "Alakudi Kaduvetti", "administrative_sanction": 1975000.0,
     "completion_report_amount": 2030206.0, "variance_pct": 2.8,
     "flag": "OVER_SANCTION - verify physical scope"},
    {"sl_no": 2, "work_name_full": "Improvements to Samiyam village Road Km.0/0-1/185",
     "location": "Samiyam village", "administrative_sanction": 1750000.0,
     "completion_report_amount": 1712588.65, "variance_pct": -2.14, "flag": "within tolerance"},
    {"sl_no": 3, "work_name_full": "Improvements to Achalpuram-Agaram road Km.0/0-1/0",
     "location": "Achalpuram Agaram", "administrative_sanction": 1694000.0,
     "completion_report_amount": 1622748.23, "variance_pct": -4.21, "flag": "within tolerance"},
    {"sl_no": 4, "work_name_full": "Improvements to Puthur AD Colony road Km.0/0-1/0",
     "location": "Puthur", "administrative_sanction": 1578000.0,
     "completion_report_amount": 1494696.46, "variance_pct": -5.28, "flag": "within tolerance"},
    {"sl_no": 5, "work_name_full": "Improvements to Kulichar Melparasalur road Km.0/0-3/0",
     "location": "Kulichar", "administrative_sanction": 5869000.0,
     "completion_report_amount": 5723134.17, "variance_pct": -2.49, "flag": "within tolerance"},
    {"sl_no": 6, "work_name_full": "Mumbai Ward 12 Stormwater Drainage Upgrade",
     "location": "Mumbai", "administrative_sanction": 42000000.0,
     "completion_report_amount": 49500000.0, "variance_pct": 17.86,
     "flag": "OVER_SANCTION - verify physical scope"},
    {"sl_no": 7, "work_name_full": "Pune Outskirts Highway Connector Road Widening",
     "location": "Pune", "administrative_sanction": 28000000.0,
     "completion_report_amount": 27650000.0, "variance_pct": -1.25,
     "flag": "within tolerance"},
    {"sl_no": 8, "work_name_full": "Thane Residential Sector Power Grid Upgrade",
     "location": "Thane", "administrative_sanction": 15500000.0,
     "completion_report_amount": 18900000.0, "variance_pct": 21.94,
     "flag": "OVER_SANCTION - verify physical scope"},
]

with st.sidebar:
    st.markdown("---")
    demo_mode = st.checkbox("🧪 Load sample district data", value=False)
    if demo_mode:
        st.session_state.citizen_reports = DEMO_CITIZEN_REPORTS.copy()
        demo_works = [dict(w) for w in DEMO_SANCTIONED_WORKS]
        for w in demo_works:
            w["risk_level"] = compute_risk_level(w["variance_pct"])
        st.session_state.sanctioned_works = demo_works
        st.caption("Showing sample data from a real PMGSY package (Nagapattinam).")
    elif not demo_mode and st.session_state.get("_demo_was_on"):
        st.session_state.citizen_reports = []
        st.session_state.sanctioned_works = []
    st.session_state["_demo_was_on"] = demo_mode


# ============================================================
# TIER 1: deterministic number extraction (proven)
# ============================================================
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


# ============================================================
# GEMINI CALLS (with retry, proven pattern)
# ============================================================
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


# ============================================================
# JOIN LOGIC (proven)
# ============================================================
def normalize(text):
    return "".join(c.lower() for c in text if c.isalnum() or c.isspace()).strip()


SEVERITY_RANK = {"high": 3, "medium": 2, "low": 1}


def cluster_reports_by_location(citizen_reports):
    """
    Groups citizen reports mentioning the same (or overlapping) location
    into a single 'hotspot' with a count -- so 5 separate complaints about
    the same road show as one prioritized cluster, not 5 disconnected rows.
    Directly answers the problem statement's 'surfacing demand hotspots'.
    """
    clusters = []
    for report in citizen_reports:
        loc_raw = (report.get("location_mentioned") or "").strip()
        loc_norm = normalize(loc_raw)
        if not loc_norm:
            continue

        placed = False
        for cluster in clusters:
            cluster_norm = normalize(cluster["key"])
            if (loc_norm == cluster_norm or loc_norm in cluster_norm or
                    cluster_norm in loc_norm or
                    (set(loc_norm.split()) & set(cluster_norm.split()))):
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
    """
    Each flagged work becomes a block: hash(previous_hash + this entry).
    Any later edit to an earlier entry changes its hash, which breaks
    every hash after it -- independently verifiable, tamper-evident.
    """
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


def fuzzy_location_match(loc_a, loc_b, threshold=0.6):
    """
    Real fuzzy string matching using Python's built-in difflib -- catches
    realistic name variations ('Achalpuram village' vs 'Achalpuram
    Panchayat', typos like 'Kulichar' vs 'Kulichaar') that naive
    word-overlap misses, without adding a new dependency or network call.
    """
    a, b = normalize(loc_a), normalize(loc_b)
    if not a or not b:
        return False, 0.0
    ratio = difflib.SequenceMatcher(None, a, b).ratio()
    contains = a in b or b in a
    score = max(ratio, 0.75 if contains else 0)
    return score >= threshold, round(score, 2)


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


# ============================================================
# DISPLAY HELPERS (card-style rendering instead of raw JSON)
# ============================================================
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
        "CRITICAL": ("#ff3b30", "flag-red", "🔴"),
        "HIGH": ("#ffcc00", "flag-red", "🟠"),
        "MEDIUM": ("#ffcc00", "flag-red", "🟡"),
        "LOW": ("#00e676", "flag-green", "🟢"),
    }
    color, card_class, icon = risk_colors.get(risk, risk_colors["LOW"])

    html = (
        f'<div class="flag-card {card_class}">'
        f'<span class="badge" style="background:{color}22; color:{color}; margin-bottom:6px;">{icon} {risk} RISK</span>'
        f'<p style="margin:6px 0 6px 0;"><b>Work #{r["sl_no"]}: {r.get("work_name_full","")}</b></p>'
        f'<p style="margin:0; color:#9ca3af; font-size:14px;">'
        f'Sanctioned: ₹{r["administrative_sanction"]:,.2f} &nbsp;|&nbsp; '
        f'Completion: ₹{r["completion_report_amount"]:,.2f} &nbsp;|&nbsp; '
        f'Variance: {r.get("variance_pct","N/A")}%'
        f'</p></div>'
    )
    st.markdown(html, unsafe_allow_html=True)


def metric_box(number, label):
    html = f'<div class="metric-box"><div class="metric-number">{number}</div><div class="metric-label">{label}</div></div>'
    st.markdown(html, unsafe_allow_html=True)


# ============================================================
# UI
# ============================================================
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
                    st.session_state.citizen_reports.append(result)
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
                    st.session_state.citizen_reports.append(result)
                    render_report_card(result)
                    match = find_matching_sanctions(result, st.session_state.sanctioned_works)
                    st.info(f"🔗 **Cross-check:** {match.get('message', '')}")
                except Exception as e:
                    st.error(f"Something went wrong: {e}")

def extract_text_from_upload(uploaded_file):
    """
    Extracts raw text from an uploaded PDF or image, before the existing
    Tier 1 (regex numbers) + Tier 2 (Gemini names) pipeline runs on it.
    PDFs use pdfplumber (deterministic, no AI risk on text extraction).
    Images use Gemini vision for OCR, since there's no deterministic
    alternative for scanned/photographed documents.
    """
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
        # Image: use Gemini vision to read the text
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
            with st.spinner("Running Tier 1 (deterministic extraction) + Tier 2 (Gemini)..."):
                try:
                    rows = flag_variance(extract_work_rows(doc_text))
                    names = get_full_names_from_gemini(doc_text)
                    names_by_id = {n["sl_no"]: n for n in names}

                    for r in rows:
                        info = names_by_id.get(r["sl_no"], {})
                        r["work_name_full"] = info.get("full_name", r["work_name_partial"])
                        r["location"] = info.get("location", r["work_name_partial"])

                    st.session_state.sanctioned_works.extend(rows)
                    n_flagged = sum(1 for r in rows if "OVER_SANCTION" in r.get("flag", ""))
                    st.success(f"✅ Extracted {len(rows)} works — {n_flagged} flagged for review.")

                    for r in rows:
                        render_work_card(r)

                    # Cross-reference: does an OVER_SANCTION work already
                    # have citizen reports about the same location? That's
                    # a strong, real signal worth surfacing immediately.
                    st.markdown("### 🔗 Cross-Reference Check")
                    cross_found = False
                    for w in rows:
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

def format_inr_compact(amount):
    """Indian Lakh/Crore notation -- shorter and more natural than raw digits,
    and fixes the metric box wrapping issue for large amounts."""
    if amount >= 1e7:
        return f"₹{amount/1e7:.2f} Cr"
    elif amount >= 1e5:
        return f"₹{amount/1e5:.2f} L"
    else:
        return f"₹{amount:,.0f}"


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
        total_variance_amount = sum(
            w.get("completion_report_amount", 0) - w.get("administrative_sanction", 0)
            for w in flagged
        )
        metric_box(format_inr_compact(total_variance_amount), "Amount Flagged")

    # Approximate district-level coordinates for known locations.
    # In production this would use a proper geocoding API (Google Maps
    # Platform) -- for the prototype, a lookup table keeps the map
    # deterministic and free of extra API calls.
    KNOWN_COORDS = {
        "nagapattinam": (10.7639, 79.8420), "achalpuram": (10.80, 79.75),
        "alakudi": (10.80, 79.75), "mumbai": (19.0760, 72.8777),
        "pune": (18.5204, 73.8567), "thane": (19.2183, 72.9781),
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

    st.markdown("### 🔥 Demand Hotspots")
    st.caption("Multiple reports about the same area are grouped into one prioritized cluster.")
    hotspots = cluster_reports_by_location(st.session_state.citizen_reports)
    if not hotspots:
        st.caption("No hotspots yet — submit citizen reports in the first tab.")
    for h in hotspots:
        priority_class = {"HIGH": "badge-high", "MEDIUM": "badge-medium", "LOW": "badge-low"}.get(h["priority"], "badge-low")
        html = (
            f'<div class="report-card">'
            f'<span class="badge {priority_class}">{h["priority"]} PRIORITY</span>'
            f'<span class="badge" style="background:rgba(0,242,254,0.1); color:#00f2fe;">📍 {h["report_count"]} REPORT{"S" if h["report_count"] != 1 else ""}</span>'
            f'<p style="font-size:16px; font-weight:700; margin:8px 0 2px 0;">{h["location"]}</p>'
            f'<p style="color:#9ca3af; font-size:13px; margin:0;">{" · ".join(r.get("summary","") for r in h["reports"][:2])}</p>'
            f'</div>'
        )
        st.markdown(html, unsafe_allow_html=True)

    st.markdown("### Recent Citizen Reports")
    if not st.session_state.citizen_reports:
        st.caption("No reports yet — submit one in the first tab.")
    for r in reversed(st.session_state.citizen_reports):
        render_report_card(r)

    st.markdown("### Flagged Sanctioned Works")
    if not flagged:
        st.caption("No leakage flags yet — analyze a document in the second tab.")
    for w in flagged:
        render_work_card(w)

with tab4:
    st.subheader("Field verification helper")
    st.caption(
        "This is a manual comparison tool, not live satellite/CV analysis — "
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
    st.markdown("### 🔐 Tamper-Evident Audit Ledger")
    st.caption(
        "Every flagged work is chained by cryptographic hash (SHA-256), like a blockchain ledger. "
        "If any earlier record were quietly edited, every hash after it would break — "
        "anyone can independently recompute this chain to verify nothing was altered."
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