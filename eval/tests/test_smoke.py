"""Smoke test — the test infrastructure itself is alive."""
import sica_eval


def test_package_version_is_set():
    assert sica_eval.__version__ == "0.0.1"
