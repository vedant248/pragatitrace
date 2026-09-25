"""India geography helpers: state/UT detection and Census 2011 populations (all 36 states/UTs)."""
import re

# Census 2011. Telangana is shown separately; Andhra Pradesh is the residual state.
# J&K excludes Ladakh (UT since 2019).
STATE_POPULATION_2011 = {
    "Andaman and Nicobar Islands": 380581, "Andhra Pradesh": 49577103, "Arunachal Pradesh": 1383727,
    "Assam": 31205576, "Bihar": 104099452, "Chandigarh": 1055450, "Chhattisgarh": 25545198,
    "Dadra and Nagar Haveli and Daman and Diu": 585764, "Delhi": 16787941, "Goa": 1458545,
    "Gujarat": 60439692, "Haryana": 25351462, "Himachal Pradesh": 6864602,
    "Jammu and Kashmir": 12267013, "Jharkhand": 32988134, "Karnataka": 61095297, "Kerala": 33406061,
    "Ladakh": 274289, "Lakshadweep": 64473, "Madhya Pradesh": 72626809, "Maharashtra": 112374333,
    "Manipur": 2855794, "Meghalaya": 2966889, "Mizoram": 1097206, "Nagaland": 1978502,
    "Odisha": 41974218, "Puducherry": 1247953, "Punjab": 27743338, "Rajasthan": 68548437,
    "Sikkim": 610577, "Tamil Nadu": 72147030, "Telangana": 35003674, "Tripura": 3673917,
    "Uttar Pradesh": 199812341, "Uttarakhand": 10086292, "West Bengal": 91276115,
}

_ALIASES = {
    "Jammu and Kashmir": ["jammu & kashmir", "jammu and kashmir"],
    "Andaman and Nicobar Islands": ["andaman"],
    "Dadra and Nagar Haveli and Daman and Diu": ["dadra", "daman"],
    "Odisha": ["orissa"], "Puducherry": ["pondicherry"], "Delhi": ["new delhi"],
    "Uttarakhand": ["uttaranchal"],
    # a few major cities/districts so short documents without a state header still tag correctly
    "Maharashtra": ["mumbai", "pune", "thane", "nagpur", "nashik"],
    "Tamil Nadu": ["chennai", "nagapattinam", "madurai", "coimbatore"],
    "Karnataka": ["bengaluru", "bangalore", "mysuru"], "Telangana": ["hyderabad"],
    "West Bengal": ["kolkata"], "Gujarat": ["ahmedabad", "surat"], "Rajasthan": ["jaipur"],
    "Uttar Pradesh": ["lucknow", "varanasi"], "Bihar": ["patna"], "Kerala": ["thiruvananthapuram", "kochi"],
}


def _patterns():
    out = {}
    for state in STATE_POPULATION_2011:
        names = {state.lower(), *_ALIASES.get(state, [])}
        out[state] = re.compile(r"\b(?:" + "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True)) + r")\b")
    return out


_PATTERNS = _patterns()


def detect_state(text):
    """Most-mentioned state/UT in the text, or None. Deterministic (no API call)."""
    t = (text or "").lower()
    if not t:
        return None
    counts = {s: len(p.findall(t)) for s, p in _PATTERNS.items()}
    best = max(counts, key=counts.get)
    return best if counts[best] else None


def population_of_states(states):
    return sum(STATE_POPULATION_2011.get(s, 0) for s in set(states))