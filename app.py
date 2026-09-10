import streamlit as st
from google import genai
import json
import re
import time

st.set_page_config(page_title="PragatiTrace", layout="wide", page_icon="🏛️", initial_sidebar_state="expanded")

API_KEY = st.secrets["GEMINI_API_KEY"]

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;700&family=Inter:wght@400;500;600&display=swap');

html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
h1, h2, h3 { font-family: 'Space Grotesk', sans-serif !important; }

.stApp { background: radial-gradient(circle at 15% 0%, #131b2e 0%, #0b0e14 55%); }

/* Hero banner */
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

/* Cards */
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

/* Tabs -> pill style */
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
    st.markdown("""
    **How it works**
    1. 📣 Citizens report a problem — by voice or text, in their own language
    2. 🔍 The system reads real government sanction papers and checks the numbers
    3. 🔗 It matches the two, so you can see if a funded project was actually finished
    """)
    st.markdown("---")
    st.caption("Built for Build with AI: Code for Communities — Google Cloud Hackathon")
    st.caption("Powered by Gemini")

st.markdown("""
<div class="hero">
    <p class="hero-title">PragatiTrace</p>
    <p class="hero-sub">Citizens report infrastructure problems. We check them against real
    government spending records to see if the money was actually spent where it should have been.</p>
    <div class="hero-pills">
        <span class="pill">🎙️ Voice and text, any language</span>
        <span class="pill">🤖 Real Gemini AI</span>
        <span class="pill">📄 Real government data</span>
        <span class="pill">🇮🇳 Works for any Indian state</span>
    </div>
</div>
""", unsafe_allow_html=True)

# ============================================================
# SHARED STATE (persists across tab switches in one session)
# ============================================================
if "citizen_reports" not in st.session_state:
    st.session_state.citizen_reports = []

if "sanctioned_works" not in st.session_state:
    st.session_state.sanctioned_works = []


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


def find_matching_sanctions(citizen_report, sanctioned_works):
    report_loc = normalize(citizen_report.get("location_mentioned") or "")
    if not report_loc:
        return {"status": "NO_LOCATION_DETECTED", "matches": []}

    matches = []
    for work in sanctioned_works:
        work_loc = normalize(work.get("location", ""))
        if not work_loc:
            continue
        if report_loc in work_loc or work_loc in report_loc:
            matches.append(work)
        else:
            if set(report_loc.split()) & set(work_loc.split()):
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

    transcript_html = ""
    if result.get("transcript"):
        transcript_html = f'<p style="color:#9ca3af; font-style:italic; margin:6px 0;">"{result["transcript"]}"</p>'

    st.markdown(f"""
    <div class="report-card">
        <span class="badge {badge_class}">{sev.upper()} PRIORITY</span>
        <span class="badge" style="background:#1e293b;color:#93c5fd;">{icon} {result.get('issue_type','?').upper()}</span>
        {transcript_html}
        <p style="font-size:16px; margin:8px 0 4px 0;"><b>{result.get('summary','')}</b></p>
        <p style="color:#9ca3af; font-size:13px; margin:0;">📍 {result.get('location_mentioned') or 'Location not detected'}</p>
    </div>
    """, unsafe_allow_html=True)


def render_work_card(r):
    is_flagged = "OVER_SANCTION" in r.get("flag", "")
    card_class = "flag-red" if is_flagged else "flag-green"
    icon = "🔴" if is_flagged else "🟢"
    status = "FLAGGED — verify physical scope" if is_flagged else "Within tolerance"

    st.markdown(f"""
    <div class="flag-card {card_class}">
        <p style="margin:0 0 6px 0;">{icon} <b>Work #{r['sl_no']}: {r.get('work_name_full','')}</b></p>
        <p style="margin:0; color:#9ca3af; font-size:14px;">
            Sanctioned: ₹{r['administrative_sanction']:,.2f} &nbsp;|&nbsp;
            Completion: ₹{r['completion_report_amount']:,.2f} &nbsp;|&nbsp;
            Variance: {r.get('variance_pct','N/A')}%
        </p>
        <p style="margin:4px 0 0 0; font-weight:600; color:{'#ff8787' if is_flagged else '#8ce99a'};">{status}</p>
    </div>
    """, unsafe_allow_html=True)


def metric_box(number, label):
    st.markdown(f"""
    <div class="metric-box">
        <div class="metric-number">{number}</div>
        <div class="metric-label">{label}</div>
    </div>
    """, unsafe_allow_html=True)


# ============================================================
# UI
# ============================================================
st.title("🛣️ PragatiTrace")
st.caption("Real citizen complaints, checked against real government spending records")

tab1, tab2, tab3 = st.tabs(["📣 Report an Issue", "🔍 Check a Sanction Order", "📊 Dashboard"])

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

with tab2:
    st.subheader("Check a government sanction order for leakage")
    st.caption("Paste text from a PMGSY or JJM sanction order PDF.")

    doc_text = st.text_area(
        "Document text:",
        height=220,
        placeholder="Paste the extracted text of a sanction order...",
        label_visibility="collapsed"
    )
    if st.button("Analyze Document", type="primary"):
        if not doc_text.strip():
            st.warning("Please paste a document first.")
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
                except Exception as e:
                    st.error(f"Something went wrong: {e}")

with tab3:
    st.subheader("Dashboard")

    c1, c2, c3 = st.columns(3)
    with c1:
        metric_box(len(st.session_state.citizen_reports), "Citizen Reports")
    with c2:
        metric_box(len(st.session_state.sanctioned_works), "Works Verified")
    with c3:
        flagged = [w for w in st.session_state.sanctioned_works if "OVER_SANCTION" in w.get("flag", "")]
        metric_box(len(flagged), "Flagged for Leakage")

    # Approximate district-level coordinates for known locations.
    # In production this would use a proper geocoding API (Google Maps
    # Platform) -- for the prototype, a lookup table keeps the map
    # deterministic and free of extra API calls.
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