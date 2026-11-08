"""Marker for tests that read data/texts, which is not part of the repository."""

import pytest

from propdoc.extraction.run import ROOT

needs_texts = pytest.mark.skipif(
    not any((ROOT / "data" / "texts").glob("*.txt")),
    reason="source texts are not in the repository (see README)",
)
