# Setdrift Plugin — Brainstorming Companion

Read alongside `SETDRIFT_Plugin_Research_Brief.docx`. This file is unfiltered sparks, gaps,
and alternative framings — pick what energises you and ignore the rest.

---

## 1. Gaps in the brief I should flag

The brief is solid on the *what*. It is light on five things you will need before week 4.

- **No competitor map.** I cited the academic prior art (SICA-Robeyns, DGM, ADAS, AutoPDL, DSPy, GEPA, TextGrad). I did **not** map adjacent *products*: claude-mem, obra/superpowers, Cursor Rules, Continue.dev, Aider's chat history, Devin, Copilot Workspace, Cline. Your defense will ask "why doesn't claude-mem already do this?" — you need a one-page differential.
- **No definition of "best result".** Section 2 says "best result when developer uses". Define it as a vector — correctness, accept-rate, edits-per-PR, time-to-green-CI, token cost, hallucination rate, developer satisfaction — and pick which two you optimise primarily.
- **No anti-goal list.** Capstones drown when scope creeps. Explicit *non-goals* (e.g. "we will not retrain any LLM weights", "we will not target JavaScript repos", "we will not optimise inference latency") shorten the dissertation.
- **No safety story.** A plugin that auto-edits CLAUDE.md or auto-installs hooks is a supply-chain risk. Need a section on rollback, audit, signed configs, opt-in promotion.
- **Telemetry privacy.** Captured developer prompts include source code, secrets, customer data. Need a PII scrubber + retention policy *before* you collect a single event.

---

## 2. Sparks — 20 mini-ideas to riff on

Numbered for easy citation in Jira. Each can be a one-week experiment or a section of the thesis.

1. **Skill genealogy graph.** Track every skill description as a node, every optimisation as an edge. Visualise which descendants beat which ancestors. Becomes a Mermaid diagram in the thesis.
2. **Configuration drift index.** A scalar metric: how stale is your CLAUDE.md against the current repo? Compute via embedding cosine between CLAUDE.md and a rolling window of recent commits.
3. **Auto-deprecate dead skills.** Skill not triggered in N sessions → archive. Skill triggered but rejected by user 80% of the time → quarantine. Cheap, novel, easy to measure.
4. **Anti-skills.** A skill whose job is to *suppress* a wrong skill. Example: an anti-skill that says "do not invoke jpa-migration when the request mentions Flyway". Models hierarchical priority cleanly.
5. **Sandbox replay.** For a given developer prompt logged in production, replay it under config A vs config B in a Docker sandbox; measure divergence in output. Lets you A/B *offline* without rerunning real sessions.
6. **Spec-bench for parking.** Mine VinSmart commits where the change is purely a Spring/Hibernate annotation. Build a micro-benchmark: 50 metadata-bug tasks. Cite [MeCheck / metadata-bug paper](https://arxiv.org/html/2502.14463) as prior art.
7. **GitBug-Java integration.** Use [GitBug-Java](https://arxiv.org/html/2402.02961v2) as a *public* benchmark before you touch the proprietary repo. Lets you publish even if the parking data never clears legal.
8. **Pareto-front skill descriptions.** Replace MIPROv2 with [GEPA](https://arxiv.org/abs/2507.19457) — maintain multiple descriptions on the Pareto frontier instead of one global best. Newer, cheaper (100–500 evals vs 10k), ICLR 2026 oral.
9. **TextGrad-style backprop through CLAUDE.md.** Treat CLAUDE.md as a parameter, LLM verdict on a session as the loss, [TextGrad](https://arxiv.org/abs/2406.07496) as the optimizer. The framing of "natural-language gradients through a config file" is a hook reviewers love.
10. **Auto-generated slash commands.** Detect repeated multi-step prompts (e.g. "create endpoint, add migration, write test") and propose them as `/parking-endpoint`. Concrete, demo-able.
11. **MCP server health probe.** Periodically ping each MCP server registered in the plugin; emit availability and latency metrics. Tiny feature, very visible value.
12. **Hook-as-policy.** Generate hooks that mirror your team's *written policies* (no direct DB writes outside repositories, no print statements). Specs come from a `policies.md`; plugin compiles them into PreToolUse hooks.
13. **Developer-prompt vocabulary drift.** Track how vocabulary in developer prompts changes over months. A skill whose triggers stop matching the team's evolving vocabulary is the canonical drift signal.
14. **Per-developer config layering.** Generic core → team pack → personal overlay. Measure whether per-developer overlays add or subtract value over team-wide config.
15. **Counterfactual debugging.** When a Claude Code task fails, replay with one config component removed at a time to localise which line of CLAUDE.md or which skill caused the failure. Ablation-as-feature.
16. **Carbon / cost dashboard.** Tie configuration changes to $ saved and kWh reduced. VinSmart's ESG team will love this. Real money is a great chart.
17. **Cross-team plugin marketplace.** When Setdrift improves a skill on team A, surface the diff to team B as a suggested PR. Federated skill-evolution.
18. **Skill PR-review bot.** Treat every auto-proposed skill edit as a PR; have a separate Claude review it before promotion. The plugin becomes self-policing.
19. **Pre-registration.** Write hypotheses into `/registrations/01-hypothesis.md` before running experiments. Reviewers in 2026 increasingly demand this. Easy credibility win.
20. **Open-skill leaderboard.** Publish your eval harness so other teams can submit skills and benchmark them. Bootstraps a research community around your plugin.

---

## 3. Three alternative thesis framings (pick one)

Each frame gives reviewers a different elevator pitch. They are mutually exclusive — pick one
and rewrite chapter 1 around it. The system you build is the same; the *story* differs.

| Frame | Elevator pitch | Strength | Risk |
|---|---|---|---|
| **A. Configuration-as-Hyperparameter** | "Treating Claude Code's skills, hooks, and CLAUDE.md as a continuously tuned parameter, the same way an ML team tunes hyperparameters." | Crisp ML analogy, fits AutoPDL / DSPy / GEPA lineage. | Reviewers may ask "but where's the new ML?". Answer: the *target* of optimisation (Claude Code configs) is new. |
| **B. Configuration Drift Detection (SE/empirical-software-engineering)** | "AI-assistant configurations rot silently as code, models, and teams change. We give the first reproducible methodology for detecting and patching that drift." | Plays in the empirical SE arena (ICSE, FSE, MSR). Strong real-world story. | Less algorithmic novelty; needs strong measurement. |
| **C. Agent-Ops for Coding Assistants** | "What MLOps is to models, AgentOps is to agents. We build the first AgentOps layer for AI coding assistants, validated on a production Java/Spring microservice platform." | Hot industry framing, easy to recruit collaborators, good blog/keynote potential. | Risk of "engineering paper" stigma at theory venues; mitigate with one sharp ablation. |

My pick for the *thesis* is **B**; my pick for the *paper* is **A**. Frame **C** is the talk you give at VinSmart.

---

## 4. Mini-research questions ready for experiments

Drop any of these into a Jira story as the *Research Question* field. Each is bounded enough
to run in 1–3 weeks.

- Does an LLM-generated skill description outperform a hand-written one *on prompts the LLM has never seen*?
- How many real-team developer prompts are needed to fit a skill-trigger optimizer to >90% F1?
- Does Pareto-front prompt evolution (GEPA) beat single-best (MIPROv2) on enterprise Java tasks?
- What fraction of CLAUDE.md content is dead weight (never referenced in a session)?
- Does adding a "policy guard" hook reduce post-merge defect rate vs. instructions in CLAUDE.md alone?
- How does skill-trigger accuracy degrade with model upgrade (Sonnet 4.6 → 5.0)?
- Is there a power law in skill usage? (Few skills used a lot; long tail used rarely.) If so, optimise only the head.
- Does counterfactual ablation (§Spark 15) reliably localise which line of CLAUDE.md caused a failure?
- For each capability (observe/diagnose/patch/verify), what is the marginal contribution to end-to-end task success? — your version of the Topic 8 ablation study from your earlier brief.

---

## 5. Defense-prep — what your committee will ask

Pre-empt these now. Each answer should be a paragraph in chapter 6 (Threats to Validity).

- *"How is this different from claude-mem / superpowers / Cursor Rules?"* — Have a one-page comparison table.
- *"You evaluated on one repo. Does it generalise?"* — Use GitBug-Java + Defects4J + Multi-SWE-bench as supplementary public evals.
- *"Self-improvement loops can collapse / diverge. How did you handle convergence?"* — Cite [DGM's archive-based safety](https://arxiv.org/abs/2505.22954) and report convergence curves explicitly.
- *"LLM-as-judge is biased."* — Validate with a 20% manual spot-check (already in your brief) and report inter-rater agreement.
- *"You used Sonnet 4.6. A new model breaks everything."* — Pin the model; report results on at least one other (Haiku 4.5) to show the methodology, not the score, generalises.
- *"What if Setdrift proposes a malicious change?"* — Section 1 on signed configs, dry-run promotion, human approval gate.
- *"Why won't the parking team revert?"* — Field study with consent + rollback button + weekly retro.

---

## 6. Additional papers / tools to add to the reading list

Beyond the brief's table — these are 2025-2026 entries worth a half-day each.

- **GEPA: Reflective Prompt Evolution** (Agrawal et al., ICLR 2026 Oral) — [arXiv 2507.19457](https://arxiv.org/abs/2507.19457). Likely your strongest optimizer choice; outperforms MIPROv2 and RL with 35× fewer rollouts.
- **TextGrad** (Yuksekgonul et al., Nature 2024) — [arXiv 2406.07496](https://arxiv.org/abs/2406.07496). Backpropagation of natural-language feedback. The framing is hugely citation-friendly.
- **GitBug-Java** (Silva et al., MSR 2024) — [arXiv 2402.02961](https://arxiv.org/html/2402.02961v2). 199 recent Java bugs, reproducible. Use as public benchmark.
- **MeCheck / metadata-related bugs in enterprise apps** (2025) — [arXiv 2502.14463](https://arxiv.org/html/2502.14463). Directly relevant: Spring annotation/XML misconfiguration is exactly your parking system's failure mode.
- **Defects4J V1.2** — 357 Java bugs with triggering test suites. Industry-standard control benchmark.
- **The Unseen Threat of "Configuration Drift"** (Khare, 2026) — non-academic but quotable for your motivation section.
- **Cursor "Rules" documentation & best-practices** — [cursor.com/docs/rules](https://cursor.com/docs/rules). Closest commercial analog to what you're proposing for Claude Code.
- **Aider's chat history & repo-map design** — public docs/blog posts. Closest open-source analog to your telemetry layer.
- **Claude Code subagents** — [code.claude.com/docs](https://code.claude.com/docs/en/skills). Re-read with fresh eyes; the subagent + skill interplay is the surface you actually optimise.

---

## 7. The shape of a great chapter 5 (Discussion)

If you collect the right data, your discussion chapter writes itself around these points:

- "Configuration matters more than model choice for routine tasks." — likely finding if you compare Sonnet+great-config to Opus+stock-config.
- "Most CLAUDE.md content is dead weight." — likely finding from §Spark 19's measurement.
- "Self-improvement converges within ~20 cycles on stable tasks but oscillates on ambiguous ones." — typical DGM-style observation.
- "Field-study satisfaction (NASA-TLX) moves more than measured throughput." — common in HCI evaluations of AI tools; lets you talk about felt productivity vs measured.
- "Cost-aware routing matters more than smarter retrieval." — likely if you run §I-6.

---

## 8. The Jira move I would make tomorrow

Create exactly these tickets so the project does not stall:

1. `SICA-1` — Decide primary contribution (Frame A / B / C from §3 above). Due end of week 1.
2. `SICA-2` — Get IP + data-access ruling from VinSmart legal. Due end of week 2.
3. `SICA-3` — Reproduce GitBug-Java baseline with stock Claude Code. Due end of week 3.
4. `SICA-4` — Mine first 50 parking-repo issue→commit pairs. Due end of week 3.
5. `SICA-5` — Decide GEPA vs. MIPROv2 vs. TextGrad as optimizer. Spike each for one day. Due end of week 4.

That is it. Five tickets buys you a month of clear work; the rest of the backlog can fill in
as you learn.

---
*Companion to SETDRIFT_Plugin_Research_Brief.docx — Trung, May 2026.*
