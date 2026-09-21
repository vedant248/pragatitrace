"""
universal_ingest.py
--------------------
Drop-in module for PragatiTrace.

Purpose: handle ANY sanction/completion document your parser hasn't seen
before, without crashing and without silently pretending to understand
something it doesn't. Every document gets a verdict:

    "variance_pair"      -> classic sanctioned-vs-completed, risk score computed
    "narrative_anomaly"  -> no clean numeric pair, but the text itself names
                             an irregularity (cost inflation, delay, action
                             ordered) -> extracted as a qualitative flag
    "batch_aggregate"     -> a real sanction, but batch-level with no
                             completion data -> logged as coverage, not scored
    "unreadable"          -> OCR/text extraction failed or text too sparse
                             to say anything -> flagged for manual review
    "no_findings"         -> readable, but nothing matches any known pattern
                             -> flagged for manual review, not discarded
    "quota_exceeded"      -> Gemini's API quota (e.g. free-tier daily limit)
                             is exhausted -- distinct from "unreadable" so
                             this doesn't get misdiagnosed as a document
                             problem when it's actually a billing/quota one

Nothing in this module ever raises out to the caller. Every function
returns a result dict with a "status" key. If Gemini errors, times out,
returns malformed JSON, or returns nothing usable, the pipeline still
returns a valid result object explaining exactly what happened.

Integrate by importing `process_document` and calling it wherever you
currently call your Tier 1 / Tier 2 extraction on uploaded text.
"""

from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Optional

from google import genai

MODEL_NAME = "gemini-3.5-flash"
MAX_RETRIES = 2
RETRY_DELAY_SECONDS = 1.5
MIN_MEANINGFUL_CHARS = 80  # below this, treat as unreadable rather than guess


# ---------------------------------------------------------------------------
# Result shape — every path returns this, so downstream code (risk scoring,
# ledger, UI) only ever has to branch on `status`, never guess a shape.
# ---------------------------------------------------------------------------

@dataclass
class IngestResult:
    status: str                     # one of the five statuses above
    source_excerpt: str = ""        # short excerpt for manual review / audit trail
    data: dict[str, Any] = field(default_factory=dict)
    tier_used: str = ""             # "tier1_regex" / "tier2_gemini" / "none"
    notes: str = ""                 # human-readable explanation, always filled in


# ---------------------------------------------------------------------------
# Tier 1: your existing deterministic regex, called first because it's free,
# fast, and fully auditable. Wrapped so a regex crash can't take down the
# pipeline. Replace the body with your actual Tier 1 function's logic, or
# import it directly (`from your_module import tier1_extract`) and call that
# instead of the placeholder below.
# ---------------------------------------------------------------------------

def _tier1_extract_variance_pair(text: str) -> Optional[dict]:
    """
    Looks for a classic 'sanctioned ... completed/disbursed' rupee pair in
    the same work entry. Returns None (not an exception) if no confident
    match is found — that's a normal outcome, not a failure.
    """
    try:
        # Placeholder pattern — swap in your real, already-tested Tier 1
        # regex here. Keeping this permissive but conservative: it only
        # fires when BOTH a sanctioned figure and a completed/disbursed
        # figure appear near each other.
        sanction_pattern = re.compile(
            r"sanction(?:ed)?[^\d₹]{0,40}(?:Rs\.?|₹)\s?([\d,]+(?:\.\d+)?)\s*(crore|lakh)?",
            re.IGNORECASE,
        )
        completed_pattern = re.compile(
            r"(?:completed|disbursed|expenditure)[^\d₹]{0,40}(?:Rs\.?|₹)\s?([\d,]+(?:\.\d+)?)\s*(crore|lakh)?",
            re.IGNORECASE,
        )

        sanction_match = sanction_pattern.search(text)
        completed_match = completed_pattern.search(text)

        if sanction_match and completed_match:
            return {
                "sanctioned_raw": sanction_match.group(0),
                "completed_raw": completed_match.group(0),
            }
        return None
    except Exception:
        # Regex should never throw on well-formed input, but if it does
        # (unexpected encoding, etc.), treat it as "no match" rather than
        # crash the pipeline.
        return None


# ---------------------------------------------------------------------------
# Tier 2: Gemini calls, each wrapped with retry + safe JSON parsing.
# Every _gemini_* function returns None on total failure — never raises.
# ---------------------------------------------------------------------------

def _extract_json_object(raw_text):
    """
    Pulls the outermost {...} object out of a response even when the
    model wraps it in extra prose or markdown despite being told not to
    (e.g. "Here's the classification: {...}"). Strips code fences first,
    then falls back to a brace-matching scan for the first complete JSON
    object in the text -- this is what actually fixes cases where the
    model adds a sentence around otherwise-valid JSON.
    """
    cleaned = re.sub(r"```json\s*|```", "", raw_text).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    start = cleaned.find("{")
    if start == -1:
        raise json.JSONDecodeError("no opening brace found", cleaned, 0)

    depth = 0
    for i in range(start, len(cleaned)):
        if cleaned[i] == "{":
            depth += 1
        elif cleaned[i] == "}":
            depth -= 1
            if depth == 0:
                candidate = cleaned[start:i + 1]
                return json.loads(candidate)  # let a real failure raise here

    raise json.JSONDecodeError("no matching closing brace found", cleaned, start)


class QuotaExceededError(Exception):
    """Raised when Gemini's API reports quota/rate-limit exhaustion (429
    RESOURCE_EXHAUSTED). This is distinct from a generic API error or a
    document-quality problem -- retrying won't help until the quota
    resets, so callers should stop immediately rather than burn more
    attempts (and more wall-clock time) against a wall that isn't moving."""
    pass


def _call_gemini_json(client: "genai.Client", prompt: str) -> Optional[dict]:
    """
    Calls Gemini expecting a JSON object back. Retries on transient
    failure, robustly extracts the JSON object even if wrapped in extra
    prose or markdown, and returns None (not an exception) if parsing
    ultimately fails. Raises QuotaExceededError immediately (no retries)
    if the failure is specifically a quota/rate-limit exhaustion, since
    that's a different problem than a flaky response and retrying
    within seconds against a daily quota limit is pointless.
    """
    last_error = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            response = client.models.generate_content(
                model=MODEL_NAME,
                contents=prompt,
            )
            raw = (response.text or "").strip()
            if not raw:
                last_error = "empty response"
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY_SECONDS)
                continue
            return _extract_json_object(raw)
        except json.JSONDecodeError as e:
            last_error = f"malformed JSON: {e}"
        except Exception as e:
            if "RESOURCE_EXHAUSTED" in str(e) or "429" in str(e) or "quota" in str(e).lower():
                raise QuotaExceededError(str(e)) from e
            last_error = f"API error: {e}"

        if attempt < MAX_RETRIES:
            time.sleep(RETRY_DELAY_SECONDS)

    # All attempts failed — caller must handle None gracefully.
    print(f"[universal_ingest] Gemini JSON call failed after retries: {last_error}")
    return None


def _classify_document_shape(client: "genai.Client", text: str) -> Optional[dict]:
    prompt = f"""Classify this Indian government infrastructure sanction/completion
document. Respond with ONLY a JSON object, no markdown, no preamble:

{{
  "shape": one of ["single_project_variance", "batch_aggregate", "narrative_only", "not_relevant"],
  "reasoning": "one short sentence"
}}

- "single_project_variance": one specific work/project with BOTH a sanctioned
  amount AND a completed/disbursed/expenditure amount stated for that same work.
- "batch_aggregate": a sanction covering many works as category totals
  (e.g. Stage-I/Stage-II/Bridges), with no per-project completion figure.
- "narrative_only": prose describing an irregularity, delay, cost inflation,
  or directed action, without a clean numeric sanctioned/completed pair.
- "not_relevant": not an infrastructure sanction/completion document at all.

DOCUMENT TEXT (may be partial):
{text[:6000]}
"""
    return _call_gemini_json(client, prompt)


def _extract_narrative_anomaly(client: "genai.Client", text: str) -> Optional[dict]:
    prompt = f"""Read this Indian government document. It may contain an
acknowledged irregularity even without a clean sanctioned-vs-completed number
pair — e.g. a stated percentage cost reduction/inflation found on scrutiny, a
directive to take action against an office/contractor, a named delay, or a
discrepancy flagged by an oversight body (NRRDA, CAG, Lokayukta, etc.).

Respond with ONLY a JSON object, no markdown:

{{
  "anomaly_found": true or false,
  "anomaly_type": "cost_inflation" | "delay" | "action_ordered" | "other" | null,
  "description": "one to two plain-language sentences, no invented numbers",
  "quoted_percentage_or_amount": "verbatim figure if one is explicitly stated, else null",
  "confidence": "high" | "medium" | "low"
}}

Only set anomaly_found to true if the document explicitly states the
irregularity — do not infer one that isn't written down.

DOCUMENT TEXT (may be partial):
{text[:6000]}
"""
    return _call_gemini_json(client, prompt)


def _extract_batch_aggregate(client: "genai.Client", text: str) -> Optional[dict]:
    prompt = f"""Extract batch-level sanction totals from this document, for
coverage-tracking purposes only (not risk scoring, since no completion data
exists). Respond with ONLY a JSON object, no markdown:

{{
  "state": "string or null",
  "scheme": "string or null (e.g. PMGSY)",
  "total_sanctioned_amount": "verbatim figure with unit, or null",
  "number_of_works": "integer or null",
  "year_or_batch": "string or null"
}}

DOCUMENT TEXT (may be partial):
{text[:6000]}
"""
    return _call_gemini_json(client, prompt)


# ---------------------------------------------------------------------------
# The pipeline itself. This is the only function most of your app needs to call.
# ---------------------------------------------------------------------------

def process_document(client: "genai.Client", text: str) -> IngestResult:
    """
    Runs a document through every fallback tier in order of cheapest/most
    auditable first. Guaranteed to return a valid IngestResult no matter
    what the input looks like or how many API calls fail.
    """
    excerpt = (text or "").strip()[:300]

    # Worst case #1: nothing usable to even send anywhere.
    if not text or len(text.strip()) < MIN_MEANINGFUL_CHARS:
        return IngestResult(
            status="unreadable",
            source_excerpt=excerpt,
            tier_used="none",
            notes=(
                "Extracted text is too short or empty — likely a scan-quality "
                "or OCR failure. Flagged for manual review rather than guessed."
            ),
        )

    # Tier 1: fast, free, deterministic. Try it first no matter what.
    tier1_result = _tier1_extract_variance_pair(text)
    if tier1_result:
        return IngestResult(
            status="variance_pair",
            source_excerpt=excerpt,
            data=tier1_result,
            tier_used="tier1_regex",
            notes="Matched sanctioned/completed pair via deterministic regex.",
        )

    # Tier 2: ask Gemini what shape this document actually is.
    try:
        shape_result = _classify_document_shape(client, text)
    except QuotaExceededError as e:
        return IngestResult(
            status="quota_exceeded",
            source_excerpt=excerpt,
            tier_used="none",
            notes=(
                "Gemini's API quota is currently exhausted (e.g. the "
                "free-tier daily request limit). This is a billing/quota "
                "issue, not a problem with this document -- it will "
                "resolve once the quota resets, or immediately if you "
                "upgrade the plan on this API key. "
                f"Details: {e}"
            ),
        )

    if shape_result is None:
        # Gemini itself failed after retries — don't fabricate a result.
        return IngestResult(
            status="unreadable",
            source_excerpt=excerpt,
            tier_used="none",
            notes=(
                "Text was readable but the classification model call failed "
                "after retries (API error or malformed response). Flagged "
                "for manual review — this is a transient failure, not a "
                "judgment that the document is unusable."
            ),
        )

    shape = shape_result.get("shape")

    try:
        if shape == "single_project_variance":
            # Gemini thinks there's a pair here that regex missed — worth a
            # dedicated extraction call rather than discarding it.
            pair_prompt = f"""Extract the sanctioned amount and the completed/
disbursed amount for the specific work described. Respond with ONLY JSON:
{{"work_name": "...", "sanctioned_amount": "verbatim with unit", "completed_amount": "verbatim with unit"}}

TEXT:
{text[:6000]}
"""
            pair_result = _call_gemini_json(client, pair_prompt)
            if pair_result and pair_result.get("sanctioned_amount") and pair_result.get("completed_amount"):
                return IngestResult(
                    status="variance_pair",
                    source_excerpt=excerpt,
                    data=pair_result,
                    tier_used="tier2_gemini",
                    notes="Classified and extracted as a variance pair via Gemini after regex missed it.",
                )
            # Classifier said variance pair, but extraction couldn't confirm it —
            # don't force a false positive, fall through to manual review.

        if shape == "batch_aggregate":
            # These two calls are independent of each other (same input text,
            # neither needs the other's output) -- running them concurrently
            # instead of one-after-another roughly halves this branch's
            # wall-clock time.
            with ThreadPoolExecutor(max_workers=2) as executor:
                batch_future = executor.submit(_extract_batch_aggregate, client, text)
                anomaly_future = executor.submit(_extract_narrative_anomaly, client, text)
                batch_result = batch_future.result()
                secondary_anomaly = anomaly_future.result()

            combined_data = dict(batch_result or {})

            # Multi-finding check: a batch-level sanction letter can ALSO
            # contain a separate narrative anomaly elsewhere in its prose
            # (e.g. an oversight body's finding buried in a conditions
            # paragraph). A single classification pass would otherwise miss
            # this entirely, so always check for it here too rather than
            # assuming one document = one finding.
            if secondary_anomaly and secondary_anomaly.get("anomaly_found"):
                combined_data["secondary_narrative_anomaly"] = secondary_anomaly

            return IngestResult(
                status="batch_aggregate",
                source_excerpt=excerpt,
                data=combined_data,
                tier_used="tier2_gemini" if batch_result else "none",
                notes=(
                    "Real sanction document, but batch-level with no per-project "
                    "completion data — logged for document-coverage stats, not "
                    "risk-scored."
                    + (
                        " A separate narrative anomaly was also found in the same document."
                        if combined_data.get("secondary_narrative_anomaly")
                        else ""
                    )
                ),
            )

        if shape == "narrative_only":
            anomaly_result = _extract_narrative_anomaly(client, text)
            if anomaly_result and anomaly_result.get("anomaly_found"):
                return IngestResult(
                    status="narrative_anomaly",
                    source_excerpt=excerpt,
                    data=anomaly_result,
                    tier_used="tier2_gemini",
                    notes="Government-acknowledged irregularity found in prose, no numeric pair required.",
                )
            return IngestResult(
                status="no_findings",
                source_excerpt=excerpt,
                data=anomaly_result or {},
                tier_used="tier2_gemini" if anomaly_result else "none",
                notes="Document read successfully but no extractable pattern matched — flagged for manual review.",
            )
    except QuotaExceededError as e:
        return IngestResult(
            status="quota_exceeded",
            source_excerpt=excerpt,
            tier_used="none",
            notes=(
                "Gemini's API quota is currently exhausted partway through "
                "analysis (e.g. the free-tier daily request limit). This is "
                "a billing/quota issue, not a problem with this document. "
                f"Details: {e}"
            ),
        )

    # shape == "not_relevant", or an unexpected/missing value.
    return IngestResult(
        status="no_findings",
        source_excerpt=excerpt,
        data=shape_result,
        tier_used="tier2_gemini",
        notes=f"Document classified as '{shape}' — not a sanction/completion pattern this pipeline scores.",
    )


# ---------------------------------------------------------------------------
# Example wiring into a Streamlit upload flow.
# ---------------------------------------------------------------------------

def example_streamlit_usage():
    """
    Not called automatically — copy this pattern into your app.py where you
    currently branch on document type after upload.
    """
    import streamlit as st  # local import so this module has no hard dep on streamlit

    client = genai.Client()  # however you currently construct it

    uploaded_text = "..."  # from your existing pdfplumber / OCR step

    result = process_document(client, uploaded_text)

    if result.status == "variance_pair":
        st.success("Sanctioned/completed pair extracted — scoring risk normally.")
        st.json(result.data)
    elif result.status == "batch_aggregate":
        st.info("Batch-level sanction recognized — added to document coverage, not risk-scored.")
        st.json(result.data)
    elif result.status == "narrative_anomaly":
        st.warning("No numeric pair, but the document itself names an irregularity:")
        st.write(result.data.get("description"))
    elif result.status == "unreadable":
        st.error("Couldn't extract usable text from this document. Flagged for manual review.")
        st.caption(result.notes)
    else:  # no_findings
        st.warning("Document read, but nothing matched a known pattern. Flagged for manual review, not discarded.")
        st.caption(result.notes)

    # Regardless of branch: always log to your audit ledger so nothing
    # silently disappears, even the "no_findings" cases.
    # your_ledger.append(result)