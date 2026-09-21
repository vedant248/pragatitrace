import re, pathlib
from google import genai

key = re.search(r'GEMINI_API_KEY\s*=\s*"(.+?)"', pathlib.Path(".streamlit/secrets.toml").read_text()).group(1)
client = genai.Client(api_key=key)

def why(e):
    s = str(e)
    if "API key not valid" in s: return "BAD KEY - copy it again from AI Studio"
    if "PerDay" in s: return "OUT OF QUOTA (daily limit used up)"
    if "PerMinute" in s: return "OUT OF QUOTA (per-minute limit - wait a minute)"
    if "429" in s or "quota" in s.lower(): return "OUT OF QUOTA"
    if "404" in s: return "model not available to this key"
    if "503" in s: return "Google overloaded (temporary)"
    return s[:100]

for m in ["gemini-3.6-flash", "gemini-3.5-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-2.5-flash"]:
    try:
        client.models.generate_content(model=m, contents="Reply OK")
        print("WORKS ", m)
    except Exception as e:
        print("FAILS ", m, "->", why(e))