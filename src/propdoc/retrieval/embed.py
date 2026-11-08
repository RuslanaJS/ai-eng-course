"""Embeddings: a local model (bge-m3 through Ollama) and the Gemini API, cached on disk by text hash.

python -m propdoc.retrieval.embed --models bge-m3 gemini   embeds every chunk once (a re-run embeds nothing)
Vectors of different models are not compatible, so every model has its own cache file and its own index.
"""

import argparse
import hashlib
import json
import os
import time

import ollama
from dotenv import load_dotenv
from google import genai
from google.genai import errors, types

from ..ingest.fetch import ROOT
from .store import load_chunks

CACHE_DIR = ROOT / "data" / "cache" / "embeddings"
GEMINI_BATCH = 100  # contents per request, every chunk counts as one request for the quota
OLLAMA_BATCH = 16
SAVE_EVERY = 200  # texts embedded between two saves of the cache


class OllamaEmbedder:
    """bge-m3: 1024 dimensions, 8K tokens of context, no prefixes for queries or documents."""

    def __init__(self, model="bge-m3"):
        self.name, self.dim, self.model = model, 1024, model

    def embed_documents(self, chunks):
        return self._embed([c["embed_text"] for c in chunks])

    def embed_query(self, text):
        return self._embed([text])[0]

    def _embed(self, texts):
        vectors = []
        for i in range(0, len(texts), OLLAMA_BATCH):
            vectors += ollama.embed(model=self.model, input=texts[i:i + OLLAMA_BATCH])["embeddings"]
        return [list(v) for v in vectors]


class GeminiEmbedder:
    """gemini-embedding-2: no task_type, the task is a text prefix (see the Gemini embeddings docs).
    Each text goes in its own Content, otherwise a list is merged into a single vector."""

    def __init__(self, model="gemini-embedding-2", dim=768):
        load_dotenv(ROOT / ".env")
        self.client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        self.model, self.dim, self.name = model, dim, f"gemini-{dim}"
        self.config = types.EmbedContentConfig(output_dimensionality=dim)

    def embed_documents(self, chunks):
        # the header of embed_text already holds the title, so the title field says none
        return self._embed([f"title: none | text: {c['embed_text']}" for c in chunks])

    def embed_query(self, text):
        return self._embed([f"task: search result | query: {text}"])[0]

    def _embed(self, texts):
        vectors = []
        for i in range(0, len(texts), GEMINI_BATCH):
            batch = texts[i:i + GEMINI_BATCH]
            vectors += self._request(batch)
        return vectors

    def _request(self, batch):
        contents = [types.Content(parts=[types.Part(text=t)]) for t in batch]
        for attempt in range(6):
            try:
                response = self.client.models.embed_content(model=self.model, contents=contents,
                                                            config=self.config)
                vectors = [list(e.values) for e in response.embeddings]
                if len(vectors) != len(batch):
                    raise RuntimeError(f"asked for {len(batch)} vectors, got {len(vectors)}")
                return vectors
            except errors.APIError as exc:
                if exc.code not in (429, 500, 503) or attempt == 5:
                    raise
                time.sleep(2 ** attempt * 2)  # back off and try again


def make_embedder(name):
    return {"bge-m3": OllamaEmbedder, "gemini": GeminiEmbedder}[name]()


def cache_key(embedder, kind, text):
    return hashlib.sha256(f"{embedder.name}|{kind}|{text}".encode()).hexdigest()


def cached(embedder, kind, texts, embed, cache_dir=CACHE_DIR):
    """Vectors for the texts: from the cache when the text was embedded before. Returns (vectors, new)."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{embedder.name}.jsonl"
    store = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            store[row["k"]] = row["v"]
    keys = [cache_key(embedder, kind, t) for t in texts]
    missing = [i for i, k in enumerate(keys) if k not in store]
    for start in range(0, len(missing), SAVE_EVERY):  # saved piece by piece: a failure keeps the progress
        part = missing[start:start + SAVE_EVERY]
        fresh = embed([texts[i] for i in part])
        with open(path, "a", encoding="utf-8") as fh:
            for i, vector in zip(part, fresh, strict=True):
                store[keys[i]] = [round(x, 6) for x in vector]
                fh.write(json.dumps({"k": keys[i], "v": store[keys[i]]}) + "\n")
    return [store[k] for k in keys], len(missing)


def document_vectors(embedder, chunks, cache_dir=CACHE_DIR):
    """Vectors of the chunks, in order. The cache key is the text that is really embedded."""
    texts = [c["embed_text"] for c in chunks]
    by_text = dict(zip(texts, chunks, strict=True))
    return cached(embedder, "doc", texts,
                  lambda missing: embedder.embed_documents([by_text[t] for t in missing]), cache_dir)


def query_vector(embedder, text, cache_dir=CACHE_DIR):
    vectors, _ = cached(embedder, "query", [text], lambda t: [embedder.embed_query(t[0])], cache_dir)
    return vectors[0]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", nargs="+", default=["bge-m3", "gemini"])
    parser.add_argument("--strategy", default="structural")
    args = parser.parse_args(argv)
    chunks = load_chunks(args.strategy)
    for name in args.models:
        embedder = make_embedder(name)
        started = time.time()
        vectors, new = document_vectors(embedder, chunks)
        print(f"{embedder.name}: {len(vectors)} chunks, embedded now {new}, "
              f"{time.time() - started:.0f}s, dimension {len(vectors[0])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
