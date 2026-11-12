"""Loading the chunks that the ingestion step wrote."""

import json

from ..ingest.build import PROCESSED


def load_chunks(name="structural", open_only=False):
    """All chunks of a strategy: the committable file and, when present, the local-only one.
    open_only=True loads only the committed chunks (the laws), the corpus that CI can see."""
    files = {"structural": ("chunks.jsonl", "chunks_local.jsonl"),
             "fixed": ("chunks_fixed_local.jsonl",)}[name]
    if open_only:
        files = files[:1]
    chunks = []
    for file in files:
        path = PROCESSED / file
        if path.exists():
            chunks += [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    return chunks
