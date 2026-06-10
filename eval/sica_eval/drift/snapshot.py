"""Content-addressed git checkout snapshot per revision (REQ-DRIFT-02).

What this module does: checks out a specific git commit into a local snapshot
directory (content-addressed, short-circuits if already materialized), computes
a deterministic sha256 content manifest over all *.java files, and returns the
(snapshot_dir, manifest_hash) pair for logging into DriftManifest.

What it does NOT do: never writes to experiments/; never reads scorer.py;
never crosses the data wall — all snapshots live under SNAPSHOT_ROOT which
defaults to data/drift/snapshots/ (gitignored).

Eval-side fail-loud: subprocess.CalledProcessError propagates (no bare except).
git checkout errors are real failures that must surface.

Seed-pinning helper note: the per-cell deterministic RNG seed is computed as:
    seed = int(sha256(f"{arm}-{model}-{revision}-{run_idx}").hexdigest()[:8], 16)
This ensures each (arm, model, revision, run_idx) tuple maps to a unique,
reproducible seed. The grid_runner (04-02) uses this formula at run time.
"""
import hashlib
import os
import subprocess
from pathlib import Path

SNAPSHOT_ROOT = Path(os.environ.get("SICA_SNAPSHOT_ROOT", "data/drift/snapshots"))


def checkout_snapshot(repo_path: Path | str, commit_sha: str) -> tuple[Path, str]:
    """Check out a specific git commit into a content-addressed snapshot directory.

    Mirrors the response_cache.py cached.exists() short-circuit pattern: if the
    snapshot directory already exists (sentinel file .snapshot_hash is present),
    return immediately without re-running git checkout. This makes repeated calls
    to the same commit cheap and idempotent.

    Args:
        repo_path: Path to the git repository to snapshot.
        commit_sha: The git commit SHA to check out.

    Returns:
        tuple[Path, str]: (snapshot_dir, manifest_hash) where snapshot_dir is the
        path to the materialized snapshot and manifest_hash is the sha256 content
        manifest of all *.java files in that directory.

    Raises:
        subprocess.CalledProcessError: If the git checkout fails (fail-loud).
        FileNotFoundError: If repo_path does not exist or is not a git repository.
    """
    repo_path = Path(repo_path)
    snapshot_dir = SNAPSHOT_ROOT / commit_sha
    sentinel = snapshot_dir / ".snapshot_hash"

    # Short-circuit: already materialized (mirrors response_cache.py cached.exists())
    if sentinel.exists():
        manifest = sentinel.read_text(encoding="utf-8").strip()
        return snapshot_dir, manifest

    # Create snapshot directory with parents (mkdir pattern from orchestrator.py)
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    # Sparse checkout: extract the commit into snapshot_dir without a full clone
    subprocess.run(
        ["git", "--work-tree", str(snapshot_dir), "checkout", commit_sha, "--", "."],
        cwd=str(repo_path),
        check=True,
        capture_output=True,
    )

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
