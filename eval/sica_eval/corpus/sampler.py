"""Manual-verification sampler.

Reads a JSONL corpus, samples 20% (rounded up, minimum 1), and writes a CSV
with one row per sampled prompt. The CSV's verified_skills column is left
blank for a human verifier to fill in; the notes column is free-form.
"""
import csv
import json
import math
import random
from pathlib import Path

DEFAULT_FRACTION = 0.20


def emit_verification_csv(
    corpus_path: Path,
    output_path: Path,
    seed: int = 42,
    fraction: float = DEFAULT_FRACTION,
) -> None:
    corpus_path = Path(corpus_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    with corpus_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))

    n = max(1, math.ceil(len(rows) * fraction)) if rows else 0
    rng = random.Random(seed)
    sample = rng.sample(rows, k=n) if rows else []

    with output_path.open("w", encoding="utf-8", newline="") as out:
        writer = csv.DictWriter(
            out,
            fieldnames=["prompt_id", "prompt", "predicted_skills", "verified_skills", "notes"],
        )
        writer.writeheader()
        for row in sample:
            writer.writerow(
                {
                    "prompt_id": row["prompt_id"],
                    "prompt": row["prompt"],
                    "predicted_skills": ",".join(row.get("predicted_skills", [])),
                    "verified_skills": "",
                    "notes": "",
                }
            )
