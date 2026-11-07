"""Deduplication by content hash: identical files and identical chunks inside one document.

Identical chunks in different documents are kept on purpose: different versions of a law or
different quarters of a report repeat text, and an answer must be able to cite the right version.
"""

import hashlib
import re

from .clean import normalize


def text_hash(text):
    """Hash of the text ignoring case and whitespace differences."""
    return hashlib.sha256(re.sub(r"\s+", " ", normalize(text)).lower().encode("utf-8")).hexdigest()


def duplicate_files(rows):
    """Manifest rows whose file is identical to an earlier row: [(id, same_as_id)]."""
    first, duplicates = {}, []
    for row in rows:
        digest = row.get("sha256")
        if not digest:
            continue
        if digest in first:
            duplicates.append((row["id"], first[digest]))
        else:
            first[digest] = row["id"]
    return duplicates


def drop_duplicate_chunks(chunks):
    """Keep the first of identical chunks inside one document. Returns (kept, dropped count)."""
    seen, kept = set(), []
    for chunk in chunks:
        digest = text_hash(chunk.text)
        if digest not in seen:
            seen.add(digest)
            kept.append(chunk)
    return kept, len(chunks) - len(kept)


def shingles(text, k=5):
    """Hashes of every run of k words: two versions of a text share most of them."""
    words = re.findall(r"\w+", text.casefold())
    return {hash(tuple(words[i:i + k])) for i in range(max(1, len(words) - k + 1))}


def jaccard(a, b):
    return len(a & b) / len(a | b) if a | b else 0.0


def near_duplicates(texts, threshold=0.8):
    """Pairs of documents whose 5-word shingles overlap above the threshold: [(id, id, score)]."""
    sets = {doc_id: shingles(text) for doc_id, text in texts.items()}
    ids = sorted(sets)
    pairs = []
    for i, first in enumerate(ids):
        for second in ids[i + 1:]:
            score = jaccard(sets[first], sets[second])
            if score >= threshold:
                pairs.append((first, second, round(score, 2)))
    return sorted(pairs, key=lambda p: -p[2])


def assign_status(rows, as_of):
    """Version status by series: the newest edition released by `as_of` is current, older ones
    are superseded, a later one is upcoming. A document without series or date is current."""
    series = {}
    for row in rows:
        if row.get("series") and row.get("effective"):
            series.setdefault(row["series"], []).append(row)
    status = {row["id"]: "current" for row in rows}
    for members in series.values():
        released = [r for r in members if r["effective"] <= as_of]
        newest = max(released, key=lambda r: r["effective"])["id"] if released else None
        for row in members:
            if row["effective"] > as_of:
                status[row["id"]] = "upcoming"
            elif row["id"] != newest:
                status[row["id"]] = "superseded"
    return status
