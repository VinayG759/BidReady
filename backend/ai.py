"""Claude reads the free-text parts of a tender (GeM "Additional Terms and Conditions", or a whole non-GeM PDF) and
returns eligibility clauses with verbatim quotes. It never decides eligibility: every quote is checked against the
document text by pipeline.validate_quote, and the rules engine decides.

Results are cached per document (sha256 of the text), so a stored tender is read once and re-assessments are free.
"""

import hashlib
import json
import os
import time
from pathlib import Path

CACHE = Path(__file__).resolve().parent / "corpus" / "ai"
MAX_CHARS = 180_000        # well inside the context window; longer documents are refused, not truncated

SYSTEM = """You extract eligibility clauses from Indian government tender documents for a pre-screening tool.
Rules:
- Copy every quote VERBATIM from the page text, 8 to 60 words, exactly as written (same words, same order). A quote that is not in the text will be rejected.
- Only report clauses about these four criteria: bidder turnover, prior experience / past performance, OEM (manufacturer) authorisation, EMD (earnest money deposit) and its exemptions. Include clauses that grant, limit or deny MSE / startup relaxations for these.
- Use the page number shown in the [Page N] marker before the text.
- Numbers: turnover in rupees lakh, EMD in rupees, experience in years. Leave a number null when the clause does not state one.
- Do not infer or guess. If the document says nothing about a criterion, report nothing for it.
- Ignore technical specifications, delivery, warranty, payment and penalty clauses."""

SCHEMA = {
    "type": "object",
    "properties": {
        "clauses": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "criterion": {"type": "string", "enum": ["turnover", "experience", "oem", "emd"]},
                    "kind": {"type": "string", "enum": ["requirement", "relaxation_granted", "relaxation_denied",
                                                        "relaxation_condition", "document_required"]},
                    "heading": {"type": "string", "description": "clause number or heading as printed, or empty"},
                    "quote": {"type": "string"},
                    "page": {"type": "integer"},
                    "turnover_lakh": {"type": ["number", "null"]},
                    "experience_years": {"type": ["number", "null"]},
                    "emd_rupees": {"type": ["number", "null"]},
                    "summary": {"type": "string", "description": "one plain-English sentence"},
                },
                "required": ["criterion", "kind", "heading", "quote", "page", "turnover_lakh", "experience_years",
                             "emd_rupees", "summary"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["clauses"],
    "additionalProperties": False,
}


def available():
    return bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())


def model():
    return os.environ.get("ANTHROPIC_MODEL", "").strip() or "claude-opus-5-5"


def _doc_text(pages, first_page=1):
    return "\n\n".join(f"[Page {i}]\n{t}" for i, t in enumerate(pages, start=1) if i >= first_page and t)


def _key(text):
    return hashlib.sha256((model() + "\n" + text).encode("utf-8")).hexdigest()[:24]


def extract(pages, first_page=1, use_cache=True, live=True):
    """-> {"clauses": [...], "model", "ms", "cached", "input_tokens", "output_tokens"} or {"error": "..."}.
    live=False reads the cache only (no paid call). Never raises: the parser-only path must keep working when
    the AI step is unavailable."""
    text = _doc_text(pages, first_page)
    if not text.strip():
        return {"error": "no readable text after the bid-details pages", "clauses": []}
    if len(text) > MAX_CHARS:
        return {"error": f"document text is {len(text):,} characters, above the {MAX_CHARS:,} limit", "clauses": []}
    key = _key(text)
    path = CACHE / f"{key}.json"
    if use_cache and path.exists():
        try:
            out = json.loads(path.read_text(encoding="utf-8"))
            out["cached"] = True
            return out
        except (OSError, ValueError):
            pass
    if not live:
        return {"error": "not read by Claude yet (cache only)", "clauses": []}
    if not available():
        return {"error": "ANTHROPIC_API_KEY is not set", "clauses": []}

    import anthropic

    client = anthropic.Anthropic(timeout=90.0, max_retries=1)
    t0 = time.perf_counter()
    try:
        response = client.beta.messages.create(
            model=model(),
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
            system=SYSTEM,
            messages=[{"role": "user", "content": f"Tender document text:\n\n{text}\n\nReturn the eligibility clauses."}],
        )
    except anthropic.AuthenticationError:
        return {"error": "Anthropic API key was rejected", "clauses": []}
    except anthropic.RateLimitError:
        return {"error": "Anthropic rate limit reached; try again shortly", "clauses": []}
    except anthropic.APIStatusError as e:
        return {"error": f"Anthropic API error {e.status_code}", "clauses": []}
    except anthropic.APIConnectionError:
        return {"error": "could not reach the Anthropic API", "clauses": []}
    ms = int((time.perf_counter() - t0) * 1000)
    if response.stop_reason == "refusal":
        return {"error": "the model declined this document", "clauses": [], "ms": ms}
    if response.stop_reason == "max_tokens":
        return {"error": "the extraction was cut off (output limit)", "clauses": [], "ms": ms}
    body = next((b.text for b in response.content if b.type == "text"), "")
    try:
        clauses = json.loads(body).get("clauses", [])
    except ValueError:
        return {"error": "the model returned invalid JSON", "clauses": [], "ms": ms}
    out = {"clauses": clauses, "model": response.model, "ms": ms, "cached": False,
           "input_tokens": response.usage.input_tokens, "output_tokens": response.usage.output_tokens}
    try:
        CACHE.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(out, indent=1), encoding="utf-8")
    except OSError:
        pass  # read-only filesystem (serverless): the result is still returned
    return out
