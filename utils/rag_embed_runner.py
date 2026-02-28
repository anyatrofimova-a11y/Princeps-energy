#!/usr/bin/env python3
"""
RAG Embedding Runner — subprocess script for .venv-geeflow (Python 3.12 + torch).

Reads JSON from stdin: {"texts": ["chunk1", "chunk2"]}
Outputs JSON array of float arrays to stdout.

Uses sentence-transformers all-MiniLM-L6-v2 (384-dim).

Usage:
    echo '{"texts":["hello world"]}' | .venv-geeflow/bin/python utils/rag_embed_runner.py
"""

import json
import sys


def main():
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        # Fallback: return zero vectors so the pipeline doesn't crash
        payload = json.loads(sys.stdin.read())
        texts = payload.get("texts", [])
        sys.stdout.write(json.dumps([[0.0] * 384 for _ in texts]))
        sys.exit(0)

    payload = json.loads(sys.stdin.read())
    texts = payload.get("texts", [])

    if not texts:
        sys.stdout.write(json.dumps([]))
        sys.exit(0)

    model = SentenceTransformer("all-MiniLM-L6-v2")
    embeddings = model.encode(texts, show_progress_bar=False, normalize_embeddings=True)

    # Convert numpy arrays to plain lists
    result = [emb.tolist() for emb in embeddings]
    sys.stdout.write(json.dumps(result))


if __name__ == "__main__":
    main()
