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

### 2026-05-31 — Methodology amendment batch (REQ-DESIGN-01)

Sources: `.planning/research/SUMMARY.md § (b)` (Pitfalls researcher synthesis, 2026-05-22). This batch follows D-08 (single-entry-with-three-subsections), D-09 (back-references use original §7-N / §8-N IDs), D-11 (Change Log only; original §7/§8 tables not edited in place).

#### NEW §7 threats (8 items)

1. **Telemetry completeness threat (hook timeouts + JSONL fragility)** — Claude Code's 60s hook limit silently drops events on slow scrubbing of large tool payloads; concurrent appends can interleave malformed JSON.
   *Mitigation:* deferred-batch hook architecture, per-session JSONL files, fail-loud parser, `_hook_runtime_ms` self-report, per-session event-count sanity check.

2. **Confounding of model capability with config quality** — A frozen-config baseline tested under a newer model measures model-portability, not config-quality.
   *Mitigation:* yoked A/B runs within same wall-clock minute under same model version; paired-difference reporting; never average F1 across non-paired model versions.

3. **Optimizer reward hacking on skill-trigger metric** — Cheapest path to maximize recall is firing every skill on every prompt.
   *Mitigation:* strict-match F1 (set equality), cardinality penalty, ≥50 adversarial negative prompts, GEPA `side_info` anti-overfit constraint pinned as default.

4. **Skill-description over-fits to training corpus** — Reflection LMs copy verbatim phrases, customer names, ticket IDs, code symbols (GEPA-documented).
   *Mitigation:* GEPA anti-overfit `Constraint` literal-string injection; post-optimization linter rejecting CamelCase/snake_case/proper-noun tokens not in allowlist; hard train/val split with split-hash logged.

5. **Mined-corpus survivorship bias** — GitBug-Java samples only fixed-and-merged bugs; F1 measured on it is conditional on fix-commit-generation, not population F1.
   *Mitigation:* stratified reporting (commit-generating vs not); ≥20% negative-labeled prompts in manual batch; explicit ecological-validity limitation in Chapter 6.

6. **Hawthorne effect in enterprise capture** — Parking engineers know they are being studied; behavior shifts.
   *Mitigation:* 4-week acclimation window not used in F1 corpus; prompt-length distribution compared to unobtrusive baseline (SWE-bench/GitBug-Java prompts); briefing-then-leave-alone; documented threat in Chapter 6.

7. **Goodhart's law on skill-trigger F1** — F1 is both optimizer's target and evaluator's metric; conflates training fit with capability.
   *Mitigation:* hard train/test partition (optimizer code path cannot touch test partition); triangulation with secondary metrics (pass-rate, token cost); pre-registered "F1 ↑ X ⇒ pass-rate Δ Y" prediction — if it fails, that is a *finding*.

8. **Inter-corpus comparability (apples-to-oranges)** — Two corpora labeled by different processes from disjoint distributions are not measuring the same F1.
   *Mitigation:* per-corpus distribution characterization document; per-corpus independent reporting; skill-set normalization within each arm comparison.

#### EXTEND existing §7 rows (3 items)

9. **§7-1 extends: "Model version drift" → "Replay non-determinism (model + filesystem + RNG + deprecation)"** — version-string pin necessary but insufficient; also temperature 0 for replay; `--network=none` except LLM proxy; content-addressed filesystem snapshot; seed pinning. Add deprecation contingency: bank transcripts pre-emptively; promote `claude-haiku-4-5` to primary; report old + new separately.

10. **§7-2 extends: "LLM-as-judge bias"** — extend with five named bias modes (verbosity, position, self-preference, authority, recency); cross-family sensitivity check (Claude vs GPT-4-class/Gemini-class on 100 prompts); blind randomized presentation; Cohen's κ floor 0.6 escalates to panel-of-3.

11. **§7-3 extends: "Insufficient drift"** — extend with closed-loop divergence/collapse/oscillation prevention: GEPA `NoImprovementStopper(patience=10)`; hard train/val/test partition with light val rotation; Pareto-diversity floor ≥5 distinct candidates; archive rollback on val-F1 regression beyond noise band.

#### EXTEND §8 fallbacks (2 items)

12. **§8-1 concretizes: GitBug-Java fallback trigger** — change from "if GitBug-Java does not yield" to "if projected to miss 500 by mid-June extrapolation" (earlier activation = cheaper).

13. **§8-3 concretizes: Sample-size escalation** — concretize generic "increase sample size" to "if A−B difference < 1.5× noise band, automatically schedule +5 more runs before declaring." Also amends §8-3 to set the default F1 noise band to **5 repeats** (was 3) — propagating to REQ-MEASURE-01 acceptance.

### 2026-06-01 — §8-2 public-only fallback activated as Phase 2 default (REQ-CORPUS-02 / D-37)

Per Phase 2 discussion decision **D-37** (`.planning/phases/02-measurement-foundation/02-CONTEXT.md`) and cut-order rank #1, the enterprise (parking) corpus **REQ-CORPUS-02 is NOT a default Phase 2 deliverable.** This entry activates the pre-registered **§8-2 "Option β"** contingency (the public-only degradation already in the §8 Risk Register, table row 2) as the dated default — recorded now, append-only, so the degradation is a planned graceful step rather than a retroactive reframing.

- **(a) Default scope.** The headline skill-trigger F1 claim runs on the **public corpus alone** — GitBug-Java (~199) plus Defects4J V1.2 (≈357, promoted from the §8-1 fallback corpus list per the 2026-05-31 §8-1 concretization). Parking validation moves to an appendix unless the trigger below fires.
- **(b) Activation trigger (hard date).** The enterprise path activates **only if** the VinSmart IP ruling (Jira `SICA-2`) clears by the hard **end-June 2026** trigger. If unresolved by then, the public-only claim stands and is the spine of the dissertation; no enterprise data is collected.
- **(c) What activation would require (deferred branch, not built here).** ≥200 labeled parking prompts, a 20% second-rater spot-check, and a 4-week Hawthorne acclimation window (per §7-6), loading through the **existing source-agnostic corpus loader** at `data/corpora/enterprise/` with **zero architecture change** — `BugSource.dataset` is a free string and no code path keys on `dataset == "gitbug-java"` (locked by the `test_source_agnostic_loader.py` regression guard added in plan 02-06).
- **(d) Back-reference.** This activates §8 Risk Register row 2 ("Parking IP ruling … blocks publication … Option β"); the §8 table itself is unmodified (D-11 append-only discipline). The 4-week-acclimation requirement traces to §7-6 (Hawthorne, 2026-05-31 amendment).

**Cross-reference:** `registrations/01-hypothesis.md` may cite this entry as the dated invocation point of the pre-registered §8-2 public-only contingency.

### 2026-06-10 — Model-call layer made backend-pluggable (eval transport)

Sources: `quick/260610-0o9` refactor task. This entry follows the append-only discipline (D-11). No changes to §1–§8 original text.

**(a) Pluggable transport.** The eval model-call layer is now a pluggable transport implemented in `eval/sica_eval/benchmark/llm_backend.py` (`call_model(model, prompt, tools) -> dict`). The backend is selected by the `SICA_LLM_BACKEND` environment variable; the default value is `anthropic`, whose behavior is byte-identical to the inline call that existed at *t=0* in `response_cache.py`. No measurement semantics changed.

**(b) Provider-lock requirement for OpenRouter runs.** Any experiment run using `SICA_LLM_BACKEND=openrouter` MUST be provider-locked to first-party Anthropic routing: `provider.order=["Anthropic"]`, `allow_fallbacks=false` (the implementation default). The model id MUST be declared in dot notation (`anthropic/claude-sonnet-4.6` for the primary arm; `anthropic/claude-haiku-4.5` for the sensitivity arm). These values MUST be declared per-run in the experiment record alongside the model version string, in the same way that `SICA_MODEL` is logged for direct-API runs.

**(c) Frozen primary metric preserved.** This change does NOT alter the frozen primary metric. `scorer.py` is byte-unchanged. The response-cache key (sha256 of model + prompt + sorted tools) and the persisted dict shape (`content`, `usage`, `stop_reason`) are byte-identical to the *t=0* baseline, so the A/B comparison semantics are fully preserved. The `arm_runner.py` and `scorer.py` modules continue to operate without modification.

**(d) Reclassification of response_cache.py.** `response_cache.py` is reclassified from a frozen-firewall file to a **pluggable-transport delegate**. It is now responsible only for cache-key generation, cache lookup, and persistence; it delegates the actual model call to `llm_backend.call_model`. The Goodhart firewall files — the modules whose byte-integrity is asserted in the Phase 4 drift-evaluation plans — are: **`scorer.py`, `experiment.py`, and `arm_runner.py`**. `response_cache.py` is explicitly removed from that frozen set.
