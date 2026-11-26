"""Load Ada documentation and smoke-test facts into PostgreSQL/pgvector."""

from __future__ import annotations

import argparse
import logging

from ada.config import ROOT, Config
from ada.rag import PostgresRAG, document_chunks

LOGGER = logging.getLogger("ada.ingest")
DOCUMENT_DIRECTORIES = (ROOT / "corpus", ROOT / "assets" / "skills")


def load_chunks():
    """Read Markdown documents in stable path order and split them into chunks."""
    chunks = []
    for directory in DOCUMENT_DIRECTORIES:
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*.md")):
            relative_source = path.relative_to(ROOT).as_posix()
            chunks.extend(
                document_chunks(relative_source, path.read_text(encoding="utf-8"))
            )
    return chunks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--if-empty",
        action="store_true",
        help="Skip embedding and ingest when the chunks table already has rows.",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    config = Config.load()
    if config.profile != "cloud":
        parser.error("Set ADA_PROFILE=cloud before running ingestion.")

    rag = PostgresRAG(config.database_url, config.ollama_host)
    rag.ensure_schema()
    if args.if_empty:
        with rag._connect() as connection:
            existing = connection.execute("SELECT EXISTS (SELECT 1 FROM chunks)").fetchone()[0]
        if existing:
            LOGGER.info("Chunks already exist; skipping initial corpus ingestion.")
            return 0

    chunks = load_chunks()
    if not chunks:
        LOGGER.error("No Markdown files found under corpus/ or assets/skills/.")
        return 1

    LOGGER.info(
        "Embedding %d document chunks with local model %s.",
        len(chunks),
        "nomic-embed-text",
    )
    inserted = rag.insert_chunks(chunks)
    LOGGER.info("Ingestion complete: %d new chunks stored.", inserted)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
