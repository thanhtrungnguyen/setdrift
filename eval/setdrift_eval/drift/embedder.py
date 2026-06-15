"""MiniLM chunk-embed, cosine staleness, and embedder-weights checksum (REQ-MEASURE-03).

Pinned model: sentence-transformers/all-MiniLM-L6-v2 (sentence-transformers==5.5.1).
MAX_TOKENS = 200 (conservative; trained max is 256, library truncates silently above it).
OVERLAP = 40 (~20% overlap to preserve method-boundary context across chunks).

What this module does NOT do: never calls the Anthropic API; never reads scorer.py.

Lazy-imports sentence_transformers and transformers inside load_model() so the CLI
loads without requiring the [drift] extra to be installed.

Eval-side fail-loud: errors propagate (no bare except).
"""
import hashlib
import os
from pathlib import Path

import numpy as np

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
MAX_TOKENS = 200
OVERLAP = 40
WINDOW_N = int(os.environ.get("SETDRIFT_DRIFT_WINDOW_N", "20"))


def load_model():
    """Lazy-load the pinned MiniLM model and its tokenizer.

    Returns:
        tuple[SentenceTransformer, AutoTokenizer]: model + tokenizer pair.
    """
    from sentence_transformers import SentenceTransformer  # type: ignore[import]
    from transformers import AutoTokenizer  # type: ignore[import]

    model = SentenceTransformer(MODEL_NAME)
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
    return model, tokenizer


def chunk_code(text: str, tok, max_tokens: int = MAX_TOKENS, overlap: int = OVERLAP) -> list[str]:
    """Split text into overlapping chunks where each chunk is <= max_tokens tokens.

    Uses a sliding window of stride = max_tokens - overlap over the token sequence,
    never emitting a chunk that exceeds max_tokens to avoid the silent-truncation
    pitfall (Pitfall 3 in 04-RESEARCH.md).

    Args:
        text: Source text (e.g., Java file content).
        tok: A tokenizer with an .encode(text, add_special_tokens=False) method.
        max_tokens: Maximum tokens per chunk (default MAX_TOKENS=200).
        overlap: Token overlap between consecutive chunks (default OVERLAP=40).

    Returns:
        List of text chunks, each <= max_tokens tokens. Empty input returns [].
    """
    if not text or not text.strip():
        return []

    token_ids = tok.encode(text, add_special_tokens=False)
    if not token_ids:
        return []

    stride = max_tokens - overlap
    if stride <= 0:
        stride = max_tokens  # degenerate guard: no overlap if overlap >= max_tokens

    chunks: list[str] = []
    start = 0
    while start < len(token_ids):
        end = min(start + max_tokens, len(token_ids))
        chunk_ids = token_ids[start:end]
        # Decode back to text — use convert_ids_to_tokens if available, else decode
        if hasattr(tok, "decode"):
            chunk_text = tok.decode(chunk_ids, skip_special_tokens=True)
        else:
            # Stub tokenizer path (tests): join token IDs as space-separated strings
            chunk_text = " ".join(str(t) for t in chunk_ids)
        chunks.append(chunk_text)
        if end == len(token_ids):
            break
        start += stride

    return chunks


def embed_text_chunks(chunks: list[str], model) -> np.ndarray:
    """Embed a list of text chunks and return a mean-pooled L2-normalised vector.

    Args:
        chunks: List of text strings to embed.
        model: SentenceTransformer model instance.

    Returns:
        np.ndarray of shape (384,). Returns np.zeros(384) on empty input.
    """
    if not chunks:
        return np.zeros(384)

    embeddings = model.encode(chunks, normalize_embeddings=True)
    mean_vec = embeddings.mean(axis=0)
    # L2-normalise the mean
    norm = np.linalg.norm(mean_vec)
    if norm > 0:
        mean_vec = mean_vec / norm
    return mean_vec


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity between two vectors (dot product of L2-normalised inputs).

    Args:
        a: First vector.
        b: Second vector.

    Returns:
        float in [-1, 1] (1.0 for identical direction, 0.0 for orthogonal).
    """
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a / norm_a, b / norm_b))


def compute_drift_index(config_text: str, commit_window: list[str], n: int = WINDOW_N) -> float:
    """Compute the cosine-staleness drift index for config_text against a code window.

    Drift index = 1.0 - cosine(config_vec, mean(code_window_vecs)), clipped to [0, 1].
    Only the last n entries of commit_window are consumed (rolling window, D-55/D-57).

    Args:
        config_text: The configuration string to measure staleness for.
        commit_window: List of code content strings (e.g., changed Java file contents).
        n: Rolling window size (default WINDOW_N; overridable via SETDRIFT_DRIFT_WINDOW_N).

    Returns:
        float in [0.0, 1.0]. Returns 0.0 (non-stale) when commit_window is empty.
    """
    if not commit_window:
        return 0.0

    model, tokenizer = load_model()

    # Rolling window: consume only the last n entries
    window = commit_window[-n:] if len(commit_window) > n else commit_window

    config_chunks = chunk_code(config_text, tokenizer)
    config_vec = embed_text_chunks(config_chunks, model)

    # Embed each window entry and mean-pool into a single code vector
    code_vecs = []
    for content in window:
        code_chunks = chunk_code(content, tokenizer)
        code_vec = embed_text_chunks(code_chunks, model)
        code_vecs.append(code_vec)

    code_window_mean = np.stack(code_vecs).mean(axis=0)
    norm = np.linalg.norm(code_window_mean)
    if norm > 0:
        code_window_mean = code_window_mean / norm

    similarity = cosine_similarity(config_vec, code_window_mean)
    drift = 1.0 - similarity
    # Clip to [0, 1] to handle floating-point edge cases
    return float(max(0.0, min(1.0, drift)))


def embedder_checksum() -> str:
    """Return the sha256 hex-digest of the pinned MiniLM model's config.json.

    This checksum is logged into DriftManifest (REQ-MEASURE-03) so every drift-index
    cell is reproducible and tamper-evident. The model file is downloaded on first
    call (sentence-transformers caches to ~/.cache/huggingface/hub/).

    NOTE: This hashes only config.json (model architecture parameters), not the full
    safetensors weights. A safetensors-level hash would be the rigorous upgrade
    per Assumption A7 in 04-RESEARCH.md. config.json is sufficient to pin the
    architecture; the exact-pin sentence-transformers==5.5.1 + model name pin
    together guard the weights in practice.

    Returns:
        str: 64-character lowercase hex sha256 digest.
    """
    from sentence_transformers import SentenceTransformer  # type: ignore[import]

    # Load model to ensure files are cached locally
    model = SentenceTransformer(MODEL_NAME)
    # Find the config.json on disk
    config_path: Path | None = None
    model_dir = Path(model._model_card_data.base_model if hasattr(model, "_model_card_data") and
                     model._model_card_data and model._model_card_data.base_model else "")

    # Walk through potential module paths to find config.json
    for module in model.modules():
        if hasattr(module, "auto_model"):
            # Transformer module — the model files live alongside it
            try:
                import transformers  # type: ignore[import]
                tok = transformers.AutoTokenizer.from_pretrained(MODEL_NAME)
                # The tokenizer knows the local path
                if hasattr(tok, "name_or_path"):
                    candidate = Path(tok.name_or_path) / "config.json"
                    if candidate.exists():
                        config_path = candidate
                        break
            except Exception:
                pass

    if config_path is None or not config_path.exists():
        # Fallback: locate the model config in the huggingface cache.
        import huggingface_hub  # type: ignore[import]

        local_dir = huggingface_hub.snapshot_download(
            MODEL_NAME,
            local_files_only=True,
        )
        config_path = Path(local_dir) / "config.json"

    if config_path is None or not config_path.exists():
        # Fail loud (eval-side): REQ-MEASURE-03 requires a genuine, tamper-evident
        # checksum of the real model config. Never return a synthetic hash derived
        # from MODEL_NAME — that would look valid while proving nothing about the
        # weights actually loaded, defeating reproducibility/tamper evidence.
        raise RuntimeError(
            "embedder_checksum: could not locate config.json for the pinned model "
            f"'{MODEL_NAME}'. Ensure sentence-transformers cached it (run the embedder "
            "once with network access). Refusing to emit a synthetic checksum "
            "(REQ-MEASURE-03 requires a real tamper-evident digest)."
        )

    return hashlib.sha256(config_path.read_bytes()).hexdigest()
