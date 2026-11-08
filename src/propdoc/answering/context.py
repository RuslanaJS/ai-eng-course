"""The context of an answer: the best chunks in rank order, cut by a token budget, as quoted sources."""

DEFAULT_BUDGET = 2500  # tokens for all sources together (5 chunks of at most about 500 tokens)


def build_context(chunks, budget=DEFAULT_BUDGET):
    """Takes chunks in rank order while they fit. The first chunk that does not fit ends the context, so a
    lower-ranked chunk never replaces a better one. Returns (used chunks, number of dropped chunks, tokens)."""
    used, tokens = [], 0
    for chunk in chunks:
        if used and tokens + chunk["n_tokens"] > budget:
            break
        used.append(chunk)
        tokens += chunk["n_tokens"]
    return used, len(chunks) - len(used), tokens


def attribute(value):
    return str(value).replace('"', "'").replace("<", "(").replace(">", ")")


def format_source(number, chunk):
    """One quoted source. The text cannot close the tag, so a document cannot step out of its quote."""
    head = {"title": chunk["title"], "section": chunk["section"], "part": chunk["label"],
            "page": chunk["page_start"] or "", "version": chunk["version"], "status": chunk["status"]}
    attrs = " ".join(f'{key}="{attribute(value)}"' for key, value in head.items() if value != "")
    text = chunk["text"].replace("</source", "<\\/source")
    return f'<source id="{number}" {attrs}>\n{text}\n</source>'


def format_context(chunks):
    return "\n\n".join(format_source(i, chunk) for i, chunk in enumerate(chunks, 1))
