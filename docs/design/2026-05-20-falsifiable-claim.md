# Design: Falsifiable Claim — Spine of the SICA Project

**Status:** Approved
**Date:** 2026-05-20
**Author:** Trung
**Pre-registration:** `registrations/01-hypothesis.md`
**Companion:** `docs/SICA_Brainstorming_Pack.md` §3 (frame selection)

---

## 1. The Claim

> An automated observe→diagnose→patch→verify loop sustains skill-trigger F1 above a frozen hand-written configuration on both a public (GitBug-Java–derived) and an enterprise (parking) developer-prompt corpus, as the underlying codebase and model drift over the evaluation window.

This sentence appears verbatim in `README.md` (top of repo) and `registrations/01-hypothesis.md`. If proven false on **either** corpus, the project's primary scientific contribution dies.

## 2. Thesis Frame

**Frame B — Configuration Drift Detection** (empirical-software-engineering story). Selected over Frame A (Configuration-as-Hyperparameter, ML lineage) and Frame C (AgentOps, industry framing) per `docs/SICA_Brainstorming_Pack.md` §3, line 58. The same system, evaluated the same way, supports all three frames; Frame B is the dissertation framing because it plays into ICSE / FSE / MSR's audience and matches the project's measurement-first character.

Frames A and C remain available as the *paper* and *talk* pitches respectively.

## 3. Primary Metric

**Skill-trigger F1**, defined as:

For each developer prompt in the held-out corpus, run Claude Code under the active configuration arm and log the set of skills it invokes. Compare that set against a ground-truth label of which skill(s) *should have* fired. Compute precision, recall, F1 per-prompt; report **macro-F1** over the corpus.

Why this metric, under Frame B: it directly measures *config-fit* — does the configuration still route prompts to the right specialized capability as conditions evolve? End-to-end pass-rate is one step downstream and confounds config-fit with model capability and task difficulty.

**What "drift" means in this study** (operationalized so the claim is testable):

- **Model drift** — Anthropic upgrades the pinned model (e.g. `claude-sonnet-4-6` → next version) during the evaluation window, or the same prompt yields different invocation behavior between runs spaced ≥1 month apart on a pinned model.
- **Codebase drift (enterprise corpus)** — the parking-platform HEAD advances by ≥N commits or introduces new modules/idioms not present at *t=0*.
- **Codebase drift (public corpus)** — GitBug-Java releases new bugs covering Spring/Hibernate API revisions, or new Java versions appear in the bug set, during the evaluation window.

The frozen configuration (arm B) is fixed at *t=0* and never sees these changes; arm A's loop sees them and is allowed to adapt.

**Secondary metrics** (reported in dissertation, not part of the claim):
- End-to-end task pass-rate on the offline replay benchmark
- Token cost per resolved task

## 4. Corpora

Both corpora are load-bearing under the claim. See §8 for what happens if one becomes unavailable.

| Corpus | Source | Ground-truth labels | Size target |
|---|---|---|---|
| **Public** (primary publishable) | GitBug-Java–derived: commit messages and linked GitHub issues from GitBug-Java's 199 reproducible Java bugs become "developer prompts." The corresponding bug-fix patch labels which skill(s) (e.g. `jpa-migration`, `spring-test-fix`, `dependency-bump`) should have fired. | Heuristic-mined from patch diffs and commit-message keywords, then manually verified on a 20% random sample. | ≥500 prompts |
| **Enterprise** (validation) | Parking telemetry captured via `plugin/hooks/capture_event.py`, gated on the VinSmart IP ruling (Jira `SICA-2`). | A senior parking-platform engineer labels which skill should have fired (single-rater for the bulk corpus; 20% spot-check by a second engineer for inter-rater agreement). | ≥200 prompts (post-IP clearance) |

## 5. Conditions

Three arms, evaluated on each corpus (so six cells total):

- **A:** SICA-managed configuration (auto-tuned each cycle by the observe→diagnose→patch→verify loop)
- **B:** Frozen hand-written configuration (snapshot at *t=0*, never updated — the comparator)
- **C:** No configuration baseline (stock Claude Code with no plugin)

The primary claim concerns the **A vs B** comparison. Condition C is reported as a sanity floor.

## 6. Decision Rule

The claim **survives** only if:

1. Condition A's macro-F1 exceeds condition B's macro-F1 by more than the **noise band** measured across three repeated runs on the same corpus, **and**
2. This holds on **both** corpora.

The claim **dies** if:

- A ≤ B on either corpus (frozen config wins or ties — configuration drift is not detectable by SICA's loop on that context), or
- A > B on neither corpus (no effect anywhere), or
- The effect on one corpus is positive but the other is negative (incoherent — methodology does not generalize across contexts).

A null or negative result is reported as a finding per the README null-result policy, not as a failure.

## 7. Threats to Validity (pinned ex-ante)

| Threat | Mitigation |
|---|---|
| Model version drift mid-evaluation | Pin to `claude-sonnet-4-6`. Sensitivity re-run on `claude-haiku-4-5` for one full corpus pass. |
| LLM-as-judge bias in skill-trigger labeling | Validate against 20% manual spot-check; report inter-rater agreement (Cohen's κ). |
| Insufficient drift to be detectable | Run over a ≥6-month evaluation window so genuine codebase and model drift can occur. Document specific drift events (model upgrades, codebase HEAD shifts ≥ N commits). |
| Heuristic mining produces noisy labels | 20% manual verification gate; if precision of mined labels < 0.85, expand manual labeling before proceeding. |

## 8. Risk Register — Pre-Registered Contingencies

These are not post-hoc rationalizations. They are committed *now* so a mid-project pivot is a planned graceful degradation, not a credibility hit.

| If… | Then… | Pre-registered fallback |
|---|---|---|
| GitBug-Java does not yield ≥500 labelable prompts after mining | Augment with Defects4J (357 Java bugs) and issue-to-patch mining from public Spring repos | Pre-approved fallback corpus list: Defects4J, then `spring-projects/*` issue tracker, then `apache/*` Java projects |
| Parking IP ruling (Jira `SICA-2`) blocks publication of parking data | Claim degrades to a single-corpus public claim (Option β from design candidates): "public corpus only is the spine; parking validation moves to appendix" | Documented here so the degradation is a *planned contingency*, not a retroactive reframing |
| Skill-trigger F1 is too noisy on either corpus alone to disprove the null | Increase sample size; do not lower the noise-band threshold | Explicitly committed: we will not weaken the significance criterion post-hoc |
| Senior parking engineer unavailable to label | Use a panel of 3 mid-level engineers with majority-vote labels; report agreement | Labeling protocol documented before any labels collected |

## 9. References

- `registrations/01-hypothesis.md` — pre-registration (this design is the long form; the registration is the one-pager that goes on the record before any experiment runs)
- `docs/SICA_Brainstorming_Pack.md` §3 — thesis-frame selection (A/B/C)
- `docs/SICA_Brainstorming_Pack.md` §6 — public-benchmark rationale (GEPA, GitBug-Java, Defects4J)
- `DATA_POLICY.md` — data wall enforced for the enterprise corpus
- README null-result policy — top of `README.md`

---

*Approved 2026-05-20. Edit only by appending dated change-log entries below.*

## Change Log

(none yet)
