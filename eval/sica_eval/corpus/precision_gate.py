"""Per-source mining-precision + Cohen's kappa gate (D-35, REQ-CORPUS-03 / REQ-CORPUS-01).

Stands between mined labels and any F1 that touches the claim (ROADMAP Phase-2
exit gate). Mechanically enforces, PER SOURCE, that mined-label precision ≥0.85
AND Cohen's kappa ≥0.6, AND batch-wide that ≥20% of the manual sample is
negative — a violation makes the gate fail (the CLI exits non-zero).

The verification CSV keeps its 5 fixed human-fillable fieldnames (no source
column), so source is recovered by joining the filled CSV to the corpus JSONL on
prompt_id. Fail-loud: a verified label outside the 8-value taxonomy raises.
The committed report carries only ids/aggregates — never prompt or diff text.
"""
import csv
import json
from collections import defaultdict
from pathlib import Path

from sklearn.metrics import cohen_kappa_score

from sica_eval.corpus.schemas import SkillLabel

_VALID = {s.value for s in SkillLabel}
_INTENTS = sorted(_VALID - {SkillLabel.NONE.value})  # positive intent space for kappa/precision


def _parse_labels(cell: str) -> set[str]:
    labels = {x.strip() for x in (cell or "").split(",") if x.strip()}
    bad = labels - _VALID
    if bad:
        raise ValueError(f"verified/predicted label(s) outside taxonomy: {sorted(bad)}")
    return labels


def load_verification(csv_path: Path, corpus_path: Path) -> dict[str, list[dict]]:
    """Join the human-filled CSV (predicted+verified) with the corpus (source) by prompt_id."""
    source_by_id: dict[str, str] = {}
    with Path(corpus_path).open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                obj = json.loads(line)
                source_by_id[obj["prompt_id"]] = obj.get("source", {}).get("dataset", "unknown")

    by_source: dict[str, list[dict]] = defaultdict(list)
    with Path(csv_path).open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            pid = row["prompt_id"]
            entry = {
                "prompt_id": pid,
                "predicted": _parse_labels(row.get("predicted_skills", "")),
                "verified": _parse_labels(row.get("verified_skills", "")),  # fail-loud
            }
            by_source[source_by_id.get(pid, "unknown")].append(entry)
    return dict(by_source)


def _precision(rows: list[dict]) -> float:
    """Strict-set positive precision: mined positive labels that appear in verified."""
    correct = total = 0
    for r in rows:
        mined_pos = r["predicted"] - {SkillLabel.NONE.value}
        total += len(mined_pos)
        correct += len(mined_pos & r["verified"])
    return correct / total if total else 1.0  # no predicted positives → vacuously precise


def _kappa(rows: list[dict]) -> float:
    """Cohen's kappa over flattened (prompt × positive-intent) binary pairs."""
    mined, verified = [], []
    for r in rows:
        for intent in _INTENTS:
            mined.append(1 if intent in r["predicted"] else 0)
            verified.append(1 if intent in r["verified"] else 0)
    if mined == verified:
        return 1.0  # perfect agreement (sklearn returns nan when there is no variance)
    k = cohen_kappa_score(verified, mined)
    return 0.0 if k != k else float(k)  # nan → 0.0 (disagreement with no co-variance)


def _label_distribution(rows: list[dict]) -> dict[str, int]:
    dist: dict[str, int] = defaultdict(int)
    for r in rows:
        for label in (r["verified"] or {SkillLabel.NONE.value}):
            dist[label] += 1
    return dict(dist)


def compute_precision_and_kappa(rows_by_source: dict[str, list[dict]]) -> dict:
    """Build the report: per-source precision/kappa/n/distribution + batch negatives fraction."""
    per_source = {}
    total = neg = 0
    for source, rows in rows_by_source.items():
        per_source[source] = {
            "precision": _precision(rows),
            "kappa": _kappa(rows),
            "n": len(rows),
            "label_distribution": _label_distribution(rows),
        }
        total += len(rows)
        neg += sum(1 for r in rows if r["verified"] == {SkillLabel.NONE.value})
    return {
        "per_source": per_source,
        "negatives_fraction": (neg / total) if total else 0.0,
        "n_total": total,
    }


def check_gate(
    report: dict,
    precision_threshold: float = 0.85,
    kappa_threshold: float = 0.6,
    min_negatives_fraction: float = 0.20,
) -> dict:
    """Mechanically enforce per-source precision≥0.85 AND kappa≥0.6 AND ≥20% negatives."""
    all_ok = True
    for source, m in report["per_source"].items():
        m["passed_precision"] = m["precision"] >= precision_threshold
        m["passed_kappa"] = m["kappa"] >= kappa_threshold
        if not (m["passed_precision"] and m["passed_kappa"]):
            all_ok = False
    report["passed_negatives"] = report["negatives_fraction"] >= min_negatives_fraction
    report["passed"] = all_ok and report["passed_negatives"]
    report["thresholds"] = {
        "precision": precision_threshold,
        "kappa": kappa_threshold,
        "min_negatives_fraction": min_negatives_fraction,
    }
    return report


def write_report(report: dict, experiments_dir: Path) -> Path:
    """Write experiments/{NNN}-mining-precision.json (git-tracked; ids/aggregates only)."""
    experiments_dir = Path(experiments_dir)
    experiments_dir.mkdir(parents=True, exist_ok=True)
    existing = list(experiments_dir.glob("*-mining-precision.json"))
    nnn = f"{len(existing) + 1:03d}"
    out = experiments_dir / f"{nnn}-mining-precision.json"
    out.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return out
