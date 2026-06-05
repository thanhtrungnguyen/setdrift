"""HMAC-SHA256 config signing (D-42, REQ-SAFETY-02 primitive).

What this module does: deterministically canonicalizes a skill-description config to
bytes, then produces (sha256 content hash, HMAC-SHA256 signature) and verifies a
signature in constant time. This is the authenticity primitive the path-guarded
applier (03-02) signs every staged config with.

What it does NOT do: it never writes the key, never logs key material, and never
crosses the data wall. The key lives at data/keys/sica-hmac.key (gitignored by both
`data/**` and `*.key`). NEVER force-add it.

stdlib-only (hmac, hashlib, json, os, pathlib) — no new dependency for signing.
Canonicalization is JSON-canonical (sort_keys=True), NOT yaml.dump (Pitfall 6: YAML
dump ordering/anchor instability would silently break the hash).
"""
import hashlib
import hmac
import json
import os
from pathlib import Path

_KEY_PATH = Path(os.environ.get("SICA_SIGNING_KEY", "data/keys/sica-hmac.key"))


class SigningKeyError(RuntimeError):
    """Raised when the HMAC key cannot be loaded (fail-loud)."""


def _load_key() -> bytes:
    """Load the HMAC key bytes from _KEY_PATH, or raise SigningKeyError if absent."""
    if not _KEY_PATH.exists():
        raise SigningKeyError(
            f"HMAC signing key not found at '{_KEY_PATH}'. "
            "Run `sica-eval init-keys` to generate one (it lives behind the data wall; "
            "set SICA_SIGNING_KEY to override the path). Never commit the key."
        )
    key = _KEY_PATH.read_bytes().strip()
    if not key:
        raise SigningKeyError(f"HMAC signing key at '{_KEY_PATH}' is empty.")
    return key


def canonicalize_config(skill_descriptions: dict[str, str]) -> bytes:
    """Deterministic, key-order-independent canonical byte form of a config.

    Sorts skill names so {"a":..,"b":..} and {"b":..,"a":..} canonicalize identically
    → a stable hash. JSON canonical (sort_keys=True, ensure_ascii=True), never YAML.
    """
    ordered = {k: skill_descriptions[k] for k in sorted(skill_descriptions)}
    return json.dumps(
        {"skills": ordered}, sort_keys=True, ensure_ascii=True
    ).encode("utf-8")


def sign_config(skill_descriptions: dict[str, str]) -> tuple[str, str]:
    """Return (config_hash hex, hmac_sig hex) for the canonicalized config."""
    canonical = canonicalize_config(skill_descriptions)
    key = _load_key()
    config_hash = hashlib.sha256(canonical).hexdigest()
    sig = hmac.new(key, canonical, hashlib.sha256).hexdigest()
    return config_hash, sig


def verify_config(skill_descriptions: dict[str, str], expected_sig: str) -> bool:
    """True iff expected_sig is the valid HMAC for this config (constant-time compare)."""
    canonical = canonicalize_config(skill_descriptions)
    key = _load_key()
    actual = hmac.new(key, canonical, hashlib.sha256).hexdigest()
    return hmac.compare_digest(actual, expected_sig)


def generate_key() -> str:
    """Return a fresh 32-byte HMAC key as hex (used by the init-keys CLI in 03-02).

    Caller is responsible for writing it behind the data wall — this function NEVER
    writes or logs the key.
    """
    return os.urandom(32).hex()
