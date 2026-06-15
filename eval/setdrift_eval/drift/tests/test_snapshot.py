"""Tests for content-addressed snapshot determinism (REQ-DRIFT-02, Plan 04-01 Task 3).

Also covers the CR-03 / WR-04 review fixes:
  - symbolic refs (HEAD~1) are resolved to full SHAs before keying (CR-03)
  - checkout_snapshot never mutates the source repo's index/work-tree (WR-04)
  - an advancing ref never silently returns a stale snapshot (CR-03)
"""
import subprocess


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _git(repo, *args: str) -> str:
    """Run a git command in repo, return stripped stdout (check=True, fail-loud)."""
    result = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=str(repo),
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _make_git_repo_two_commits(tmp_path):
    """Create a real git repo with two commits; return its path.

    Commit 1: src/Main.java only.
    Commit 2: src/Main.java modified + src/Util.java added.
    """
    repo = tmp_path / "src_repo"
    repo.mkdir()
    _git(repo, "init")
    src = repo / "src"
    src.mkdir()
    (src / "Main.java").write_text("public class Main { int v = 1; }", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "c1")
    (src / "Main.java").write_text("public class Main { int v = 2; }", encoding="utf-8")
    (src / "Util.java").write_text("public class Util { }", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "c2")
    return repo

def _make_java_tree(tmp_path, files: dict[str, str]):
    """Create a fake directory tree with Java files; return the root path.

    Args:
        tmp_path: Pytest tmp_path fixture base directory.
        files: dict mapping relative path -> file content strings.

    Returns:
        Path to the directory containing the Java files.
    """
    repo_dir = tmp_path / "fake_repo"
    repo_dir.mkdir(parents=True, exist_ok=True)
    for rel_path, content in files.items():
        target = repo_dir / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return repo_dir


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_content_manifest_deterministic(tmp_path):
    """Test 5a: _content_manifest over the same directory tree returns the same sha256 twice."""
    from setdrift_eval.drift.snapshot import _content_manifest

    repo_dir = _make_java_tree(tmp_path, {
        "src/Main.java": "public class Main { }",
        "src/Util.java": "public class Util { }",
    })
    hash1 = _content_manifest(repo_dir)
    hash2 = _content_manifest(repo_dir)
    assert hash1 == hash2, f"_content_manifest not deterministic: {hash1} != {hash2}"
    assert len(hash1) == 64, f"Expected 64-char sha256 hex, got {len(hash1)}"
    assert all(c in "0123456789abcdef" for c in hash1), "Expected lowercase hex"


def test_content_manifest_changes_with_file_content(tmp_path):
    """Test 5b: changing a file content changes the _content_manifest hash."""
    from setdrift_eval.drift.snapshot import _content_manifest

    repo_dir = _make_java_tree(tmp_path, {
        "src/Main.java": "public class Main { int x = 1; }",
    })
    hash_before = _content_manifest(repo_dir)

    # Modify the Java file
    (repo_dir / "src" / "Main.java").write_text(
        "public class Main { int x = 2; }", encoding="utf-8"
    )
    hash_after = _content_manifest(repo_dir)
    assert hash_before != hash_after, (
        "_content_manifest should change when file content changes"
    )


def test_content_manifest_only_java_files(tmp_path):
    """Test 5c: _content_manifest ignores non-.java files (only *.java contribute to hash)."""
    from setdrift_eval.drift.snapshot import _content_manifest

    # Directory with only Java files
    repo_dir_java = _make_java_tree(tmp_path / "java_only", {
        "src/Main.java": "public class Main { }",
    })
    hash_java_only = _content_manifest(repo_dir_java)

    # Same Java file + extra non-Java file (should produce identical hash)
    repo_dir_mixed = _make_java_tree(tmp_path / "mixed", {
        "src/Main.java": "public class Main { }",
        "src/README.txt": "This should be ignored",
        "src/config.xml": "<config/>",
    })
    hash_mixed = _content_manifest(repo_dir_mixed)
    assert hash_java_only == hash_mixed, (
        "_content_manifest should ignore non-.java files; "
        f"java_only={hash_java_only}, mixed={hash_mixed}"
    )


def test_checkout_snapshot_resolves_symbolic_ref(tmp_path, monkeypatch):
    """Test 6 (CR-03): a symbolic ref is resolved to the full SHA before keying the snapshot dir."""
    from setdrift_eval.drift import snapshot

    repo = _make_git_repo_two_commits(tmp_path)
    monkeypatch.setattr(snapshot, "SNAPSHOT_ROOT", tmp_path / "snaps")

    snap_dir, manifest = snapshot.checkout_snapshot(repo, "HEAD~1")

    expected_sha = _git(repo, "rev-parse", "HEAD~1")
    assert snap_dir.name == expected_sha, (
        f"Snapshot dir must be keyed by the RESOLVED full SHA {expected_sha}, "
        f"got {snap_dir.name!r} (symbolic-ref keying breaks content-addressing, CR-03)"
    )
    # Commit 1 content only: Util.java did not exist yet
    assert (snap_dir / "src" / "Main.java").exists()
    assert not (snap_dir / "src" / "Util.java").exists(), (
        "HEAD~1 snapshot must not contain files added in HEAD"
    )
    assert len(manifest) == 64


def test_checkout_snapshot_does_not_mutate_source_repo(tmp_path, monkeypatch):
    """Test 7 (WR-04): snapshotting an old commit leaves the source repo's index/work-tree clean."""
    from setdrift_eval.drift import snapshot

    repo = _make_git_repo_two_commits(tmp_path)
    monkeypatch.setattr(snapshot, "SNAPSHOT_ROOT", tmp_path / "snaps")

    snapshot.checkout_snapshot(repo, "HEAD~1")

    status = _git(repo, "status", "--porcelain")
    assert status == "", (
        "checkout_snapshot must not stage/modify anything in the source repo "
        f"(WR-04); git status reports:\n{status}"
    )
    # Work-tree content must still be commit 2's
    assert "int v = 2" in (repo / "src" / "Main.java").read_text(encoding="utf-8")


def test_checkout_snapshot_advancing_ref_is_not_stale(tmp_path, monkeypatch):
    """Test 8 (CR-03): after HEAD advances, snapshotting 'HEAD' again returns the NEW content."""
    from setdrift_eval.drift import snapshot

    repo = _make_git_repo_two_commits(tmp_path)
    monkeypatch.setattr(snapshot, "SNAPSHOT_ROOT", tmp_path / "snaps")

    dir_before, manifest_before = snapshot.checkout_snapshot(repo, "HEAD")

    # Advance HEAD with a third commit changing Java content
    (repo / "src" / "New.java").write_text("public class New { }", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "c3")

    dir_after, manifest_after = snapshot.checkout_snapshot(repo, "HEAD")

    assert dir_after != dir_before, (
        "Advancing HEAD must produce a NEW snapshot directory (stale-reuse bug, CR-03)"
    )
    assert manifest_after != manifest_before, (
        "Advancing HEAD must produce a different content manifest (stale-reuse bug, CR-03)"
    )
