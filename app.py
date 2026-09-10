import streamlit as st
from google import genai
import json
import re
import time

st.set_page_config(page_title="PragatiTrace", layout="wide")

API_KEY = st.secrets["GEMINI_API_KEY"]
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
# UI
# ============================================================
st.title("PragatiTrace")
st.caption("Aligning citizen infrastructure demand with verified government spending")

tab1, tab2, tab3 = st.tabs(["Report an Issue", "Check a Sanction Order", "Dashboard"])

with tab1:
    st.subheader("Report an infrastructure issue")
    complaint = st.text_area(
        "Describe the issue (any language, e.g. Hindi/English mixed is fine):",
        placeholder="Sir humare gaon Achalpuram mein road bahut kharab hai..."
    )
    if st.button("Submit Report"):
        if not complaint.strip():
            st.warning("Please describe the issue first.")
        else:
            with st.spinner("Classifying with Gemini..."):
                try:
                    result = classify_report(complaint)
                    st.session_state.citizen_reports.append(result)
                    st.success("Report classified and logged.")
                    st.json(result)

                    match = find_matching_sanctions(result, st.session_state.sanctioned_works)
                    st.subheader("Cross-check against sanctioned projects")
                    st.info(match.get("message", ""))
                except Exception as e:
                    st.error(f"Something went wrong: {e}")

with tab2:
    st.subheader("Check a government sanction order for leakage")
    doc_text = st.text_area(
        "Paste the sanction order text here:",
        height=250,
        placeholder="Paste the extracted text of a PMGSY/JJM sanction order..."
    )
    if st.button("Analyze Document"):
        if not doc_text.strip():
            st.warning("Please paste a document first.")
        else:
            with st.spinner("Running Tier 1 extraction..."):
                rows = flag_variance(extract_work_rows(doc_text))

            with st.spinner("Running Tier 2 (Gemini name + location extraction)..."):
                try:
                    names = get_full_names_from_gemini(doc_text)
                    names_by_id = {n["sl_no"]: n for n in names}

                    for r in rows:
                        info = names_by_id.get(r["sl_no"], {})
                        r["work_name_full"] = info.get("full_name", r["work_name_partial"])
                        r["location"] = info.get("location", r["work_name_partial"])

                    st.session_state.sanctioned_works.extend(rows)
                    st.success(f"Extracted {len(rows)} works.")

                    for r in rows:
                        flag_color = "🔴" if "OVER_SANCTION" in r.get("flag", "") else "🟢"
                        st.write(f"{flag_color} **Work #{r['sl_no']}: {r['work_name_full']}**")
                        st.write(
                            f"Sanctioned: Rs.{r['administrative_sanction']:,.2f} | "
                            f"Completion: Rs.{r['completion_report_amount']:,.2f} | "
                            f"Variance: {r.get('variance_pct', 'N/A')}% | {r.get('flag', 'N/A')}"
                        )
                except Exception as e:
                    st.error(f"Something went wrong: {e}")

with tab3:
    st.subheader("Dashboard")
    col1, col2 = st.columns(2)

    with col1:
        st.write(f"**Citizen Reports Logged:** {len(st.session_state.citizen_reports)}")
        for r in st.session_state.citizen_reports:
            st.write(f"- {r.get('issue_type', '?')} in {r.get('location_mentioned', '?')} ({r.get('severity', '?')})")

    with col2:
        st.write(f"**Sanctioned Works Verified:** {len(st.session_state.sanctioned_works)}")
        flagged = [w for w in st.session_state.sanctioned_works if "OVER_SANCTION" in w.get("flag", "")]
        st.write(f"**Flagged for leakage review:** {len(flagged)}")
        for w in flagged:
            st.write(f"- {w.get('work_name_full', '?')}: {w.get('variance_pct', '?')}% over")