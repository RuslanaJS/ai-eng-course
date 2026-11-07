"""Tests for the corpus fetcher (no network: the HTTP call is replaced by a fake)."""

import hashlib
import json

import pytest

from propdoc.ingest.fetch import (
    download,
    find_local,
    main,
    problem_with,
    read_manifest,
)

HTML = b"<!doctype html><html><body>" + b"Art. 1. " * 400 + b"</body></html>"
PDF = b"%PDF-1.7 " + b"x" * 100
COLUMNS = "id,title,url,format,license_status\n"


def make_manifest(path, *rows):
    path.write_text(COLUMNS + "".join(rows), encoding="utf-8")


def test_problem_with_recognises_bad_responses():
    assert problem_with(b"", "pdf") == "empty response"
    assert problem_with(b"<html>nope", "pdf") == "not a PDF"
    assert problem_with(b"<html><title>Request Rejected</title></html>", "html")
    assert problem_with(b"just text " * 500, "html") == "not an HTML page"
    assert problem_with(b"<html>short</html>", "html") == "too short for a law text"
    assert problem_with(HTML, "html") is None
    assert problem_with(PDF, "pdf") is None


def test_find_local_prefers_own_name_then_original_name(tmp_path):
    row = {"id": "D009", "format": "pdf", "url": "https://x.pl/a/Raport%20roczny.pdf"}
    assert find_local(row, tmp_path) is None
    (tmp_path / "Raport roczny.pdf").write_bytes(PDF)
    assert find_local(row, tmp_path).name == "Raport roczny.pdf"
    (tmp_path / "D009.pdf").write_bytes(PDF)
    assert find_local(row, tmp_path).name == "D009.pdf"


def test_download_writes_file_row_and_log(tmp_path):
    row = {"id": "D001", "format": "html", "url": "https://x.pl/law", "license_status": "open_law"}
    row.update(file="", bytes="", sha256="", retrieved_at="", retrieved_via="")
    log = tmp_path / "log.jsonl"
    download(row, tmp_path, log, fetch=lambda url: (200, url + "/final", "text/html", HTML))
    assert (tmp_path / "D001.html").read_bytes() == HTML
    assert row["sha256"] == hashlib.sha256(HTML).hexdigest() and row["retrieved_via"] == "script"
    event = json.loads(log.read_text(encoding="utf-8"))
    assert event["url"] == "https://x.pl/law" and event["final_url"] == "https://x.pl/law/final"
    assert event["http_status"] == 200 and not list(tmp_path.glob("*.part"))


def test_download_rejects_a_blocked_page_and_leaves_no_file(tmp_path):
    row = {"id": "D001", "format": "html", "url": "https://x.pl/law"}
    blocked = b"<html><title>Request Rejected</title></html>"
    with pytest.raises(RuntimeError, match="firewall"):
        download(row, tmp_path, tmp_path / "log.jsonl", fetch=lambda url: (200, url, "text/html", blocked))
    assert list(tmp_path.iterdir()) == []


def test_main_fetches_only_open_rows_and_registers_manual_files(tmp_path):
    manifest, raw, log = tmp_path / "manifest.csv", tmp_path / "raw", tmp_path / "log.jsonl"
    raw.mkdir()
    (raw / "report.pdf").write_bytes(PDF)
    make_manifest(
        manifest,
        "D001,Law,https://x.pl/law,html,open_law\n",
        "D002,Report,https://x.pl/files/report.pdf,pdf,attribution\n",
        "D003,Barometer,https://x.pl/files/other.pdf,pdf,restricted\n",
    )
    calls = []

    def fake_fetch(url):
        calls.append(url)
        return 200, url, "text/html", HTML

    assert main(["--delay", "0"], manifest, raw, log, fake_fetch) == 0
    assert calls == ["https://x.pl/law"]
    _, rows = read_manifest(manifest)
    by_id = {r["id"]: r for r in rows}
    assert by_id["D001"]["retrieved_via"] == "script" and by_id["D002"]["retrieved_via"] == "manual"
    assert by_id["D002"]["sha256"] == hashlib.sha256(PDF).hexdigest()
    assert by_id["D003"]["sha256"] == ""
    assert len(log.read_text(encoding="utf-8").splitlines()) == 2


def test_dry_run_changes_nothing(tmp_path):
    manifest, raw, log = tmp_path / "manifest.csv", tmp_path / "raw", tmp_path / "log.jsonl"
    make_manifest(manifest, "D001,Law,https://x.pl/law,html,open_law\n")
    before = manifest.read_text(encoding="utf-8")

    def no_network(url):
        raise AssertionError("dry run must not download")

    assert main(["--dry-run"], manifest, raw, log, no_network) == 0
    assert manifest.read_text(encoding="utf-8") == before and not log.exists()
