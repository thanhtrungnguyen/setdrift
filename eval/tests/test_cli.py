"""CLI argparse wiring tests."""
import sys
from pathlib import Path

from setdrift_eval.cli import main


def test_corpus_build_invokes_pipeline(monkeypatch, tmp_path: Path, capsys):
    """`setdrift-eval corpus build --raw-dir X --output Y --version Z` runs the builder."""
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    output_path = tmp_path / "out.jsonl"

    calls: dict[str, object] = {}

    def fake_build_corpus(raw_dir: Path, output_path: Path, corpus_version: str,
                          corpus_name: str = "gitbug-java", **kwargs):
        from setdrift_eval.corpus.schemas import Corpus

        calls["raw_dir"] = raw_dir
        calls["output_path"] = output_path
        calls["corpus_version"] = corpus_version
        return Corpus(name=corpus_name, version=corpus_version, prompts=[])

    monkeypatch.setattr("setdrift_eval.cli.build_corpus", fake_build_corpus, raising=True)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "setdrift-eval",
            "corpus",
            "build",
            "--raw-dir",
            str(raw_dir),
            "--output",
            str(output_path),
            "--version",
            "2026-05-22",
        ],
    )

    exit_code = main()

    assert exit_code == 0
    assert calls["raw_dir"] == raw_dir
    assert calls["output_path"] == output_path
    assert calls["corpus_version"] == "2026-05-22"
