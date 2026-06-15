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
| Copilot Workspace | NO | NO | NO | NO | [Tier 2](#8-github-copilot-workspace) |

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
| Tier 2 | Prose citation — source URL + access date (D-07) | Aider, Cline, Devin, Copilot Workspace |

Full evidence log with per-comparator URLs, access dates, state summaries, and
screenshot capture notes: [`docs/competitor-verification-log.md`](competitor-verification-log.md)

**30-day re-verification deadline:** All entries were verified within the research
window ending 2026-07-15. All comparators must be re-checked within 30 days of
dissertation submission.

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
[Verification log: Tier 1 — mcpmarket.com; accessed 2026-06-15; ASSUMED; screenshot
and direct URL verification needed before submission; Assumption A4 resolution pending]

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
[Verification log: Tier 2 — cognition.ai/blog/swe-bench-technical-report, accessed 2026-06-15]

### 8. GitHub Copilot Workspace
Spec-to-PR planning workflow within GitHub; turns issues into pull requests.
No per-project skill-trigger configuration layer; no configuration optimization.
[Verification log: Tier 2 — blink.new/blog/best-ai-coding-agents-2026, accessed 2026-06-15]

---

*Source: `docs/competitor-verification-log.md` (tiered evidence per D-07)*
*Research date: 2026-06-15 | Valid until: 2026-07-15*
*Setdrift Phase 5 Plan 03 | REQ-DELIV-03*
