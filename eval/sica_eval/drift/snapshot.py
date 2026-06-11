"""Content-addressed git snapshot per revision (REQ-DRIFT-02).

What this module does: resolves a git revision (symbolic refs like HEAD~10 are
resolved to a full commit SHA first — CR-03), extracts that commit into a local
snapshot directory keyed by the RESOLVED SHA via `git archive` (no index or
work-tree side effects on the source repo — WR-04), computes a deterministic
sha256 content manifest over all *.java files, and returns the
(snapshot_dir, manifest_hash) pair for logging into DriftManifest.
snapshot_dir.name is the resolved full commit SHA — callers record it as the
revision's reproducibility pin.

What it does NOT do: never writes to experiments/; never reads scorer.py;
never crosses the data wall — all snapshots live under SNAPSHOT_ROOT which
defaults to data/drift/snapshots/ (gitignored). Never mutates the source
repository's index or working tree (`git archive` reads object storage only).

Eval-side fail-loud: subprocess.CalledProcessError propagates (no bare except).
git rev-parse / archive errors are real failures that must surface. A snapshot
directory that exists WITHOUT its .snapshot_hash sentinel is a corrupt partial
materialization and raises rather than being silently reused.

Seed-pinning helper note: the per-cell deterministic RNG seed is computed as:
    seed = int(sha256(f"{arm}-{model}-{revision}-{run_idx}").hexdigest()[:8], 16)
This ensures each (arm, model, revision, run_idx) tuple maps to a unique,
reproducible seed. The grid_runner (04-02) uses this formula at run time.
"""
import hashlib
import io
import os
import subprocess
import tarfile
from pathlib import Path

SNAPSHOT_ROOT = Path(os.environ.get("SICA_SNAPSHOT_ROOT", "data/drift/snapshots"))


def checkout_snapshot(repo_path: Path | str, commit_sha: str) -> tuple[Path, str]:
    """Extract a specific git commit into a content-addressed snapshot directory.

    CR-03: `commit_sha` may be a symbolic ref (HEAD~10, branch name, tag). It is
    resolved to the full commit SHA via `git rev-parse` BEFORE keying the snapshot
    directory, so the content-address guarantee holds as the repo's HEAD advances.
    snapshot_dir.name is always the resolved full SHA.

    WR-04: extraction uses `git archive` (object-store read only) — the source
    repository's index and working tree are never touched, and the snapshot
    directory is created fresh so deleted files can never leak in from a prior
    commit's checkout.

    Mirrors the response_cache.py cached.exists() short-circuit pattern: if the
    snapshot directory already exists (sentinel file .snapshot_hash is present),
    return immediately without re-extracting. This makes repeated calls for the
    same commit cheap and idempotent.

    Args:
        repo_path: Path to the git repository to snapshot.
        commit_sha: Git revision to extract (full SHA, short SHA, or symbolic ref).

    Returns:
        tuple[Path, str]: (snapshot_dir, manifest_hash) where snapshot_dir is the
        path to the materialized snapshot (dir name = resolved full commit SHA)
        and manifest_hash is the sha256 content manifest of all *.java files in
        that directory.

    Raises:
        subprocess.CalledProcessError: If git rev-parse or git archive fails (fail-loud).
        RuntimeError: If the snapshot directory exists without its sentinel
            (corrupt partial materialization — never silently reused).
    """
    repo_path = Path(repo_path)

    # CR-03: resolve symbolic refs to the full commit SHA before keying.
    resolved = subprocess.run(
        ["git", "rev-parse", commit_sha],
        cwd=str(repo_path),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    snapshot_dir = SNAPSHOT_ROOT / resolved
    sentinel = snapshot_dir / ".snapshot_hash"

    # Short-circuit: already materialized (mirrors response_cache.py cached.exists())
    if sentinel.exists():
        manifest = sentinel.read_text(encoding="utf-8").strip()
        return snapshot_dir, manifest

    # Fail-loud: a directory without its sentinel is a corrupt partial snapshot.
    if snapshot_dir.exists():
        raise RuntimeError(
            f"Snapshot directory {snapshot_dir} exists without its .snapshot_hash "
            "sentinel — corrupt partial materialization. Delete the directory and "
            "re-run (never silently reused)."
        )

    snapshot_dir.mkdir(parents=True, exist_ok=False)

    # WR-04: `git archive` reads object storage only — no index/work-tree mutation,
    # and the fresh directory guarantees no stale files from other commits.
    archive = subprocess.run(
        ["git", "archive", "--format=tar", resolved],
        cwd=str(repo_path),
        check=True,
        capture_output=True,
    )
    with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as tf:
        tf.extractall(snapshot_dir, filter="data")

    # Compute and persist the content manifest as the sentinel
    manifest = _content_manifest(snapshot_dir)
    sentinel.write_text(manifest, encoding="utf-8")

    return snapshot_dir, manifest


def _content_manifest(d: Path | str) -> str:
    """Compute a deterministic sha256 hash over all *.java files in directory d.

    Hash is over sorted (posix-path, file-bytes) pairs for *.java files only.
    Order-stable (lexicographic posix path sort) so same commit checkout always
    yields the same hash regardless of filesystem enumeration order (D-56).

    Non-Java files (README, XML, properties, etc.) are intentionally excluded:
    only source content that affects skill-trigger behavior contributes.

    Args:
        d: Directory to scan recursively for *.java files.

    Returns:
        str: 64-character lowercase hex sha256 digest.
    """
    d = Path(d)
    hasher = hashlib.sha256()

    # Collect all .java files, sort by posix path for deterministic ordering
    java_files = sorted(d.rglob("*.java"), key=lambda p: p.relative_to(d).as_posix())

    for java_file in java_files:
        # Include both the path (relative, posix) and the file bytes in the hash
        rel_posix = java_file.relative_to(d).as_posix()
        hasher.update(rel_posix.encode("utf-8"))
        hasher.update(java_file.read_bytes())

    return hasher.hexdigest()
