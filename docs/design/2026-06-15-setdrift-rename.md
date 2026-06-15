# Design: Rename SICA → Setdrift (public brand + full identifier rename)

**Date:** 2026-06-15
**Status:** Approved — implementing
**Type:** Project-wide rename / rebrand

## Motivation

The project's working name **SICA** ("Self-Improving Configuration Agent") collides
with **Robeyns et al. 2025, _Self-Improving Coding Agent_** — a distinct system in which
the agent edits its **own source code** to improve itself. This project optimizes
*configuration* (skills, hooks, CLAUDE.md, sub-agents, MCP wiring) in a closed
observe→diagnose→patch→verify loop, holding skill-trigger F1 above a frozen
hand-written baseline as the codebase and model drift. The name collision is an
academic-integrity and positioning risk at defense (Chapter 2 background/related work).

**Decision:** adopt **Setdrift** as the project name and rename SICA out of the codebase
entirely. "Setdrift" is a coined control-theory term — *setpoint* (the target value a
feedback loop holds, i.e. skill-trigger F1) + *drift* (the codebase/model change the loop
corrects) — which names the falsifiable claim in a single word and carries no
"Self-Improving … Agent" echo. The name was availability-vetted (PyPI / npm / GitHub /
web-trademark) and is uncontested; "Setpoint" was rejected for trademark/SEO conflicts
(Setpoint.io, Logitech SetPoint) and an npm squat.

## Scope — target identifiers

| Old | New |
|-----|-----|
| brand "SICA" (prose, README, CLAUDE.md, docs) | **Setdrift** |
| Python import package `sica_eval` | `setdrift_eval` |
| Distribution + CLI `sica-eval` | `setdrift-eval` |
| Environment variables `SICA_*` (e.g. `SICA_MODEL`) | `SETDRIFT_*` |
| Plugin id `sica` / marketplace `sica-marketplace` | `setdrift` / `setdrift-marketplace` |
| GitHub repo `sica-plugin` | `setdrift` |

### Measured blast radius (2026-06-15)

- `sica_eval` (import pkg): 89 files, 1,225 refs
- `sica-eval` (dist/CLI): 189 refs
- `SICA_*` (env): 379 refs
- plugin manifests: 4 refs
- `.planning/` + memory: 113 files, 2,661 refs (brand + path refs)

## Implementation strategy — tiered, test-gated

Each tier is an atomic commit on branch `rename/sica-to-setdrift` in `repo/sica-plugin`,
with `pytest` run to green before the next tier. `git mv` is used for the package
directory so `git log --follow` / `git blame` survive the rename (auditable research artifact).

1. **Import package** — `git mv eval/sica_eval eval/setdrift_eval`; rewrite all
   `sica_eval` references; `pytest` green.
2. **Dist/CLI** — `pyproject.toml` name + entry point + package discovery; reinstall
   editable; CLI smoke test.
3. **Env vars** — `SICA_*` → `SETDRIFT_*` across config, hooks, `.env.example`.
4. **Plugin + brand** — plugin id/manifests; README (H1 + rewritten Name note); CLAUDE.md;
   remaining docs.
5. **Reproducibility change-log** — dated entry appended to the append-only
   `docs/design/2026-05-20-falsifiable-claim.md` (see below).
6. **Planning + memory sweep** — brand and code-path refs in `.planning/` and the
   auto-memory store (non-git).
7. **External** — rename GitHub repo `sica-plugin` → `setdrift`; update git remote URL.
   (Jira project key `SICA` handled by the owner; keys are typically not renamable.)

## Reproducibility handling (methodology rigor)

Experiments pin a **config hash**. The FROZEN benchmark file `arm_runner.py` imports
`sica_eval`, and renaming the import package + env vars (`SICA_MODEL`→`SETDRIFT_MODEL`)
changes file text and therefore config hashes. **Behavior is byte-identical** — this is a
pure identifier rename with no logic change — so the frozen arm's *results* are preserved;
the full `pytest` suite (incl. the D-13 byte-identity tests from Phase 5 plan 05-01) gates
each tier to prove it. To preserve provenance, a **dated change-log entry** is appended to
the append-only `docs/design/2026-05-20-falsifiable-claim.md` recording the rename, the
old→new identifier map, and that frozen-arm behavior is unchanged. Pre-rename experiments
remain valid under their original hashes; post-rename runs are re-pinned under the new map.

## Explicit deferral

- **Local working-folder name `repo/sica-plugin`** is intentionally **kept** for now.
  Renaming the on-disk directory would invalidate ~2,661 path references across `.planning/`
  and the active Phase-5 plan/STATE/ROADMAP paths mid-execution. The folder name is cosmetic
  and independent of the GitHub repo name. Rename it as a clean follow-up after Phase 5 lands.

## Non-goals

- No logic/behavior changes. This is a pure rename.
- No change to the falsifiable claim text (§1 of the design doc is append-only).
- No data-wall impact: nothing under `data/` is touched.
