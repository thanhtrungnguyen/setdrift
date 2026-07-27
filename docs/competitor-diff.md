# Competitor Differential — Setdrift vs. 8 Comparators

**Chapter 2 figure — Competitor Positioning**

**Rubric columns (fixed per D-07/CONTEXT.md §specifics):**

| Column | Definition |
|--------|-----------|
| **Closed-loop** | Automated observe→diagnose→patch→verify cycle without human intervention to propose and gate config changes |
| **Ground-truth labels** | Labeled prompt→expected-skill corpus with inter-rater agreement (κ) used for evaluation |
| **F1 metric** | Skill-trigger macro-F1 measured over the labeled corpus as the primary optimization target |
| **Drift-aware** | Monitoring of skill-trigger quality over time as model or codebase drifts; dedicated drift index |

---

## Differential Table

| Comparator | Closed-loop | Ground-truth labels | F1 metric | Drift-aware | Evidence tier |
|-----------|:-----------:|:-------------------:|:---------:|:-----------:|:-------------:|
| **Setdrift (ours)** | **YES** | **YES** (labeled corpus, κ ≥ 0.6) | **YES** (macro-F1, noise band) | **YES** (drift index) | [Tier 1 — internal](#setdrift-ours) |
| obra/superpowers | NO | NO | NO | NO | [Tier 1](#1-obrasuperpowers) |
| claude-mem | Partial\* | NO | NO | NO | [Tier 1](#2-claude-mem) |
| Cursor Rules | NO | NO† | NO† | NO | [Tier 1](#3-cursor-rules-cursorrules--cursor_rulesmd) |
| Continue.dev | NO | NO | NO | NO | [Tier 1](#4-continuedev) |
| Aider | NO | NO | NO | NO | [Tier 2](#5-aider) |
| Cline | NO | NO† | NO† | NO | [Tier 2](#6-cline-formerly-claude-dev) |
| Devin | NO | NO† | NO† | NO | [Tier 2](#7-devin-cognition) |
| Copilot cloud agent‡ | NO | NO | NO | NO | [Tier 2](#8-github-copilot-cloud-agent) |

**Footnote \*:** Partial — claude-mem uses human-in-the-loop memory writing to a
`.learnings/` directory. Some implementations record failures and missing capabilities
in real time, but there is no automated optimize→verify loop with a scorer and
promotion gate. Classification is ASSUMED; requires full dated URL verification
before dissertation submission (see verification log Entry 2, Assumption A4).

**Footnote †:** A third-party research experiment (Arize AI, 2026) optimized
`.clinerules` (Cline's analog) and Cursor Rules via DSPy meta-prompting, using
SWE-bench Lite unit-test pass/fail as ground truth. This is not a native product
feature. The evaluation target (task-completion accuracy) is distinct from Setdrift's
target (skill-trigger label F1 against a labeled corpus). These cells are marked
NO† to acknowledge the third-party experiment while correctly classifying the
native product capability.

**Footnote ‡:** GitHub Copilot Workspace's issue→draft-PR capability is now
documented by GitHub itself as **"Copilot cloud agent"** (GA, all paid plans) —
live-verified 2026-07-27 via direct fetch of GitHub's own current documentation
and changelog (see `competitor-verification-log.md`). This row is renamed from
"Copilot Coding Agent" to "GitHub Copilot cloud agent (formerly Copilot Workspace)"
to match GitHub's own official terminology. Note: third-party 2026 sources commonly
use "Copilot Coding Agent" for a separate, IDE-embedded agent-mode feature (VS
Code/JetBrains, GA March 2026) — this naming landscape is genuinely unsettled;
readers encountering "Copilot Coding Agent" elsewhere may be looking at a different
GitHub product. Verdicts (NO/NO/NO/NO) confirmed unchanged after live re-verification
and human approval (Trung, "spot-check approved", 2026-07-27).

---

## Setdrift's Defensible Novelty

**Setdrift is the only entry in this table that simultaneously holds all four rubric
columns.** Each of the 8 comparators fails at least three of the four columns.
The closest comparator, obra/superpowers, fails all four: it provides the same
composable SKILL.md pattern as Setdrift's plugin layer but adds no measurement loop,
no labeled corpus, no F1 metric, and no drift signal. claude-mem comes nearest
on the closed-loop column (Partial) but still lacks ground-truth labels, F1 scoring,
and drift awareness. The Arize/SWE-bench research thread (Cline, Cursor Rules, Devin)
demonstrates that automated config optimization is an active research area, but it
uses a different evaluation target — task-level pass-rate over a static benchmark —
rather than skill-trigger F1 over a labeled, drift-sensitive corpus. Setdrift's
contribution is precisely this combination: a closed loop that optimizes the
configuration parameter that directly governs skill-trigger quality (F1), with
a drift-aware monitoring signal as the loop's trigger.

---

## Evidence Tier Notes

| Tier | Depth | Comparators |
|------|-------|-------------|
| Tier 1 | Full dated verification — source URL + access date + screenshot/commit-ref note (D-07) | obra/superpowers, claude-mem, Cursor Rules, Continue.dev |
| Tier 2 | Prose citation — source URL + access date (D-07) | Aider, Cline, Devin, Copilot cloud agent |

Full evidence log with per-comparator URLs, access dates, state summaries, and
screenshot capture notes: [`docs/competitor-verification-log.md`](competitor-verification-log.md)

**30-day re-verification deadline:** Original deadline 2026-07-15 was missed
(recorded honestly, not backdated — see verification log's 2026-07-27
Re-verification section). A targeted spot re-verification (Copilot, Devin,
claude-mem, Cursor per D8-01) was live-verified 2026-07-27 via WebSearch/WebFetch/
`gh api`, with findings reviewed and approved by Trung directly ("spot-check
approved"). New re-verification deadline: 2026-08-26.

---

## Per-Comparator Rationale

### Setdrift (ours)
Automated observe→diagnose→patch→verify loop; labeled developer-prompt corpus
(GitBug-Java–derived, κ ≥ 0.6 floor); skill-trigger macro-F1 as primary metric;
drift index monitoring over evaluation window.
[Verification: internal — `registrations/01-hypothesis.md`]

### 1. obra/superpowers
Open-source Claude Code plugin marketplace framework (177K+ GitHub stars, May 2026).
Composable SKILL.md pattern identical to Setdrift's plugin layer; no measurement loop,
no labeled corpus, no F1 metric, no drift signal. Skills are hand-curated.
[Verification log: Tier 1 — github.com/obra/superpowers, accessed 2026-06-15;
screenshot needed before submission]

### 2. claude-mem
Memory-augmentation plugin for Claude Code; persists session summaries via
`.learnings/`. Some implementations record failures in real time (Partial closed-loop)
but no automated optimize→verify loop exists. No labeled corpus, no F1, no drift index.
Live-verified 2026-07-27 via `gh api`: latest release v13.12.4 (published 2026-07-23),
88,717 GitHub stars.
[Verification log: Tier 1 — mcpmarket.com; accessed 2026-06-15; ASSUMED; screenshot
and direct URL verification needed before submission; Assumption A4 resolution pending;
version/star count re-verified 2026-07-27 (`competitor-verification-log.md`)]

### 3. Cursor Rules (`.cursorrules` / `cursor_rules.md`)
Hand-authored per-project configuration files for the Cursor IDE. No automated
optimization in the native Cursor product. A third-party DSPy experiment (Arize, 2026)
optimized analogous `.clinerules` (Cline) using SWE-bench pass-rate — different
product, different evaluation target.
[Verification log: Tier 1 — deployhq.com/blog + arize.com/blog, accessed 2026-06-15;
screenshot needed before submission]

### 4. Continue.dev
Open-source VS Code / JetBrains coding assistant with `.continue/rules/` Markdown
configuration. Rules are hand-authored; no automated improvement loop found in the
product documentation.
[Verification log: Tier 1 — continue.dev; accessed 2026-06-15; ASSUMED; screenshot
needed before submission; Assumption A5 resolution pending]

### 5. Aider
Terminal-based agentic coding tool with `.aider.conf.yml` static configuration.
Auto-commits changes using git context; no configuration optimization.
[Verification log: Tier 2 — aider.chat, accessed 2026-06-15]

### 6. Cline (formerly Claude Dev)
VS Code agent with `.clinerules` configuration. Third-party Arize experiment (SWE-bench
pass-rate) is not a native product feature. No native closed-loop optimization.
[Verification log: Tier 2 — github.com/cline/cline + arize.com/blog, accessed 2026-06-15]

### 7. Devin (Cognition)
Autonomous AI software engineer; 71% on SWE-bench Verified as of 2026. Operates
task-by-task with no skill-configuration layer; no trigger-quality measurement.
Pricing restructured 2026 into subscription tiers (Free $0 / Pro $20/mo / Max $200/mo /
Teams $80/mo+$40/seat, consumption unit "ACU") — a ~96% cut from the original $500/mo
entry tier, live-verified 2026-07-27.
[Verification log: Tier 2 — cognition.ai/blog/swe-bench-technical-report, accessed 2026-06-15;
pricing re-verified 2026-07-27 (`competitor-verification-log.md`)]

### 8. GitHub Copilot cloud agent
Spec-to-PR async workflow within GitHub; assign an issue, it runs in a sandboxed
GitHub Actions environment and opens a draft PR. No per-project skill-trigger
configuration layer; no configuration optimization. GitHub's own current
documentation (docs.github.com, fetched 2026-07-27) calls this "Copilot cloud
agent" — no mention of "Copilot Workspace" as a former name on that page, though
GitHub's changelog usage shifted away from "Copilot Workspace" sometime after its
last named mention in December 2024. Third-party sources commonly use "Copilot
Coding Agent" for a separate, IDE-embedded feature — see Footnote ‡ for the
naming ambiguity.
[Verification log: Tier 2 — docs.github.com/en/copilot/concepts/agents/coding-agent/about-coding-agent,
live-fetched and human-approved 2026-07-27 (`competitor-verification-log.md`)]

---

*Source: `docs/competitor-verification-log.md` (tiered evidence per D-07)*
*Research date: 2026-06-15 | Original valid-until: 2026-07-15 (missed) | Re-verified and human-approved: 2026-07-27 | New valid-until: 2026-08-26*
*Setdrift Phase 5 Plan 03 | Phase 8 Plan 03 (WRITE-01, D8-01) | REQ-DELIV-03*
