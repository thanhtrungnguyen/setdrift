"""Per-source precision/kappa/negatives gate tests (Plan 02-03 Task 2). Offline."""
import csv
import json

import pytest

from sica_eval.corpus import precision_gate
from sica_eval.corpus.precision_gate_cli import main as gate_main


def _corpus(tmp_path, rows):
    """rows: list of (prompt_id, source_dataset)."""
    p = tmp_path / "corpus.jsonl"
    with p.open("w", encoding="utf-8") as f:
        for pid, src in rows:
            f.write(json.dumps({"prompt_id": pid, "source": {"dataset": src}}) + "\n")
    return p


def _csv(tmp_path, rows, name="verify.csv"):
    """rows: list of (prompt_id, predicted_skills, verified_skills)."""
    p = tmp_path / name
    with p.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["prompt_id", "prompt", "predicted_skills", "verified_skills", "notes"])
        w.writeheader()
        for pid, pred, ver in rows:
            w.writerow({"prompt_id": pid, "prompt": "x", "predicted_skills": pred, "verified_skills": ver, "notes": ""})
    return p


def test_per_source_precision_and_passing_gate(tmp_path):
    corpus = _corpus(tmp_path, [("g1", "gitbug-java"), ("g2", "gitbug-java"), ("g3", "gitbug-java"), ("g4", "gitbug-java")])
    csv_path = _csv(tmp_path, [
        ("g1", "null-check", "null-check"),  # TP
        ("g2", "none", "none"),              # negative
        ("g3", "none", "none"),              # negative
        ("g4", "import-fix", "import-fix"),  # TP
    ])
    rbs = precision_gate.load_verification(csv_path, corpus)
    report = precision_gate.check_gate(precision_gate.compute_precision_and_kappa(rbs))
    assert report["per_source"]["gitbug-java"]["precision"] == 1.0
    assert report["per_source"]["gitbug-java"]["passed_precision"] is True
    assert report["passed"] is True  # precision 1.0, kappa 1.0, negatives 0.5


def test_low_precision_source_fails(tmp_path):
    corpus = _corpus(tmp_path, [("d1", "defects4j"), ("d2", "defects4j"), ("d3", "defects4j")])
    csv_path = _csv(tmp_path, [
        ("d1", "null-check", "none"),        # FP — mined positive not verified
        ("d2", "import-fix", "import-fix"),  # TP
        ("d3", "none", "none"),
    ])
    rbs = precision_gate.load_verification(csv_path, corpus)
    report = precision_gate.check_gate(precision_gate.compute_precision_and_kappa(rbs))
    assert report["per_source"]["defects4j"]["precision"] == 0.5
    assert report["per_source"]["defects4j"]["passed_precision"] is False
    assert report["passed"] is False


def test_kappa_violation_drives_nonzero_exit(tmp_path):
    """precision can pass while kappa fails — kappa is enforced independently (B1)."""
    # mined all-none but verified has positives → precision 1.0 (vacuous) but kappa 0.0.
    corpus = _corpus(tmp_path, [(f"g{i}", "gitbug-java") for i in range(10)])
    rows = [(f"g{i}", "none", "null-check" if i < 5 else "none") for i in range(10)]
    csv_path = _csv(tmp_path, rows)
    rbs = precision_gate.load_verification(csv_path, corpus)
    report = precision_gate.check_gate(precision_gate.compute_precision_and_kappa(rbs))
    assert report["per_source"]["gitbug-java"]["passed_precision"] is True
    assert report["per_source"]["gitbug-java"]["passed_kappa"] is False  # kappa < 0.6
    exit_code = gate_main([
        "--csv", str(csv_path), "--corpus", str(corpus),
        "--experiments-dir", str(tmp_path / "experiments"),
    ])
    assert exit_code == 1  # gate blocks on kappa alone


def test_low_negatives_fraction_fails(tmp_path):
    corpus = _corpus(tmp_path, [(f"g{i}", "gitbug-java") for i in range(10)])
    # only 1/10 verified-none → negatives_fraction 0.1 < 0.20
    rows = [("g0", "null-check", "none")] + [(f"g{i}", "null-check", "null-check") for i in range(1, 10)]
    csv_path = _csv(tmp_path, rows)
    exit_code = gate_main([
        "--csv", str(csv_path), "--corpus", str(corpus),
        "--experiments-dir", str(tmp_path / "experiments"),
    ])
    assert exit_code == 1


def test_out_of_taxonomy_verified_label_raises(tmp_path):
    corpus = _corpus(tmp_path, [("g1", "gitbug-java")])
    csv_path = _csv(tmp_path, [("g1", "null-check", "not-a-real-label")])
    with pytest.raises(ValueError, match="outside taxonomy"):
        precision_gate.load_verification(csv_path, corpus)


def test_report_has_no_prompt_text_and_passing_exit(tmp_path):
    corpus = _corpus(tmp_path, [(f"g{i}", "gitbug-java") for i in range(5)])
    rows = [("g0", "null-check", "null-check")] + [(f"g{i}", "none", "none") for i in range(1, 5)]
    csv_path = _csv(tmp_path, rows)
    exp = tmp_path / "experiments"
    exit_code = gate_main(["--csv", str(csv_path), "--corpus", str(corpus), "--experiments-dir", str(exp)])
    assert exit_code == 0
    report_file = next(exp.glob("*-mining-precision.json"))
    text = report_file.read_text(encoding="utf-8")
    assert "prompt" not in text.lower()  # data wall: no prompt/diff text in the committed report
    data = json.loads(text)
    assert "per_source" in data and "negatives_fraction" in data and data["passed"] is True
