#!/usr/bin/env python3
"""Analyze SAM.gov public attachments once and persist normalized evidence.

Examples:

  py -3 -m pip install -r requirements-contract-brain-ingest.txt
  set SUPABASE_SERVICE_ROLE_KEY=...
  py scripts/contract_brain_ingest.py --notice-id <NOTICE_ID>

The script deliberately separates source extraction from semantic promotion. It
stores exact source rows; CONOPS, requirements, components, and relationships are
later derived from those rows with their provenance intact.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from contract_brain_pipeline.extractor import (  # noqa: E402
    PARSER_VERSION,
    ExtractionResult,
    extract_payload,
    sha256_bytes,
    source_row_id,
)

WORKER = os.environ.get("CONTRACT_BRAIN_WORKER_URL", "https://samgovsearch.spotterdeer.workers.dev").rstrip("/")
SUPABASE_URL = os.environ.get("CONTRACT_BRAIN_SUPABASE_URL", "https://igkjmfjmwatgtubfjcok.supabase.co").rstrip("/")
SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def progress(stage: str, message: str, **data: Any) -> None:
    suffix = " " + json.dumps(data, ensure_ascii=False, sort_keys=True) if data else ""
    print(f"[{time.strftime('%H:%M:%S')}] {stage:<13} {message}{suffix}", flush=True)


def request_bytes(url: str, *, timeout: int = 120) -> tuple[bytes, dict[str, str]]:
    request = urllib.request.Request(url, headers={"Accept": "*/*", "User-Agent": "ContractBrain/0.1"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = response.read()
        headers = {key.lower(): value for key, value in response.headers.items()}
    return payload, headers


def rest_request(method: str, table: str, *, query: list[tuple[str, str]] | None = None, body: Any = None, prefer: str = "return=representation") -> Any:
    if not SERVICE_KEY:
        raise RuntimeError("SUPABASE_SERVICE_ROLE_KEY is required for persistent ingestion")
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    if query:
        url += "?" + urllib.parse.urlencode(query, doseq=True, safe=".*(),:")
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = {
        "apikey": SERVICE_KEY,
        "Authorization": f"Bearer {SERVICE_KEY}",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Prefer": prefer,
    }
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            raw = response.read().decode("utf-8", errors="replace")
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Supabase {method} {table} failed: {exc.code} {raw[:1000]}") from exc


def get_document(resource_id: str) -> dict[str, Any] | None:
    rows = rest_request(
        "GET",
        "documents",
        query=[("select", "notice_id,resource_id,document_name,download_url,size_bytes,document_hash"), ("resource_id", f"eq.{resource_id}"), ("limit", "1")],
    )
    return rows[0] if rows else None


def documents_for_notice(notice_id: str) -> list[dict[str, Any]]:
    return rest_request(
        "GET",
        "documents",
        query=[("select", "notice_id,resource_id,document_name,download_url,size_bytes,document_hash"), ("notice_id", f"eq.{notice_id}"), ("order", "document_name.asc")],
    ) or []


def find_binary(resource_id: str, sha256: str) -> dict[str, Any] | None:
    rows = rest_request(
        "GET",
        "source_binaries",
        query=[("select", "*"), ("resource_id", f"eq.{resource_id}"), ("sha256", f"eq.{sha256}"), ("limit", "1")],
    )
    return rows[0] if rows else None


def find_complete_run(binary_id: int) -> dict[str, Any] | None:
    rows = rest_request(
        "GET",
        "extraction_runs",
        query=[
            ("select", "*"),
            ("source_binary_id", f"eq.{binary_id}"),
            ("parser_version", f"eq.{PARSER_VERSION}"),
            ("status", "eq.complete"),
            ("limit", "1"),
        ],
    )
    return rows[0] if rows else None


def upsert_binary(doc: dict[str, Any], payload: bytes, headers: dict[str, str], digest: str) -> dict[str, Any]:
    resource_id = str(doc["resource_id"])
    existing = find_binary(resource_id, digest)
    if existing:
        rest_request(
            "PATCH",
            "source_binaries",
            query=[("id", f"eq.{existing['id']}")],
            body={"last_seen_at": utc_now()},
            prefer="return=minimal",
        )
        return existing
    rows = rest_request(
        "POST",
        "source_binaries",
        body={
            "notice_id": doc.get("notice_id") or "",
            "resource_id": resource_id,
            "document_name": doc.get("document_name") or resource_id,
            "sha256": digest,
            "size_bytes": len(payload),
            "mime_type": headers.get("content-type") or mimetypes.guess_type(doc.get("document_name") or "")[0],
            "source_url": doc.get("download_url") or f"{WORKER}/download/{urllib.parse.quote(resource_id)}",
        },
    )
    return rows[0]


def create_run(binary_id: int) -> dict[str, Any]:
    rows = rest_request(
        "POST",
        "extraction_runs",
        body={"source_binary_id": binary_id, "parser_version": PARSER_VERSION, "status": "running"},
    )
    return rows[0]


def update_run(run_id: str, result: ExtractionResult) -> None:
    status = result.status if result.status in {"complete", "failed", "review_required"} else "failed"
    rest_request(
        "PATCH",
        "extraction_runs",
        query=[("id", f"eq.{run_id}")],
        body={
            "status": status,
            "extraction_mode": result.mode,
            "page_count": result.page_count,
            "logical_row_count": len(result.rows),
            "ocr_page_count": result.ocr_page_count,
            "completed_at": utc_now(),
            "error_text": result.error or None,
        },
        prefer="return=minimal",
    )


def insert_rows(binary_id: int, run_id: str, digest: str, result: ExtractionResult, batch_size: int = 300) -> None:
    payload_rows = []
    for row in result.rows:
        payload_rows.append(
            {
                "source_binary_id": binary_id,
                "extraction_run_id": run_id,
                "source_row_id": source_row_id(digest, row),
                "page_number": row.page_number,
                "locator": row.locator,
                "row_type": row.row_type,
                "exact_text": row.text,
                "sort_index": row.sort_index,
                "geometry": row.geometry,
            }
        )
    for start in range(0, len(payload_rows), batch_size):
        batch = payload_rows[start : start + batch_size]
        rest_request(
            "POST",
            "source_rows",
            query=[("on_conflict", "source_row_id")],
            body=batch,
            prefer="resolution=merge-duplicates,return=minimal",
        )
        progress("STORE", f"stored rows {start + 1}-{start + len(batch)} of {len(payload_rows)}")


def mark_document_hash(resource_id: str, digest: str) -> None:
    rest_request(
        "PATCH",
        "documents",
        query=[("resource_id", f"eq.{resource_id}")],
        body={"document_hash": digest, "last_checked_at": utc_now()},
        prefer="return=minimal",
    )


def analyze_document(doc: dict[str, Any], *, force: bool = False, dry_run: bool = False) -> dict[str, Any]:
    resource_id = str(doc.get("resource_id") or "").strip()
    name = str(doc.get("document_name") or resource_id).strip()
    if not resource_id:
        raise RuntimeError("document is missing resource_id")

    download_url = doc.get("download_url") or f"{WORKER}/download/{urllib.parse.quote(resource_id)}"
    progress("DOWNLOAD", name, resource_id=resource_id)
    payload, headers = request_bytes(download_url)
    digest = sha256_bytes(payload)
    progress("HASH", f"sha256={digest[:16]}…", bytes=len(payload))

    if dry_run:
        result = extract_payload(name, payload)
        progress("EXTRACT", result.mode or result.status, rows=len(result.rows), pages=result.page_count, ocr_pages=result.ocr_page_count)
        return {"resource_id": resource_id, "name": name, "sha256": digest, "status": result.status, "rows": len(result.rows), "mode": result.mode, "error": result.error}

    binary = upsert_binary(doc, payload, headers, digest)
    complete = find_complete_run(int(binary["id"]))
    if complete and not force:
        progress("CACHE", "unchanged binary already analyzed; reusing Supabase evidence", rows=complete.get("logical_row_count"), parser=complete.get("parser_version"))
        mark_document_hash(resource_id, digest)
        return {"resource_id": resource_id, "name": name, "sha256": digest, "status": "cached", "rows": complete.get("logical_row_count", 0), "mode": complete.get("extraction_mode", "")}

    run = create_run(int(binary["id"]))
    try:
        progress("EXTRACT", f"starting {Path(name).suffix.lower() or 'unknown'} extraction")
        result = extract_payload(name, payload)
        progress("EXTRACT", result.mode or result.status, rows=len(result.rows), pages=result.page_count, ocr_pages=result.ocr_page_count)
        if result.rows:
            insert_rows(int(binary["id"]), str(run["id"]), digest, result)
        update_run(str(run["id"]), result)
        mark_document_hash(resource_id, digest)
        return {"resource_id": resource_id, "name": name, "sha256": digest, "status": result.status, "rows": len(result.rows), "mode": result.mode, "error": result.error}
    except Exception as exc:
        failed = ExtractionResult(status="failed", mode="ingestion pipeline", error=str(exc))
        update_run(str(run["id"]), failed)
        raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--notice-id", help="Process every indexed attachment for this notice ID")
    group.add_argument("--resource-id", help="Process one indexed SAM.gov attachment resource ID")
    parser.add_argument("--force", action="store_true", help="Run this parser version again even when an unchanged successful analysis exists")
    parser.add_argument("--dry-run", action="store_true", help="Download and extract without writing to Supabase")
    parser.add_argument("--summary-json", type=Path, help="Optional path for a machine-readable run summary")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.dry_run and not SERVICE_KEY:
        print("ERROR: set SUPABASE_SERVICE_ROLE_KEY before persistent ingestion. Use --dry-run to test parsing without writes.", file=sys.stderr)
        return 2

    if args.notice_id:
        docs = documents_for_notice(args.notice_id) if not args.dry_run else []
        if args.dry_run:
            print("ERROR: --notice-id dry-run still needs Supabase read access; set SUPABASE_SERVICE_ROLE_KEY or use --resource-id with persistence enabled.", file=sys.stderr)
            return 2
    else:
        doc = get_document(args.resource_id) if SERVICE_KEY else None
        if not doc:
            if args.dry_run:
                doc = {"resource_id": args.resource_id, "document_name": args.resource_id, "download_url": f"{WORKER}/download/{urllib.parse.quote(args.resource_id)}", "notice_id": "dry-run"}
            else:
                print(f"ERROR: resource_id {args.resource_id} is not indexed in documents", file=sys.stderr)
                return 3
        docs = [doc]

    if not docs:
        print("No indexed public attachments found for this notice.")
        return 0

    progress("START", f"{len(docs)} attachment(s)", parser=PARSER_VERSION)
    summary = []
    failures = 0
    for index, doc in enumerate(docs, start=1):
        progress("SOURCE", f"{index}/{len(docs)} {doc.get('document_name') or doc.get('resource_id')}")
        try:
            summary.append(analyze_document(doc, force=args.force, dry_run=args.dry_run))
        except Exception as exc:
            failures += 1
            progress("FAILED", str(exc), resource_id=doc.get("resource_id"))
            summary.append({"resource_id": doc.get("resource_id"), "name": doc.get("document_name"), "status": "failed", "error": str(exc)})

    if args.summary_json:
        args.summary_json.parent.mkdir(parents=True, exist_ok=True)
        args.summary_json.write_text(json.dumps({"parser_version": PARSER_VERSION, "results": summary}, indent=2, ensure_ascii=False), encoding="utf-8")
    progress("DONE", f"processed {len(summary)} attachment(s)", failures=failures, cached=sum(1 for x in summary if x.get("status") == "cached"), rows=sum(int(x.get("rows") or 0) for x in summary))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
