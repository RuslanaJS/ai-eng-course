"""Loading the chunks that the ingestion step wrote."""

import json

from ..ingest.build import PROCESSED


def load_chunks(name="structural"):
    """All chunks of a strategy: the committable file and, when present, the local-only one."""
    files = {"structural": ("chunks.jsonl", "chunks_local.jsonl"),
             "fixed": ("chunks_fixed_local.jsonl",)}[name]
    chunks = []
    for file in files:
        path = PROCESSED / file
        if path.exists():
            chunks += [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    return chunks
