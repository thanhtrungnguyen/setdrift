"""Negative miner (D-36): in-distribution non-fix commits + constructed near-misses.

≥20% of the corpus must be genuine negatives ("no skill should fire"). Two sources:
  - non-fix commits (refactor/chore/format/docs/style/rename) from the SAME source
    repos → real, in-distribution; a candidate the labeler labels non-NONE is
    dropped (it accidentally matched a rule, so it is NOT a clean negative).
  - hand-authored near-miss prompts → adversarial top-up to guarantee the floor.

Provenance is carried in `LabeledPrompt.metadata["negative_source"]` ∈
{"non_fix_commit","constructed"} — the schema's BugSource has no such field and
one must NOT be added. Both functions yield LabeledPrompt (not BugRecord) so the
negative_source tag travels with the prompt. Fail-loud on malformed TSV.
"""
import subprocess
from collections.abc import Iterable, Iterator
from pathlib import Path

from sica_eval.corpus.fetcher import BugRecord
from sica_eval.corpus.labeler import label_bug
from sica_eval.corpus.schemas import BugSource, LabeledPrompt, SkillLabel
from sica_eval.corpus.synthesizer import synthesize_prompt

_NON_FIX_PREFIXES = ("refactor", "chore", "format", "docs", "doc", "style", "rename")


def _is_non_fix(message: str) -> bool:
    return message.strip().lower().startswith(_NON_FIX_PREFIXES)


def mine_non_fix_negatives(
    repo_dirs: Iterable[Path], fix_shas: set[str], max_per_repo: int = 50
) -> Iterator[LabeledPrompt]:
    """Yield in-distribution negatives from non-fix commits (provenance-tagged)."""
    for repo in repo_dirs:
        repo = Path(repo)
        log = subprocess.run(
            ["git", "-C", str(repo), "log", "--format=%H\t%s", "--no-merges"],
            capture_output=True, text=True, check=True,
        )
        count = 0
        for line in log.stdout.splitlines():
            if count >= max_per_repo:
                break
            sha, _, msg = line.partition("\t")
            if sha in fix_shas or not _is_non_fix(msg):
                continue
            diff = subprocess.run(
                ["git", "-C", str(repo), "diff", f"{sha}~1", sha],
                capture_output=True, text=True, check=True,
            ).stdout
            record = BugRecord(
                bug_id=f"nonfix-{repo.name}-{sha[:12]}",
                commit=sha, parent_commit=f"{sha}~1",
                diff=diff, commit_message=msg, project_id=repo.name,
            )
            if label_bug(record) != [SkillLabel.NONE]:
                continue  # accidentally triggered a rule → not a clean negative
            count += 1
            yield LabeledPrompt(
                prompt_id=record.bug_id,
                prompt=synthesize_prompt(record),
                predicted_skills=[SkillLabel.NONE],
                ground_truth_skills=None,
                source=BugSource(
                    dataset=f"nonfix-{repo.name}", bug_id=sha,
                    commit=sha, parent_commit=f"{sha}~1",
                ),
                metadata={"negative_source": "non_fix_commit"},
            )


def load_constructed_negatives(tsv_path: Path) -> list[LabeledPrompt]:
    """Parse a TSV (`<id>\\t<prompt text>`) of hand-authored near-miss negatives.

    Fail-loud (raise) on a malformed row — never silently skip a bad data line.
    Blank lines and `#` comments are ignored.
    """
    tsv_path = Path(tsv_path)
    out: list[LabeledPrompt] = []
    for lineno, raw in enumerate(tsv_path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if "\t" not in raw:
            raise ValueError(
                f"{tsv_path}:{lineno}: malformed constructed-negative row (no TAB): {raw!r}"
            )
        bug_id, prompt_text = raw.split("\t", 1)
        out.append(
            LabeledPrompt(
                prompt_id=f"neg-constructed-{bug_id.strip()}",
                prompt=prompt_text.strip(),
                predicted_skills=[SkillLabel.NONE],
                ground_truth_skills=None,
                source=BugSource(
                    dataset="constructed", bug_id=bug_id.strip(),
                    commit="", parent_commit="",
                ),
                metadata={"negative_source": "constructed"},
            )
        )
    return out
