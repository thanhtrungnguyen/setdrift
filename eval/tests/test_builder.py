"""End-to-end builder integration test (network-free)."""
import json
from pathlib import Path

from sica_eval.corpus.builder import build_corpus
from sica_eval.corpus.schemas import Corpus, SkillLabel


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
