"""Search over the chunks: vector (Qdrant in memory), BM25, hybrid with RRF, and a reranker.

python -m propdoc.retrieval.search "Czy cudzoziemiec potrzebuje zezwolenia?" --config hybrid+rerank
Filters on metadata are applied inside every search, not after it.
"""

import argparse
import re
import time

import numpy as np
from fastembed.rerank.cross_encoder import TextCrossEncoder
from qdrant_client import QdrantClient, models
from rank_bm25 import BM25Okapi

from ..ingest.fetch import ROOT
from .embed import CACHE_DIR, document_vectors, make_embedder, query_vector
from .store import load_chunks

K = 5  # results that are evaluated and passed on
CANDIDATES = 10  # hybrid candidates that the reranker reads: 10 beat 20 on MRR and take half the time
RRF_K = 60
RERANK_MODEL = "BAAI/bge-reranker-v2-m3-int8"  # multilingual, 0.57 GB
STEM = 6  # BM25 variant: cut every word to its first 6 letters, a cheap stand-in for Polish stemming
DEFAULT_FILTER = {"status": ["current", "upcoming"]}  # superseded versions only on request
LIST_FIELDS = ("status", "doc_type", "lang", "series", "doc_id")  # filters: field -> allowed values


def matches(chunk, filters):
    """The same rules as the Qdrant filter, for the searches that run in plain Python."""
    if not filters:
        return True
    for field in LIST_FIELDS:
        allowed = filters.get(field)
        if allowed and chunk[field] not in allowed:
            return False
    if filters.get("effective_from") and chunk["effective"] < filters["effective_from"]:
        return False
    if filters.get("effective_to") and chunk["effective"] > filters["effective_to"]:
        return False
    wanted = filters.get("access")
    return not wanted or bool(set(chunk["access"]) & set(wanted))


def qdrant_filter(filters):
    if not filters:
        return None
    must = [models.FieldCondition(key=f, match=models.MatchAny(any=list(filters[f])))
            for f in LIST_FIELDS if filters.get(f)]
    if filters.get("access"):
        must.append(models.FieldCondition(key="access", match=models.MatchAny(any=list(filters["access"]))))
    if filters.get("effective_from") or filters.get("effective_to"):
        must.append(models.FieldCondition(key="effective_int", range=models.Range(
            gte=to_int(filters.get("effective_from")), lte=to_int(filters.get("effective_to")))))
    return models.Filter(must=must) if must else None


def to_int(day):
    return int(day.replace("-", "")) if day else None


def effective_int(chunk):
    return to_int(chunk["effective"]) or 0


class VectorIndex:
    def __init__(self, chunks, embedder, cache_dir=CACHE_DIR):
        self.chunks, self.embedder, self.cache_dir = chunks, embedder, cache_dir
        vectors, _ = document_vectors(embedder, chunks, cache_dir)
        self.client = QdrantClient(":memory:")
        self.client.create_collection("chunks", vectors_config=models.VectorParams(
            size=embedder.dim, distance=models.Distance.COSINE))
        points = [models.PointStruct(id=i, vector=v, payload={"i": i, "effective_int": effective_int(c), **c})
                  for i, (c, v) in enumerate(zip(chunks, vectors, strict=True))]
        for i in range(0, len(points), 500):
            self.client.upsert("chunks", points[i:i + 500])

    def search(self, query, filters=None, k=K):
        hits = self.client.query_points("chunks", query=query_vector(self.embedder, query, self.cache_dir), limit=k,
                                        query_filter=qdrant_filter(filters)).points
        return [{**self.chunks[h.payload["i"]], "score": float(h.score)} for h in hits]


def tokenize(text, stem=0):
    words = re.findall(r"\w+", text.lower())
    return [w[:stem] for w in words] if stem else words


class BM25Index:
    def __init__(self, chunks, stem=0):
        self.chunks, self.stem = chunks, stem
        self.bm25 = BM25Okapi([tokenize(c["embed_text"], stem) for c in chunks])

    def search(self, query, filters=None, k=K):
        scores = self.bm25.get_scores(tokenize(query, self.stem))
        out = []
        for i in np.argsort(-scores):
            if scores[i] <= 0 or len(out) == k:
                break
            if matches(self.chunks[i], filters):
                out.append({**self.chunks[i], "score": float(scores[i])})
        return out


def rrf(rankings, k=K):
    """Reciprocal Rank Fusion: the scores of the searches are not comparable, the ranks are."""
    fused, by_id = {}, {}
    for ranking in rankings:
        for rank, chunk in enumerate(ranking, 1):
            by_id[chunk["chunk_id"]] = chunk
            fused[chunk["chunk_id"]] = fused.get(chunk["chunk_id"], 0.0) + 1.0 / (RRF_K + rank)
    best = sorted(fused, key=lambda cid: -fused[cid])[:k]
    return [{**by_id[cid], "score": fused[cid]} for cid in best]


class Reranker:
    """A cross-encoder reads the query and each candidate together: slower, but a finer order."""

    def __init__(self):
        self.model = TextCrossEncoder(RERANK_MODEL, cache_dir=str(ROOT / "data" / "cache" / "models"))

    def rerank(self, query, candidates, k=K):
        if not candidates:
            return []
        scores = list(self.model.rerank(query, [c["embed_text"] for c in candidates]))
        order = sorted(range(len(candidates)), key=lambda i: -scores[i])[:k]
        return [{**candidates[i], "score": float(scores[i])} for i in order]


def make_configs(chunks, embedder_names=("bge-m3", "gemini"), rerank=True):
    """Name -> function(query, filters) for every search configuration that we compare."""
    bm25, bm25_stem = BM25Index(chunks), BM25Index(chunks, STEM)
    configs = {"bm25": lambda q, f=None: bm25.search(q, f), f"bm25-stem{STEM}": lambda q, f=None: bm25_stem.search(q, f)}
    reranker = Reranker() if rerank else None
    for name in embedder_names:
        vector = VectorIndex(chunks, make_embedder(name))

        def hybrid(q, f=None, vector=vector):
            return rrf([vector.search(q, f, CANDIDATES), bm25_stem.search(q, f, CANDIDATES)], CANDIDATES)

        configs[f"vector[{name}]"] = lambda q, f=None, vector=vector: vector.search(q, f)
        configs[f"hybrid[{name}]"] = lambda q, f=None, hybrid=hybrid: hybrid(q, f)[:K]
        if reranker:
            configs[f"hybrid+rerank[{name}]"] = (
                lambda q, f=None, hybrid=hybrid: reranker.rerank(q, hybrid(q, f)))
    return configs


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query")
    parser.add_argument("--config", default="hybrid+rerank[gemini]")
    parser.add_argument("--status", nargs="*", help="only these version statuses, e.g. current upcoming")
    parser.add_argument("--doc-type", nargs="*")
    parser.add_argument("--lang", nargs="*")
    args = parser.parse_args(argv)
    filters = {"status": args.status, "doc_type": args.doc_type, "lang": args.lang}
    configs = make_configs(load_chunks())
    started = time.time()
    for hit in configs[args.config](args.query, filters):
        print(f"{hit['score']:8.4f}  {hit['chunk_id']:<10} {hit['status']:<10} "
              f"{hit['title'][:44]:<44} {hit['section'][:24]} {hit['label']}")
    print(f"{time.time() - started:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
