"""Cleaning helpers: normalisation, joining wrapped lines, headers and footers, chart noise."""

import re
import unicodedata

MIN_PAGES_FOR_REPEATS = 6  # repeated-line detection needs enough pages to be meaningful
LEGAL_MARK = re.compile(r"^(Art\.\s*\d+[a-z]*\.|\d+[a-z]*[.)]|[a-z]\)|–)(\s|$)")


ZERO_WIDTH = re.compile("[" + "".join(map(chr, (0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF, 0xAD))) + "]")  # zero-width, BOM, soft hyphen
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE = re.compile(r"\+\d{2}[\s-]?\d{3}[\s-]?\d{3}[\s-]?\d{3}\b|\b(?:tel|fax)\.?:?\s*[+\d][\d\s()-]{6,}\d",
                   re.IGNORECASE)  # not bare digit groups: Polish amounts are written "100 000 000"


def normalize(text):
    """One canonical form: NFKC (nbsp, ligatures, m2), LF line ends, no invisible characters."""
    text = unicodedata.normalize("NFKC", text.replace("\r\n", "\n").replace("\r", "\n"))
    return re.sub(r"[ \t]+", " ", ZERO_WIDTH.sub("", text)).strip()


def mask_pii(text):
    """Replace e-mail addresses and phone numbers; returns the text and how many were masked."""
    text, emails = EMAIL.subn("[EMAIL]", text)
    text, phones = PHONE.subn("[PHONE]", text)
    return text, emails + phones


def join_lines(lines):
    """Join wrapped lines into one paragraph and remove hyphenation at the line ends."""
    out = ""
    for line in (ln.strip() for ln in lines):
        if not line:
            continue
        if out.endswith("-") and line[:1].islower() and out[-2:-1].isalpha():
            out = out[:-1] + line
        elif out and line[:1] in ".,;:)":  # punctuation that an inline tag split off
            out += line
        else:
            out = f"{out} {line}" if out else line
    return out


def join_legal_lines(lines):
    """Join wrapped lines of a law, starting a new paragraph at every Art., ust., pkt marker."""
    paragraphs = []
    for line in (ln.strip() for ln in lines):
        if not line:
            continue
        if not paragraphs or LEGAL_MARK.match(line):
            paragraphs.append([line])
        else:
            paragraphs[-1].append(line)
    return "\n".join(join_lines(p) for p in paragraphs)


def is_noise(text):
    """Axis labels and rotated chart text: digits and symbols only, or letters spread apart."""
    compact = text.replace(" ", "")
    if not compact:
        return True
    tokens = text.split()
    letters = sum(ch.isalpha() for ch in compact)
    if letters / len(compact) < 0.3 and len(tokens) <= 12:
        return True
    return len(tokens) >= 4 and sum(len(t) for t in tokens) / len(tokens) < 1.7


def line_key(text):
    return re.sub(r"\d+", "#", text.strip().lower())


def repeated_line_keys(pages, share=0.3):
    """Keys of lines that appear on many pages: running headers, footers, chart axis labels."""
    if len(pages) < MIN_PAGES_FOR_REPEATS:
        return set()
    counts = {}
    for page in pages:
        for key in {line_key(text) for text in page if text.strip()}:
            counts[key] = counts.get(key, 0) + 1
    return {key for key, n in counts.items() if n >= max(3, share * len(pages))}
