"""Exit Gate #5: known-answer adversarial PII recall must be 100% (NOC-4, Plan 01-04).

See adversarial_pii.py for methodology. The gate config (deny-list tuned with the known
project terms) must remove EVERY tracked plant from the scrubbed corpus. A leak here is a
hard fail — telemetry PII is zero-tolerance.
"""

from setdrift_eval.telemetry.tests import adversarial_pii


def test_adversarial_pii_recall_is_100pct():
    r = adversarial_pii.measure_recall(use_deny_list=True)
    assert r["n_events"] >= 200, f"corpus too small: {r['n_events']}"
    assert r["overall"] == 1.0, (
        f"PII LEAK: overall recall {r['overall'] * 100:.2f}% — survivors: {r['survivors']}\n"
        f"per-category: {r['by_category']}"
    )


def test_every_category_present_and_clean():
    """All 13 plant categories are exercised and each reaches 100%."""
    r = adversarial_pii.measure_recall(use_deny_list=True)
    expected = {
        "EMAIL",
        "PHONE",
        "US_SSN",
        "CREDIT_CARD",
        "IP",
        "AWS_KEY",
        "GITHUB_TOKEN",
        "OPENAI_KEY",
        "SLACK_TOKEN",
        "PRIVATE_KEY",
        "PERSON",
        "CUSTOMER_NAME",
        "JDBC_CREDS",
    }
    assert set(r["by_category"]) == expected, set(r["by_category"]) ^ expected
    assert all(v == 1.0 for v in r["by_category"].values()), r["by_category"]
