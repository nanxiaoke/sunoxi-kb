#!/usr/bin/env python3
"""Smoke checks for WebUI audit, preview metadata, and repair preview flows."""

from __future__ import annotations

import csv
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from web_ui import app  # noqa: E402


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    with app.test_client() as client:
        home = client.get("/")
        _assert(home.status_code == 200, f"home returned {home.status_code}")
        html = home.get_data(as_text=True)
        for token in [
            "focusDocInList",
            "openAuditDoc",
            "openDocAudit",
            "LLM 审计链路",
            "列表定位",
        ]:
            _assert(token in html, f"missing WebUI token: {token}")

        docs_resp = client.get("/api/documents")
        _assert(docs_resp.status_code == 200, f"documents returned {docs_resp.status_code}")
        docs = docs_resp.get_json().get("documents", [])
        _assert(docs, "expected at least one document")
        doc_path = docs[0].get("path") or docs[0].get("relpath")
        _assert(bool(doc_path), "first document is missing path")

        doc_resp = client.get(f"/api/documents/{doc_path}")
        _assert(doc_resp.status_code == 200, f"document preview returned {doc_resp.status_code}")
        doc_payload = doc_resp.get_json()
        _assert(isinstance(doc_payload.get("meta"), dict), "document preview missing meta")
        _assert("quality" in doc_payload["meta"], "document preview meta missing quality")

        audit_resp = client.get("/api/llm/audit")
        _assert(audit_resp.status_code == 200, f"audit returned {audit_resp.status_code}")
        audit = audit_resp.get_json()
        _assert("items" in audit, "audit missing items")
        _assert("filtered_total" in audit, "audit missing filtered_total")
        if audit["items"]:
            first = audit["items"][0]
            _assert("generation_chain" in first, "audit item missing generation_chain")

        filtered = client.get("/api/llm/audit?missing=true")
        _assert(filtered.status_code == 200, f"filtered audit returned {filtered.status_code}")
        filtered_payload = filtered.get_json()
        _assert(filtered_payload.get("filters", {}).get("missing") is True, "missing filter not reflected")

        csv_resp = client.get("/api/llm/audit?format=csv")
        _assert(csv_resp.status_code == 200, f"audit csv returned {csv_resp.status_code}")
        _assert(csv_resp.content_type.startswith("text/csv"), f"unexpected csv type {csv_resp.content_type}")
        rows = list(csv.reader(io.StringIO(csv_resp.get_data(as_text=True))))
        _assert(rows and "generation_chain" in rows[0], "audit csv missing generation_chain column")

        dry_run = client.post("/api/quality/repair", json={"limit": 1, "dry_run": True})
        _assert(dry_run.status_code == 200, f"quality repair dry-run returned {dry_run.status_code}")
        dry_payload = dry_run.get_json()
        _assert(dry_payload.get("dry_run") is True, "quality repair dry-run flag missing")
        _assert("planned" in dry_payload, "quality repair dry-run missing planned count")

    print(f"PASS webui audit smoke -> {doc_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
