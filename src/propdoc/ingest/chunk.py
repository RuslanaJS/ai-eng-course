"""Chunking: structural chunks that follow the document, and a fixed-size baseline to compare.

Structural strategy: an article of a law, a table or a figure caption is one unit and is never cut
unless it is longer than MAX_TOKENS; paragraphs are packed up to TARGET_TOKENS and never cross a
section boundary. The fixed-size baseline ignores the structure and cuts every FIXED_CHARS characters.
"""

import re
from dataclasses import dataclass

from .clean import join_lines
from .model import CHARS_PER_TOKEN, Block, Chunk, approx_tokens

TARGET_TOKENS = 450
MAX_TOKENS = 700
MIN_TOKENS = 100
FIXED_CHARS = round(TARGET_TOKENS * CHARS_PER_TOKEN)  # the same size as the structural target
FIXED_OVERLAP = round(FIXED_CHARS * 0.15)
ABBREVIATIONS = ("kw", "r", "tys", "mln", "mld", "ok", "np", "ul", "poz", "art", "ust", "pkt", "zł",
                 "tj", "por", "nr", "al", "godz", "ww", "dz", "tzw", "szt", "wg", "m.in", "itp", "itd")
# a sentence ends at . ! ? followed by a capital letter, but not after an abbreviation like "kw."
SENTENCE_END = re.compile("".join(f"(?<!\\b{re.escape(a)}\\.)" for a in ABBREVIATIONS)
                          + r"(?<=[.!?])\s+(?=[A-ZĄĆĘŁŃÓŚŹŻ])")


def _sentences_within(text, limit):
    """Pieces of the text that are at most `limit` tokens: cut at sentence ends, then by length."""
    if approx_tokens(text) <= limit:
        return [text]
    pieces = []
    for sentence in SENTENCE_END.split(text):
        step = int(limit * CHARS_PER_TOKEN)
        pieces.extend(sentence[i:i + step] for i in range(0, len(sentence), step))
    return pieces


def _pack(pieces, target, joiner):
    groups, current, size = [], [], 0
    for piece in pieces:
        tokens = approx_tokens(piece)
        if current and size + tokens > target:
            groups.append(current)
            current, size = [], 0
        current.append(piece)
        size += tokens
    if current:
        groups.append(current)
    return [joiner.join(group) for group in groups]


def _split_block(block):
    """One chunk for a table, article or figure; several only when it is longer than MAX_TOKENS."""
    if approx_tokens(block.text) <= MAX_TOKENS:
        return [Chunk(block.text, block.section, block.label, block.page, block.page, block.kind)]
    lines = block.text.split("\n")
    if block.kind in ("table", "figure"):
        head = lines[0]  # the caption stays on top of every part
        rows = _pack(lines[1:], TARGET_TOKENS - approx_tokens(head), "\n")
        parts = [f"{head}\n{rows_text}" for rows_text in rows]
    else:
        pieces = [p for line in lines for p in _sentences_within(line, TARGET_TOKENS)]
        parts = _pack(pieces, TARGET_TOKENS, "\n")
    return [
        Chunk(part, block.section, f"{block.label} (part {i}/{len(parts)})".strip(), block.page,
              block.page, block.kind)
        for i, part in enumerate(parts, 1)
    ]


def _pack_paragraphs(buffer):
    pieces = []
    for block in buffer:
        for text in _sentences_within(block.text, TARGET_TOKENS):
            pieces.append((text, block))
    groups, current, size = [], [], 0
    for text, block in pieces:
        tokens = approx_tokens(text)
        if current and size + tokens > TARGET_TOKENS:
            groups.append(current)
            current, size = [], 0
        current.append((text, block))
        size += tokens
    if current:
        groups.append(current)
    if len(groups) > 1:  # a tiny last group joins the previous one when the result is not too long
        tail = sum(approx_tokens(t) for t, _ in groups[-1])
        previous = sum(approx_tokens(t) for t, _ in groups[-2])
        if tail < MIN_TOKENS and tail + previous <= MAX_TOKENS:
            last = groups.pop()
            groups[-1] = groups[-1] + last
    return [
        Chunk("\n".join(t for t, _ in g), g[0][1].section, "", g[0][1].page, g[-1][1].page)
        for g in groups
    ]


def structural_chunks(blocks):
    chunks, buffer = [], []

    def flush():
        nonlocal buffer
        chunks.extend(_pack_paragraphs(buffer))
        buffer = []

    for block in blocks:
        if block.kind == "figure" and approx_tokens(block.text) <= MAX_TOKENS:
            # a caption alone says little (title and source); it travels with the text around it
            block = Block(join_lines(block.text.split("\n")), block.section, "", block.page, "paragraph")
        if block.kind == "paragraph":
            if buffer and buffer[-1].section != block.section:
                flush()
            buffer.append(block)
        else:
            flush()
            chunks.extend(_split_block(block))
    flush()
    return chunks


@dataclass
class FixedInfo:
    mid_sentence: bool  # the chunk starts in the middle of a sentence
    sections: int  # how many sections the chunk touches


def fixed_chunks(blocks, size=FIXED_CHARS, overlap=FIXED_OVERLAP):
    """Fixed-size baseline over the concatenated text. Returns the chunks and the cut statistics."""
    text, spans = "", []
    for block in blocks:
        start = len(text)
        text += block.text + "\n\n"
        spans.append((start, start + len(block.text), block))
    chunks, infos, windows, pos = [], [], [], 0
    while pos < len(text):
        end = min(pos + size, len(text))
        windows.append((pos, end))
        piece = text[pos:end].strip()
        touched = [b for s, e, b in spans if s < end and e > pos]
        if piece and touched:
            pages = [b.page for b in touched if b.page is not None]
            chunks.append(Chunk(piece, touched[0].section, touched[0].label,
                                min(pages) if pages else None, max(pages) if pages else None,
                                "fixed"))
            starts_block = any(s == pos for s, _, _ in spans)
            infos.append(FixedInfo(
                mid_sentence=pos > 0 and not starts_block and text[pos - 1] not in ".!?:\n",
                sections=len({b.section for b in touched}),
            ))
        if end == len(text):
            break
        pos += size - overlap
    return chunks, infos, windows, spans


def compare_strategies(blocks):
    """Numbers for the README: structural against fixed-size chunking of the same document."""
    structural = structural_chunks(blocks)
    fixed, infos, windows, spans = fixed_chunks(blocks)

    def tokens(chunks):
        sizes = [approx_tokens(c.text) for c in chunks]
        return round(sum(sizes) / len(sizes)), max(sizes)

    units = [(s, e) for s, e, b in spans if b.kind in ("table", "article")]
    covered = sum(any(ws <= s and e <= we for ws, we in windows) for s, e in units)
    avg_s, max_s = tokens(structural)
    avg_f, max_f = tokens(fixed)
    return {
        "structural": {
            "chunks": len(structural), "avg_tokens": avg_s, "max_tokens": max_s,
            "mid_sentence_starts_pct": 0,
            "tables_and_articles_cut": sum(
                approx_tokens(b.text) > MAX_TOKENS for b in blocks if b.kind in ("table", "article")),
            "mixed_section_chunks_pct": 0,
        },
        "fixed": {
            "chunks": len(fixed), "avg_tokens": avg_f, "max_tokens": max_f,
            "mid_sentence_starts_pct": round(100 * sum(i.mid_sentence for i in infos) / len(infos)),
            "tables_and_articles_cut": len(units) - covered,
            "mixed_section_chunks_pct": round(100 * sum(i.sections > 1 for i in infos) / len(infos)),
        },
        "tables_and_articles": len(units),
    }
