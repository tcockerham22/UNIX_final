"""Local Ollama embeddings and PostgreSQL/pgvector retrieval for cloud chat."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Iterable

import ollama

EMBEDDING_MODEL = "nomic-embed-text"
EMBEDDING_DIMENSIONS = 768
CHUNK_TOKEN_TARGET = 450
CHUNK_TOKEN_OVERLAP = 60
TOKEN_PATTERN = re.compile(r"\w+|[^\w\s]", re.UNICODE)
HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")


@dataclass(frozen=True)
class Chunk:
    """A stable document passage prepared for database storage."""

    id: str
    source: str
    chunk_idx: int
    content: str
    content_hash: str


def _token_count(text: str) -> int:
    """Count word and punctuation tokens as a lightweight tokenizer estimate."""
    return len(TOKEN_PATTERN.findall(text))


def _split_long_paragraph(text: str, max_tokens: int, overlap: int) -> list[str]:
    words = text.split()
    parts = []
    start = 0
    while start < len(words):
        end = start
        token_count = 0
        while end < len(words):
            word_tokens = _token_count(words[end])
            if end > start and token_count + word_tokens > max_tokens:
                break
            token_count += word_tokens
            end += 1
        parts.append(" ".join(words[start:end]))
        if end >= len(words):
            break
        next_start = end
        overlap_count = 0
        while next_start > start:
            word_tokens = _token_count(words[next_start - 1])
            if overlap_count + word_tokens > overlap:
                break
            overlap_count += word_tokens
            next_start -= 1
        start = max(start + 1, next_start)
    return parts


def chunk_markdown(
    text: str,
    *,
    target_tokens: int = CHUNK_TOKEN_TARGET,
    overlap_tokens: int = CHUNK_TOKEN_OVERLAP,
) -> list[str]:
    """Chunk Markdown near headings, retaining heading paths and token overlap."""
    sections: list[tuple[str, list[str]]] = []
    heading_stack: list[str] = []
    current: list[str] = []

    for line in text.splitlines():
        heading = HEADING_PATTERN.match(line.strip())
        if heading:
            if current:
                sections.append(("\n".join(heading_stack), current))
            level = len(heading.group(1))
            heading_stack = heading_stack[: level - 1]
            heading_stack.append(heading.group(2))
            current = []
        else:
            current.append(line)
    if current:
        sections.append(("\n".join(heading_stack), current))
    if not sections and text.strip():
        sections.append(("", text.splitlines()))

    chunks: list[str] = []
    for heading_path, lines in sections:
        paragraphs = [
            " ".join(line.strip() for line in block.splitlines()).strip()
            for block in re.split(r"\n\s*\n", "\n".join(lines))
        ]
        paragraphs = [paragraph for paragraph in paragraphs if paragraph]
        prefix = f"{heading_path}\n\n" if heading_path else ""
        pending: list[str] = []
        pending_tokens = _token_count(prefix)

        for paragraph in paragraphs:
            parts = _split_long_paragraph(
                paragraph,
                max_tokens=target_tokens - _token_count(prefix) - overlap_tokens,
                overlap=0,
            )
            for part in parts:
                part_tokens = _token_count(part)
                if pending and pending_tokens + part_tokens > target_tokens:
                    chunks.append(prefix + "\n\n".join(pending))
                    overlap_words = " ".join(pending).split()
                    carried: list[str] = []
                    carried_tokens = 0
                    for word in reversed(overlap_words):
                        word_tokens = _token_count(word)
                        if carried_tokens + word_tokens > overlap_tokens:
                            break
                        carried.insert(0, word)
                        carried_tokens += word_tokens
                    overlap = " ".join(carried)
                    pending = [overlap] if overlap else []
                    pending_tokens = _token_count(prefix) + _token_count(overlap)
                pending.append(part)
                pending_tokens += part_tokens

        if pending:
            chunks.append(prefix + "\n\n".join(pending))

    return [chunk.strip() for chunk in chunks if chunk.strip()]


def make_chunk(source: str, chunk_idx: int, content: str) -> Chunk:
    """Create the required content hash and stable primary key."""
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    chunk_id = hashlib.sha256(
        f"{source}{chunk_idx}{content}".encode("utf-8")
    ).hexdigest()
    return Chunk(chunk_id, source, chunk_idx, content, content_hash)


def document_chunks(source: str, text: str) -> list[Chunk]:
    """Split a source document and assign zero-based chunk indexes."""
    return [
        make_chunk(source, index, content)
        for index, content in enumerate(chunk_markdown(text))
    ]


class PostgresRAG:
    """Embed document passages locally and retrieve them with pgvector."""

    def __init__(self, database_url: str | None, ollama_host: str):
        if not database_url:
            raise RuntimeError("ADA_DATABASE_URL must be set in the cloud profile.")
        self.database_url = database_url
        self.client = ollama.Client(host=ollama_host, timeout=30)

    def _connect(self):
        import psycopg

        return psycopg.connect(self.database_url, connect_timeout=5)

    def ensure_schema(self) -> None:
        """Create the required pgvector extension, table, and cosine index."""
        with self._connect() as connection:
            connection.execute("SELECT pg_advisory_xact_lock(416488673200)")
            connection.execute("CREATE EXTENSION IF NOT EXISTS vector")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS chunks (
                    id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    chunk_idx INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    embedding vector(768) NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw_idx
                ON chunks USING hnsw (embedding vector_cosine_ops)
                """
            )

    def embed(self, texts: str | list[str]) -> list[list[float]]:
        """Use Ollama's local embedding model and verify its vector shape."""
        response = self.client.embed(model=EMBEDDING_MODEL, input=texts)
        embeddings = (
            response.get("embeddings", [])
            if isinstance(response, dict)
            else response.embeddings
        )
        if isinstance(texts, str):
            embeddings = [embeddings[0]] if embeddings else []
        if not embeddings:
            raise RuntimeError("Ollama returned no document embeddings.")
        for embedding in embeddings:
            if len(embedding) != EMBEDDING_DIMENSIONS:
                raise RuntimeError(
                    f"{EMBEDDING_MODEL} must return {EMBEDDING_DIMENSIONS} dimensions; "
                    f"received {len(embedding)}."
                )
        return [list(embedding) for embedding in embeddings]

    def insert_chunks(self, chunks: Iterable[Chunk], batch_size: int = 16) -> int:
        """Insert missing chunk IDs in batches; repeated ingestion adds no rows."""
        self.ensure_schema()
        inserted = 0
        pending = list(chunks)
        for start in range(0, len(pending), batch_size):
            batch = pending[start : start + batch_size]
            vectors = self.embed([chunk.content for chunk in batch])
            with self._connect() as connection:
                for chunk, vector in zip(batch, vectors, strict=True):
                    cursor = connection.execute(
                        """
                        INSERT INTO chunks
                            (id, source, chunk_idx, content, content_hash, embedding)
                        VALUES (%s, %s, %s, %s, %s, %s::vector)
                        ON CONFLICT (id) DO NOTHING
                        """,
                        (
                            chunk.id,
                            chunk.source,
                            chunk.chunk_idx,
                            chunk.content,
                            chunk.content_hash,
                            _vector_literal(vector),
                        ),
                    )
                    inserted += cursor.rowcount
        return inserted

    def retrieve(self, question: str, top_k: int = 4) -> list[dict]:
        """Return the nearest corpus passages ordered by cosine similarity."""
        if top_k < 1:
            raise ValueError("top_k must be at least one.")
        query_vector = _vector_literal(self.embed(question)[0])
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT source, chunk_idx, content, 1 - (embedding <=> %s::vector) AS score
                FROM chunks
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                (query_vector, query_vector, min(top_k, 10)),
            ).fetchall()
        return [
            {
                "source": source,
                "chunk_idx": chunk_idx,
                "content": content,
                "score": float(score),
            }
            for source, chunk_idx, content, score in rows
        ]


def _vector_literal(vector: Iterable[float]) -> str:
    """Serialize a numeric vector in pgvector's text input format."""
    return "[" + ",".join(f"{float(value):.8f}" for value in vector) + "]"
