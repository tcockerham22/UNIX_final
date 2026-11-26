"""Tests for Markdown chunking and the local pgvector retrieval helpers."""

from __future__ import annotations

import re
import unittest
from pathlib import Path
from types import SimpleNamespace
from contextlib import contextmanager
from unittest.mock import Mock, patch

from ada.rag import (
    CHUNK_TOKEN_OVERLAP,
    CHUNK_TOKEN_TARGET,
    EMBEDDING_DIMENSIONS,
    EMBEDDING_MODEL,
    PostgresRAG,
    chunk_markdown,
    document_chunks,
    make_chunk,
)

ROOT = Path(__file__).resolve().parents[1]
TOKEN_PATTERN = re.compile(r"\w+|[^\w\s]", re.UNICODE)


class MarkdownChunkTests(unittest.TestCase):
    def test_chunks_are_bounded_and_retain_markdown_heading_context(self):
        body = " ".join(f"word{i}" for i in range(1500))
        chunks = chunk_markdown(f"# Guide\n\n## Details\n\n{body}")

        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertLessEqual(len(TOKEN_PATTERN.findall(chunk)), CHUNK_TOKEN_TARGET)
            self.assertIn("Guide\nDetails", chunk)

        first_words = re.findall(r"word\d+", chunks[0])
        second_words = re.findall(r"word\d+", chunks[1])
        overlap_size = min(CHUNK_TOKEN_OVERLAP, len(first_words), len(second_words))
        self.assertEqual(
            first_words[-overlap_size:],
            second_words[:overlap_size],
        )

    def test_chunk_ids_follow_the_required_source_index_and_content_hash(self):
        first = make_chunk("docs/example.md", 2, "A stable passage.")
        same = make_chunk("docs/example.md", 2, "A stable passage.")
        other_source = make_chunk("docs/other.md", 2, "A stable passage.")

        self.assertEqual(first.id, same.id)
        self.assertNotEqual(first.id, other_source.id)
        self.assertEqual(len(first.id), 64)
        self.assertEqual(len(first.content_hash), 64)

    def test_corpus_and_ada_skills_provide_at_least_twenty_five_chunks(self):
        documents = [
            *sorted((ROOT / "corpus").rglob("*.md")),
            *sorted((ROOT / "assets" / "skills").rglob("*.md")),
        ]
        chunks = [
            chunk
            for path in documents
            for chunk in document_chunks(
                path.relative_to(ROOT).as_posix(),
                path.read_text(encoding="utf-8"),
            )
        ]

        self.assertGreaterEqual(len(chunks), 25)
        self.assertTrue(any("Pacific Ocean" in chunk.content for chunk in chunks))


class PostgresRAGTests(unittest.TestCase):
    def test_embedding_output_is_checked_for_the_pgvector_dimension(self):
        with patch("ada.rag.ollama.Client") as client_class:
            client_class.return_value.embed.return_value = SimpleNamespace(
                embeddings=[[0.0] * EMBEDDING_DIMENSIONS]
            )
            rag = PostgresRAG("postgresql://db/ada", "http://ollama")
            embeddings = rag.embed("known fact")

        self.assertEqual(len(embeddings), 1)
        self.assertEqual(len(embeddings[0]), EMBEDDING_DIMENSIONS)
        client_class.return_value.embed.assert_called_once_with(
            model=EMBEDDING_MODEL,
            input="known fact",
        )
        self.assertEqual(EMBEDDING_MODEL, "nomic-embed-text")

    def test_embedding_output_with_wrong_dimension_is_rejected(self):
        with patch("ada.rag.ollama.Client") as client_class:
            client_class.return_value.embed.return_value = SimpleNamespace(
                embeddings=[[0.0] * (EMBEDDING_DIMENSIONS - 1)]
            )
            rag = PostgresRAG("postgresql://db/ada", "http://ollama")

        with self.assertRaisesRegex(RuntimeError, "must return 768 dimensions"):
            rag.embed("known fact")

    def test_database_url_is_required(self):
        with self.assertRaisesRegex(RuntimeError, "ADA_DATABASE_URL"):
            PostgresRAG(None, "http://ollama")

    def test_insert_uses_sha_ids_and_conflict_safe_inserts(self):
        rag = PostgresRAG.__new__(PostgresRAG)
        rag.database_url = "postgresql://db/ada"
        rag.ensure_schema = Mock()
        rag.embed = Mock(return_value=[[0.0] * EMBEDDING_DIMENSIONS] * 2)

        connection = Mock()
        connection.execute.side_effect = [
            SimpleNamespace(rowcount=1),
            SimpleNamespace(rowcount=0),
        ]

        @contextmanager
        def connect():
            yield connection

        rag._connect = connect
        chunks = [
            make_chunk("docs/a.md", 0, "First"),
            make_chunk("docs/a.md", 1, "Second"),
        ]

        self.assertEqual(rag.insert_chunks(chunks), 1)
        self.assertEqual(connection.execute.call_count, 2)
        for call in connection.execute.call_args_list:
            self.assertIn("ON CONFLICT (id) DO NOTHING", call.args[0])

    def test_retrieval_uses_cosine_distance_and_caps_top_k(self):
        rag = PostgresRAG.__new__(PostgresRAG)
        rag.database_url = "postgresql://db/ada"
        rag.ensure_schema = Mock()
        rag.embed = Mock(return_value=[[0.25] * EMBEDDING_DIMENSIONS])
        connection = Mock()
        connection.execute.return_value.fetchall.return_value = [
            ("corpus/fact.md", 0, "A known fact.", 0.95),
        ]

        @contextmanager
        def connect():
            yield connection

        rag._connect = connect
        results = rag.retrieve("question", top_k=99)

        query = connection.execute.call_args.args[0]
        self.assertIn("embedding <=> %s::vector", query)
        self.assertEqual(connection.execute.call_args.args[1][-1], 10)
        self.assertEqual(results[0]["source"], "corpus/fact.md")
        self.assertEqual(results[0]["score"], 0.95)


if __name__ == "__main__":
    unittest.main()
