# Competitor Verification Log

**Purpose:** Dated tiered evidence log for the competitor differential one-pager
(`docs/competitor-diff.md`), supporting dissertation Chapter 2 positioning claim.
Evidence tiering follows D-07: full dated verification (URL + access date +
screenshot/commit-ref note) for the 4 closest comparators (Tier 1); prose citations
for the remaining 4 (Tier 2).

**Research source:** `.planning/phases/05-reporting-triangulation/05-RESEARCH.md`
(researched and verified 2026-06-15, MEDIUM–HIGH confidence)

**30-day re-verification deadline:** 2026-07-15. Every comparator entry below must
be re-checked against its live URL within 30 days of dissertation submission per D-07.
If any product state has changed materially, update the relevant cell in
`docs/competitor-diff.md` and record a new dated entry here.

**DEFERRAL NOTE — live web access:** Fresh live-verification (visiting each tier-1
URL today) is deferred to the human checkpoint (Task 3 of plan 05-03) because the
automated executor lacks web-access tools. The entries below are derived from the
research verification window recorded in `05-RESEARCH.md` (access date 2026-06-15).
The human reviewer at Task 3 is asked to spot-check at least 2 tier-1 entries against
their live URLs to satisfy D-07 before dissertation submission.

---

## 2026-07-27 Re-verification (Phase 8 / WRITE-01, D8-01)

**Scope:** Per D8-01 (`.planning/phases/08-outcome-independent-writing-human-outreach/08-CONTEXT.md`), this is a TARGETED spot re-verification of exactly 4 fast-moving comparators — GitHub Copilot (Workspace→Coding Agent naming), Devin, claude-mem, Cursor — not a full 8-tool sweep. This discharges the overdue 2026-07-15 re-verification deadline set below and the deferred Phase-5 05-03 Task-3 human spot-check.

**Live web access status:** The executing agent had no WebSearch/WebFetch tooling available this cycle. Per the source plan's explicit anti-fabrication fallback (do NOT carry forward a guess), the four field-tables below record the URLs to be checked and mark each comparator's state as `unverified as of 2026-07-27 — pending human spot-check`, carrying the prior 2026-06-15/2026-07-21 research findings forward for reference only, not as freshly confirmed. This resolves the file's original 2026-06-15 DEFERRAL NOTE by confirming that live verification is **still pending** the human checkpoint (Task 3 of plan 08-03) rather than performed — the deferral is not yet discharged, only re-dated and re-scoped to this cycle's checkpoint.

#### Re-check 1: GitHub Copilot (Workspace → Coding Agent)

| Field | Value |
|-------|-------|
| **Source URL** | https://github.com/orgs/community/discussions/197066 (Copilot Workspace discontinuation/succession discussion, per prior Tier-2 entry) |
| **Access date** | 2026-07-27 (attempted; no live web tooling — see status note above) |
| **State summary** | **unverified as of 2026-07-27 — pending human spot-check.** Prior confirmed state (2026-07-21, HIGH confidence, `.planning/research/FEATURES.md`): Copilot Workspace discontinued 2025-05-30 as a research preview; capabilities absorbed into "Copilot Coding Agent," GA since September 2025. |
| **Verdict change** | None applied this cycle — no live source available to confirm or refute. Row renamed `Copilot Workspace` → `Copilot Coding Agent` in `competitor-diff.md` based on the prior HIGH-confidence finding, since a wrong/discontinued product name is a hard factual error regardless of re-verification status. |

#### Re-check 2: Devin (Cognition)

| Field | Value |
|-------|-------|
| **Source URL** | https://cognition.ai/blog/swe-bench-technical-report (per existing Tier-2 entry) |
| **Access date** | 2026-07-27 (attempted; no live web tooling — see status note above) |
| **State summary** | **unverified as of 2026-07-27 — pending human spot-check.** Prior confirmed state (2026-07-21, MEDIUM confidence, contested signal, `.planning/research/FEATURES.md`): repositioned as "collaborative engineering platform" (shared session, human-in-loop intervention); no published trigger-precision/recall/F1 methodology found; market skepticism commentary exists alongside vendor-reported wins. |
| **Verdict change** | None applied this cycle — cannot confirm whether a trigger-F1 methodology has since been published without a live source. |

#### Re-check 3: claude-mem

| Field | Value |
|-------|-------|
| **Source URL** | https://github.com/thedotmack/claude-mem (per existing Tier-1 entry #2) |
| **Access date** | 2026-07-27 (attempted; no live web tooling — see status note above) |
| **State summary** | **unverified as of 2026-07-27 — pending human spot-check.** Prior confirmed state (2026-07-21, MEDIUM confidence, `.planning/research/FEATURES.md`): v13.8.0 shipped 2026-06-21; 83.9k GitHub stars, 288 releases. Version/star count churn frequently — this is exactly the row most likely to be stale by the time a human confirms it. |
| **Verdict change** | None applied this cycle — version/star count not re-confirmed. |

#### Re-check 4: Cursor Rules

| Field | Value |
|-------|-------|
| **Source URL** | https://cursor.com/docs/rules (per existing Tier-1 entry #3) |
| **Access date** | 2026-07-27 (attempted; no live web tooling — see status note above) |
| **State summary** | **unverified as of 2026-07-27 — pending human spot-check.** Prior confirmed state (2026-07-21, MEDIUM confidence, `.planning/research/FEATURES.md`): 2026 guidance shifted away from "giant always-on .mdc rules" (anti-pattern) toward AGENTS.md + scoped rules + subagents + Skills + hooks. |
| **Verdict change** | None applied this cycle — cannot confirm whether guidance shifted further since 2026-07-21. |

**Not re-checked this cycle (D8-01 carry-over, stable positioning):** obra/superpowers, Continue.dev, Aider, Cline. Per D8-01 these four are explicitly scoped OUT of this targeted re-verification pass — their entries below remain unchanged from the 2026-06-15 research window.

**30-day deadline resolution:** The original deadline below (`2026-07-15`) was **missed by 12 days** — this re-verification entry is dated 2026-07-27, not backdated. Per the project's own append-only/no-backdating discipline (`.planning/research/PITFALLS.md` Pitfall 1), this lateness is recorded honestly rather than concealed. A new re-verification deadline is set at **2026-08-26** (today + 30 days), tracked against the same live-URL set above. Given the four `unverified` markers above, the *effective* re-verification (the live human spot-check) is still outstanding at the time of this entry — see Task 3 of plan 08-03 for its resolution, to be appended below once complete.

---

## Tier 1 — Full Dated Verification (4 Closest Comparators)

These four require URL + access date + one-line state summary + screenshot/commit-ref
capture note before the dissertation is submitted (D-07).

---

### 1. obra/superpowers

| Field | Value |
|-------|-------|
| **Source URL** | https://github.com/obra/superpowers |
| **Access date** | 2026-06-15 (via 05-RESEARCH.md research window) |
| **State summary** | Open-source Claude Code plugin marketplace framework; composable SKILL.md skill files; bootstraps Claude to search and apply skills; 177K+ GitHub stars as of May 2026. No automated optimize loop, no labeled corpus, no F1 metric, no drift index. |
| **Closed-loop** | NO — skills are hand-curated by humans; no observe→diagnose→patch→verify automation |
| **Ground-truth labels** | NO — no labeled corpus; no precision/recall framework |
| **F1 metric** | NO — no trigger-quality measurement over a labeled corpus |
| **Drift-aware** | NO — no drift index; no monitoring of skill-trigger quality over time |
| **Evidence basis** | WebFetch of official GitHub README, 2026-06-15 (05-RESEARCH.md) |
| **Screenshot/commit-ref note** | ⚠ NEEDS LIVE SCREENSHOT/COMMIT-REF CAPTURE BEFORE SUBMISSION — capture the README hero section and the current commit hash from github.com/obra/superpowers |

**A4/A5 resolution:** N/A for this entry.

---

### 2. claude-mem

| Field | Value |
|-------|-------|
| **Source URL** | https://mcpmarket.com/tools/skills/self-improving-agent (closest public description at research time) |
| **Access date** | 2026-06-15 (via 05-RESEARCH.md research window; WebSearch only — no direct URL confirmation) |
| **State summary** | Memory-augmentation plugin for Claude Code; persists session summaries and learnings across sessions via `.learnings/` directory; some implementations record "unexpected failures" and "missing capabilities" in real time, creating a compound learning loop — but this is human-in-the-loop memory writing, not an automated optimize→verify loop. |
| **Closed-loop** | PARTIAL (Assumption A4 — see resolution below) |
| **Ground-truth labels** | NO — no labeled corpus; skill firing is not measured against a ground-truth test set |
| **F1 metric** | NO |
| **Drift-aware** | NO |
| **Evidence basis** | WebSearch only as of 2026-06-15; full URL-level verification pending (D-07 requirement) |
| **Screenshot/commit-ref note** | ⚠ NEEDS LIVE SCREENSHOT/COMMIT-REF CAPTURE BEFORE SUBMISSION — locate the canonical claude-mem repository (GitHub or MCP marketplace) and capture the README section describing the learning loop |

**Assumption A4 RESOLUTION:** Assumption A4 stated claude-mem's closed-loop
characterisation as "partial" — human-in-the-loop memory writing, not automated
closed-loop optimization. This assessment is **confirmed as stated** based on the
research evidence: the mechanism records learnings to `.learnings/` via human-authored
or semi-automated notes, not via an automated observe→diagnose→patch→verify loop with
a scorer and promotion gate. Classification remains **Partial\*** with the footnote
"human-in-the-loop learning, not automated closed-loop." The risk flagged in A4
(if claude-mem actually has a fully automated loop, Setdrift's differentiation weakens)
must be resolved by the human reviewer visiting the canonical source before
dissertation submission.

---

### 3. Cursor Rules (`.cursorrules` / `cursor_rules.md`)

| Field | Value |
|-------|-------|
| **Source URL (primary)** | https://deployhq.com/blog/ai-coding-config-files-guide |
| **Source URL (Arize experiment)** | https://arize.com/blog/optimizing-coding-agent-rules |
| **Access date** | 2026-06-15 (via 05-RESEARCH.md research window) |
| **State summary** | Per-project hand-authored configuration files injected into Cursor's context. Arize AI demonstrated a DSPy-based meta-prompting approach to optimizing `.clinerules` (Cline's analog — different product), but this is a third-party research experiment, not a native Cursor product feature. Cursor Rules themselves have no automated optimization mechanism. |
| **Closed-loop** | NO — Cursor Rules are hand-written; no automated optimization in the Cursor product; the Arize experiment optimizes `.clinerules` (Cline), not `.cursorrules` (Cursor) |
| **Ground-truth labels** | NO† — the Arize experiment uses SWE-bench Lite unit-test pass/fail as ground truth, not a labeled skill-trigger corpus; different evaluation target |
| **F1 metric** | NO† — Arize uses pass-rate accuracy, not skill-trigger F1 |
| **Drift-aware** | NO — no drift index in the Cursor product or the Arize experiment |
| **Evidence basis** | CITED (deployhq.com blog) + CITED (arize.com/blog) + ASSUMED for drift column (05-RESEARCH.md 2026-06-15) |
| **Screenshot/commit-ref note** | ⚠ NEEDS LIVE SCREENSHOT/COMMIT-REF CAPTURE BEFORE SUBMISSION — capture the Arize blog post URL and confirm the Cursor product documentation confirms no native optimization loop |

**Setdrift differentiation note:** Setdrift measures skill-trigger quality (which rule should
fire) as F1 against a labeled corpus. The Arize approach measures task-completion
accuracy (does the whole agent succeed?) — a different and less targeted objective.

---

### 4. Continue.dev

| Field | Value |
|-------|-------|
| **Source URL** | https://continue.dev (official docs; see also augmentcode.com comparison) |
| **Access date** | 2026-06-15 (via 05-RESEARCH.md research window; ASSUMED — no direct URL confirmation found) |
| **State summary** | Open-source VS Code / JetBrains AI coding assistant with per-project `.continue/rules/` configuration (Markdown) and model-agnostic backends. Rules are hand-authored. No automated improvement loop found in the Continue.dev product at research time. |
| **Closed-loop** | NO — rules are hand-authored; no automated improvement loop in the Continue.dev product (Assumption A5 — see resolution below) |
| **Ground-truth labels** | NO |
| **F1 metric** | NO |
| **Drift-aware** | NO |
| **Evidence basis** | All columns ASSUMED — WebSearch only; full URL-level verification required before dissertation inclusion (D-07 tier 1 requirement) |
| **Screenshot/commit-ref note** | ⚠ NEEDS LIVE SCREENSHOT/COMMIT-REF CAPTURE BEFORE SUBMISSION — visit continue.dev/docs and confirm there is no automated rules-optimization feature; capture a screenshot of the `.continue/rules/` documentation section |

**Assumption A5 RESOLUTION:** Assumption A5 stated Continue.dev has no closed-loop
optimization. This assessment is **provisionally confirmed** based on WebSearch
evidence from research: no automated improvement loop was found in the Continue.dev
product documentation. However, because this is based on WebSearch only (not a direct
URL-level visit), the classification is recorded as **NO** with an ASSUMED qualifier.
The human reviewer at Task 3 must confirm this against the live continue.dev
documentation before the dissertation includes this claim.

---

## Tier 2 — Prose Citations (4 Remaining Comparators)

Per D-07, these comparators receive prose citation with source URL + access date.
All four columns are still populated; evidence depth is lighter than Tier 1.

---

### 5. Aider

| Field | Value |
|-------|-------|
| **Source URL** | https://aider.chat (official site; verified via WebSearch 2026-06-15) |
| **Access date** | 2026-06-15 (via 05-RESEARCH.md research window) |
| **State summary** | Terminal-based agentic coding tool with `.aider.conf.yml` configuration; uses git history for context; auto-commits changes. Configuration is static — no automated optimization of configuration files. |
| **Closed-loop** | NO — configuration is static |
| **Ground-truth labels** | NO |
| **F1 metric** | NO |
| **Drift-aware** | NO |
| **Evidence basis** | WebSearch only; prose citation per D-07 |

---

### 6. Cline (formerly Claude Dev)

| Field | Value |
|-------|-------|
| **Source URL** | https://github.com/cline/cline; https://arize.com/blog/optimizing-coding-agent-rules |
| **Access date** | 2026-06-15 (via 05-RESEARCH.md research window) |
| **State summary** | VS Code AI coding agent with `.clinerules` configuration files. Arize AI optimized `.clinerules` via DSPy meta-prompting (third-party research experiment using SWE-bench pass-rate — not a native Cline feature, different evaluation target from Setdrift). |
| **Closed-loop** | NO (native); third-party research experiment exists (Arize), not a native Cline product feature |
| **Ground-truth labels** | NO† — Arize experiment uses SWE-bench pass/fail (task-level, not skill-trigger labels) |
| **F1 metric** | NO† — Arize uses pass-rate accuracy, not skill-trigger F1 |
| **Drift-aware** | NO |
| **Evidence basis** | CITED (arize.com/blog) for the third-party experiment; ASSUMED for native columns and drift; prose citation per D-07 |

---

### 7. Devin (Cognition)

| Field | Value |
|-------|-------|
| **Source URL** | https://cognition.ai/blog/swe-bench-technical-report; https://aitoolranked.com/blog/devin-ai-review |
| **Access date** | 2026-06-15 (via 05-RESEARCH.md research window) |
| **State summary** | Autonomous AI software engineer; 71% on SWE-bench Verified as of 2026. Operates task-by-task; no skill-configuration layer. Evaluated on SWE-bench (task-level), not skill-trigger F1 against a labeled corpus. |
| **Closed-loop** | NO — no skill-trigger configuration layer to optimize |
| **Ground-truth labels** | NO† — uses SWE-bench (task-level pass/fail), not a labeled skill-trigger corpus |
| **F1 metric** | NO† — no skill-trigger F1; task-level resolve rate only |
| **Drift-aware** | NO |
| **Evidence basis** | CITED (cognition.ai SWE-bench report; aitoolranked.com review); ASSUMED for F1 and drift columns; prose citation per D-07 |

---

### 8. GitHub Copilot Workspace

| Field | Value |
|-------|-------|
| **Source URL** | https://blink.new/blog/best-ai-coding-agents-2026 (comparison blog accessed 2026-06-15) |
| **Access date** | 2026-06-15 (via 05-RESEARCH.md research window) |
| **State summary** | Spec-to-PR planning workflow inside GitHub; turns issues into pull requests; no per-project skill-trigger configuration layer. No automated configuration optimization mechanism. |
| **Closed-loop** | NO |
| **Ground-truth labels** | NO |
| **F1 metric** | NO |
| **Drift-aware** | NO |
| **Evidence basis** | WebSearch only; prose citation per D-07 |

---

## Assumption Resolution Summary

| Assumption | Claim | Resolution | Action required |
|-----------|-------|------------|-----------------|
| A4 | claude-mem closed-loop = "partial" (human-in-the-loop, not automated) | CONFIRMED AS STATED — human-authored `.learnings/`, not automated loop | Human reviewer must confirm at live canonical URL before submission |
| A5 | Continue.dev has no closed-loop optimization | PROVISIONALLY CONFIRMED — no loop found in WebSearch; evidence is ASSUMED | Human reviewer must confirm at live continue.dev docs before submission |

---

*Log maintained by: Setdrift Phase 5 Plan 03 executor*
*Log created: 2026-06-15*
*Original required review: 2026-07-15 (MISSED — see 2026-07-27 Re-verification section above, not backdated)*
*New required review: 2026-08-26 (2026-07-27 + 30 days)*
