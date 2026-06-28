"""Fail-loud strict JSONL parser for clean telemetry read-back (Exit Gate #4).

"F1 against silently-incomplete telemetry is worthless." This parser makes any
corruption LOUD: a single malformed line raises MalformedLineError (with the
exact path + line number) instead of being silently skipped. Blank lines are
the only thing allowed to be skipped.

This deliberately diverges from corpus/sampler.py (which tolerates bad lines) —
the clean events.jsonl read path must never hide a dropped/interleaved line.
"""

import json
from pathlib import Path


class MalformedLineError(ValueError):
    """Raised when a non-blank JSONL line fails to parse. Never swallowed."""

    def __init__(self, path: Path, line_no: int, raw: str, cause: Exception):
        self.path = path
        self.line_no = line_no
        self.raw = raw
        self.cause = cause
        super().__init__(f"Malformed JSONL at {path}:{line_no}: {cause!r}")


def parse_events_jsonl(path: Path) -> list[dict]:
    """Parse a per-session events file. RAISES MalformedLineError on any bad line."""
    path = Path(path)
    events: list[dict] = []
    with path.open("r", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, start=1):
            line = line.rstrip("\n")
            if not line.strip():
                continue  # blank lines allowed (the ONLY permitted skip)
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError as exc:
                # Fail loud — never skip a bad line, never return a truncated list.
                raise MalformedLineError(path, line_no, line, exc) from exc
    return events
