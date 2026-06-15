"""Sanity-check + rotation logic tests (Plan 01-04 Task 2)."""
import importlib
import json


def _reload(mod_name, tmp_path, monkeypatch):
    monkeypatch.setenv("SICA_TELEMETRY_DIR", str(tmp_path))
    monkeypatch.setenv("SICA_TELEMETRY_QUARANTINE_DIR", str(tmp_path / "quarantine"))
    import importlib as _il
    mod = _il.import_module(mod_name)
    _il.reload(mod)
    return mod


def _write_events(tmp_path, session, n, quarantined=0):
    (tmp_path).mkdir(parents=True, exist_ok=True)
    (tmp_path / f"{session}.events.jsonl").write_text(
        "\n".join(json.dumps({"_session": session, "i": i}) for i in range(n)) + "\n", encoding="utf-8"
    )
    if quarantined:
        qd = tmp_path / "quarantine"
        qd.mkdir(parents=True, exist_ok=True)
        (qd / f"{session}.jsonl").write_text(
            "\n".join(json.dumps({"_session": session, "q": i}) for i in range(quarantined)) + "\n", encoding="utf-8"
        )


def test_quarantined_events_count_toward_captured(tmp_path, monkeypatch):
    sanity = _reload("setdrift_eval.telemetry.sanity", tmp_path, monkeypatch)
    _write_events(tmp_path, "s1", n=8, quarantined=2)
    # captured = 8 clean + 2 quarantined = 10; expected 10 → gap 0 (quarantine != gap)
    assert sanity.captured_count("s1") == 10
    assert sanity.session_count_gap("s1", expected_count=10) == 0.0


def test_gap_over_threshold_is_flagged_not_dropped(tmp_path, monkeypatch):
    sanity = _reload("setdrift_eval.telemetry.sanity", tmp_path, monkeypatch)
    _write_events(tmp_path, "s2", n=4)  # captured 4
    flagged = sanity.check_all_sessions(threshold=0.05, expected_counts={"s2": 10})  # 60% gap
    assert "s2" in flagged
    assert (tmp_path / "sanity-flags.jsonl").exists()  # flagged, events NOT deleted
    assert (tmp_path / "s2.events.jsonl").exists()


def test_rotate_prunes_over_budget(tmp_path, monkeypatch):
    rotate = _reload("setdrift_eval.telemetry.rotate", tmp_path, monkeypatch)
    _write_events(tmp_path, "big", n=200)
    assert rotate.rotate_if_over_budget(budget_bytes=10**12) is False  # under budget
    acted = rotate.rotate_if_over_budget(budget_bytes=1)  # force
    assert acted is True
    assert any((tmp_path / "parquet").rglob("*.parquet"))  # compressed archive in-wall
