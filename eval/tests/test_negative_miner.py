"""Negative miner tests (Plan 02-02 Task 2). Offline — git is monkeypatched."""
import pytest

from setdrift_eval.corpus import negative_miner
from setdrift_eval.corpus.schemas import SkillLabel


def test_load_constructed_negatives(tmp_path):
    tsv = tmp_path / "neg.tsv"
    tsv.write_text(
        "# hand-authored near-miss negatives\n"
        "q1\tRename the local variable foo to bar in this method.\n"
        "q2\tAdd a Javadoc comment describing this method.\n",
        encoding="utf-8",
    )
    negs = negative_miner.load_constructed_negatives(tsv)
    assert len(negs) == 2
    assert all(n.predicted_skills == [SkillLabel.NONE] for n in negs)
    assert all(n.metadata["negative_source"] == "constructed" for n in negs)
    assert negs[0].prompt_id == "neg-constructed-q1"


def test_load_constructed_negatives_failloud_on_malformed(tmp_path):
    tsv = tmp_path / "bad.tsv"
    tsv.write_text("q1\tok prompt\nthisrowhasnotab\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no TAB"):
        negative_miner.load_constructed_negatives(tsv)


def test_mine_non_fix_negatives_tags_and_filters(tmp_path, monkeypatch):
    """Fix commits excluded; a non-fix that the labeler labels non-NONE is dropped."""
    log_out = (
        "aaaaaaaaaaaa\tfix: handle npe\n"          # a fix SHA → excluded
        "bbbbbbbbbbbb\trefactor: extract method\n"  # clean non-fix → kept
        "cccccccccccc\trefactor: add null guard\n"  # non-fix but diff fires a rule → dropped
    )

    def fake_run(cmd, **kwargs):
        class _R:
            stdout = ""
        r = _R()
        if "log" in cmd:
            r.stdout = log_out
        elif "diff" in cmd:
            sha = cmd[-1]
            r.stdout = (
                "diff --git a/A.java b/A.java\n+        int x = compute();\n"
                if sha == "bbbbbbbbbbbb"
                else "diff --git a/A.java b/A.java\n+        if (x == null) return;\n"
            )
        return r

    monkeypatch.setattr(negative_miner.subprocess, "run", fake_run)
    negs = list(
        negative_miner.mine_non_fix_negatives(
            [tmp_path / "repoX"], fix_shas={"aaaaaaaaaaaa"}, max_per_repo=50
        )
    )
    assert [n.source.bug_id for n in negs] == ["bbbbbbbbbbbb"]
    assert negs[0].metadata["negative_source"] == "non_fix_commit"
    assert negs[0].predicted_skills == [SkillLabel.NONE]
