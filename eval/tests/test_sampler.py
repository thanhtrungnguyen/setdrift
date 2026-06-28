"""Verification sampler tests."""

import csv
from pathlib import Path

from setdrift_eval.corpus.sampler import emit_verification_csv


def _write_jsonl(path: Path, n: int) -> None:
    import json

    with path.open("w", encoding="utf-8") as f:
        for i in range(n):
            f.write(
                json.dumps(
                    {
                        "prompt_id": f"p-{i}",
                        "prompt": f"prompt text {i}",
                        "predicted_skills": ["none"],
                        "ground_truth_skills": None,
                        "source": {
                            "dataset": "gitbug-java",
                            "bug_id": str(i),
                            "commit": "c",
                            "parent_commit": "p",
                        },
                        "metadata": {},
                    }
                )
                + "\n"
            )


def test_sampler_emits_twenty_percent(tmp_path: Path):
    corpus_path = tmp_path / "corpus.jsonl"
    output_path = tmp_path / "verify.csv"
    _write_jsonl(corpus_path, n=100)

    emit_verification_csv(corpus_path=corpus_path, output_path=output_path, seed=42)

    with output_path.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 20
    assert set(rows[0].keys()) == {
        "prompt_id",
        "prompt",
        "predicted_skills",
        "verified_skills",
        "notes",
    }
    assert rows[0]["verified_skills"] == ""  # for human to fill in


def test_sampler_is_deterministic_under_same_seed(tmp_path: Path):
    corpus_path = tmp_path / "corpus.jsonl"
    _write_jsonl(corpus_path, n=50)

    out_a = tmp_path / "a.csv"
    out_b = tmp_path / "b.csv"
    emit_verification_csv(corpus_path=corpus_path, output_path=out_a, seed=7)
    emit_verification_csv(corpus_path=corpus_path, output_path=out_b, seed=7)

    assert out_a.read_text() == out_b.read_text()


def test_sampler_handles_small_corpus(tmp_path: Path):
    """A 3-prompt corpus produces at least 1 row (rounded up)."""
    corpus_path = tmp_path / "corpus.jsonl"
    output_path = tmp_path / "verify.csv"
    _write_jsonl(corpus_path, n=3)

    emit_verification_csv(corpus_path=corpus_path, output_path=output_path, seed=1)

    with output_path.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) >= 1


# ── Plan 02-03 Task 1: source-stratified sampling (D-35, Pitfall 6) ──────────
def _write_jsonl_multi(path: Path, counts: dict) -> None:
    import json

    with path.open("w", encoding="utf-8") as f:
        for src, n in counts.items():
            for j in range(n):
                f.write(
                    json.dumps(
                        {
                            "prompt_id": f"{src}-{j}",
                            "prompt": f"text {src} {j}",
                            "predicted_skills": ["none"],
                            "ground_truth_skills": None,
                            "source": {
                                "dataset": src,
                                "bug_id": str(j),
                                "commit": "c",
                                "parent_commit": "p",
                            },
                            "metadata": {},
                        }
                    )
                    + "\n"
                )


def test_stratify_represents_all_sources(tmp_path: Path):
    corpus = tmp_path / "c.jsonl"
    _write_jsonl_multi(corpus, {"gitbug-java": 100, "defects4j": 100})
    out = tmp_path / "v.csv"
    emit_verification_csv(corpus, out, seed=42, stratify_by_source=True, min_per_source=5)
    rows = list(csv.DictReader(out.open(encoding="utf-8")))
    assert any(r["prompt_id"].startswith("gitbug-java") for r in rows)
    assert any(r["prompt_id"].startswith("defects4j") for r in rows)


def test_min_per_source_floor_capped_at_availability(tmp_path: Path):
    corpus = tmp_path / "c.jsonl"
    _write_jsonl_multi(corpus, {"gitbug-java": 100, "constructed": 3})
    out = tmp_path / "v.csv"
    emit_verification_csv(corpus, out, seed=1, stratify_by_source=True, min_per_source=20)
    rows = list(csv.DictReader(out.open(encoding="utf-8")))
    constructed = [r for r in rows if r["prompt_id"].startswith("constructed")]
    gitbug = [r for r in rows if r["prompt_id"].startswith("gitbug-java")]
    assert len(constructed) == 3  # only 3 available → all 3, not over-sampled to 20
    assert len(gitbug) == 20  # max(20, ceil(100*0.2)=20) = 20


def test_stratified_sampling_is_deterministic(tmp_path: Path):
    corpus = tmp_path / "c.jsonl"
    _write_jsonl_multi(corpus, {"gitbug-java": 50, "defects4j": 50})
    a, b = tmp_path / "a.csv", tmp_path / "b.csv"
    emit_verification_csv(corpus, a, seed=7, stratify_by_source=True)
    emit_verification_csv(corpus, b, seed=7, stratify_by_source=True)
    assert a.read_text() == b.read_text()
