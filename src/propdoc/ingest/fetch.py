"""Download the open-licence corpus documents and record where every file came from.

Only rows with an open licence are fetched by the script. Documents with other terms are
downloaded by hand into data/raw/ and registered here by hash and download time.
Every download or registration adds a line to data/fetch_log.jsonl and fills the provenance
columns of data/manifest.csv.
"""

import argparse
import csv
import hashlib
import json
import ssl
import time
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

import certifi

ROOT = Path(__file__).resolve().parents[3]
MANIFEST = ROOT / "data" / "manifest.csv"
RAW_DIR = ROOT / "data" / "raw"
LOG = ROOT / "data" / "fetch_log.jsonl"
USER_AGENT = "propdoc-course-project (student RAG project)"
AUTO_LICENSES = {"open_law"}
PROVENANCE_COLUMNS = ["file", "bytes", "sha256", "retrieved_at", "retrieved_via"]


def read_manifest(path=MANIFEST):
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)
        columns = list(reader.fieldnames)
    for col in PROVENANCE_COLUMNS:
        if col not in columns:
            columns.append(col)
    for row in rows:
        for col in PROVENANCE_COLUMNS:
            row.setdefault(col, "")
    return columns, rows


def write_manifest(path, columns, rows):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def find_local(row, raw_dir):
    """The file of a row: our own name first, then the original file name from the URL."""
    own = f"{row['id']}.{row['format']}"
    original = urllib.parse.unquote(row["url"].rsplit("/", 1)[-1])
    for name in (own, original):
        if (raw_dir / name).is_file():
            return raw_dir / name
    return None


def sha256_of(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def problem_with(content, fmt):
    """Why a response cannot be the document we asked for, or None."""
    if not content:
        return "empty response"
    if fmt == "pdf" and not content.startswith(b"%PDF"):
        return "not a PDF"
    if fmt == "html":
        head = content[:4000].lower()
        if b"request rejected" in head:
            return "blocked by a firewall page"
        if b"<html" not in head and b"<!doctype" not in head:
            return "not an HTML page"
        if len(content) < 2000:
            return "too short for a law text"
    return None


def fetch_url(url, timeout=60):
    # The macOS CA file lacks the Certum EC-384 root used by api.sejm.gov.pl, the Mozilla bundle has it.
    context = ssl.create_default_context(cafile=certifi.where())
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout, context=context) as resp:
        content_type = resp.headers.get("Content-Type", "").split(";")[0]
        return resp.status, resp.geturl(), content_type, resp.read()


def now_utc():
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def log_event(log, event):
    with open(log, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False) + "\n")


def fill(row, path, via, at):
    row.update(
        file=path.name,
        bytes=str(path.stat().st_size),
        sha256=sha256_of(path),
        retrieved_at=at,
        retrieved_via=via,
    )


def download(row, raw_dir, log, fetch=fetch_url):
    status, final_url, content_type, content = fetch(row["url"])
    if status != 200:
        raise RuntimeError(f"{row['id']}: HTTP {status}")
    bad = problem_with(content, row["format"])
    if bad:
        raise RuntimeError(f"{row['id']}: {bad}")
    path = raw_dir / f"{row['id']}.{row['format']}"
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_bytes(content)
    tmp.replace(path)  # a half-written file never gets the final name
    at = now_utc()
    fill(row, path, "script", at)
    log_event(log, {
        "at": at, "id": row["id"], "via": "script", "url": row["url"], "final_url": final_url,
        "http_status": status, "content_type": content_type, "bytes": row["bytes"],
        "sha256": row["sha256"], "file": path.name, "user_agent": USER_AGENT,
    })


def register(row, path, log):
    """Record a file that was downloaded by hand (or earlier): its time is the file's mtime."""
    via = "manual" if row["license_status"] not in AUTO_LICENSES else "existing-file"
    at = datetime.fromtimestamp(path.stat().st_mtime, UTC).replace(microsecond=0).isoformat()
    fill(row, path, via, at)
    log_event(log, {
        "at": at, "id": row["id"], "via": via, "url": row["url"], "final_url": None,
        "http_status": None, "content_type": None, "bytes": row["bytes"],
        "sha256": row["sha256"], "file": path.name, "user_agent": None,
        "note": "download time is the file modification time",
    })


def plan(rows, raw_dir, ids, force):
    to_fetch, to_register, missing = [], [], []
    for row in rows:
        if ids and row["id"] not in ids:
            continue
        path = find_local(row, raw_dir)
        if row["license_status"] in AUTO_LICENSES and (path is None or force):
            to_fetch.append(row)
        elif path is not None and not row["sha256"]:
            to_register.append((row, path))
        elif path is None:
            missing.append(row)
    return to_fetch, to_register, missing


def main(argv=None, manifest=MANIFEST, raw_dir=RAW_DIR, log=LOG, fetch=fetch_url):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="show the plan, change nothing")
    parser.add_argument("--ids", nargs="+", help="only these manifest ids, for example D001 D002")
    parser.add_argument("--force", action="store_true", help="download again if the file exists")
    parser.add_argument("--delay", type=float, default=1.0, help="seconds between requests")
    args = parser.parse_args(argv)

    columns, rows = read_manifest(manifest)
    raw_dir.mkdir(parents=True, exist_ok=True)
    to_fetch, to_register, missing = plan(rows, raw_dir, args.ids, args.force)
    print(f"to download ({len(to_fetch)}):")
    for row in to_fetch:
        print(f"  {row['id']}  {row['url']}")
    print(f"to register from files already in {raw_dir.name}/ ({len(to_register)}):")
    for row, path in to_register:
        print(f"  {row['id']}  {path.name}")
    print(f"not downloaded here, no file yet ({len(missing)}): {', '.join(r['id'] for r in missing)}")
    if args.dry_run:
        return 0

    failed = 0
    for i, row in enumerate(to_fetch):
        if i:
            time.sleep(args.delay)
        try:
            download(row, raw_dir, log, fetch)
            print(f"fetched  {row['id']}  {int(row['bytes']):>9,} bytes  {row['url']}")
        except (OSError, RuntimeError) as exc:  # reported per document, the run continues
            failed += 1
            print(f"FAILED   {row['id']}  {exc}")
    for row, path in to_register:
        register(row, path, log)
        print(f"recorded {row['id']}  {int(row['bytes']):>9,} bytes  {path.name}")
    write_manifest(manifest, columns, rows)
    return 1 if failed else 0
