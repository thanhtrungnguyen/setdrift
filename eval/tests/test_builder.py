"""End-to-end builder integration test (network-free)."""
import json
from pathlib import Path

from setdrift_eval.corpus.builder import build_corpus
from setdrift_eval.corpus.schemas import Corpus, SkillLabel


def _write_manifest(target: Path, payload: dict) -> None:
    target.write_text(json.dumps(payload))


def test_build_corpus_produces_one_prompt_per_manifest(tmp_path: Path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    _write_manifest(
        raw_dir / "bug-001.json",
        {
            "bug_id": "bug-001",
            "commit_hash": "c1",
            "parent_commit_hash": "p1",
            "diff": "diff --git a/pom.xml b/pom.xml\n-<version>1.0</version>\n+<version>1.1</version>\n",
            "commit_message": "fix: bump dependency",
            "issue_text": "Build fails after upgrading.",
            "project_id": "org/repo",
        },
    )
    _write_manifest(
        raw_dir / "bug-002.json",
        {
            "bug_id": "bug-002",
            "commit_hash": "c2",
            "parent_commit_hash": "p2",
            "diff": "diff --git a/Foo.java b/Foo.java\n+if (x != null) {}\n",
            "commit_message": "fix: NPE when x missing",
            "issue_text": "",
            "project_id": "org/repo",
        },
    )

    output_path = tmp_path / "corpus.jsonl"
    corpus = build_corpus(raw_dir=raw_dir, output_path=output_path, corpus_version="test-1")

    assert isinstance(corpus, Corpus)
    assert len(corpus.prompts) == 2

    # JSONL written to disk
    lines = output_path.read_text().strip().splitlines()
    assert len(lines) == 2

    # Labels reflect the diff content
    labels_by_id = {p.prompt_id: p.predicted_skills for p in corpus.prompts}
    assert SkillLabel.DEPENDENCY_BUMP in labels_by_id["gitbug-java-bug-001"]
    assert SkillLabel.NULL_CHECK in labels_by_id["gitbug-java-bug-002"]


def test_build_corpus_handles_empty_dir(tmp_path: Path):
    raw_dir = tmp_path / "raw-empty"
    raw_dir.mkdir()
    output_path = tmp_path / "empty.jsonl"
    corpus = build_corpus(raw_dir=raw_dir, output_path=output_path, corpus_version="test-empty")
    assert corpus.prompts == []
    assert output_path.read_text() == ""


# ── Plan 02-02 Task 3: multi-source + split freeze + negative floor ──────────
import hashlib

import pytest

from setdrift_eval.corpus.builder import freeze_split
from setdrift_eval.corpus.schemas import BugSource, LabeledPrompt

# Defects4J .src.patch (SVN reverse patch) — a benign rename, labeler → [NONE].
_D4J_PATCH = (
    "Index: src/Foo.java\n"
    "===================================================================\n"
    "--- src/Foo.java\t(revision 2)\n"
    "+++ src/Foo.java\t(revision 1)\n"
    "@@ -1,3 +1,3 @@\n"
    " class Foo {\n"
    "-  int alpha;\n"
    "+  int beta;\n"
    " }\n"
)


def _neg(i: int) -> LabeledPrompt:
    return LabeledPrompt(
        prompt_id=f"neg-constructed-c{i}",
        prompt=f"Rename a local variable, instance {i}.",
        predicted_skills=[SkillLabel.NONE],
        source=BugSource(dataset="constructed", bug_id=str(i), commit="", parent_commit=""),
        metadata={"negative_source": "constructed"},
    )


def _make_d4j_fixture(tmp_path: Path, bugs=(1, 2)) -> Path:
    root = tmp_path / "d4j" / "framework" / "projects" / "Lang"
    (root / "patches").mkdir(parents=True)
    (root / "commit-db").write_text(
        "".join(f"{b},aaa{b},bbb{b}\n" for b in bugs), encoding="utf-8"
    )
    for b in bugs:
        (root / "patches" / f"{b}.src.patch").write_text(_D4J_PATCH, encoding="utf-8")
    return tmp_path / "d4j"


def _null_check_manifest(raw_dir: Path, bug_id: str) -> None:
    _write_manifest(
        raw_dir / f"{bug_id}.json",
        {
            "bug_id": bug_id, "commit_hash": "c", "parent_commit_hash": "p",
            "diff": "diff --git a/Foo.java b/Foo.java\n+if (x != null) {}\n",
            "commit_message": "fix: npe", "issue_text": "", "project_id": "r",
        },
    )


def test_freeze_split_is_deterministic(tmp_path: Path):
    prompts = [_neg(i) for i in range(20)]
    _, h1 = freeze_split(prompts, tmp_path / "o1", rng_seed=42)
    _, h2 = freeze_split(prompts, tmp_path / "o2", rng_seed=42)
    assert h1 == h2  # same seed → identical split_hash
    _, h3 = freeze_split(prompts, tmp_path / "o3", rng_seed=99)
    assert h3 != h1  # different seed → different split


def test_freeze_split_writes_split_json_with_matching_hash(tmp_path: Path):
    prompts = [_neg(i) for i in range(12)]
    assignment, split_hash = freeze_split(prompts, tmp_path, rng_seed=7)
    split_json = tmp_path / "split.json"
    assert split_json.exists()
    assert hashlib.sha256(split_json.read_bytes()).hexdigest() == split_hash
    assert set(assignment.values()) <= {"train", "val", "test"}


def test_multi_source_build_includes_defects4j(tmp_path: Path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    _null_check_manifest(raw_dir, "b1")
    d4j = _make_d4j_fixture(tmp_path, bugs=(1, 2))
    out = tmp_path / "corpus.jsonl"
    corpus = build_corpus(
        raw_dir=raw_dir, output_path=out, corpus_version="t", defects4j_dir=d4j
    )
    datasets = {p.source.dataset for p in corpus.prompts}
    assert "defects4j" in datasets and "gitbug-java" in datasets
    assert len(corpus.prompts) == 3  # 1 gitbug + 2 defects4j


def test_negative_topup_reaches_floor(tmp_path: Path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    for i in range(8):  # 8 positives, 0 negatives initially
        _null_check_manifest(raw_dir, f"b{i}")
    tsv = tmp_path / "neg.tsv"
    tsv.write_text("\n".join(f"c{i}\tRename variable {i}." for i in range(10)) + "\n", encoding="utf-8")
    out = tmp_path / "corpus.jsonl"
    corpus = build_corpus(
        raw_dir=raw_dir, output_path=out, corpus_version="t",
        min_negative_fraction=0.20, constructed_negatives_path=tsv,
    )
    none = sum(1 for p in corpus.prompts if p.predicted_skills == [SkillLabel.NONE])
    assert none / len(corpus.prompts) >= 0.20
    assert any(p.metadata.get("negative_source") == "constructed" for p in corpus.prompts)


def test_negative_topup_exhausted_raises(tmp_path: Path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    for i in range(20):
        _null_check_manifest(raw_dir, f"b{i}")
    tsv = tmp_path / "neg.tsv"
    tsv.write_text("c1\tonly one negative\n", encoding="utf-8")  # too few to reach 20%
    out = tmp_path / "corpus.jsonl"
    with pytest.raises(RuntimeError, match="exhausted constructed negatives"):
        build_corpus(
            raw_dir=raw_dir, output_path=out, corpus_version="t",
            min_negative_fraction=0.20, constructed_negatives_path=tsv,
        )


def test_duplicate_prompt_id_raises(tmp_path: Path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    out = tmp_path / "c.jsonl"
    with pytest.raises(AssertionError, match="duplicate prompt_id"):
        build_corpus(
            raw_dir=raw_dir, output_path=out, corpus_version="t",
            negatives=[_neg(1), _neg(1)],  # same prompt_id twice
        )
