# Data Policy — the wall between open code and closed data

This repository is **public**. Its case study runs on a **proprietary** parking
platform. The two only coexist because of a strict boundary:

## What MAY live in git (open)
- Plugin source (skills, hooks, manifests, agents, commands)
- The evaluation harness (Python)
- Experiment *configurations* and *aggregate results* (metrics, charts, tables)
- Public-benchmark task IDs (e.g. GitBug-Java, Defects4J, SWE-bench)
- Documentation, hypotheses, analysis

## What MUST NEVER enter git (closed) — lives only under `data/`
- Captured developer prompts or session transcripts
- Any Vingroup / parking-platform source code or config
- Mined issue→commit pairs containing proprietary code
- Secrets, API keys, customer data, PII
- Raw telemetry event logs (`*.jsonl`, `*.sqlite`)

## Enforcement
1. `.gitignore` blocks `data/**`, telemetry, secrets, and parking source.
2. Telemetry hooks write ONLY under `data/telemetry/` (the ignored zone).
3. Before publishing: run a history scan (e.g. `gitleaks`, `trufflehog`) — never
   rely on `.gitignore` alone for a repo that started private.
4. Never use `git add -f`. If you must, stop and think about the wall.

## Open question still blocking full public release
Get a written IP/data ruling from VinSmart (Jira `SICA-2`) confirming that the
*aggregate, anonymized* results may be published. Until then, keep the repo
private even though the license intent is permissive.
