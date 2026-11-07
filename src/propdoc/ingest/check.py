"""Check the built chunks against rules that the real corpus must satisfy (like check.py of lesson 6).

python -m propdoc.ingest.check   (or: make check-ingest)
Reads chunks.jsonl and, when it exists, chunks_local.jsonl. Exit code 1 if any rule fails.
"""

import json
import re
import sys
from collections import Counter, defaultdict

from .build import PROCESSED
from .chunk import MAX_TOKENS
from .clean import EMAIL, ZERO_WIDTH

REQUIRED = ["chunk_id", "chunk_index", "doc_id", "source", "source_url", "title", "doc_type", "lang",
            "version", "series", "effective", "status", "access", "section", "label", "page_start",
            "page_end", "kind", "n_tokens", "doc_hash", "chunk_hash", "pipeline_version",
            "dataset_version", "text", "embed_text"]
FORBIDDEN = {
    "invisible characters": re.compile(ZERO_WIDTH.pattern[:-1] + "\r]"),
    "ligatures": re.compile("[ﬀ-ﬆ]"),
    "firewall page": re.compile("Request Rejected"),
    "page number on its own line": re.compile(r"(?m)^\d{1,3}$"),
    "e-mail address": EMAIL,
}
MUST_CONTAIN = {  # a few sentences that prove the right text arrived, per document
    "D001": ["Nabycie nieruchomości przez cudzoziemca wymaga zezwolenia"],
    "D007": ["Ustawa wchodzi w życie"],
    "D009": ["Tabela 2", "Warszawa 1,9%"],
}
STATUSES = {"current", "superseded", "upcoming"}
SIZE_SLACK = 60  # tokens above MAX_TOKENS tolerated by the approximate counter
REAL_TOKEN_LIMIT = 1100


def is_chart_residue(line):
    """Axis labels and rotated chart text: a long line without any word, or letters spread apart."""
    tokens = line.split()
    spread = len(tokens) >= 4 and sum(len(t) for t in tokens) / len(tokens) < 1.7
    return spread or (len(line) > 12 and not re.search(r"[^\W\d_]{2,}", line))


def load():
    records = []
    for name in ("chunks.jsonl", "chunks_local.jsonl"):
        path = PROCESSED / name
        if path.exists():
            records += [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    return records


def real_token_counts(records):
    try:
        import tiktoken
        encoding = tiktoken.get_encoding("cl100k_base")
    except (ImportError, OSError):  # not installed, or no network for the vocabulary file
        return None
    return [len(encoding.encode(r["text"])) for r in records]


def run_checks(records):
    """Returns a list of (rule, problem or None)."""
    results = []

    def rule(name, problems):
        results.append((name, "; ".join(problems[:3]) + (f" (+{len(problems) - 3} more)" if len(problems) > 3 else "")
                        if problems else None))

    rule("every chunk has all fields and a text", [
        r.get("chunk_id", "?") for r in records
        if any(f not in r for f in REQUIRED) or not r.get("text", "").strip()])
    ids = Counter(r["chunk_id"] for r in records)
    rule("chunk ids are unique", [i for i, n in ids.items() if n > 1])
    rule(f"no chunk is longer than {MAX_TOKENS + SIZE_SLACK} tokens (approximate)", [
        f"{r['chunk_id']} ({r['n_tokens']})" for r in records if r["n_tokens"] > MAX_TOKENS + SIZE_SLACK])
    for name, pattern in FORBIDDEN.items():
        rule(f"no {name}", [r["chunk_id"] for r in records if pattern.search(r["text"])])

    by_doc = defaultdict(list)
    for r in records:
        by_doc[r["doc_id"]].append(r)
    leaks = []
    for doc_id, chunks in by_doc.items():
        counts = Counter(line.strip() for c in chunks for line in set(c["text"].split("\n")) if len(line.strip()) >= 12)
        for line, n in counts.items():
            if len(chunks) >= 8 and n >= max(5, 0.3 * len(chunks)):
                leaks.append(f"{doc_id}: {line[:50]!r} in {n} chunks")
    rule("no header or footer repeats across the chunks of a document", leaks)
    rule("no chart residue outside tables", [
        f"{r['chunk_id']}: {line[:40]!r}" for r in records if r["kind"] in ("paragraph", "article")
        for line in r["text"].split("\n") if is_chart_residue(line)])

    present = defaultdict(str)
    for r in records:
        present[r["doc_id"]] += r["text"] + "\n"
    for doc_id, phrases in MUST_CONTAIN.items():
        if doc_id in present:
            rule(f"{doc_id} contains the expected text", [p for p in phrases if p not in present[doc_id]])

    rule("statuses are valid", sorted({r["status"] for r in records} - STATUSES))
    current = defaultdict(set)
    for r in records:
        if r["series"] and r["status"] == "current":
            current[r["series"]].add(r["doc_id"])
    rule("at most one current document per series", [f"{s}: {sorted(d)}" for s, d in current.items() if len(d) > 1])
    return results


def main():
    records = load()
    if not records:
        print("no chunks found: run make ingest first")
        return 1
    results = run_checks(records)
    for name, problem in results:
        print(f"{'OK  ' if problem is None else 'FAIL'} {name}" + (f": {problem}" if problem else ""))
    counts = real_token_counts(records)
    if counts is None:
        print("SKIP real token counts (tiktoken is not available)")
    else:
        ordered = sorted(counts)
        over = sum(c > 800 for c in counts)
        print(f"INFO real tokens per chunk (cl100k_base): median {ordered[len(ordered) // 2]}, "
              f"p95 {ordered[int(len(ordered) * 0.95)]}, max {ordered[-1]}, over 800: {over}")
        if ordered[-1] > REAL_TOKEN_LIMIT:
            results.append(("real size", f"a chunk has {ordered[-1]} tokens"))
            print(f"FAIL no chunk is longer than {REAL_TOKEN_LIMIT} real tokens")
    failed = [name for name, problem in results if problem]
    print(f"{len(records)} chunks checked, {len(failed)} rules failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
