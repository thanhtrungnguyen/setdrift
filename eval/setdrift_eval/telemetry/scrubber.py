"""Layered PII/secret scrubber for Setdrift telemetry (REQ-SAFETY-01).

Runs OFF the hot path (Stop-hook batch / cron context, 600s budget) so Presidio's
NLP cold start is acceptable. Three layers:

  Layer 1 (Presidio):      PERSON / EMAIL_ADDRESS / PHONE_NUMBER / URL / ... PII.
  Layer 1b (SECRET regex): known secret formats (AWS, GitHub, OpenAI, private
                           keys) registered as a Presidio recognizer so the
                           anonymizer REDACTS them, not just audits them.
  Layer 2 (detect-secrets):defense-in-depth detection incl. high-entropy strings,
                           run inside `default_settings()` (REQUIRED — without the
                           settings context scan_line is a silent no-op). Any
                           detect-secrets-flagged line also gets its high-entropy
                           tokens masked, so entropy secrets the regex misses
                           still leave the scrubbed text.
  Layer 3 (CUSTOM_DENY):   project deny-list (JDBC URLs / customer names) — starts
                           empty, tuned in 01-04 via add_deny_terms().

Contract (D-27): scrub_text / scrub_event RAISE on unexpected error — they do NOT
return partial/unscrubbed output. The batch scrubber catches and QUARANTINES.
Audit records carry only a sha256[:16] hash of the original span — never the
original text.
"""

import hashlib
import json
import os
import re
from dataclasses import dataclass

from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer
from presidio_analyzer.nlp_engine import NlpEngineProvider
from presidio_anonymizer import AnonymizerEngine
from detect_secrets.core import scan
from detect_secrets.settings import default_settings

# Presidio confidence floor (Claude's Discretion — tunable in 01-04).
SCORE_THRESHOLD = 0.5

# Known secret formats — redacted via Presidio so they leave the scrubbed text.
_SECRET_PATTERNS = [
    Pattern(name="aws_access_key", regex=r"AKIA[0-9A-Z]{16}", score=0.9),
    Pattern(name="github_token", regex=r"gh[pousr]_[A-Za-z0-9]{36,}", score=0.9),
    Pattern(name="openai_key", regex=r"sk-[A-Za-z0-9]{20,}", score=0.9),
    Pattern(name="slack_token", regex=r"xox[baprs]-[A-Za-z0-9-]{10,}", score=0.9),
    Pattern(name="private_key_header", regex=r"-----BEGIN [A-Z ]*PRIVATE KEY-----", score=0.95),
]
_SECRET_RECOGNIZER = PatternRecognizer(supported_entity="SECRET", patterns=_SECRET_PATTERNS)

# Deterministic PII-shape regex (Exit Gate #5 hardening, 01-04). Presidio's NLP
# recognizers VALIDATE (e.g. libphonenumber rejects 555-01xx fictional numbers; US_SSN
# scoring is context-dependent), which leaks PII-SHAPED strings on a zero-tolerance
# telemetry path. For telemetry we OVER-redact anything phone/SSN-shaped regardless of
# validity. Evidence: tests/adversarial_pii.py (PHONE 0% / US_SSN 50% before this).
_PII_PATTERNS = [
    # 3-2-4 SSN.
    Pattern(name="us_ssn_shape", regex=r"\b\d{3}-\d{2}-\d{4}\b", score=0.9),
    # Phone: optional +country, 3-3-4 with at least separators between the trailing groups.
    Pattern(
        name="phone_shape",
        regex=r"(?:\+\d{1,3}[\s.-]?)?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}",
        score=0.85,
    ),
]
_PII_RECOGNIZER = PatternRecognizer(supported_entity="PII_SHAPE", patterns=_PII_PATTERNS)

# Module-level singletons (cold start paid once per process).
# Spacy model is configurable so CI can use the lightweight en_core_web_sm
# (~12MB) instead of the production default en_core_web_lg (~560MB). Production
# behaviour is unchanged unless SETDRIFT_SPACY_MODEL is set. Both models ship a
# PERSON/EMAIL NER pipeline, which the safety tests (REQ-SAFETY-01) depend on.
_SPACY_MODEL = os.environ.get("SETDRIFT_SPACY_MODEL", "en_core_web_lg")
_NLP_ENGINE = NlpEngineProvider(
    nlp_configuration={
        "nlp_engine_name": "spacy",
        "models": [{"lang_code": "en", "model_name": _SPACY_MODEL}],
    }
).create_engine()
_ANALYZER = AnalyzerEngine(nlp_engine=_NLP_ENGINE)
_ANALYZER.registry.add_recognizer(_SECRET_RECOGNIZER)
_ANALYZER.registry.add_recognizer(_PII_RECOGNIZER)
_ANONYMIZER = AnonymizerEngine()

# Project deny-list (Layer 3) — empty in Phase 1, tuned in 01-04.
_DENY_TERMS: list[str] = []
_DENY_ENTITY = "CUSTOM_DENY"

# Fail-safe: a run of 20+ secret-ish chars on a detect-secrets-flagged line.
_ENTROPY_TOKEN = re.compile(r"[A-Za-z0-9+/=_\-]{20,}")

_LAYER_BY_ENTITY = {
    _DENY_ENTITY: "custom_deny",
    "SECRET": "secret_pattern",
    "PII_SHAPE": "pii_shape",
}


@dataclass
class RedactionRecord:
    layer: str  # "presidio" | "secret_pattern" | "detect_secrets" | "custom_deny"
    entity_type: str
    start: int
    end: int
    score: float
    original_hash: str  # sha256(original span)[:16] — NEVER the original text


def _hash(span: str) -> str:
    return hashlib.sha256(span.encode("utf-8")).hexdigest()[:16]


def add_deny_terms(terms) -> None:
    """Register project deny-list terms (Layer 3). Called by 01-04 tuning."""
    global _DENY_TERMS
    fresh = [t for t in terms if t and t not in _DENY_TERMS]
    if not fresh:
        return
    _DENY_TERMS.extend(fresh)
    # A PatternRecognizer with an empty deny_list raises; (re)register only when non-empty.
    _ANALYZER.registry.add_recognizer(
        PatternRecognizer(
            supported_entity=_DENY_ENTITY, deny_list=list(_DENY_TERMS), deny_list_score=0.85
        )
    )


def scrub_text(text: str) -> tuple[str, list["RedactionRecord"]]:
    """Redact PII + secrets from `text`. RAISES on unexpected error (caller quarantines)."""
    if not isinstance(text, str) or not text:
        return text, []

    records: list[RedactionRecord] = []

    # Layer 2 first: detect-secrets detection + entropy fail-safe mask on flagged lines.
    # MUST run inside default_settings() or scan_line silently yields nothing.
    masked_lines = []
    with default_settings():
        for lineno, line in enumerate(text.split("\n")):
            line_secrets = list(scan.scan_line(line))
            if line_secrets:
                for sec in line_secrets:
                    records.append(
                        RedactionRecord(
                            "detect_secrets", sec.type, lineno, lineno, 0.8, _hash(line)
                        )
                    )
                # Mask high-entropy tokens so the secret leaves the text even if the
                # SECRET regex below doesn't recognize this exact format.
                line = _ENTROPY_TOKEN.sub("<SECRET>", line)
            masked_lines.append(line)
    working = "\n".join(masked_lines)

    # Layers 1 / 1b / 3: Presidio analyze (PII + SECRET regex + CUSTOM_DENY) then anonymize.
    results = _ANALYZER.analyze(text=working, language="en", score_threshold=SCORE_THRESHOLD)
    for r in results:
        layer = _LAYER_BY_ENTITY.get(r.entity_type, "presidio")
        records.append(
            RedactionRecord(
                layer,
                r.entity_type,
                r.start,
                r.end,
                float(r.score),
                _hash(working[r.start : r.end]),
            )
        )
    scrubbed = _ANONYMIZER.anonymize(text=working, analyzer_results=results).text  # type: ignore[arg-type]
    return scrubbed, records


# Event string fields that may carry PII/secret content.
_SCRUB_FIELDS = ("tool_input", "tool_result", "prompt", "message_preview")


def scrub_event(event: dict) -> tuple[dict, list["RedactionRecord"]]:
    """Scrub every string-bearing field of an event. RAISES on error (caller quarantines)."""
    out = dict(event)
    audit: list[RedactionRecord] = []
    for field in _SCRUB_FIELDS:
        val = event.get(field)
        if val is None:
            continue
        as_text = val if isinstance(val, str) else json.dumps(val, ensure_ascii=False)
        scrubbed, recs = scrub_text(as_text)
        out[field] = scrubbed
        audit.extend(recs)
    return out, audit
