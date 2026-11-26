#!/usr/bin/env python3
"""Unit tests for chunking and ID logic (no database needed).
Run: python3 tests/test_chunking.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from ingest import chunk_id, chunk_words, load_documents  # noqa: E402


def test_chunk_sizes_and_overlap():
    text = " ".join(f"w{i}" for i in range(200))
    chunks = chunk_words(text, 50, 10)
    assert chunks[0].split()[0] == "w0"
    assert len(chunks[0].split()) == 50
    # second chunk starts 40 words in (size - overlap)
    assert chunks[1].split()[0] == "w40"
    # every word appears in at least one chunk
    seen = {w for c in chunks for w in c.split()}
    assert seen == set(text.split())


def test_short_text_is_one_chunk():
    assert chunk_words("just a few words", 50, 10) == ["just a few words"]


def test_empty_text_has_no_chunks():
    assert chunk_words("   ", 50, 10) == []


def test_ids_are_deterministic_and_distinct():
    assert chunk_id("a.md", 0, "hello") == chunk_id("a.md", 0, "hello")
    assert chunk_id("a.md", 0, "hello") != chunk_id("a.md", 1, "hello")
    assert chunk_id("a.md", 0, "hello") != chunk_id("b.md", 0, "hello")


def test_corpus_yields_at_least_25_chunks():
    docs = load_documents(Path(__file__).resolve().parent.parent / "data" / "docs")
    total = sum(len(chunk_words(t, 90, 15)) for _, t in docs)
    assert total >= 25, f"only {total} chunks"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("PASS", name)
