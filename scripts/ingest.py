#!/usr/bin/env python3
"""Loads the documents into the database for RAG.

Reads the .md/.txt files in data/docs, splits them into overlapping chunks,
gets an embedding for each chunk from the embedding service (Ollama), and
upserts them into the chunks table. Each chunk's id is a hash of its source,
position and text, so running this again doesn't create duplicates. Chunks
that no longer exist in the documents are deleted.

Settings come from env vars (defaults in parentheses):
  DB_HOST (127.0.0.1), DB_PORT (5432), DB_NAME (ragdb), DB_USER (raguser)
  DB_PASSWORD (required)
  OLLAMA_URL (http://127.0.0.1:11434)
  EMBED_MODEL (nomic-embed-text), EMBED_DIM (768)
  EMBED_DOC_PREFIX ("search_document: ")
      nomic-embed-text wants this prefix on documents and "search_query: " on
      questions. Set it to "" for models that don't use prefixes.
"""

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import psycopg

REPO_ROOT = Path(__file__).resolve().parent.parent


def env(name, default=None):
    return os.environ.get(name, default)


def chunk_words(text, size, overlap):
    """Split text into chunks of `size` words, overlapping by `overlap` words."""
    if overlap >= size:
        raise ValueError("overlap must be smaller than chunk size")
    words = text.split()
    chunks = []
    step = size - overlap
    for start in range(0, len(words), step):
        chunks.append(" ".join(words[start:start + size]))
        if start + size >= len(words):
            break
    return chunks


def chunk_id(source, index, text):
    """Deterministic ID: same input always gives the same row key."""
    raw = f"{source}\x00{index}\x00{text}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def load_documents(docs_dir):
    files = sorted(
        p for p in Path(docs_dir).rglob("*") if p.suffix.lower() in (".md", ".txt")
    )
    docs = []
    for path in files:
        if path.name.lower() == "readme.md":
            continue
        docs.append((str(path.relative_to(docs_dir)), path.read_text(encoding="utf-8")))
    return docs


def embed_batch(texts, url, model, retries=5):
    payload = json.dumps({"model": model, "input": texts}).encode("utf-8")
    req = urllib.request.Request(
        f"{url}/api/embed",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read())["embeddings"]
        except (urllib.error.URLError, ConnectionError, TimeoutError) as exc:
            if attempt == retries:
                raise RuntimeError(f"embedding service unreachable at {url}: {exc}")
            print(f"  embedding attempt {attempt} failed ({exc}); retrying...")
            time.sleep(3 * attempt)


def connect(retries=30):
    for attempt in range(1, retries + 1):
        try:
            return psycopg.connect(
                host=env("DB_HOST", "127.0.0.1"),
                port=env("DB_PORT", "5432"),
                dbname=env("DB_NAME", "ragdb"),
                user=env("DB_USER", "raguser"),
                password=env("DB_PASSWORD"),
                autocommit=True,
            )
        except psycopg.OperationalError as exc:
            if attempt == retries:
                raise
            print(f"  database not ready (attempt {attempt}): {str(exc).strip()}")
            time.sleep(2)


def vector_literal(values):
    return "[" + ",".join(repr(float(v)) for v in values) + "]"


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--docs", default=str(REPO_ROOT / "data" / "docs"))
    parser.add_argument("--schema", default=str(REPO_ROOT / "db" / "schema.sql"))
    parser.add_argument("--chunk-size", type=int, default=90, help="words per chunk")
    parser.add_argument("--overlap", type=int, default=15, help="overlapping words")
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--min-chunks", type=int, default=25,
                        help="fail if the table ends with fewer rows (spec: 25+)")
    parser.add_argument("--if-empty", action="store_true",
                        help="skip everything if the chunks table already has rows")
    args = parser.parse_args()

    if not env("DB_PASSWORD"):
        sys.exit("DB_PASSWORD is not set")

    model = env("EMBED_MODEL", "nomic-embed-text")
    ollama = env("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
    dim = int(env("EMBED_DIM", "768"))
    prefix = env("EMBED_DOC_PREFIX", "search_document: ")

    conn = connect()
    conn.execute(Path(args.schema).read_text(encoding="utf-8"))

    existing = conn.execute("SELECT count(*) FROM chunks").fetchone()[0]
    if args.if_empty and existing > 0:
        print(f"chunks table already has {existing} rows; skipping (--if-empty)")
        return

    docs = load_documents(args.docs)
    if not docs:
        sys.exit(f"no .md/.txt documents found under {args.docs}")

    records = []  # (id, source, index, text)
    for source, text in docs:
        for index, piece in enumerate(chunk_words(text, args.chunk_size, args.overlap)):
            records.append((chunk_id(source, index, piece), source, index, piece))
    print(f"{len(docs)} documents -> {len(records)} chunks")

    for start in range(0, len(records), args.batch_size):
        batch = records[start:start + args.batch_size]
        vectors = embed_batch([prefix + r[3] for r in batch], ollama, model)
        if len(vectors) != len(batch):
            sys.exit("embedding service returned the wrong number of vectors")
        for (cid, source, index, text), vec in zip(batch, vectors):
            if len(vec) != dim:
                sys.exit(f"embedding has {len(vec)} dimensions but EMBED_DIM={dim}; "
                         "update EMBED_DIM and db/schema.sql together")
            conn.execute(
                """
                INSERT INTO chunks (id, source, chunk_index, content, embedding)
                VALUES (%s, %s, %s, %s, %s::vector)
                ON CONFLICT (id) DO UPDATE
                   SET content = EXCLUDED.content,
                       embedding = EXCLUDED.embedding
                """,
                (cid, source, index, text, vector_literal(vec)),
            )
        print(f"  upserted {min(start + args.batch_size, len(records))}/{len(records)}")

    # Prune: remove rows that are no longer produced by the current documents.
    keep_ids = [r[0] for r in records]
    removed = conn.execute(
        "DELETE FROM chunks WHERE NOT (id = ANY(%s))", (keep_ids,)
    ).rowcount
    total = conn.execute("SELECT count(*) FROM chunks").fetchone()[0]
    print(f"pruned {removed} stale rows; table now has {total} chunks")

    if total < args.min_chunks:
        sys.exit(f"only {total} chunks; the project requires at least {args.min_chunks}")


if __name__ == "__main__":
    main()
