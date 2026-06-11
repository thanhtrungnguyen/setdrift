"""Transcript-banking standby script — pre-banks Sonnet-4.6 responses against deprecation (Pitfall 7).

STANDBY STATUS: This script is NOT run as part of normal evaluation. It is activated
ONLY if Anthropic announces claude-sonnet-4-6 deprecation (verified Active with
retirement not before 2027-02-17 as of 2026-06-09). If a deprecation notice lands:

  1. Run: python eval/scripts/bank_transcripts.py --corpus data/corpora/public/corpus.jsonl
  2. All corpus prompt+tool combinations will be pre-banked into data/cache/
  3. Subsequent grid runs satisfy all load_or_call() invocations from cache (no live API traffic)

What this script does:
  - Iterates the corpus JSONL (one prompt per line, each with a 'text' or 'prompt' field).
  - For each prompt, calls response_cache.load_or_call(model, prompt, tools, cache_dir)
    with the arm A toolset and the arm B (no-tools) toolset.
  - Pre-populates the content-addressed cache at data/cache/ so replay runs are cache hits.
  - Prints [sica-eval] progress lines per the project print convention.

What this script does NOT do:
  - Never runs automatically as part of eval pipeline (standby only).
  - Never writes to experiments/ (only writes to data/cache/ inside the data wall).
  - Never modifies scorer.py or any frozen Phase-2 instrument.
  - Never reads or writes drift-event-log.jsonl.

Eval-side fail-loud: API errors propagate (no bare except).

Usage:
    python eval/scripts/bank_transcripts.py \\
        [--corpus PATH] [--model MODEL] [--skills-dir PATH] [--cache-dir PATH]

    Defaults:
        --corpus    data/corpora/public/corpus.jsonl
        --model     claude-sonnet-4-6
        --skills-dir plugin/skills
        --cache-dir  data/cache
"""
import argparse
import json
import os
import sys
from pathlib import Path

# Add eval/ to sys.path so sica_eval imports work when run as a script
_EVAL_DIR = Path(__file__).parent.parent
if str(_EVAL_DIR) not in sys.path:
    sys.path.insert(0, str(_EVAL_DIR))

from sica_eval.benchmark.response_cache import load_or_call, CACHE_DIR

_DEFAULT_MODEL = os.environ.get("SICA_MODEL", "claude-sonnet-4-6")
_DEFAULT_CORPUS = Path("data/corpora/public/corpus.jsonl")
_DEFAULT_SKILLS_DIR = Path("plugin/skills")


def _load_arm_tools(skills_dir: Path) -> list[dict]:
    """Load skill tool specs from skills_dir for the arm A toolset.

    Returns a list of tool dicts matching the response_cache.load_or_call tools format.
    Each tool has 'name', 'description', and 'input_schema' fields (Anthropic API format).
    Returns an empty list (arm B / arm C) if skills_dir does not exist.
    """
    skills_dir = Path(skills_dir)
    if not skills_dir.exists():
        return []
    tools = []
    for skill_md in sorted(skills_dir.rglob("SKILL.md")):
        try:
            import yaml
            text = skill_md.read_text(encoding="utf-8")
            if not text.startswith("---"):
                continue
            _, frontmatter, _ = text.split("---", 2)
            meta = yaml.safe_load(frontmatter)
            name = meta.get("name", skill_md.parent.name)
            description = meta.get("description", "")
            tools.append({
                "name": name,
                "description": description,
                "input_schema": {"type": "object", "properties": {}, "required": []},
            })
        except Exception:
            # fail-loud only on critical errors; skip malformed SKILL.md
            pass
    return tools


def bank_all(
    corpus_path: Path,
    model: str = _DEFAULT_MODEL,
    skills_dir: Path = _DEFAULT_SKILLS_DIR,
    cache_dir: Path = CACHE_DIR,
) -> int:
    """Pre-bank all corpus prompt+tool combinations into the content-addressed cache.

    Iterates each prompt in corpus_path and calls load_or_call() for:
    - Arm A toolset (skills from skills_dir)
    - Arm B toolset (empty tools list — frozen hand-written config with no dynamic skills)

    Returns the number of (prompt, arm) pairs banked.

    Eval-side fail-loud: API errors propagate.
    """
    corpus_path = Path(corpus_path)
    cache_dir = Path(cache_dir)

    if not corpus_path.exists():
        print(f"[sica-eval] bank_transcripts: corpus not found at {corpus_path} — nothing to bank")
        return 0

    arm_a_tools = _load_arm_tools(skills_dir)
    arm_b_tools: list[dict] = []  # arm B: frozen config, no dynamic tools

    prompts = [
        json.loads(line)
        for line in corpus_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    banked = 0
    for i, record in enumerate(prompts):
        prompt_text = record.get("text") or record.get("prompt") or ""
        if not prompt_text:
            continue

        for arm_label, tools in [("A", arm_a_tools), ("B", arm_b_tools)]:
            load_or_call(model=model, prompt=prompt_text, tools=tools, cache_dir=cache_dir)
            banked += 1

        if (i + 1) % 10 == 0 or (i + 1) == len(prompts):
            print(
                f"[sica-eval] bank_transcripts: {i + 1}/{len(prompts)} prompts banked "
                f"model={model} cache={cache_dir}"
            )

    print(f"[sica-eval] bank_transcripts: complete — {banked} (prompt, arm) pairs banked into {cache_dir}")
    return banked


def main() -> None:
    """CLI entrypoint for the transcript-banking standby."""
    parser = argparse.ArgumentParser(
        description="Pre-bank Sonnet-4.6 responses into the content-addressed cache (Pitfall 7 standby)."
    )
    parser.add_argument(
        "--corpus",
        type=Path,
        default=_DEFAULT_CORPUS,
        help=f"Path to corpus JSONL (default: {_DEFAULT_CORPUS})",
    )
    parser.add_argument(
        "--model",
        default=_DEFAULT_MODEL,
        help=f"Model to bank (default: {_DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--skills-dir",
        type=Path,
        default=_DEFAULT_SKILLS_DIR,
        help=f"Path to plugin/skills/ for arm A tool loading (default: {_DEFAULT_SKILLS_DIR})",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=CACHE_DIR,
        help=f"Cache directory for content-addressed responses (default: {CACHE_DIR})",
    )
    args = parser.parse_args()

    n = bank_all(
        corpus_path=args.corpus,
        model=args.model,
        skills_dir=args.skills_dir,
        cache_dir=args.cache_dir,
    )
    sys.exit(0 if n >= 0 else 1)


if __name__ == "__main__":
    main()
