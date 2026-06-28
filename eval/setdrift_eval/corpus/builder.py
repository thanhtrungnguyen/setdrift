"""Corpus builder pipeline.

Reads BugRecord objects from one or more sources (GitBug-Java + Defects4J),
applies the labeler and synthesizer, appends provenance-tagged negatives, and
writes a single labeled JSONL. Enforces global prompt_id uniqueness and a ≥20%
negative floor (fail-loud, never ship under-floor). Freezes a train/val/test
split at build time and emits a deterministic split_hash (Phase-3 exit-gate
substrate). The builder owns ONLY split_hash — the intent-map hash is the
harness/scorer's concern (02-04/02-05) and is never computed here (W7); the
builder never reads the intent map.
"""

import hashlib
import json
import random
from pathlib import Path

from setdrift_eval.corpus.fetcher import BugRecord, iter_bug_records
from setdrift_eval.corpus.labeler import label_bug
from setdrift_eval.corpus.schemas import BugSource, Corpus, LabeledPrompt, SkillLabel
from setdrift_eval.corpus.synthesizer import synthesize_prompt


def _record_to_prompt(record: BugRecord, dataset: str) -> LabeledPrompt:
    return LabeledPrompt(
        prompt_id=f"{dataset}-{record.bug_id}",
        prompt=synthesize_prompt(record),
        predicted_skills=label_bug(record),
        source=BugSource(
            dataset=dataset,
            bug_id=record.bug_id,
            commit=record.commit,
            parent_commit=record.parent_commit,
        ),
        metadata={"project_id": record.project_id} if record.project_id else {},
    )


def _none_fraction(prompts: list[LabeledPrompt]) -> float:
    if not prompts:
        return 0.0
    neg = sum(1 for p in prompts if p.predicted_skills == [SkillLabel.NONE])
    return neg / len(prompts)


def build_corpus(
    raw_dir: Path,
    output_path: Path,
    corpus_version: str,
    corpus_name: str = "gitbug-java",
    *,
    gitbug_meta_dir: Path | None = None,
    defects4j_dir: Path | None = None,
    negatives: list[LabeledPrompt] | None = None,
    min_negative_fraction: float = 0.0,
    constructed_negatives_path: Path | None = None,
) -> Corpus:
    """Build a (multi-source) labeled corpus and write it as JSONL.

    Single-source default is unchanged (back-compat). When ``defects4j_dir`` is
    given, Defects4J bugs are appended via the patch-file fetcher. ``negatives``
    (already provenance-tagged LabeledPrompts) are appended; if the resulting
    [NONE] fraction is below ``min_negative_fraction``, constructed negatives are
    pulled from ``constructed_negatives_path`` until the floor is met — or a
    RuntimeError is raised (never ship an under-floor corpus).
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    prompts: list[LabeledPrompt] = []
    seen_ids: set[str] = set()

    def _add(prompt: LabeledPrompt) -> None:
        assert prompt.prompt_id not in seen_ids, f"duplicate prompt_id: {prompt.prompt_id}"
        seen_ids.add(prompt.prompt_id)
        prompts.append(prompt)

    for record in iter_bug_records(Path(raw_dir)):
        _add(_record_to_prompt(record, corpus_name))

    if gitbug_meta_dir is not None:
        from setdrift_eval.corpus import gitbug_fetcher

        for record in gitbug_fetcher.iter_bug_records(Path(gitbug_meta_dir)):
            _add(_record_to_prompt(record, "gitbug-java"))

    if defects4j_dir is not None:
        from setdrift_eval.corpus import defects4j_fetcher

        for record in defects4j_fetcher.iter_bug_records(Path(defects4j_dir)):
            _add(_record_to_prompt(record, "defects4j"))

    for neg in negatives or []:
        _add(neg)

    # Enforce the ≥negative-fraction floor via constructed top-up (D-36).
    if min_negative_fraction > 0 and _none_fraction(prompts) < min_negative_fraction:
        if constructed_negatives_path is None:
            raise RuntimeError(
                f"negative fraction {_none_fraction(prompts):.3f} < "
                f"{min_negative_fraction}, and no constructed_negatives_path to top up from."
            )
        from setdrift_eval.corpus.negative_miner import load_constructed_negatives

        pool = [
            n
            for n in load_constructed_negatives(Path(constructed_negatives_path))
            if n.prompt_id not in seen_ids
        ]
        while _none_fraction(prompts) < min_negative_fraction and pool:
            _add(pool.pop(0))
        if _none_fraction(prompts) < min_negative_fraction:
            raise RuntimeError(
                f"exhausted constructed negatives; fraction "
                f"{_none_fraction(prompts):.3f} still < {min_negative_fraction}"
            )

    with output_path.open("w", encoding="utf-8") as out:
        for entry in prompts:
            out.write(entry.model_dump_json() + "\n")

    return Corpus(name=corpus_name, version=corpus_version, prompts=prompts)


def freeze_split(
    prompts: list[LabeledPrompt],
    output_dir: Path,
    rng_seed: int = 42,
    train_frac: float = 0.6,
    val_frac: float = 0.2,
) -> tuple[dict[str, str], str]:
    """Freeze a deterministic train/val/test split; write split.json; return (map, hash).

    The split_hash is sha256 of the written split.json bytes (the Phase-3
    exit-gate token: optimizer code paths must never read the test partition;
    a changed split → changed hash → visible in any manifest diff). Same seed →
    identical split_hash.
    """
    ids = sorted(p.prompt_id for p in prompts)  # deterministic base order
    rng = random.Random(rng_seed)
    rng.shuffle(ids)

    n = len(ids)
    n_train = int(n * train_frac)
    n_val = int(n * val_frac)
    assignment: dict[str, str] = {}
    for i, pid in enumerate(ids):
        if i < n_train:
            assignment[pid] = "train"
        elif i < n_train + n_val:
            assignment[pid] = "val"
        else:
            assignment[pid] = "test"

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    split_path = output_dir / "split.json"
    split_path.write_text(json.dumps(assignment, indent=2, sort_keys=True), encoding="utf-8")
    split_hash = hashlib.sha256(split_path.read_bytes()).hexdigest()
    return assignment, split_hash
