# Public Corpus Construction

The public prompt corpus (`data/corpus/gitbug-java.jsonl`) is the GitBug-Java–derived prompt corpus that feeds the falsifiable claim's skill-trigger F1 measurement (see `docs/design/2026-05-20-falsifiable-claim.md` §4).

## Build pipeline

```bash
cd eval
pip install -e ".[dev]"

# 1. Fetch the upstream dataset (idempotent; clones or pulls).
python -c "from sica_eval.corpus.fetcher import clone_or_update; clone_or_update()"

# 2. Build the labeled corpus.
sica-eval corpus build --version 2026-05-22

# 3. Emit a 20% manual-verification sample.
sica-eval corpus verify --corpus data/corpus/gitbug-java.jsonl
```

Output files (all gitignored under `data/`):
- `data/raw/gitbug-java/` — upstream dataset clone
- `data/corpus/gitbug-java.jsonl` — one `LabeledPrompt` per line
- `data/corpus/verify.csv` — 20% sample for manual labeling

## Skill taxonomy (eight labels)

| Label | Heuristic trigger |
|---|---|
| `dependency-bump` | `pom.xml` / `build.gradle` with `<version>` changes |
| `null-check` | Added lines containing `!= null`, `Optional.`, `Objects.requireNonNull` |
| `spring-annotation-fix` | Added `@Component`, `@Service`, `@Autowired`, etc. |
| `jpa-migration` | Added `@Entity`, `@Table`, `@Column`, etc. |
| `test-fixture-fix` | Diff touches `**/test/**` or `*Test.java` / `*IT.java` |
| `config-property` | Diff touches `application.properties` / `application.yml` |
| `import-fix` | Added `import` lines (excluding JPA double-tags) |
| `none` | Catch-all when no other rule fires |

The taxonomy is fixed for v1 of the corpus. Adding labels requires:
1. Adding the value to `SkillLabel` in `eval/sica_eval/corpus/schemas.py`.
2. Adding the heuristic rule to `eval/sica_eval/corpus/labeler.py`.
3. Bumping the corpus version string so downstream consumers re-verify.

## Manual verification protocol

1. Open `data/corpus/verify.csv` in any spreadsheet tool.
2. For each row, read the `prompt` and decide which skill labels from the taxonomy *should* fire. Fill `verified_skills` as a comma-separated list. Use `notes` if the prompt is ambiguous or out-of-scope.
3. Save the file. Heuristic precision is then computed as the fraction of rows where `predicted_skills == verified_skills`. A precision floor of 0.85 is the design-spec gate; if precision is lower, expand manual labeling before proceeding.

## Reaching the ≥500-prompt target

GitBug-Java provides 199 reproducible Java bugs. To reach the ≥500 target in the falsifiable claim's pre-registered fallback corpus list, layer in Defects4J (357 bugs) via a follow-up plan that reuses this corpus's schemas and labeler but adds a Defects4J-specific fetcher.
