# Pre-registration 01 — primary hypothesis

> Write this BEFORE running experiments. Edit only by appending dated notes.

## Falsifiable claim

An automated observe→diagnose→patch→verify loop sustains skill-trigger F1 above
a frozen hand-written configuration on both a public (GitBug-Java–derived) and
an enterprise (parking) developer-prompt corpus, as the underlying codebase and
model drift over the evaluation window.

## Primary metric

- **Skill-trigger F1** (macro, computed per-prompt over the held-out corpus) — the spine of the claim.

## Secondary metrics (reported, not part of the claim)

- End-to-end task pass-rate on the offline replay benchmark
- Token cost per resolved task

## Corpora

- **Public (primary publishable):** GitBug-Java–derived developer prompts, ≥500 prompts, heuristic-labeled with 20% manual verification.
- **Enterprise (validation):** Parking telemetry, ≥200 prompts, senior-engineer-labeled, gated on the VinSmart IP ruling (Jira `SICA-2`).

See `docs/design/2026-05-20-falsifiable-claim.md` §4 for sourcing details.

## Conditions

- **A:** Setdrift-managed config
- **B:** Frozen hand-written config *(comparator)*
- **C:** No-config baseline (stock Claude Code)

The claim concerns A vs B; C is reported as a sanity floor.

## Decision rule

- The claim survives only if A's macro-F1 exceeds B's macro-F1 by more than the noise band measured across 3 repeated runs, on **both** corpora.
- A null or negative result is reported as a finding (see README null-result policy), not a failure.
- The noise-band threshold will not be lowered post-hoc.

## Threats to validity (pinned)

- Model version pinned: `claude-sonnet-4-6`. Sensitivity re-run on `claude-haiku-4-5`.
- LLM-as-judge validated against a 20% manual spot-check; inter-rater agreement (Cohen's κ) reported.
- 6-month evaluation window so genuine drift can occur.

## Pre-registered contingencies (graceful degradations)

See `docs/design/2026-05-20-falsifiable-claim.md` §8 for the full risk register. Headlines:

- If GitBug-Java yields < 500 labelable prompts → augment with Defects4J + open Spring repos (pre-approved fallback corpus list).
- If the VinSmart IP ruling (`SICA-2`) blocks publication of parking data → the claim degrades to a public-corpus-only form (design candidate Option β); parking validation moves to appendix.
- If F1 is too noisy on either corpus → increase sample size; do not weaken the significance criterion.

_Registered: 2026-05-20_

Threat list extended on 2026-05-31; see docs/design/2026-05-20-falsifiable-claim.md Change Log entry of that date.
