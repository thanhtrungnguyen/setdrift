"""Tests for content-addressed snapshot determinism (REQ-DRIFT-02, Plan 04-01 Task 3)."""


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _make_java_tree(tmp_path, files: dict[str, str]):
    """Create a fake directory tree with Java files; return the root path.

    Args:
        tmp_path: Pytest tmp_path fixture base directory.
        files: dict mapping relative path -> file content strings.

    Returns:
        Path to the directory containing the Java files.
    """
    repo_dir = tmp_path / "fake_repo"
    repo_dir.mkdir()
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
    from sica_eval.drift.snapshot import _content_manifest

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
    from sica_eval.drift.snapshot import _content_manifest

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
    from sica_eval.drift.snapshot import _content_manifest

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
