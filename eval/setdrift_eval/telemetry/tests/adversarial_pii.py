"""Known-answer adversarial PII recall harness (Plan 01-04, Exit Gate #5, NOC-4).

CEO scope decision: validating a scrubber needs KNOWN-ANSWER PII, not organic
human PII. We build a corpus of >=200 events deliberately salted with TRACKED fake
PII plants, run every event through the REAL `scrubber.scrub_event()`, and MEASURE
recall = plants_removed / plants_total per category and overall. A plant is "removed"
iff its literal string no longer appears anywhere in the serialized scrubbed event.

This is stronger than a passive 200-event human review: every plant is tracked, so a
miss is *measured*, not eyeballed. The gate requires overall recall == 100% + gitleaks 0.

Methodology / honesty note (clean evidence > flattering number):
  - STRUCTURED types (EMAIL, PHONE, US_SSN, CREDIT_CARD, IP, AWS/GITHUB/OPENAI/SLACK
    keys, PRIVATE_KEY header) are caught by the scrubber's GENERIC recognizers
    (Presidio + the SECRET regex + detect-secrets entropy mask). No per-plant
    registration — this is a real generalization test.
  - KNOWN-TERM types (PERSON, CUSTOMER_NAME, JDBC_CREDS) are project-specific strings
    the production scrubber removes via its Layer-3 deny-list (`add_deny_terms`,
    empty by design, "tuned in 01-04" per D-27). `register_known_terms()` populates it
    with exactly the plants of those categories — this mirrors production tuning and is
    the gate-legitimate mechanism for known sensitive terms.
  - `measure_recall(use_deny_list=False)` additionally reports the UNAIDED
    generic-recognizer recall as a diagnostic, so the report states plainly how much the
    scrubber catches with no deny-list help.

All plant values are OBVIOUSLY FAKE (RFC-5737 IPs, example.com, 555 / test-vector
numbers, canonical AWS example key, shape-valid-but-junk tokens). NEVER a real secret.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from setdrift_eval.telemetry import scrubber

# --- The tracked plants: (category, literal, mechanism) ---------------------------
# mechanism: "recognizer" = generic Presidio/SECRET/entropy; "deny_list" = known-term tuning.
PLANTS: list[tuple[str, str, str]] = [
    # Structured PII — generic recognizers
    ("EMAIL", "marcus.chen@example.com", "recognizer"),
    ("EMAIL", "p.nair@example.org", "recognizer"),
    ("PHONE", "+1 415 555 0142", "recognizer"),
    ("PHONE", "(415) 555-0148", "recognizer"),
    ("US_SSN", "078-05-1120", "recognizer"),
    ("US_SSN", "457-55-5462", "recognizer"),
    ("CREDIT_CARD", "4111 1111 1111 1111", "recognizer"),
    ("CREDIT_CARD", "5500 0000 0000 0004", "recognizer"),
    ("IP", "192.0.2.5", "recognizer"),
    ("IP", "198.51.100.23", "recognizer"),
    # Secrets — SECRET regex / entropy
    ("AWS_KEY", "AKIAIOSFODNN7EXAMPLE", "recognizer"),
    ("GITHUB_TOKEN", "ghp_016C7e0FAKEtoken0123456789abcdefABCD", "recognizer"),
    ("OPENAI_KEY", "sk-FAKEproj0123456789abcdefABCDEF0123456789", "recognizer"),
    ("SLACK_TOKEN", "xoxb-1111111111-2222222222-FAKEslacktokenABCDE", "recognizer"),
    ("PRIVATE_KEY", "-----BEGIN RSA PRIVATE KEY-----", "recognizer"),
    # Known project-specific terms — deny-list (production tuning mechanism)
    ("PERSON", "Marcus Chen", "deny_list"),
    ("PERSON", "Priya Nair", "deny_list"),
    ("CUSTOMER_NAME", "Helvetia Brakes AG", "deny_list"),
    ("CUSTOMER_NAME", "Northwind Logistics", "deny_list"),
    ("JDBC_CREDS", "S3cr3tPw0rd", "deny_list"),  # the password inside the JDBC URL
    ("JDBC_CREDS", "db-prod-7.internal.northwind.example", "deny_list"),  # internal host
]


def register_known_terms() -> None:
    """Populate the Layer-3 deny-list with the known sensitive project terms.

    Mirrors production scrubber tuning (D-27: deny-list is empty by default and tuned
    in 01-04). Only the deny_list-category plants are registered; structured types are
    left to the generic recognizers.
    """
    terms = [literal for cat, literal, mech in PLANTS if mech == "deny_list"]
    scrubber.add_deny_terms(terms)


# --- Realistic context templates --------------------------------------------------
def _diff_hunk(p: str) -> str:
    return (
        "diff --git a/src/billing/Account.java b/src/billing/Account.java\n"
        "@@ -42,6 +42,8 @@ public class Account {\n"
        f"-    // owner: {p}\n"
        f"+    // owner: {p}  (verified)\n"
        "     private BigDecimal balance;\n"
    )


def _stack_trace(p: str) -> str:
    return (
        "Traceback (most recent call last):\n"
        '  File "app/handler.py", line 88, in process\n'
        f"    raise ValueError(f'bad record for {p}')\n"
        f"ValueError: bad record for {p}\n"
    )


def _json_tool_input(p: str) -> str:
    return json.dumps({"query": "SELECT * FROM users WHERE token = ?", "param": p, "limit": 50})


def _jdbc_blob(pw: str, host: str) -> str:
    return (
        "spring.datasource.url="
        f"jdbc:postgresql://svcuser:{pw}@{host}:5432/orders?sslmode=require\n"
        "spring.datasource.hikari.maximum-pool-size=20\n"
    )


def _prompt(p: str) -> str:
    return f"Please review the change for {p} and confirm the migration is safe to ship."


_CONTEXTS = [_diff_hunk, _stack_trace, _json_tool_input, _prompt]
_FIELDS = ["tool_input", "tool_result", "prompt", "message_preview"]


def build_corpus(min_events: int = 210) -> list[dict]:
    """Build >=min_events events, each embedding >=1 tracked plant in a realistic context.

    JDBC plants are embedded together in a config blob (the natural place creds appear);
    all other plants rotate through the diff / stack-trace / json / prompt contexts and
    the four scrubbable fields.
    """
    events: list[dict] = []
    # Non-JDBC plants rotate through contexts/fields.
    rotating = [(c, lit) for c, lit, _ in PLANTS if c != "JDBC_CREDS"]
    i = 0
    while len(events) < min_events - 6:
        cat, literal = rotating[i % len(rotating)]
        ctx = _CONTEXTS[i % len(_CONTEXTS)]
        field = _FIELDS[i % len(_FIELDS)]
        events.append({
            "session_id": f"adv-{i:04d}",
            "tool_name": "Edit" if i % 2 else "Read",
            field: ctx(literal),
            "_synthetic": True,
            "_adversarial_pii": True,
        })
        i += 1
    # 6 dedicated JDBC config events (password + host plants).
    pw = next(lit for c, lit, _ in PLANTS if c == "JDBC_CREDS" and lit == "S3cr3tPw0rd")
    host = next(lit for c, lit, _ in PLANTS if c == "JDBC_CREDS" and lit.startswith("db-prod"))
    for j in range(6):
        events.append({
            "session_id": f"adv-jdbc-{j}",
            "tool_name": "Write",
            "tool_input": _jdbc_blob(pw, host),
            "prompt": f"Update the datasource for {host}",
            "_synthetic": True,
            "_adversarial_pii": True,
        })
    return events


def measure_recall(use_deny_list: bool = True, dump_dir: Path | None = None) -> dict:
    """Scrub every event and measure per-category + overall plant recall.

    use_deny_list=True registers the known-term deny-list first (the gate config).
    use_deny_list=False measures UNAIDED generic-recognizer recall (diagnostic).
    A plant is removed iff its literal appears in NO scrubbed event's serialized text.
    """
    if use_deny_list:
        register_known_terms()
    events = build_corpus()
    scrubbed_blobs: list[str] = []
    for ev in events:
        scrubbed, _audit = scrubber.scrub_event(ev)
        scrubbed_blobs.append(json.dumps(scrubbed, ensure_ascii=False))
    haystack = "\n".join(scrubbed_blobs)

    by_cat: dict[str, dict] = {}
    survivors: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for cat, literal, _mech in PLANTS:
        if (cat, literal) in seen:
            continue
        seen.add((cat, literal))
        removed = literal not in haystack
        d = by_cat.setdefault(cat, {"total": 0, "removed": 0})
        d["total"] += 1
        d["removed"] += int(removed)
        if not removed:
            survivors.append((cat, literal))

    total = sum(d["total"] for d in by_cat.values())
    removed = sum(d["removed"] for d in by_cat.values())
    if dump_dir is not None:
        dump_dir.mkdir(parents=True, exist_ok=True)
        (dump_dir / "scrubbed_events.jsonl").write_text("\n".join(scrubbed_blobs), encoding="utf-8")
    return {
        "n_events": len(events),
        "overall": removed / total if total else 0.0,
        "total_plants": total,
        "removed_plants": removed,
        "by_category": {c: round(d["removed"] / d["total"], 4) for c, d in sorted(by_cat.items())},
        "survivors": survivors,
    }


def _fmt(r: dict) -> str:
    lines = [
        f"events={r['n_events']}  plants={r['total_plants']}  removed={r['removed_plants']}",
        f"OVERALL RECALL = {r['overall']*100:.2f}%",
        "per-category:",
    ]
    for cat, rec in r["by_category"].items():
        lines.append(f"  {cat:<14} {rec*100:6.2f}%")
    if r["survivors"]:
        lines.append("SURVIVORS (LEAKED):")
        for cat, lit in r["survivors"]:
            lines.append(f"  !! {cat}: {lit!r}")
    else:
        lines.append("survivors: NONE")
    return "\n".join(lines)


if __name__ == "__main__":
    os.environ.setdefault("SICA_TELEMETRY_OPT_IN", "1")
    out = Path(tempfile.mkdtemp(prefix="adv_pii_"))
    print("=== UNAIDED (generic recognizers only, no deny-list) ===")
    diag = measure_recall(use_deny_list=False)
    print(_fmt(diag))
    print("\n=== GATE CONFIG (deny-list tuned with known terms) ===")
    tuned = measure_recall(use_deny_list=True, dump_dir=out)
    print(_fmt(tuned))
    print(f"\nscrubbed dump for gitleaks: {out}")
