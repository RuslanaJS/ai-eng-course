"""Data shapes shared by the ingestion steps."""

from dataclasses import dataclass, field

# Measured with tiktoken cl100k_base on this corpus: Polish law 2.6, Polish reports 2.3, English 3.7.
# 2.5 is a safe value for the mixed corpus; other models tokenize a little differently.
CHARS_PER_TOKEN = 2.5


def approx_tokens(text):
    return max(1, round(len(text) / CHARS_PER_TOKEN))


@dataclass
class Block:
    """One unit of the source: a paragraph, an article of a law, a table or a figure caption."""

    text: str
    section: str = ""
    label: str = ""  # citation label inside the section, for example "Art. 5" or "Tabela 2"
    page: int | None = None
    kind: str = "paragraph"  # paragraph | article | table | figure


@dataclass
class Document:
    doc_id: str
    title: str
    blocks: list[Block] = field(default_factory=list)
    status: str = "ok"  # ok | ocr_required
    note: str = ""


@dataclass
class Chunk:
    text: str
    section: str = ""
    label: str = ""
    page_start: int | None = None
    page_end: int | None = None
    kind: str = "paragraph"
