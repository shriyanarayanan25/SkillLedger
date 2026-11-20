"""Sentence embeddings (384-d). Uses all-MiniLM-L6-v2 if sentence-transformers is installed,
otherwise a deterministic hashing fallback (lexical only, NOT semantic) so everything still runs."""
import os, hashlib, numpy as np
DIM = 384
_model = None

def _load():
    global _model
    if _model is None:
        _model = False
        if os.getenv("SKILLLEDGER_EMBED") != "hash":
            try:
                from sentence_transformers import SentenceTransformer
                _model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
            except Exception as e:
                print("[embed] sentence-transformers unavailable -> hashing fallback:", type(e).__name__)
    return _model

def backend(): return "MiniLM" if _load() else "hash-fallback"

def _hash_vec(text):
    v = np.zeros(DIM, dtype=np.float32); t = f" {text.lower()} "
    for n in (3, 4):
        for i in range(len(t) - n + 1):
            v[int(hashlib.md5(t[i:i+n].encode()).hexdigest(), 16) % DIM] += 1
    return v

def embed(texts):
    if isinstance(texts, str): texts = [texts]
    m = _load()
    a = m.encode(list(texts), normalize_embeddings=True) if m else np.array([_hash_vec(t) for t in texts])
    a = a.astype(np.float32); a /= np.linalg.norm(a, axis=1, keepdims=True) + 1e-9
    return a

def vec_literal(a): return "[" + ",".join(f"{x:.4f}" for x in a) + "]"
