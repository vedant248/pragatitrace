import pathlib
try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:
    import tomli as tomllib  # pip install tomli  (Python <3.11)

from google import genai

secrets = tomllib.loads(pathlib.Path(".streamlit/secrets.toml").read_text())
key = secrets.get("GEMINI_API_KEY")
if not key:
    raise SystemExit('GEMINI_API_KEY not found in .streamlit/secrets.toml (expected: GEMINI_API_KEY = "your-key")')

client = genai.Client(api_key=key)

def why(e):
    s = str(e)
    if "API key not valid" in s: return "BAD KEY - copy it again from AI Studio"
    if "PerDay" in s: return "OUT OF QUOTA (daily limit used up)"
    if "PerMinute" in s: return "OUT OF QUOTA (per-minute limit - wait a minute)"
    if "429" in s or "quota" in s.lower(): return "OUT OF QUOTA"
    if "404" in s or "NOT_FOUND" in s: return "model not available to this key"
    if "503" in s: return "Google overloaded (temporary)"
    return s[:100]

# Keep this list in sync with app.py's MODEL / FALLBACK_MODELS and
# universal_ingest.py's MODEL_NAME / FALLBACK_MODEL_NAMES.
MODELS_TO_CHECK = ["gemini-3.5-flash", "gemini-3.5-flash-lite", "gemini-2.5-flash"]

any_worked = False
for m in MODELS_TO_CHECK:
    try:
        client.models.generate_content(model=m, contents="Reply OK")
        print("WORKS ", m)
        any_worked = True
    except Exception as e:
        print("FAILS ", m, "->", why(e))

if not any_worked:
    print("\nWARNING: none of the configured models work with this key. "
          "The app WILL fail on every Gemini call until this is fixed.")