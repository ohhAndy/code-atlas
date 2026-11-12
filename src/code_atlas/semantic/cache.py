"""On-disk cache of document embeddings, shared by every snapshot, keyed by text.

key = sha256(model id + NUL + text). The model id includes the pinned model version, so a
different model or version never reads another's vectors. The key is the text, not the
chunk id or the commit: most chunks are unchanged across the commits of a repo, so one
embedding serves every snapshot that contains the same text.

One SQLite file per model (`<cache dir>/<model id>.sqlite`), table key -> float32 bytes.
SQLite gives atomic writes and fast lookups by key in a single file, and it ships with
Python. `embed_with_cache` commits after every batch, so an interrupted run keeps the work
it finished. Only document embeddings are cached; queries are embedded fresh.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from types import TracebackType

import numpy as np

from code_atlas.semantic.embed import Embedder
from code_atlas.semantic.search import Vectors

ROOT = Path(__file__).resolve().parents[3]
EMBEDDING_CACHE_DIR = ROOT / ".cache" / "embeddings"
_LOOKUP_CHUNK = 500  # keys per SELECT, under SQLite's limit on query parameters


def text_key(model_id: str, text: str) -> bytes:
    return hashlib.sha256(f"{model_id}\0{text}".encode()).digest()


def cache_path(cache_dir: Path, model_id: str) -> Path:
    return cache_dir / f"{re.sub(r'[^A-Za-z0-9.-]+', '_', model_id)}.sqlite"


class EmbeddingCache:
    """Key -> vector store for one model. Use as a context manager, or call `close`."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS vectors (key BLOB PRIMARY KEY, vector BLOB NOT NULL)"
        )
        self.conn.commit()

    def get_many(self, keys: Iterable[bytes]) -> dict[bytes, Vectors]:
        """The cached vectors among `keys`; missing keys are left out."""
        unique = list(dict.fromkeys(keys))
        found: dict[bytes, Vectors] = {}
        for start in range(0, len(unique), _LOOKUP_CHUNK):
            part = unique[start : start + _LOOKUP_CHUNK]
            marks = ",".join("?" * len(part))
            rows = self.conn.execute(
                f"SELECT key, vector FROM vectors WHERE key IN ({marks})", part
            )
            for key, blob in rows:
                found[key] = np.frombuffer(blob, dtype=np.float32)
        return found

    def put_many(self, items: Mapping[bytes, Vectors]) -> None:
        """Store vectors and commit."""
        self.conn.executemany(
            "INSERT OR REPLACE INTO vectors (key, vector) VALUES (?, ?)",
            [(key, np.asarray(v, dtype=np.float32).tobytes()) for key, v in items.items()],
        )
        self.conn.commit()

    def __len__(self) -> int:
        (count,) = self.conn.execute("SELECT COUNT(*) FROM vectors").fetchone()
        return int(count)

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> EmbeddingCache:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


def embed_with_cache(
    embedder: Embedder,
    texts: Sequence[str],
    cache: EmbeddingCache,
    batch_size: int = 256,
    progress: Callable[[int, int], None] | None = None,
) -> Vectors:
    """Document vectors for `texts`, one row per text in input order. Texts already in the
    cache are not embedded again, and a text repeated in `texts` is embedded once.
    `progress(done, total)` is called after each batch of missing texts."""
    if not texts:
        return np.zeros((0, 0), dtype=np.float32)
    keys = [text_key(embedder.model_id, t) for t in texts]
    vectors = cache.get_many(keys)
    missing = list({k: t for k, t in zip(keys, texts, strict=True) if k not in vectors}.items())
    for start in range(0, len(missing), batch_size):
        batch = missing[start : start + batch_size]
        embedded = embedder.embed_documents([t for _, t in batch])
        if embedded.shape[0] != len(batch):
            raise RuntimeError(f"asked for {len(batch)} vectors, got {embedded.shape[0]}")
        new = {key: embedded[i] for i, (key, _) in enumerate(batch)}
        cache.put_many(new)
        vectors.update(new)
        if progress is not None:
            progress(start + len(batch), len(missing))
    return np.stack([vectors[k] for k in keys]).astype(np.float32, copy=False)
