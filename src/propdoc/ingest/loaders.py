"""Loaders: turn a law (HTML or PDF) or a report (PDF) into a Document made of blocks."""

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from statistics import median

import pdfplumber
from bs4 import BeautifulSoup

from .clean import (
    is_noise,
    join_legal_lines,
    join_lines,
    line_key,
    normalize,
    repeated_line_keys,
)
from .model import Block, Document

CAPTION_WORDS = "Wykres|Tabela|Rysunek|Mapa|Schemat|Chart|Table|Figure|Map"
CAPTION = re.compile(rf"^({CAPTION_WORDS})\s+\d+", re.IGNORECASE)
CAPTION_ANYWHERE = re.compile(rf"\b({CAPTION_WORDS})\s+\d+", re.IGNORECASE)
SOURCE = re.compile(r"^(Źródło|Source)\b", re.IGNORECASE)
NOTE = re.compile(r"^(Uwaga|Uwagi|Note|Notes)\b", re.IGNORECASE)
HEADING = re.compile(r"^\d+(\.\d+)*\.?\s+[A-ZĄĆĘŁŃÓŚŹŻ]")
BULLET = re.compile(r"^([▪•]|o(?=\s+[A-ZĄĆĘŁŃÓŚŹŻ])|[-–](?=\s))\s*")
ARTICLE = re.compile(r"^Art\.\s*(\d+[a-z]*)\.")
CHAPTER = re.compile(r"^(Dział|Rozdział|Oddział)\s+[IVXLC\d]+")
ANNEX = re.compile(r"^(ZAŁĄCZNIK|Załącznik|WZÓR)\b")
FOOTNOTE_REF = re.compile(r"(?<=[^\W\d_])\d{1,3}\)")  # "ogłoszenia29)" -> "ogłoszenia"
UNIT_LABEL = re.compile(r"^(Art\.\s*\d+[a-z]*\.|\d+[a-z]*[.)]|[a-z]\))$")
MAX_CAPTURE_LINES = 40  # a caption without a source line must not swallow the document
MIN_FONT_SIZE = 6.5  # points; text below it is chart internals (measured on the NBP reports)
MIN_CHARS_PER_PAGE = 50  # a PDF with less text per page has no usable text layer: a scan


@dataclass
class Line:
    text: str
    page: int
    bold: bool = False
    size: float = 0.0  # median font size of the line, 0 when unknown


# --- laws published as HTML (ELI) ---


def article_text(lines):
    """Paragraphs of an article: a new paragraph starts at every label line (Art., ust., pkt)."""
    paragraphs = []
    for line in lines:
        starts_new = UNIT_LABEL.match(line) or not paragraphs
        if len(paragraphs) == 1 and ARTICLE.match(paragraphs[0][0]) and len(paragraphs[0]) == 1:
            starts_new = False  # "Art. 5." stays on the line of the first paragraph
        if starts_new:
            paragraphs.append([line])
        else:
            paragraphs[-1].append(line)
    return "\n".join(join_lines(p) for p in paragraphs)


def load_law_html(path, doc_id):
    soup = BeautifulSoup(Path(path).read_text(encoding="utf-8"), "html.parser")
    for tag in soup.select("span.tooltip-text, span.xHidden, a.gloss-link sup"):  # notes, refs
        tag.decompose()
    h1 = soup.find("h1")
    title = normalize(h1.get_text(" ", strip=True)) if h1 else doc_id
    part = chapter = ""
    blocks = []
    for el in soup.find_all(["h2", "h3", "div"]):
        classes = el.get("class") or []
        if el.name == "h2" and "part" in classes:
            part, chapter = normalize(el.get_text(" ", strip=True)), ""
        elif el.name == "h3":
            head = normalize(el.get_text(" ", strip=True))
            if CHAPTER.match(head):
                chapter = head
        elif "unit_arti" in classes and not el.find_parent("div", class_="unit_arti"):
            if part.startswith("Treść obwieszczenia"):  # the announcement, not the law itself
                continue
            lines = [normalize(s) for s in el.get_text("\n").split("\n")]
            lines = [s for s in lines if s]
            match = ARTICLE.match(lines[0]) if lines else None
            if match:
                blocks.append(Block(article_text(lines), chapter, f"Art. {match.group(1)}",
                                    None, "article"))
    return Document(doc_id, title, blocks)


# --- PDF ---


def _visible(obj):
    """Drops rotated text and tiny glyphs: chart bars drawn as letters and overlapping axis labels."""
    if obj.get("object_type") != "char":
        return True
    return obj.get("upright", True) and obj["size"] >= MIN_FONT_SIZE


def _footnote_rule_top(page):
    """Height of the short thin rule that separates the footnotes from the text, if the page has one."""
    tops = [r["top"] for r in page.rects
            if r["height"] < 1.0 and 100 <= r["x1"] - r["x0"] <= 200 and r["x0"] < 100
            and r["top"] > page.height * 0.5]
    return min(tops) if tops else None


def _lines_of(page, number, keep_footnotes=True):
    out = []
    cut = None if keep_footnotes else _footnote_rule_top(page)
    for line in page.filter(_visible).extract_text_lines(x_tolerance=4, return_chars=True):
        if cut is not None and line["top"] >= cut:
            continue
        chars = [c for c in line["chars"] if not c["text"].isspace()]
        bold = bool(chars) and all("bold" in c["fontname"].lower() for c in chars)
        size = median(c["size"] for c in chars) if chars else 0.0
        out.append(Line(normalize(line["text"]), number, bold, size))
    return out


def pdf_lines(path, keep_footnotes=True):
    """Text lines of every page. Pages with two captions side by side are read column by column."""
    pages = []
    with pdfplumber.open(path) as pdf:
        for number, page in enumerate(pdf.pages, 1):
            lines = _lines_of(page, number, keep_footnotes)
            if any(len(CAPTION_ANYWHERE.findall(line.text)) >= 2 for line in lines):
                half = page.width / 2
                left = page.crop((0, 0, half, page.height))
                right = page.crop((half, 0, page.width, page.height))
                lines = _lines_of(left, number) + _lines_of(right, number)
            pages.append(lines)
    return pages


def drop_page_furniture(pages):
    """Remove running headers, footers and page numbers."""
    repeated = repeated_line_keys([[line.text for line in page] for page in pages])
    return [
        [ln for ln in page if ln.text and line_key(ln.text) not in repeated
         and not re.fullmatch(r"\d{1,3}|\d{4}-\d{2}-\d{2}", ln.text)]
        for page in pages
    ]


def report_blocks(pages):
    """Paragraphs, tables and figure captions of a report, each with its numbered section."""
    blocks, section, para, para_page, capture = [], "", [], None, None

    def flush_para():
        nonlocal para, para_page
        if para:
            blocks.append(Block(join_lines(para), section, "", para_page, "paragraph"))
        para, para_page = [], None

    def close_capture():
        nonlocal capture
        if capture:
            blocks.append(Block("\n".join(capture["lines"]), section, capture["label"],
                                capture["page"], capture["kind"]))
        capture = None

    for page in pages:
        for line in page:
            text = line.text
            if capture:
                if capture["tail"]:  # after the source line only notes may follow
                    wrapped_note = capture["note"] and text[:1].islower() and not CAPTION.match(text)
                    if NOTE.match(text) or wrapped_note:
                        capture["lines"].append(text)
                        capture["note"] = True
                        continue
                    close_capture()
                else:
                    if capture["kind"] == "figure" and is_noise(text):
                        continue
                    capture["lines"].append(text)
                    capture["tail"] = bool(SOURCE.match(text))
                    if len(capture["lines"]) > MAX_CAPTURE_LINES:
                        close_capture()
                    continue
            if line.bold and HEADING.match(text) and len(text) < 160:
                flush_para()
                section = text
                continue
            match = CAPTION.match(text)
            if match:
                flush_para()
                kind = "table" if match.group(1).lower() in ("tabela", "table") else "figure"
                capture = {"kind": kind, "label": match.group(0), "lines": [text],
                           "page": line.page, "tail": False, "note": False}
                continue
            if is_noise(text):
                continue
            if BULLET.match(text):
                flush_para()
                text = "- " + BULLET.sub("", text, count=1)
            if not para:
                para_page = line.page
            para.append(text)
    close_capture()
    flush_para()
    return blocks


def law_pdf_blocks(pages):
    """Articles of a law published as PDF, with the chapter heading as the section.

    Footnotes (smaller font), footnote numbers glued to words and the annexes (forms) are left out.
    """
    sizes = Counter()
    for page in pages:
        for line in page:
            sizes[round(line.size, 1)] += len(line.text)
    body = sizes.most_common(1)[0][0] if sizes else 0.0
    blocks, chapter, article, lines, page_no = [], "", None, [], None

    def flush():
        if article:
            blocks.append(Block(join_legal_lines(lines), chapter, f"Art. {article}", page_no,
                                "article"))

    for page in pages:
        for line in page:
            if line.size and line.size < body - 0.5:
                continue  # a footnote, in case the page has no footnote rule
            text = FOOTNOTE_REF.sub("", line.text)
            match = ARTICLE.match(text)
            if ANNEX.match(text):
                flush()
                return blocks
            if CHAPTER.match(text):
                flush()
                article, lines = None, []
                chapter = text
            elif match:
                flush()
                article, lines, page_no = match.group(1), [text], line.page
            elif article:
                lines.append(text)
    flush()
    return blocks


def needs_ocr(pages):
    """A scan has pages but (almost) no text layer: flag it instead of indexing nothing."""
    chars = sum(len(line.text) for page in pages for line in page)
    return chars < MIN_CHARS_PER_PAGE * max(1, len(pages))


def _scan_notice(doc_id, title):
    return Document(doc_id, title, [], "ocr_required", "no text layer: send to OCR, not to the index")


def load_report_pdf(path, doc_id, title):
    pages = pdf_lines(path)
    if needs_ocr(pages):
        return _scan_notice(doc_id, title)
    return Document(doc_id, title, report_blocks(drop_page_furniture(pages)))


def load_law_pdf(path, doc_id, title):
    pages = pdf_lines(path, keep_footnotes=False)
    if needs_ocr(pages):
        return _scan_notice(doc_id, title)
    return Document(doc_id, title, law_pdf_blocks(drop_page_furniture(pages)))
