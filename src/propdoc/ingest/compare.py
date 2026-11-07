"""Compare structural and fixed-size chunking on a few documents (numbers for the README).

python -m propdoc.ingest.compare   writes data/processed/chunking_comparison.json
"""

import json

from .build import PROCESSED, load_document
from .chunk import compare_strategies
from .fetch import MANIFEST, RAW_DIR, read_manifest

SAMPLE = ["D001", "D007", "D009", "D018", "D019"]  # a law as HTML and as PDF, three reports
ROWS = [
    ("chunks", "chunks"),
    ("avg_tokens", "avg tokens"),
    ("max_tokens", "max tokens"),
    ("mid_sentence_starts_pct", "start mid-sentence, %"),
    ("tables_and_articles_cut", "tables and articles cut"),
    ("mixed_section_chunks_pct", "mix several sections, %"),
]


def main(argv=None, manifest=MANIFEST, raw_dir=RAW_DIR, out=PROCESSED / "chunking_comparison.json"):
    _, rows = read_manifest(manifest)
    result = {}
    for row in rows:
        if row["id"] not in SAMPLE or not row["file"] or not (raw_dir / row["file"]).is_file():
            continue
        stats = compare_strategies(load_document(row, raw_dir).blocks)
        result[row["id"]] = {"title": row["title"], **stats}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    print("| document | metric | structural | fixed-size |\n|---|---|---|---|")
    for doc_id, stats in result.items():
        units = stats["tables_and_articles"]
        for key, name in ROWS:
            label = f"{doc_id} ({units} tables and articles)" if key == "chunks" else ""
            print(f"| {label} | {name} | {stats['structural'][key]} | {stats['fixed'][key]} |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
