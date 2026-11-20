CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS chunks (
    id          TEXT PRIMARY KEY,          -- sha256 of source + index + text
    source      TEXT NOT NULL,             -- file the chunk came from
    chunk_index INTEGER NOT NULL,          -- position within that file
    content     TEXT NOT NULL,             -- the chunk text
    embedding   vector(768) NOT NULL,      -- embedding of the chunk
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS chunks_source_idx ON chunks (source);

CREATE INDEX IF NOT EXISTS chunks_embedding_idx
    ON chunks USING hnsw (embedding vector_cosine_ops);
