"""Verification sampler tests."""
import csv
from pathlib import Path

from sica_eval.corpus.sampler import emit_verification_csv


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
    assert set(rows[0].keys()) == {"prompt_id", "prompt", "predicted_skills", "verified_skills", "notes"}
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
