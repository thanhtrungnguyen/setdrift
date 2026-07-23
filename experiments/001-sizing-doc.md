# RUN-01 Sizing Doc: Evidence-Run Cost / Wall-Clock Estimate

**Status:** DRAFT — pre-pilot. All output-token figures below are `[ASSUMED — pending pilot]`
until Task 2 (STEP B/C) replaces them with measured numbers.

**Purpose:** RUN-01 is Phase 7's spend gate (D7-01, D7-02). NO live API call of any kind — other
than the explicitly-approved ~10-prompt pilot (D7-05) — may happen before Trung approves the
final ceiling in this document. This doc blocks all of Wave 3 (RUN-03..06).

**Committed BEFORE any non-pilot live call**, per the phase's must-have truth.

---

## 1. NAIVE arithmetic (overstatement — labeled explicitly)

Multiplying `corpus_size × runs × arms × cells × cycles` at published per-token rates, with
**no deduplication**, produces the following call counts:

| Workload | Formula | Calls |
|---|---|---|
| RUN-03 (arm B + arm C health, full corpus) | 2 arms × 5 runs × 618 prompts | 6,180 |
| RUN-05/06 (12-cell drift grid: 2 arms × 2 models × 3 revisions, Sonnet=val+test=248, Haiku=test=125) | Sonnet: 2 arms × 3 revisions × 5 runs × 248 = 7,440<br>Haiku: 2 arms × 3 revisions × 5 runs × 125 = 3,750 | 11,190 |
| **Naive total (RUN-03 + RUN-05/06)** | | **17,370** |

This is **the overstatement**. It assumes every run and every drift-grid revision issues a fresh
live API call. It does not.

## 2. DISTINCT-TRIPLE arithmetic (the real cost driver)

Per `response_cache.cache_key(model, prompt, tools)` (`repo/sica-plugin/eval/setdrift_eval/benchmark/response_cache.py:28-42`):

```python
payload = json.dumps({"model": model, "prompt": prompt, "tools": sorted(tools, ...)}, sort_keys=True)
return hashlib.sha256(payload.encode()).hexdigest()
```

The cache key has **no `run_idx` and no `revision`**. Because:
- the corpus is static (`_load_corpus_prompts` reads the same `corpus_path` regardless of
  `revision`, per `grid_runner.py`), and
- each arm's toolset (`arm_configs["A"/"B"]` → `load_skill_tools(skills_dir)`) does not change
  across revisions or runs within one grid invocation,

only the **first** call for any given `(model, prompt, tools)` triple is ever live. Every repeat
run in a 5-run noise band, and every revision in the drift grid that reuses the same
`(model, prompt, tools)` triple, is a cache hit (byte-identical replay — see
`drift/paired_stats.py`'s documented zero within-pair variance).

| Workload | Distinct-triple formula | Distinct calls |
|---|---|---|
| RUN-03 (arm B + arm C health) | 2 arms × 618 prompts (5 runs collapse to 1 per triple) | 1,236 |
| RUN-05/06 grid, Sonnet arms (val+test) | 2 arms × 248 prompts (3 revisions × 5 runs collapse to 1 per triple) | 496 |
| RUN-05/06 grid, Haiku arms (test only, D-59) | 2 arms × 125 prompts (3 revisions × 5 runs collapse to 1 per triple) | 250 |
| **Distinct-triple total (RUN-03 + RUN-05/06)** | | **1,982** |

**Collapse factor:** 17,370 naive / 1,982 distinct ≈ **8.8×** — the naive estimate overstates
live-call volume by roughly an order of magnitude, exactly as RESEARCH.md Pattern 1 / Pitfall 1
predicted. This is a **derived, not yet measured**, claim (RESEARCH Assumption A1) — confirmed
empirically by the ~10-prompt pilot in Task 2 before the ceiling is finalized.

RUN-04 (GEPA loop, 2 skills × ≤3 cycles) is **interactive**, not corpus-replay-shaped, and is
sized separately in §5 below — it does not benefit from the distinct-triple corpus-cache
collapse the same way (each GEPA reflection/propose step tends to explore a novel skill
description, so cache-hit rate is expected to be low for this workload).

## 3. PROMPT-CACHING quantification (D7-07, with vs without)

Shared prefix per call = system prompt + skill descriptions (fixed per arm/model, repeats across
every prompt in that arm's group). `[ASSUMED — pending pilot]`: prefix ≈ 800 tokens of a ≈1,500
token input; per-prompt unique content ≈ 700 tokens.

Grouping by (arm, model) — 2 arms × (618 health-corpus prompts) + 2 arms × (248 Sonnet grid
prompts) + 2 arms × (125 Haiku grid prompts) ≈ 4 large groups, avg group size ≈ 433 distinct
prompts sharing one prefix.

| | Without caching | With caching (Anthropic prompt-cache pricing model: ~1.25× write, ~0.1× read) |
|---|---|---|
| First call in a group | full price on 1,500 tok | 1.25× price on 800-tok prefix (write) + full price on 700-tok unique |
| Subsequent calls in a group | full price on 1,500 tok (input) | 0.1× price on 800-tok prefix (read) + full price on 700-tok unique |
| Per-call input-cost delta (subsequent calls, Sonnet $3/MTok) | $0.00450 | $0.00234 (≈ 48% cut on input-token cost) |

Applied to the ≈1,732 Sonnet distinct-triple calls (RUN-03 + RUN-05 Sonnet arms) across ≈4
groups (≈432 "subsequent" calls per group after the first), caching saves roughly **$3-4** off
the Sonnet distinct-triple input-token cost (§5). Small in absolute terms at this scale, but the
saving compounds if the estimate turns out to be an underestimate (A1 risk) — caching stays ON
by default per D7-07 regardless of absolute dollar impact, since it is free correctness (no
downside) once Batches is also applied.

## 4. BATCHES-API decision (D7-03)

| Workload | Routing | Rationale |
|---|---|---|
| RUN-03 (arm B/C health, 5-run bands) | **Batches API** (50% discount, 24h SLA) | Batch-shaped: many independent scoring calls, no interactive feedback loop |
| RUN-05/06 (12-cell drift grid, incl. Haiku) | **Batches API** (50% discount, 24h SLA) | Same — `benchmark/batch_runner.py::prewarm_cache` (07-02) submits one Batches job per workload's distinct-triple cache-miss set, polls to `ended`, and writes results into `data/cache/{key}.json` in the exact shape `response_cache.load_or_call`'s cache-miss branch produces. Every frozen call path (`arm_runner.run_arm`, `grid_runner.run_grid`) then hits the cache-HIT branch with zero live calls and zero edits to frozen scorer files. |
| RUN-04 (GEPA loop, 2 skills × ≤3 cycles) | **Interactive** (no Batches) | Per D7-03 / STACK.md: the GEPA optimizer's propose/reflect step needs synchronous feedback to drive its search; batching would defeat the loop's iterative nature. |

Supervision model (D7-14/D7-23): Trung is present at batch **submission** (config check, spend
commit) and at batch **collection/validation**; the async middle (up to 24h SLA) requires no
continuous watching. GEPA loop sessions are fully supervised end-to-end (interactive).

## 5. Cost estimate (distinct-triple basis, WITH Batches + caching)

`[ASSUMED — pending pilot]` per-call token estimate: input ≈1,500 tok, output ≈150 tok (capped
by `MAX_TOKENS=256` default). `[ASSUMED — confirm against Anthropic Console pricing page at
approval time]` rates: Sonnet $3/MTok in, $15/MTok out; Haiku $0.80/MTok in, $4/MTok out.

| Workload | Distinct calls | Per-call cost (no discount) | Subtotal (no discount) | With 50% Batches discount | With caching (Sonnet only, §3) |
|---|---|---|---|---|---|
| RUN-03 (Sonnet, arm B/C) | 1,236 | $0.00675 | $8.34 | $4.17 | ≈ $3.20 |
| RUN-05 Sonnet grid arms | 496 | $0.00675 | $3.35 | $1.68 | ≈ $1.20 |
| RUN-05 Haiku grid arms | 250 | $0.00180 | $0.45 | $0.225 | $0.225 (no caching modeled for Haiku) |
| **Batch-shaped subtotal** | 1,982 | | $12.14 | **≈ $6.08** | **≈ $4.63** |
| RUN-04 GEPA loop (interactive, `[ASSUMED]` ≈900 calls: 2 skills × 3 cycles × ≈150 calls/cycle, no Batches/caching discount) | ≈900 | $0.00675 | | | **≈ $6.08** |
| **Grand total (distinct-triple, with Batches + caching where applicable)** | | | | | **≈ $10.71** |

For comparison, the **naive** total (§1 volumes, no dedup, no Batches, no caching) would be
≈**$105** — the same ≈8-10× overstatement shown structurally in §1/§2.

## 6. PROPOSED CEILING

Point estimate (§5): **≈$11**. Given A1's risk (the distinct-triple cache-hit-rate assumption
is derived, not yet measured — if it fails, live-call volume could run 3-5× higher than
modeled) and rate-figure uncertainty (`[ASSUMED]` per-token rates and output-token counts),
propose a ceiling with generous headroom:

> **PROPOSED CEILING (pre-pilot draft): $75** (≈7× the point estimate; ≈70% margin even against
> the fully-naive $105 estimate). Final number is set in Task 2 STEP D after the pilot
> recalibrates output-token figures — this draft ceiling is presented to Trung alongside the
> pilot micro-approval in STEP A for context, not as the final approved number.

Per D7-04: if the ceiling is breached mid-run, finish the current atomic run unit (one 5-run
band, one cell batch) so no partial artifact is wasted, then HALT and report spend-so-far to
Trung — never silently continue past the ceiling.

## 7. Wall-clock estimate (against the early-August ceiling, ~2 weeks remaining)

| Session | Estimated supervised time | Notes |
|---|---|---|
| Pilot (Task 2 STEP B) | ~15-20 min | ~10 prompts, Sonnet, interactive, sequential |
| RUN-03 Batches submit + collect (2 supervised touches) | ~30-45 min total | Async 24h SLA in between, non-blocking |
| RUN-05/06 grid Batches submit + collect (2 supervised touches) | ~30-45 min total | Same async model |
| RUN-04 GEPA loop, 2 skills × ≤3 cycles (fully interactive/supervised) | ~3-4 hours total | Sequential single-threaded calls (no Inspect-AI concurrency wired per RESEARCH Anti-Pattern) |
| **Total supervised human time** | **≈5-6 hours**, spread across multiple days per D7-14 | Well within the ~2-week remaining ceiling; the 24h Batches SLA is calendar time, not supervised time |

## 8. PILOT PLAN (Task 2)

- **Scope:** ~10 prompts, drawn from the `val` partition, Sonnet (`claude-sonnet-4-6`), arm B
  toolset, interactive (no Batches) — small enough for a single supervised micro-approval.
- **Preconditions:** `assert_evidence_run("claude-sonnet-4-6")`
  (`repo/sica-plugin/eval/setdrift_eval/evidence/preflight.py`) must pass; invoked via
  `uv run --no-sync --no-env-file` to avoid the `.env`/openrouter-flip landmine.
- **Measurement:** record actual input/output tokens per prompt (from each response's `usage`
  block) and observed cache-hit/miss behavior across the ~10 calls.
- **STEP A (blocking):** Trung approves running this pilot (the only live call permitted before
  the final ceiling approval).
- **STEP B:** run the pilot; record measured tokens.
- **STEP C:** replace every `[ASSUMED]` output-token figure in §5/§6 with the pilot-measured
  number; recompute the distinct-triple total and the proposed ceiling.
- **STEP D (blocking):** Trung approves the finalized ceiling. No batch-shaped or full run
  (RUN-03..06) may start before this approval.

---

*Sizing doc format follows the append-only tone convention of
`repo/sica-plugin/docs/design/2026-05-20-falsifiable-claim.md` (dated, evidence-cited, explicit
about what is measured vs assumed). This document itself is not append-only — Task 2 STEP C
edits it in place to replace `[ASSUMED]` figures with pilot-measured ones, then the finalized
version is what Trung approves in STEP D.*

**Data-wall note:** this document contains only prompt counts, partition sizes, per-token rate
assumptions, and cost/wall-clock arithmetic — no raw prompt bodies, no telemetry content, no
secrets.
