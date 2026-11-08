"""Build the chunk files from the downloaded corpus documents.

python -m propdoc.ingest.build   (or: make ingest)
  data/processed/chunks.jsonl        chunks of documents whose text may be committed (commit_text = yes)
  data/processed/chunks_local.jsonl  chunks of all other documents, kept out of git
  data/processed/ingest_report.json  per-document counts, near-duplicate pairs, version statuses
  data/processed/audit.jsonl         what happened to every document and why
--strategy fixed writes only chunks_fixed_local.jsonl: the naive fixed-size baseline (no sections), for the
retrieval comparison.
One broken file does not stop the run: it gets the status "error" and the run exits with code 1.
"""

import argparse
import hashlib
import json
from collections import Counter
from datetime import date

from .chunk import fixed_chunks, structural_chunks
from .clean import mask_pii
from .dedup import (
    assign_status,
    drop_duplicate_chunks,
    duplicate_files,
    near_duplicates,
    text_hash,
)
from .fetch import MANIFEST, RAW_DIR, ROOT, read_manifest
from .loaders import load_law_html, load_law_pdf, load_report_pdf
from .model import Chunk, approx_tokens

PROCESSED = ROOT / "data" / "processed"
PIPELINE_VERSION = "ingest-v2"
NEAR_DUP_JACCARD = 0.8


def load_document(row, raw_dir):
    path = raw_dir / row["file"]
    if row["doc_type"] == "law" and row["format"] == "html":
        return load_law_html(path, row["id"])
    if row["doc_type"] == "law" and row["format"] == "pdf":
        return load_law_pdf(path, row["id"], row["title"])
    if row["format"] == "pdf":
        return load_report_pdf(path, row["id"], row["title"])
    return None


def split(blocks, strategy):
    if strategy == "structural":
        return structural_chunks(blocks)
    chunks = fixed_chunks(blocks)[0]  # the baseline knows nothing about sections or labels
    return [Chunk(c.text, "", "", c.page_start, c.page_end, c.kind) for c in chunks]


def dataset_version(rows):
    """One id for the exact inputs and the pipeline version: same inputs, same id (lineage)."""
    files = sorted((r["id"], r["sha256"]) for r in rows if r.get("sha256"))
    payload = json.dumps([PIPELINE_VERSION, files], sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def chunk_record(row, chunk, index, text, status, version):
    header = " | ".join(p for p in (row["title"], chunk.section, chunk.label) if p)
    return {
        "chunk_id": f"{row['id']}#{index}",
        "chunk_index": index,
        "doc_id": row["id"],
        "source": row["file"],
        "source_url": row["url"],
        "title": row["title"],
        "doc_type": row["doc_type"],
        "lang": row["lang"],
        "version": row["period_or_version"],
        "series": row.get("series", ""),
        "effective": row.get("effective", ""),
        "status": status,
        "access": ["public"],  # every document of this corpus is public
        "section": chunk.section,
        "label": chunk.label,
        "page_start": chunk.page_start,
        "page_end": chunk.page_end,
        "kind": chunk.kind,
        "n_tokens": approx_tokens(text),
        "doc_hash": row["sha256"],
        "chunk_hash": text_hash(text),
        "pipeline_version": PIPELINE_VERSION,
        "dataset_version": version,
        "text": text,
        "embed_text": f"{header}\n{text}",  # the header tells apart similar documents
    }


def write_jsonl(path, records):
    with open(path, "w", encoding="utf-8") as fh:
        fh.writelines(json.dumps(record, ensure_ascii=False) + "\n" for record in records)


def main(argv=None, manifest=MANIFEST, raw_dir=RAW_DIR, out_dir=PROCESSED):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ids", nargs="+", help="only these ids; nothing is written then")
    parser.add_argument("--strategy", choices=("structural", "fixed"), default="structural")
    parser.add_argument("--as-of", default=date.today().isoformat(),
                        help="date for the version status (current, superseded, upcoming, outdated)")
    args = parser.parse_args(argv)

    _, rows = read_manifest(manifest)
    version = dataset_version(rows)
    status = assign_status(rows, args.as_of)
    audit = []
    for row_id, same_as in duplicate_files(rows):
        audit.append({"event": "exact_duplicate", "id": row_id, "of": same_as})
        print(f"duplicate file: {row_id} is identical to {same_as}")

    committed, local, report, texts, failed = [], [], [], {}, 0
    for row in rows:
        if (args.ids and row["id"] not in args.ids) or not row["file"]:
            continue
        if not (raw_dir / row["file"]).is_file():
            continue
        try:
            document = load_document(row, raw_dir)
            if document is None:
                print(f"no loader for {row['id']} ({row['doc_type']}, {row['format']})")
                continue
            if document.status != "ok":
                audit.append({"event": document.status, "id": row["id"], "note": document.note})
                report.append({"id": row["id"], "title": row["title"], "status": document.status,
                               "note": document.note})
                print(f"{row['id']}  {document.status}: {document.note}")
                continue
            chunks, dropped = drop_duplicate_chunks(split(document.blocks, args.strategy))
            masked, records = 0, []
            for i, chunk in enumerate(chunks):
                text, n = mask_pii(chunk.text)
                masked += n
                records.append(chunk_record(row, chunk, i, text, status[row["id"]], version))
        except Exception as exc:  # noqa: BLE001  one broken file must not stop the batch
            failed += 1
            audit.append({"event": "error", "id": row["id"], "error": f"{type(exc).__name__}: {exc}"})
            report.append({"id": row["id"], "title": row["title"], "status": "error",
                           "note": f"{type(exc).__name__}: {exc}"})
            print(f"{row['id']}  ERROR {type(exc).__name__}: {exc}")
            continue
        texts[row["id"]] = "\n".join(r["text"] for r in records)
        (committed if row["commit_text"] == "yes" else local).extend(records)
        kinds = Counter(r["kind"] for r in records)
        tokens = sum(r["n_tokens"] for r in records)
        audit.append({"event": "ingested", "id": row["id"], "chunks": len(records),
                      "status": status[row["id"]], "duplicates_dropped": dropped,
                      "pii_masked": masked})
        report.append({"id": row["id"], "title": row["title"], "status": status[row["id"]],
                       "blocks": len(document.blocks), "chunks": len(records), "tokens": tokens,
                       "duplicates_dropped": dropped, "pii_masked": masked, "kinds": dict(kinds),
                       "commit_text": row["commit_text"]})
        print(f"{row['id']}  {status[row['id']]:<10} {len(document.blocks):>4} blocks  "
              f"{len(records):>4} chunks  {tokens:>7} tokens  {dropped} duplicates  {dict(kinds)}")

    pairs = near_duplicates(texts, NEAR_DUP_JACCARD)
    for first, second, score in pairs:
        decision = (f"kept both, statuses {status[first]} and {status[second]}: "
                    "old versions stay searchable and are filtered out by status")
        audit.append({"event": "near_duplicate", "ids": [first, second], "jaccard": score,
                      "decision": decision})
        print(f"near duplicate: {first} ~ {second} (jaccard {score}), {decision}")

    if args.strategy == "fixed":
        if not args.ids:
            out_dir.mkdir(parents=True, exist_ok=True)
            write_jsonl(out_dir / "chunks_fixed_local.jsonl", committed + local)
        return 1 if failed else 0
    hashes = Counter(r["chunk_hash"] for r in committed + local)
    shared = sum(n > 1 for n in hashes.values())
    print(f"total {len(committed) + len(local)} chunks; {shared} texts occur in more than one document")
    if args.ids:
        return 1 if failed else 0
    out_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(out_dir / "chunks.jsonl", committed)
    write_jsonl(out_dir / "chunks_local.jsonl", local)
    write_jsonl(out_dir / "audit.jsonl", audit)
    summary = {"pipeline_version": PIPELINE_VERSION, "dataset_version": version,
               "as_of": args.as_of, "chunks": len(committed) + len(local),
               "committed": len(committed), "local_only": len(local),
               "texts_shared_between_documents": shared,
               "near_duplicates": [list(p) for p in pairs], "documents": report}
    (out_dir / "ingest_report.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
