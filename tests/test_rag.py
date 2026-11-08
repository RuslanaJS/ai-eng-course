"""Tests for embeddings cache, search, filters, fusion and evaluation on tiny synthetic data."""

from propdoc.evaluation.retrieval import evaluate, is_relevant, question_filters
from propdoc.retrieval import embed
from propdoc.retrieval.search import BM25Index, VectorIndex, matches, rrf, tokenize


class FakeEmbedder:
    """Three topics become three dimensions, so that nearest chunks are easy to predict."""

    name, dim = "fake", 3

    def __init__(self):
        self.embedded = 0

    def _vector(self, text):
        t = text.lower()
        return [float(w in t) + 0.01 for w in ("alfa", "beta", "gamma")]

    def embed_documents(self, chunks):
        self.embedded += len(chunks)
        return [self._vector(c["embed_text"]) for c in chunks]

    def embed_query(self, text):
        self.embedded += 1
        return self._vector(text)


def chunk(index, text, status="current", doc="D1", effective="2020-01-01", lang="pl"):
    return {"chunk_id": f"{doc}#{index}", "doc_id": doc, "status": status, "doc_type": "law",
            "lang": lang, "series": "act", "effective": effective, "access": ["public"],
            "title": "T", "section": "", "label": f"Art. {index}", "text": text,
            "embed_text": f"T\n{text}"}


FILLER = [chunk(10 + i, f"temat{i} zwykła treść") for i in range(6)]  # BM25 needs a larger corpus
CHUNKS = [
    chunk(0, "alfa opis nowej zasady"),
    chunk(1, "alfa opis starej zasady", status="superseded", doc="D2", effective="2015-01-01"),
    chunk(2, "beta mieszkania w Warszawie", doc="D3", effective="2024-06-30", lang="en"),
    chunk(3, "gamma zupełnie inny temat", doc="D3", effective="2024-06-30"),
]


def test_cache_embeds_each_text_once(tmp_path):
    embedder = FakeEmbedder()
    _, new = embed.document_vectors(embedder, CHUNKS, tmp_path)
    assert new == 4 and embedder.embedded == 4
    _, new = embed.document_vectors(embedder, CHUNKS, tmp_path)
    assert new == 0 and embedder.embedded == 4  # the second run embeds nothing
    assert embed.query_vector(embedder, "alfa", tmp_path) == embed.query_vector(embedder, "alfa", tmp_path)
    assert embedder.embedded == 5  # the query was embedded once


def test_cache_keeps_progress_when_a_batch_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(embed, "SAVE_EVERY", 2)

    class Failing(FakeEmbedder):
        def embed_documents(self, chunks):
            if self.embedded >= 2:
                raise RuntimeError("quota")
            return super().embed_documents(chunks)

    try:
        embed.document_vectors(Failing(), CHUNKS, tmp_path)
    except RuntimeError:
        pass
    embedder = FakeEmbedder()
    _, new = embed.document_vectors(embedder, CHUNKS, tmp_path)
    assert new == 2  # the first two were saved before the failure


def test_filters_work_inside_vector_and_bm25_search(tmp_path):
    index = VectorIndex(CHUNKS, FakeEmbedder(), tmp_path)
    bm25 = BM25Index(CHUNKS + FILLER)
    everything = [h["chunk_id"] for h in index.search("alfa", None, 2)]
    assert set(everything) == {"D1#0", "D2#1"}
    current = {"status": ["current", "upcoming"]}
    assert index.search("alfa", current, 2)[0]["chunk_id"] == "D1#0"
    assert "D2#1" not in [h["chunk_id"] for h in index.search("alfa", current, 4)]
    assert [h["chunk_id"] for h in bm25.search("alfa", current, 4)] == ["D1#0"]
    assert [h["chunk_id"] for h in index.search("beta", {"lang": ["en"]}, 4)] == ["D3#2"]
    dated = {"effective_from": "2024-01-01"}
    found = index.search("alfa", dated, 4)
    assert {h["chunk_id"] for h in found} == {"D3#2", "D3#3"}  # only the 2024 document is that new
    assert all(matches(h, dated) for h in found)
    assert not any(matches(c, dated) for c in CHUNKS if c["doc_id"] in ("D1", "D2"))


def test_bm25_with_stemming_matches_polish_word_forms():
    assert tokenize("Mieszkania w Warszawie", 6) == ["mieszk", "w", "warsza"]
    chunks = [chunk(0, "ceny mieszkań rosną")] + FILLER
    stemmed = BM25Index(chunks, stem=6)
    assert [h["chunk_id"] for h in stemmed.search("mieszkania", None, 2)] == ["D1#0"]
    assert BM25Index(chunks).search("mieszkania", None, 2) == []


def test_rrf_puts_a_chunk_found_by_both_searches_first():
    a = [{"chunk_id": "x"}, {"chunk_id": "y"}]
    b = [{"chunk_id": "z"}, {"chunk_id": "y"}]
    fused = rrf([a, b], 3)
    assert fused[0]["chunk_id"] == "y" and len(fused) == 3


def test_evaluation_counts_recall_and_mrr_by_document_and_quote():
    questions = [
        {"id": "a", "question": "q1", "docs": ["D1"], "quotes": ["Opis  NOWEJ zasady"], "history": False},
        {"id": "b", "question": "q2", "docs": ["D1"], "quotes": ["nie ma", "temat1 zwykła"], "history": False},
        {"id": "c", "question": "q3", "docs": ["D3"], "quotes": ["mieszkania"], "history": True},
    ]
    assert is_relevant(CHUNKS[0], questions[0]) and not is_relevant(CHUNKS[1], questions[0])

    def search(query, filters):
        seen.append((query, filters))
        return {"q1": [CHUNKS[2], CHUNKS[0]], "q2": CHUNKS, "q3": [CHUNKS[2]]}[query]

    seen = []
    result = evaluate(search, questions, k=5)
    assert result["ranks"] == {"a": 2, "b": None, "c": 1}
    assert round(result["recall"], 2) == 0.67 and round(result["mrr"], 2) == 0.5
    assert result["misses"] == ["b"]
    assert seen[0][1] == {"status": ["current", "upcoming"]} and seen[2][1] is None  # history: no filter


def test_a_question_can_have_several_right_passages_and_its_own_filters():
    question = {"docs": ["D1", "D3"], "quotes": ["alfa opis nowej", "beta mieszkania"], "history": False}
    assert is_relevant(CHUNKS[0], question) and is_relevant(CHUNKS[2], question)
    assert not is_relevant(CHUNKS[3], question) and not is_relevant(CHUNKS[1], question)
    assert question_filters(question) == {"status": ["current", "upcoming"]}
    old = {**question, "history": True, "filters": {"effective_from": "2025-10-01"}}
    assert question_filters(old) == {"effective_from": "2025-10-01"}  # history drops the status filter
    both = {**question, "filters": {"lang": ["en"]}}
    assert question_filters(both) == {"status": ["current", "upcoming"], "lang": ["en"]}
