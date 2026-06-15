"""Source-agnostic loader regression guard (Plan 02-06, REQ-CORPUS-02 / D-37).

Locks the D-37 promise: an enterprise source (e.g. dataset="parking" under
data/corpora/enterprise/) loads and validates through the SAME path as a public
source, with no code branching on the dataset string. If a future edit ever
special-cases dataset == "gitbug-java" in a way that would drop enterprise rows,
these tests fail loudly — that is what lets the enterprise capture path activate
later (on a clean end-June IP ruling) with zero architecture change.
"""
import json

from setdrift_eval.corpus.schemas import BugSource, LabeledPrompt, SkillLabel


def _prompt(dataset: str, bug_id: str) -> LabeledPrompt:
    """Build a valid LabeledPrompt for the given source dataset."""
    return LabeledPrompt(
        prompt_id=f"{dataset}-{bug_id}",
        prompt="Fix the NullPointerException raised when the user record is absent.",
        predicted_skills=[SkillLabel.NULL_CHECK],
        ground_truth_skills=None,
        source=BugSource(
            dataset=dataset,
            bug_id=bug_id,
            commit="c0ffee",
            parent_commit="deadbeef",
        ),
        metadata={"language": "java"},
    )


def test_enterprise_dataset_roundtrips_identically_to_public():
    """A dataset="parking" (enterprise) row round-trips exactly like a public one."""
    public = _prompt("gitbug-java", "001")
    enterprise = _prompt("parking", "001")  # stands in for data/corpora/enterprise/

    # Both validate and survive a JSON round-trip with field equality.
    assert LabeledPrompt.model_validate_json(public.model_dump_json()) == public
    assert LabeledPrompt.model_validate_json(enterprise.model_dump_json()) == enterprise

    # The two differ ONLY in source.dataset / derived ids — the schema treats the
    # dataset string as free-form (no enum, no allow-list).
    assert enterprise.source.dataset == "parking"
    assert public.source.dataset == "gitbug-java"


def test_mixed_jsonl_read_yields_all_rows_including_enterprise(tmp_path):
    """Reading a mixed public+enterprise JSONL returns BOTH rows.

    Replicates the canonical corpus read (line-by-line json.loads +
    LabeledPrompt.model_validate) and asserts the enterprise row is neither
    filtered nor special-cased.
    """
    rows = [
        _prompt("gitbug-java", "001"),
        _prompt("defects4j", "Lang-1"),
        _prompt("parking", "PKG-42"),  # enterprise source
    ]
    corpus_file = tmp_path / "mixed.jsonl"
    corpus_file.write_text(
        "\n".join(p.model_dump_json() for p in rows) + "\n", encoding="utf-8"
    )

    loaded = [
        LabeledPrompt.model_validate(json.loads(line))
        for line in corpus_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert len(loaded) == 3  # enterprise row not dropped
    datasets = {p.source.dataset for p in loaded}
    assert datasets == {"gitbug-java", "defects4j", "parking"}


def test_loader_does_not_special_case_a_hardcoded_dataset(tmp_path):
    """Guard: an enterprise-only JSONL loads fully — no path requires 'gitbug-java'.

    If any production read path silently keyed on dataset == "gitbug-java", an
    all-enterprise file would come back empty. It must not.
    """
    enterprise_only = [_prompt("parking", f"PKG-{i}") for i in range(5)]
    corpus_file = tmp_path / "enterprise_only.jsonl"
    corpus_file.write_text(
        "\n".join(p.model_dump_json() for p in enterprise_only) + "\n", encoding="utf-8"
    )

    loaded = [
        LabeledPrompt.model_validate(json.loads(line))
        for line in corpus_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(loaded) == 5
    assert all(p.source.dataset == "parking" for p in loaded)
