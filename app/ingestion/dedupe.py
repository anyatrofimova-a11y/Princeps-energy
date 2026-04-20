"""
app/ingestion/dedupe.py — near-duplicate detection via MinHash.

Used by :class:`app.ingestion.base.IngestionWorker` to skip insertion of
documents that have already been ingested under a different URL (eg. a
news release republished on two portals). Default Jaccard threshold is
0.85.

The schema does not currently have a ``supersedes_doc_id`` column on
``documents``; rather than add one here (schema agent owns the DDL), we
just skip the insert and log. The downstream router knows documents come
from multiple sources and tolerates missing coverage.
"""

from __future__ import annotations

import logging
import re

log = logging.getLogger("princeps.ingestion.dedupe")

# Default MinHash perm count — 128 gives reasonable accuracy at low cost.
_NUM_PERM = 128
_JACCARD_THRESHOLD = 0.85


_WORD_RE = re.compile(r"[A-Za-z0-9]{3,}")


def _shingles(text: str, k: int = 5) -> list[str]:
    """5-word shingles — standard for document-similarity MinHash."""
    words = [w.lower() for w in _WORD_RE.findall(text or "")]
    if len(words) < k:
        return [" ".join(words)] if words else []
    return [" ".join(words[i:i + k]) for i in range(len(words) - k + 1)]


def minhash_signature(text: str):
    """
    Compute a MinHash signature. Returns the ``datasketch.MinHash`` when
    the library is installed, otherwise a tuple of (set, token_count) so
    the Jaccard fallback in :func:`is_near_duplicate` still works.
    """
    shingles = _shingles(text)
    try:
        from datasketch import MinHash
        m = MinHash(num_perm=_NUM_PERM)
        for s in shingles:
            m.update(s.encode("utf-8"))
        return m
    except Exception:
        # Fallback — python set, no MinHash. Still usable for Jaccard on
        # small corpora.
        return (set(shingles), len(shingles))


def is_near_duplicate(sig_a, sig_b, threshold: float = _JACCARD_THRESHOLD) -> bool:
    """
    Return True if ``sig_a`` and ``sig_b`` are near-duplicates. Accepts
    either ``datasketch.MinHash`` or the ``(set, count)`` fallback; handles
    mixed types by coercing to sets.
    """
    if sig_a is None or sig_b is None:
        return False

    # datasketch.MinHash has a ``jaccard`` method.
    try:
        if hasattr(sig_a, "jaccard") and hasattr(sig_b, "jaccard"):
            return sig_a.jaccard(sig_b) >= threshold
    except Exception:
        pass

    # Fallback — coerce to sets
    set_a = sig_a[0] if isinstance(sig_a, tuple) else None
    set_b = sig_b[0] if isinstance(sig_b, tuple) else None
    if set_a is None or set_b is None:
        return False
    if not set_a or not set_b:
        return False
    inter = len(set_a & set_b)
    union = len(set_a | set_b)
    if union == 0:
        return False
    return (inter / union) >= threshold


# ── Cosine-similarity variant over embeddings ───────────────────────────────

def cosine_near_duplicate(
    vec_a: list[float] | None,
    vec_b: list[float] | None,
    threshold: float = 0.92,
) -> bool:
    """
    Secondary dedupe check — cosine similarity on embeddings.

    Callers can use this to confirm a MinHash near-match before skipping.
    Returns False (not a duplicate) whenever either embedding is missing.
    """
    if not vec_a or not vec_b:
        return False
    if len(vec_a) != len(vec_b):
        return False
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for a, b in zip(vec_a, vec_b, strict=True):
        dot += a * b
        norm_a += a * a
        norm_b += b * b
    if norm_a == 0 or norm_b == 0:
        return False
    sim = dot / ((norm_a ** 0.5) * (norm_b ** 0.5))
    return sim >= threshold
