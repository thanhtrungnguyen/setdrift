"""HMAC-SHA256 signer unit tests (REQ-SAFETY-02 primitive). Offline, no API.

Covers: canonical key-order independence, sign->verify round-trip, tamper rejection
(constant-time compare), and fail-loud missing-key error. The key is supplied via a
tmp file pointed at by SETDRIFT_SIGNING_KEY so no test ever touches the real data-wall key.
"""

import importlib

import pytest


def _signer_with_key(monkeypatch, tmp_path):
    """Return the signer module rebound to a temp key file via SETDRIFT_SIGNING_KEY."""
    key_file = tmp_path / "sica-hmac.key"
    key_file.write_text("a" * 64, encoding="utf-8")  # deterministic test key
    monkeypatch.setenv("SETDRIFT_SIGNING_KEY", str(key_file))
    from setdrift_eval.optimizer import signer

    importlib.reload(signer)  # re-evaluate module-level _KEY_PATH against the env
    return signer


def test_canonicalize_is_key_order_independent(monkeypatch, tmp_path):
    signer = _signer_with_key(monkeypatch, tmp_path)
    assert signer.canonicalize_config({"a": "1", "b": "2"}) == signer.canonicalize_config(
        {"b": "2", "a": "1"}
    )


def test_sign_verify_round_trip(monkeypatch, tmp_path):
    signer = _signer_with_key(monkeypatch, tmp_path)
    config = {"spring-boot-endpoint": "desc-1", "spring-jpa-entity": "desc-2"}
    config_hash, sig = signer.sign_config(config)
    assert len(config_hash) == 64 and len(sig) == 64
    assert signer.verify_config(config, sig) is True


def test_verify_rejects_tampered_config(monkeypatch, tmp_path):
    signer = _signer_with_key(monkeypatch, tmp_path)
    config = {"spring-boot-endpoint": "desc-1"}
    _, sig = signer.sign_config(config)
    tampered = {"spring-boot-endpoint": "desc-1-EVIL"}
    assert signer.verify_config(tampered, sig) is False


def test_missing_key_raises(monkeypatch, tmp_path):
    missing = tmp_path / "nope.key"
    monkeypatch.setenv("SETDRIFT_SIGNING_KEY", str(missing))
    from setdrift_eval.optimizer import signer

    importlib.reload(signer)
    with pytest.raises(signer.SigningKeyError):
        signer.sign_config({"a": "1"})


def test_generate_key_is_64_hex(monkeypatch, tmp_path):
    signer = _signer_with_key(monkeypatch, tmp_path)
    k = signer.generate_key()
    assert len(k) == 64 and all(c in "0123456789abcdef" for c in k)
