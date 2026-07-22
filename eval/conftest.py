"""Root-level pytest configuration for the Setdrift eval harness.

Placed at the rootdir (alongside pyproject.toml) so its fixtures apply to the
ENTIRE session — both the ``tests/`` tree and every ``setdrift_eval/**/tests/``
subtree named in ``testpaths``.

Why this file exists
--------------------
The unit suite must be hermetic — its behaviour must not depend on a developer's
local ``.env``. Two mechanisms otherwise break that:

1. Library import side-effect. ``litellm`` (pulled in transitively via ``dspy``)
   calls ``dotenv.load_dotenv()`` (``override=False``) the FIRST time it is
   imported in the process. Because several tests import ``orchestrator``/
   ``gepa_wrapper`` LAZILY, inside the test body (not at module collection
   time), this first-import trigger could otherwise fire mid-test — AFTER any
   setup-time env strip has already run — since ``load_dotenv(override=False)``
   only refuses to clobber a key that is ALREADY PRESENT; a key that was merely
   deleted is fair game again. The repo-root ``.env`` sets
   ``SETDRIFT_LLM_BACKEND=openrouter`` plus a non-pinned ``SETDRIFT_MODEL``
   (``openai/gpt-oss-120b:free``) and a live ``OPENROUTER_API_KEY``; left
   unguarded this silently flipped ``tests/test_response_cache.py`` /
   ``tests/test_arm_runner.py`` onto the OpenRouter path — past the
   Anthropic-only ``mock_anthropic_client`` fixture and into a live HTTP
   client — producing ``openai.AuthenticationError``. The same leak also trips
   ``evidence.preflight.assert_evidence_run`` (D7-19, Phase 7) wherever it is
   wired in (``grid_runner``, ``haiku_arm``, ``orchestrator``, ``cli.py``'s
   health path) AND poisons ``orchestrator._MODEL`` (a module-level constant
   captured at ``orchestrator``'s own import time).

   Fix: this module eagerly imports ``dspy`` at CONFTEST COLLECTION time
   (below, module level — before any test's autouse fixture ever runs), so the
   one-time ``load_dotenv()`` side effect fires and is immediately neutralised
   by the very first ``_hermetic_env`` setup. Every later lazy in-body
   ``import dspy``/``orchestrator`` in any test is then a ``sys.modules`` cache
   hit — no further ``load_dotenv()`` call can occur, so the plain per-test pop
   below is sufficient (no need to force a fixed default value that would
   itself conflict with call sites that intentionally pass a different pinned
   model, e.g. the Haiku sensitivity arm).

2. Raw ``os.environ`` writes in product code. e.g. ``judge/runner.py`` sets
   ``os.environ["SETDRIFT_LLM_BACKEND"] = backend`` per judge family. Unlike
   ``monkeypatch.setenv`` (reverted at teardown), a direct assignment persists
   into later tests in the same process.

The ``_hermetic_env`` autouse fixture (a) snapshots the environment and restores
it verbatim at teardown — neutralising leaks of type 2 — and (b) actively strips
the backend-selection overrides at SETUP so every test starts from the frozen
production default (``anthropic`` → the mock) rather than whatever ``.env``
injected — neutralising leaks of type 1 (now safe because of the eager
collection-time import above). Tests that genuinely exercise the OpenRouter
path, or a non-default pinned model, opt in explicitly via
``monkeypatch.setenv`` inside the test body, which runs after this setup.
Zero changes to frozen contracts.
"""

import os

import pytest

# Backend-selection env vars that a developer ``.env`` (auto-loaded by litellm at
# import time) must not be allowed to impose on the hermetic unit suite. Stripped
# at every test's setup; tests that need them set them via monkeypatch.
# SETDRIFT_MODEL is included here (Phase 7, D7-19) because the repo-root ``.env``
# pins a non-pinned OpenRouter model id (``openai/gpt-oss-120b:free``); leaving it
# in place would make every test hitting ``evidence.preflight.assert_evidence_run``
# fail on an unrelated developer-env artifact rather than the test's own scenario.
_BACKEND_OVERRIDE_KEYS = ("SETDRIFT_LLM_BACKEND", "OPENROUTER_API_KEY", "SETDRIFT_MODEL")

# Eagerly trigger dspy/litellm's one-time load_dotenv() NOW, at conftest
# COLLECTION time — before pytest imports ANY test module. This matters because
# ``setdrift_eval/optimizer/__init__.py`` itself imports ``orchestrator`` at
# PACKAGE level, so any test file that does a module-level
# ``from setdrift_eval.optimizer.X import Y`` (several do, e.g.
# ``test_rollback_cli.py``) transitively imports ``orchestrator`` — and thus
# triggers ``dspy``/``litellm``'s import-time ``load_dotenv()`` — DURING
# COLLECTION, before any per-test ``_hermetic_env`` fixture has ever run. That
# poisons ``orchestrator._MODEL`` (captured once, at that first import, as a
# plain module-level constant) for the rest of the process. Strip immediately
# after this eager import (module level, not just inside the fixture) so any
# later collection-time import of ``orchestrator`` sees a clean environment.
try:
    import dspy  # noqa: F401
except ImportError:
    pass  # [optimize] extra not installed — no dspy/litellm to poison env with
else:
    for _key in _BACKEND_OVERRIDE_KEYS:
        os.environ.pop(_key, None)


@pytest.fixture(autouse=True)
def _hermetic_env():
    """Isolate each test from the developer ``.env`` and cross-test env leaks.

    Snapshot/restore guards against raw ``os.environ`` writes in product code
    (e.g. ``judge/runner.py``); the setup-time strip of ``_BACKEND_OVERRIDE_KEYS``
    guards against ``litellm``'s import-time ``load_dotenv()`` flipping the
    harness onto the OpenRouter backend and past the Anthropic mock. Safe as a
    plain pop (no forced default value) because the module-level eager ``dspy``
    import above already neutralised any later re-trigger of ``load_dotenv()``.
    """
    snapshot = dict(os.environ)
    for key in _BACKEND_OVERRIDE_KEYS:
        os.environ.pop(key, None)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(snapshot)
