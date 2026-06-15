# Setdrift

**A self-improving Claude Code plugin** that treats AI-coding-agent configuration
(CLAUDE.md, skills, hooks, sub-agents, MCP wiring) as a continuously optimizable
parameter — observed, diagnosed, patched, and verified in a closed loop.
Validated on a production Java / Spring Boot microservice platform.

Repo: <https://github.com/thanhtrungnguyen/setdrift>
(the local working folder is still `repo/sica-plugin/`).

> ⚠️ **Name note.** **Setdrift** is a coined control-theory term — *setpoint*
> (the target value a feedback loop holds, here skill-trigger F1) + *drift*
> (the codebase/model change the loop corrects) — naming this project's
> falsifiable claim in one word. It is **not** to be confused with Robeyns
> et al. 2025, *Self-Improving Coding Agent* (sometimes abbreviated "SICA"),
> which targets a different layer: the agent edits its **own source code** to
> improve itself. Setdrift optimizes *configuration*, not source code —
> related but distinct work. A 5-axis differential against Robeyns 2025 lands
> in dissertation Chapter 2 (background and related work). *(Previously
> codenamed "SICA"; the Jira project key remains `SICA`.)*

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

## Status

Active development (~10-week ceiling to early August 2026). Phase-level progress
from `.planning/ROADMAP.md`:

| Phase | Status |
|-------|--------|
| 0. Pre-flight | Complete (plans closed; a few human-only logistics outstanding) |
| 1. Telemetry Foundation | In progress (hard exit gate) |
| 2. Measurement Foundation | **Complete** (2026-06-02) |
| 3. The Loop | Pending |
| 4. Drift Evaluation | **Complete** (2026-06-11) |
| 5. Reporting & Triangulation | In progress |
| 6. Writeup, Defense, FSB Gate | Pending |

Tracked in the Jira project `SICA`; per-run results land in `experiments/`.

## Architecture

```text
┌───────────────────────────────────────────────────────────────────┐
│                     Claude Code Runtime                            │
│          (where the plugin manifests, hooks, and skills live)      │
├──────────────────┬──────────────────────┬───────────────────────────┤
│  Plugin Manifest │   Hooks (Event       │   Skills, Commands,       │
│  & Marketplace   │   Capture)           │   Sub-agents              │
│ `.claude-plugin/ │ `plugin/hooks/       │ `plugin/skills/`          │
│  plugin.json`    │  capture_event.py`   │ `plugin/commands/`        │
│                  │                      │ `plugin/agents/`          │
└──────────────────┴──────────────────────┴───────────────────────────┘
         │                                │
         │ Telemetry events              │ Observable skill triggers
         ▼                                │ and config drifts
┌───────────────────────────────────────────────────────────────────┐
│                    Telemetry Storage (gitignored)                  │
│              `data/telemetry/events.jsonl` (appended)              │
│  Contains: session_id, tool_name, success, ts, cwd (scrubbed)     │
└───────────────────────────────────────────────────────────────────┘
         │
         │ Raw telemetry logs
         ▼
┌───────────────────────────────────────────────────────────────────┐
│             Python Evaluation Harness (eval/setdrift_eval/)        │
├──────────────────┬──────────────────────┬───────────────────────────┤
│  benchmark/      │   optimizer/         │   telemetry/              │
│  - Issue→commit  │  - Skill-trigger     │  - Parse events.jsonl     │
│    replay        │    optimization      │  - Compute health metrics │
│  - Task dataset  │  - CLAUDE.md tuning  │  - Detect drift signals   │
│  - Offline eval  │  - DSPy MIPROv2,     │  - F1, pass-rate scoring  │
│                  │    GEPA backends     │                           │
└──────────────────┴──────────────────────┴───────────────────────────┘
         │
         │ Diagnosis (skill match analysis, config score)
         ▼
┌───────────────────────────────────────────────────────────────────┐
│                    Patch Proposal Engine                           │
│                (not yet implemented; scaffolding)                  │
│  - Generates new skill descriptions                               │
│  - Proposes CLAUDE.md edits                                       │
│  - Ranks by predicted impact                                      │
└───────────────────────────────────────────────────────────────────┘
         │
         │ Proposed config changes
         ▼
┌───────────────────────────────────────────────────────────────────┐
│                    Verification & Rollback                         │
│  - Replay benchmark with new config                               │
│  - Auto-promote (outside noise band) or auto-revert               │
│  - Audit trail in registrations/ + experiments/                   │
└───────────────────────────────────────────────────────────────────┘
```

Setdrift runs one loop — **observe → diagnose → patch → verify** — across two halves:

- **`plugin/`** — the Claude Code plugin (CC-native).
  - `hooks/` — capture developer tool-use telemetry (PostToolUse / UserPromptSubmit /
    Stop), with a layered PII/secret scrubber and a fail-loud JSONL path.
  - `skills/` — triggerable prompt enhancements whose `description` frontmatter is the
    optimization target (`spring-boot-endpoint`, `spring-jpa-entity`).
  - `agents/`, `commands/` — scaffolds for later phases.
- **`eval/`** — the Python evaluation harness (`setdrift_eval` package).
  - `telemetry/` — parse captured events into health metrics and drift signals.
  - `corpus/` — build the labeled GitBug-Java prompt corpus and gate mining precision.
  - `benchmark/` — offline replay of arms (B frozen, C stock) through the F1 scorer.
  - `optimizer/` — `dspy.GEPA` / `dspy.MIPROv2` wrappers that propose config edits.
  - `drift/` — Inspect-AI synthetic-drift task + drift-index detector.
  - `schemas/` — shared experiment/manifest data models.

**Loop discipline:** telemetry observes; the harness diagnoses (skill-trigger F1,
pass-rate, cost); the optimizer patches; the benchmark verifies offline and only
promotes a candidate when its mean is outside the baseline noise band. All hypotheses
are pre-registered; results are tracked in `experiments/` and tied to git commits.

## Tech stack

- **Language:** Python 3.14+.
- **Core deps:** `anthropic`, `pydantic`, `rich`, `gitpython`, `openai` (OpenRouter
  transport); `duckdb` + `pyarrow` (columnar telemetry); `presidio-analyzer` /
  `presidio-anonymizer` / `detect-secrets` (scrubber); `scikit-learn`, `scipy`, `numpy`,
  `pyyaml` (F1 / bootstrap-CI scorer).
- **Optional extras:** `optimize` → `dspy`; `drift` → `inspect-ai`, `sentence-transformers`.
- **Tooling:** `uv` (env + installs), `ruff`, `mypy`, `pytest`.

## Repository layout (monorepo)

```
setdrift/
├── plugin/          Claude Code plugin (CC-native: manifests, skills, hooks, agents, commands)
├── eval/            Python evaluation harness (setdrift_eval: benchmark, optimizer, telemetry, corpus, drift)
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

The environment is [uv](https://docs.astral.sh/uv/)-managed (Python 3.14+):

```bash
cp .env.example .env                 # add your ANTHROPIC_API_KEY
uv venv                              # create eval/.venv
uv pip install -e ./eval             # install the harness (editable)
# optional extras:
uv pip install -e "./eval[optimize,drift,dev]"
```

The harness exposes the `setdrift-eval` CLI. Install the plugin into Claude Code by
adding this repo as a marketplace (`plugin/.claude-plugin/marketplace.json`). Verify
the hook + skill load, then run the harness against the benchmark in `eval/`.

## Building the public corpus

The skill-trigger F1 measurement runs on a labeled prompt corpus mined from
GitBug-Java. See `docs/corpus.md` for the build and verification recipe.

## CI

None configured yet.

## License

MIT (see `LICENSE`). Swap to Apache-2.0 if a patent grant is needed for the
enterprise collaboration.
