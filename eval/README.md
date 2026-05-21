# eval — SICA evaluation harness

Python package (`sica_eval`). Three pillars mirroring the brief:

- `benchmark/` — build an offline replay benchmark from issue→commit pairs
  (start with public GitBug-Java/Defects4J; add the parking repo after the IP ruling).
- `optimizer/` — skill-trigger / CLAUDE.md optimization (DSPy MIPROv2, GEPA, or TextGrad).
- `telemetry/` — parse the gitignored event logs into health metrics & drift signals.

Install: `pip install -e .[optimize,dev]`
