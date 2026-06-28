"""Smoke test — the test infrastructure itself is alive."""

import setdrift_eval


def test_package_version_is_set():
    assert setdrift_eval.__version__ == "0.0.1"
