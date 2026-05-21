# data/ — the gitignored wall

Everything in this directory is **ignored by git** except this README.
Captured telemetry, mined repos, parking source, secrets, and PII live here and
**never** get committed. See ../DATA_POLICY.md.

Subfolders (created at runtime, all ignored):
- `telemetry/` — raw Claude Code event logs (`events.jsonl`)
- `mined_repos/` — cloned issue→commit task material
- `replays/` — sandbox replay artifacts
