# sica-plugin

**A self-improving Claude Code plugin** that treats AI-coding-agent configuration
(CLAUDE.md, skills, hooks, sub-agents, MCP wiring) as a continuously optimizable
parameter — observed, diagnosed, patched, and verified in a closed loop.
Validated on a production Java / Spring Boot microservice platform.

> ⚠️ **Name note:** "SICA" is also a 2025 paper (Robeyns et al., *Self-Improving
> Coding Agent*). This project is distinct: it optimizes *configuration*, not the
> agent's own source code. See `docs/` for the differential.

## The falsifiable claim

> An automated observe→diagnose→patch→verify loop sustains skill-trigger F1
> above a frozen hand-written configuration on both a public (GitBug-Java–derived)
> and an enterprise (parking) developer-prompt corpus, as the underlying codebase
> and model drift over the evaluation window.

See `registrations/01-hypothesis.md` for the pre-registration and
`docs/design/2026-05-20-falsifiable-claim.md` for the full methodology design
(thesis frame, metric operationalization, corpora, decision rule, pre-registered
contingencies).

**Null-result policy:** if a senior engineer's hand-tuned config beats the
auto-tuned one, that is a *finding*, not a failure (see `registrations/`).

## Repository layout (monorepo)

```
sica-plugin/
├── plugin/          Claude Code plugin (CC-native: manifests, skills, hooks, agents, commands)
├── eval/            Python evaluation harness (benchmark, optimizer, telemetry analysis)
├── experiments/     Experiment configs + tracked RESULTS (never raw data)
├── registrations/   Pre-registered hypotheses (write BEFORE running)
├── docs/            Research brief, brainstorming pack, design docs
└── data/            ⛔ GITIGNORED proprietary wall — telemetry, mined repos, parking source
```

## The data wall (read before your first commit)

This repo is **public**. Everything under `data/` is gitignored. Captured
developer prompts, mined parking-repo history, secrets, and any Vingroup source
**must never** be `git add -f`-ed across that wall. See `DATA_POLICY.md`.

## Quickstart

```bash
cp .env.example .env          # add your ANTHROPIC_API_KEY
python -m venv .venv && source .venv/bin/activate
pip install -e ./eval         # install the harness (editable)
```

Install the plugin into Claude Code by adding this repo as a marketplace
(`plugin/.claude-plugin/marketplace.json`). Verify the hook + skill load, then
run the harness against the benchmark in `eval/`.

## Building the public corpus

The skill-trigger F1 measurement runs on a labeled prompt corpus mined from
GitBug-Java. See `docs/corpus.md` for the build and verification recipe.

## Status

Scaffold — see `registrations/01-hypothesis.md` and the Jira project `SICA`.

## License

MIT (see `LICENSE`). Swap to Apache-2.0 if a patent grant is needed for the
enterprise collaboration.
