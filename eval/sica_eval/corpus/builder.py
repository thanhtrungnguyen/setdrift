"""Corpus builder pipeline.

Reads BugRecord objects from a raw data directory, applies the labeler and
synthesizer, and writes JSONL to disk. Returns the in-memory Corpus so callers
can compute aggregate stats without re-reading.
"""
from pathlib import Path

from sica_eval.corpus.fetcher import iter_bug_records
from sica_eval.corpus.labeler import label_bug
from sica_eval.corpus.schemas import BugSource, Corpus, LabeledPrompt
from sica_eval.corpus.synthesizer import synthesize_prompt


def build_corpus(
    raw_dir: Path,
    output_path: Path,
    corpus_version: str,
    corpus_name: str = "gitbug-java",
) -> Corpus:
    """Build a corpus from a directory of bug manifest JSON files.

    Each bug becomes one LabeledPrompt. Output is written as JSONL (one
    LabeledPrompt per line) to ``output_path``; the parent directory is created
    if missing.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    prompts: list[LabeledPrompt] = []
    with output_path.open("w", encoding="utf-8") as out:
        for record in iter_bug_records(Path(raw_dir)):
            labels = label_bug(record)
            prompt_text = synthesize_prompt(record)
            entry = LabeledPrompt(
                prompt_id=f"{corpus_name}-{record.bug_id}",
                prompt=prompt_text,
                predicted_skills=labels,
                source=BugSource(
                    dataset=corpus_name,
                    bug_id=record.bug_id,
                    commit=record.commit,
                    parent_commit=record.parent_commit,
                ),
                metadata={"project_id": record.project_id} if record.project_id else {},
            )
            out.write(entry.model_dump_json() + "\n")
            prompts.append(entry)

    return Corpus(name=corpus_name, version=corpus_version, prompts=prompts)
