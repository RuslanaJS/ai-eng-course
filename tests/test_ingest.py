"""Tests for the ingestion steps on small synthetic inputs (the real documents are not in git)."""

import json

from propdoc.ingest import build, check, compare
from propdoc.ingest.chunk import (
    MAX_TOKENS,
    compare_strategies,
    fixed_chunks,
    structural_chunks,
)
from propdoc.ingest.clean import (
    is_noise,
    join_legal_lines,
    join_lines,
    mask_pii,
    normalize,
    repeated_line_keys,
)
from propdoc.ingest.dedup import (
    assign_status,
    drop_duplicate_chunks,
    duplicate_files,
    near_duplicates,
    text_hash,
)
from propdoc.ingest.loaders import (
    Line,
    article_text,
    drop_page_furniture,
    law_pdf_blocks,
    load_law_html,
    needs_ocr,
    report_blocks,
)
from propdoc.ingest.model import Block, Chunk, approx_tokens

LAW_HTML = """<html><body><h1>Ustawa&nbsp;testowa</h1>
<h2 class="part">Treść obwieszczenia</h2>
<div class="unit unit_arti"><h3>Art. 1.</h3><div class="unit-inner">Ogłasza się tekst.</div></div>
<h2 class="part">Załącznik - Tekst jednolity ustawy</h2>
<h3>Rozdział 1 Przepisy ogólne</h3>
<div class="unit unit_arti"><h3>Art. 1.</h3><div class="unit-inner"><h3>1.</h3>Ustawa określa
<a class="gloss-link tooltip"><sup>6)</sup><span class="tooltip-text">Przypis</span></a>:
<div class="unit unit_pint"><h3>1)</h3>środki ochrony;</div>
<div class="unit unit_pint"><h3>2)</h3>zasady wypłaty.</div></div></div>
<div class="unit unit_arti"><h3>Art. 2.</h3><div class="unit-inner">Zmiana
<div class="unit unit_arti pro-cite-text"><h3>Art. 9.</h3>cytowany przepis</div></div></div>
</body></html>"""


def lines(*texts, page=1, bold=False):
    return [Line(t, page, bold) for t in texts]


# --- cleaning ---


def test_normalize_and_join_lines():
    assert normalize("  a" + chr(0xA0) + " b" + chr(0xAD) + "c ") == "a bc"
    assert join_lines(["podob-", "nego tekstu", "i dalej"]) == "podobnego tekstu i dalej"
    assert join_lines(["biało-", "Czerwony"]) == "biało- Czerwony"  # only before lower case
    assert join_lines(["ogłoszeniu", ".", "Dalej"]) == "ogłoszeniu. Dalej"


def test_join_legal_lines_starts_a_paragraph_at_every_mark():
    text = join_legal_lines(["Art. 1. Ustawa określa:", "1) środki", "ochrony;", "2) zasady."])
    assert text.split("\n") == ["Art. 1. Ustawa określa:", "1) środki ochrony;", "2) zasady."]


def test_is_noise_recognises_chart_residue_but_not_text():
    assert is_noise("44333332222211111 2086420864208642086")
    assert is_noise("W a rs z a w a R P T")
    assert not is_noise("Ceny mieszkań w Warszawie wzrosły o 2,4% r/r.")
    assert not is_noise("Warszawa 1,9% 1,2% 2,4% 1,3% 0,9% 0,2% -0,4% -1,5% 0,6% -0,1% -2,8% -3,8%")


def test_repeated_lines_need_enough_pages():
    pages = [["Raport NBP", f"tekst strony {i}"] for i in range(8)]
    assert "raport nbp" in repeated_line_keys(pages)
    assert repeated_line_keys(pages[:3]) == set()


def test_drop_page_furniture_removes_header_page_number_and_date():
    words = ["alfa", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta"]
    pages = [lines("Informacja o cenach", f"{i + 1}", "2026-07-02", f"Treść {w}")
             for i, w in enumerate(words)]
    kept = drop_page_furniture(pages)
    assert [ln.text for ln in kept[0]] == ["Treść alfa"]


# --- loaders ---


def test_article_text_keeps_the_article_label_with_the_first_paragraph():
    text = article_text(["Art. 1.", "1.", "Ustawa określa", ":", "1)", "środki;", "2)", "zasady."])
    assert text.split("\n") == ["Art. 1. 1. Ustawa określa:", "1) środki;", "2) zasady."]


def test_load_law_html_skips_announcement_notes_and_quoted_articles(tmp_path):
    path = tmp_path / "law.html"
    path.write_text(LAW_HTML, encoding="utf-8")
    doc = load_law_html(path, "D001")
    assert doc.title == "Ustawa testowa"
    assert [b.label for b in doc.blocks] == ["Art. 1", "Art. 2"]
    first = doc.blocks[0]
    assert first.section == "Rozdział 1 Przepisy ogólne" and first.kind == "article"
    assert "Przypis" not in first.text and "6)" not in first.text
    assert first.text.split("\n")[1:] == ["1) środki ochrony;", "2) zasady wypłaty."]
    assert "Art. 9. cytowany przepis" in doc.blocks[1].text  # a quoted article stays in its parent


def test_report_blocks_sections_bullets_tables_and_figures():
    page = [
        Line("1. Ceny mieszkań", 3, bold=True),
        Line("Ceny były stabilne w całym", 3),
        Line("kwartale.", 3),
        Line("▪ Pierwszy punkt", 3),
        Line("Tabela 2 Dynamika cen", 4),
        Line("Warszawa 1,9% 1,2%", 4),
        Line("II 2025 23 268 8 116", 4),
        Line("Źródło: NBP, GUS", 4),
        Line("Uwaga: dane wstępne", 4),
        Line("Wykres 7 Indeks cen", 4),
        Line("44333332222211111 2086420864", 4),
        Line("Źródło: NBP", 4),
        Line("Dalszy tekst akapitu.", 5),
    ]
    blocks = report_blocks([page])
    kinds = [(b.kind, b.label) for b in blocks]
    assert kinds == [("paragraph", ""), ("paragraph", ""), ("table", "Tabela 2"),
                     ("figure", "Wykres 7"), ("paragraph", "")]
    assert blocks[0].text == "Ceny były stabilne w całym kwartale." and blocks[0].section == "1. Ceny mieszkań"
    assert blocks[1].text == "- Pierwszy punkt"
    assert "II 2025 23 268 8 116" in blocks[2].text and blocks[2].text.endswith("Uwaga: dane wstępne")
    assert "4433" not in blocks[3].text  # chart noise is dropped
    assert blocks[4].page == 5


def test_a_caption_without_a_source_line_does_not_swallow_the_document():
    page = [Line("Tabela 1 Bez źródła", 1)] + [Line(f"wiersz {i}", 1) for i in range(60)]
    blocks = report_blocks([page])
    assert blocks[0].kind == "table" and len(blocks[0].text.split("\n")) <= 42


def test_law_pdf_blocks_chapters_footnotes_and_annex():
    page = [
        Line("Rozdział 1", 1, size=10.0),
        Line("Art. 1. Ustawa określa:", 1, size=10.0),
        Line("1) środki ochrony;", 1, size=10.0),
        Line("26) Dodany przez art. 11 ustawy z 2025 r.", 1, size=9.0),
        Line("Art. 2. Ustawa wchodzi w życie po ogłoszeniu29).", 2, size=10.0),
        Line("WZÓR Stan na dzień sporządzenia prospektu", 2, size=10.0),
        Line("Art. 3. Nie powinno być widoczne.", 3, size=10.0),
    ]
    blocks = law_pdf_blocks([page])
    assert [(b.label, b.section, b.page) for b in blocks] == [("Art. 1", "Rozdział 1", 1),
                                                              ("Art. 2", "Rozdział 1", 2)]
    assert "Dodany" not in blocks[0].text and blocks[1].text.endswith("po ogłoszeniu.")


# --- chunking ---


def article(label, n_paragraphs, section="Rozdział 1"):
    text = "\n".join(f"{i}. " + "Zdanie o ochronie wpłat nabywcy. " * 12 for i in range(n_paragraphs))
    return Block(f"{label}. {text}", section, label, None, "article")


def test_a_short_article_is_one_chunk_with_its_label():
    chunks = structural_chunks([article("Art. 5", 2)])
    assert len(chunks) == 1 and chunks[0].label == "Art. 5" and chunks[0].section == "Rozdział 1"


def test_a_long_article_is_split_into_labelled_parts_of_limited_size():
    chunks = structural_chunks([article("Art. 50", 40)])
    assert len(chunks) > 2
    assert chunks[0].label == f"Art. 50 (part 1/{len(chunks)})"
    assert all(approx_tokens(c.text) <= MAX_TOKENS for c in chunks)


def test_paragraphs_are_packed_and_never_cross_a_section():
    para = "Zdanie o cenach mieszkań. " * 20
    blocks = [Block(para, "1. Ceny", "", 1), Block(para, "1. Ceny", "", 1),
              Block(para, "2. Koszty", "", 2)]
    chunks = structural_chunks(blocks)
    assert [c.section for c in chunks] == ["1. Ceny", "2. Koszty"]
    assert chunks[0].page_start == 1 and chunks[1].page_end == 2
    assert chunks[0].text.count("Zdanie") == 40


def test_a_table_stays_whole_and_a_long_table_repeats_its_caption():
    short = Block("Tabela 1 Ceny\nWarszawa 1\nKraków 2\nŹródło: NBP", "S", "Tabela 1", 1, "table")
    assert len(structural_chunks([short])) == 1
    rows = "\n".join(f"Miasto {i} " + "12,3% " * 12 for i in range(120))
    long = Block(f"Tabela 2 Duża\n{rows}\nŹródło: NBP", "S", "Tabela 2", 1, "table")
    parts = structural_chunks([long])
    assert len(parts) > 1 and all(p.text.startswith("Tabela 2 Duża") for p in parts)


def test_long_paragraphs_are_not_split_after_abbreviations():
    sentence = "W II kw. 2025 r. ceny mieszkań wzrosły o 2,4% (por. tabela 1). "
    paragraph = (sentence + "Kolejne zdanie o rynku. ") * 40
    chunks = structural_chunks([Block(paragraph, "1. Ceny", "", 1)])
    assert len(chunks) > 1
    for chunk in chunks:
        for line in chunk.text.split("\n"):
            assert not line.startswith(("2025", "r. ", "1)"))


def test_fixed_chunks_cut_inside_sentences_and_articles():
    blocks = [article(f"Art. {i}", 3) for i in range(1, 6)]
    chunks, infos, _windows, _spans = fixed_chunks(blocks)
    assert len(chunks) == len(infos) >= 3
    assert any(i.mid_sentence for i in infos)
    stats = compare_strategies(blocks)
    assert stats["fixed"]["tables_and_articles_cut"] > stats["structural"]["tables_and_articles_cut"]
    assert stats["structural"]["mid_sentence_starts_pct"] == 0


# --- deduplication ---


def test_dedup_ignores_case_and_whitespace_and_works_inside_one_document():
    assert text_hash("Ala  ma\nkota") == text_hash("ala ma kota")
    kept, dropped = drop_duplicate_chunks([Chunk("Ala ma kota"), Chunk("ala  ma kota"), Chunk("Inny")])
    assert [c.text for c in kept] == ["Ala ma kota", "Inny"] and dropped == 1
    rows = [{"id": "D1", "sha256": "a"}, {"id": "D2", "sha256": "b"}, {"id": "D3", "sha256": "a"}]
    assert duplicate_files(rows) == [("D3", "D1")]


# --- versions, scans, personal data ---


def test_normalize_uses_nfkc_and_removes_invisible_characters():
    assert normalize("zł/m\u00b2") == "zł/m2"
    assert normalize("\ufb01nal\u200b\ufeff\r\n") == "final"


def test_mask_pii_masks_contacts_but_not_amounts():
    text, n = mask_pii("Pisz na jan.kowalski@firma.pl lub dzwoń +48 600 700 800, tel. 22 123 45 67.")
    assert "@" not in text and "600" not in text and "123 45" not in text and n == 3
    assert mask_pii("Wartość 257 263 932 zł") == ("Wartość 257 263 932 zł", 0)


def test_needs_ocr_flags_a_document_without_a_text_layer():
    scan = [[Line("", 1)], [Line("12", 2)], [Line("x", 3)]]
    text_pdf = [lines("Ceny mieszkań w Warszawie wzrosły w drugim kwartale roku 2026.", page=i)
                for i in range(1, 4)]
    assert needs_ocr(scan) and not needs_ocr(text_pdf)


def test_near_duplicates_find_versions_of_one_text():
    old = " ".join(f"słowo{i}" for i in range(200))
    new = old.replace("słowo50", "inne50")  # one word changed
    other = " ".join(f"zupełnie{i}" for i in range(200))
    pairs = near_duplicates({"A": old, "B": new, "C": other}, threshold=0.8)
    assert [(a, b) for a, b, _ in pairs] == [("A", "B")] and pairs[0][2] > 0.9


def test_assign_status_marks_the_newest_released_edition_current():
    rows = [
        {"id": "D1", "series": "act", "effective": "2014-01-01"},
        {"id": "D2", "series": "act", "effective": "2017-01-01"},
        {"id": "D3", "series": "amendment", "effective": "2026-11-19"},
        {"id": "D4", "series": "", "effective": ""},
    ]
    assert assign_status(rows, "2026-11-07") == {
        "D1": "superseded", "D2": "current", "D3": "upcoming", "D4": "current"}
    assert assign_status(rows, "2026-11-20")["D3"] == "current"


# --- the whole pipeline ---

HEADER = ("id,title,publisher,doc_type,lang,period_or_version,format,url,url_status,license_status,"
          "commit_text,notes,file,bytes,sha256,retrieved_at,retrieved_via,series,effective\n")


def manifest_row(doc_id, title, fmt="html", commit="yes", series="act", effective="2017-01-01"):
    return (f"{doc_id},{title},Sejm,{'law' if fmt == 'html' else 'report'},pl,2017,{fmt},"
            f"https://x.pl/{doc_id},verified,open_law,{commit},,{doc_id}.{fmt},1,hash{doc_id},t,script,"
            f"{series},{effective}\n")


def read_lines(path):
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]


def test_build_splits_chunks_by_commit_permission_and_dry_ids_write_nothing(tmp_path):
    raw, out, manifest = tmp_path / "raw", tmp_path / "out", tmp_path / "manifest.csv"
    raw.mkdir()
    (raw / "D001.html").write_text(LAW_HTML, encoding="utf-8")
    (raw / "D002.html").write_text(LAW_HTML, encoding="utf-8")
    manifest.write_text(HEADER + manifest_row("D001", "Law A") + manifest_row(
        "D002", "Law B", commit="no", effective="2016-01-01"), encoding="utf-8")
    assert build.main(["--ids", "D001"], manifest, raw, out) == 0 and not out.exists()
    assert build.main(["--as-of", "2026-11-07"], manifest, raw, out) == 0
    committed, local = read_lines(out / "chunks.jsonl"), read_lines(out / "chunks_local.jsonl")
    assert {r["doc_id"] for r in committed} == {"D001"} and {r["doc_id"] for r in local} == {"D002"}
    first = committed[0]
    assert first["chunk_id"] == "D001#0" and first["chunk_index"] == 0 and first["doc_hash"] == "hashD001"
    assert first["status"] == "current" and local[0]["status"] == "superseded"
    assert first["access"] == ["public"] and first["pipeline_version"] == "ingest-v2"
    assert first["embed_text"].startswith("Law A | Rozdział 1 Przepisy ogólne | Art. 1\n")
    assert first["dataset_version"] == local[0]["dataset_version"]
    report = json.loads((out / "ingest_report.json").read_text(encoding="utf-8"))
    assert report["committed"] == 2 and report["local_only"] == 2 and report["as_of"] == "2026-11-07"
    assert [p[:2] for p in report["near_duplicates"]] == [["D001", "D002"]]
    audit = read_lines(out / "audit.jsonl")
    assert {e["event"] for e in audit} == {"ingested", "near_duplicate"}


def test_one_broken_file_does_not_stop_the_run(tmp_path):
    raw, out, manifest = tmp_path / "raw", tmp_path / "out", tmp_path / "manifest.csv"
    raw.mkdir()
    (raw / "D001.html").write_text(LAW_HTML, encoding="utf-8")
    (raw / "D002.pdf").write_bytes(b"this is not a pdf")
    manifest.write_text(HEADER + manifest_row("D001", "Law A") + manifest_row(
        "D002", "Broken report", fmt="pdf", series="", effective=""), encoding="utf-8")
    assert build.main([], manifest, raw, out) == 1  # the exit code tells that something failed
    assert {r["doc_id"] for r in read_lines(out / "chunks.jsonl")} == {"D001"}
    events = {e["id"]: e["event"] for e in read_lines(out / "audit.jsonl")}
    assert events == {"D001": "ingested", "D002": "error"}


def test_compare_writes_numbers_for_the_sample_documents(tmp_path):
    raw, manifest, out = tmp_path / "raw", tmp_path / "manifest.csv", tmp_path / "cmp.json"
    raw.mkdir()
    (raw / "D001.html").write_text(LAW_HTML, encoding="utf-8")
    manifest.write_text(HEADER + manifest_row("D001", "Law A"), encoding="utf-8")
    assert compare.main([], manifest, raw, out) == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert set(data) == {"D001"}
    assert data["D001"]["structural"]["mid_sentence_starts_pct"] == 0
    assert data["D001"]["tables_and_articles"] == 2


# --- the check of real chunks ---


def good_record(**changes):
    record = {field: "x" for field in check.REQUIRED}
    record.update(chunk_id="D1#0", doc_id="D1", n_tokens=100, kind="article", series="act",
                  status="current", text="Art. 1. Ustawa określa zasady.")
    record.update(changes)
    return record


def failed_rules(records):
    return [name for name, problem in check.run_checks(records) if problem]


def test_check_accepts_clean_chunks_and_flags_the_known_problems():
    assert failed_rules([good_record()]) == []
    assert "no invisible characters" in failed_rules([good_record(text="a\u200bb")])
    assert "no ligatures" in failed_rules([good_record(text="o\ufb01cjalny")])
    assert "chunk ids are unique" in failed_rules([good_record(), good_record()])
    assert "statuses are valid" in failed_rules([good_record(status="old")])
    two_current = [good_record(), good_record(chunk_id="D2#0", doc_id="D2")]
    assert "at most one current document per series" in failed_rules(two_current)
    assert "no chart residue outside tables" in failed_rules(
        [good_record(text="44333332222211111 2086420864208642086")])
