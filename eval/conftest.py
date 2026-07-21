"""Root-level pytest configuration for the Setdrift eval harness.

Placed at the rootdir (alongside pyproject.toml) so its fixtures apply to the
ENTIRE session — both the ``tests/`` tree and every ``setdrift_eval/**/tests/``
subtree named in ``testpaths``.

Why this file exists
--------------------
The unit suite must be hermetic — its behaviour must not depend on a developer's
local ``.env``. Two mechanisms otherwise break that:

1. Library import side-effect. ``litellm`` (pulled in transitively via ``dspy``)
   calls ``dotenv.load_dotenv()` at *import* time. Importing any optimizer module
   during pytest COLLECTION therefore injects the repo-root ``.env`` into the
   process environment. That ``.env`` sets ``SETDRIFT_LLM_BACKEND=openrouter``
   (plus a live ``OPENROUTER_API_KEY``), which silently flipped
   ``tests/test_response_cache.py`` and ``tests/test_arm_runner.py`` onto the
   OpenRouter path — past the Anthropic-only ``mock_anthropic_client`` fixture
   and into a live HTTP client — producing ``openai.AuthenticationError``.

2. Raw ``os.environ`` writes in product code. e.g. ``judge/runner.py`` sets
   ``os.environ["SETDRIFT_LLM_BACKEND"] = backend`` per judge family. Unlike
   ``monkeypatch.setenv`` (reverted at teardown), a direct assignment persists
   into later tests in the same process.

The ``_hermetic_env`` autouse fixture (a) snapshots the environment and restores
it verbatim at teardown — neutralising leaks of type 2 — and (b) actively strips
the backend-selection overrides at SETUP so every test starts from the frozen
production default (``anthropic`` → the mock) rather than whatever ``.env``
injected at collection time — neutralising leaks of type 1. Tests that genuinely
exercise the OpenRouter path opt in explicitly via ``monkeypatch.setenv`` inside
the test body, which runs after this setup. Zero changes to frozen contracts.
"""

import os

import pytest

# Backend-selection env vars that a developer ``.env`` (auto-loaded by litellm at
# import time) must not be allowed to impose on the hermetic unit suite. Stripped
# at every test's setup; tests that need them set them via monkeypatch.
_BACKEND_OVERRIDE_KEYS = ("SETDRIFT_LLM_BACKEND", "OPENROUTER_API_KEY")


@pytest.fixture(autouse=True)
def _hermetic_env():
    """Isolate each test from the developer ``.env`` and cross-test env leaks.

    Snapshot/restore guards against raw ``os.environ`` writes in product code
    (e.g. ``judge/runner.py``); the setup-time strip of ``_BACKEND_OVERRIDE_KEYS``
    guards against ``litellm``'s import-time ``load_dotenv()`` flipping the
    harness onto the OpenRouter backend and past the Anthropic mock.
    """
    snapshot = dict(os.environ)
    for key in _BACKEND_OVERRIDE_KEYS:
        os.environ.pop(key, None)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(snapshot)
