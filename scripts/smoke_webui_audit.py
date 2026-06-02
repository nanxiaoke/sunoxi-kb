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
            "Translation Policy",
            "Translation Backfill",
            "Full Translation",
            "llm_full_translation",
            "bilingual_on_import",
            "mergeTranslationPolicy",
            "loadTranslationBackfillAudit",
            "previewTranslationBackfillDryRun",
        ]:
            _assert(token in html, f"missing WebUI token: {token}")

        web_ui_source = (ROOT / "scripts" / "web_ui.py").read_text(encoding="utf-8")
        _assert(
            'use_cache=(qa_mode == "extractive")' in web_ui_source,
            "LLM QA answers should bypass persistent cache",
        )
        _assert(
            "provider must be online or local" not in web_ui_source,
            "retranslation API should accept configured provider IDs",
        )

        webui_config_resp = client.get("/api/webui/config")
        _assert(webui_config_resp.status_code == 200, f"webui config returned {webui_config_resp.status_code}")
        webui_config = webui_config_resp.get_json()
        policy = webui_config.get("translation_policy")
        _assert(isinstance(policy, dict), "webui config missing translation_policy")
        _assert(policy.get("mode") in {"off", "preview_only", "bilingual_on_import", "bilingual_for_selected"}, "invalid translation policy mode")
        _assert(isinstance(policy.get("full_translate"), dict), "translation policy missing full_translate group")
        _assert(isinstance(policy.get("chinese_source", {}).get("translate_to_english"), bool), "Chinese source English translation flag missing")
        _assert(isinstance(policy.get("english_source", {}).get("translate_to_chinese"), bool), "English source Chinese translation flag missing")

        models_resp = client.get("/api/translation/models")
        _assert(models_resp.status_code == 200, f"translation models returned {models_resp.status_code}")
        models = models_resp.get_json().get("models", [])
        _assert(models, "expected translation models")
        _assert(all(m.get("provider") == m.get("provider_name") for m in models), "translation model provider should be real provider ID")
        _assert(all(m.get("kind") in {"online", "local"} for m in models), "translation model kind should classify provider")

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
        _assert("llm_full_translation" in doc_payload["meta"], "document preview meta missing full translation metadata")

        audit_resp = client.get("/api/llm/audit")
        _assert(audit_resp.status_code == 200, f"audit returned {audit_resp.status_code}")
        audit = audit_resp.get_json()
        _assert("items" in audit, "audit missing items")
        _assert("filtered_total" in audit, "audit missing filtered_total")
        _assert("full_translation_count" in audit, "audit missing full translation count")
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
        _assert("full_translation_provider" in rows[0], "audit csv missing full translation columns")

        backfill_audit = client.get("/api/translation/backfill?limit=3")
        _assert(backfill_audit.status_code == 200, f"translation backfill audit returned {backfill_audit.status_code}")
        backfill_payload = backfill_audit.get_json()
        _assert("stats" in backfill_payload, "translation backfill audit missing stats")
        _assert("items" in backfill_payload, "translation backfill audit missing items")

        backfill_dry = client.post("/api/translation/backfill", json={"limit": 1, "dry_run": True})
        _assert(backfill_dry.status_code == 200, f"translation backfill dry-run returned {backfill_dry.status_code}")
        backfill_dry_payload = backfill_dry.get_json()
        _assert(backfill_dry_payload.get("dry_run") is True, "translation backfill dry-run flag missing")
        _assert("planned" in backfill_dry_payload, "translation backfill dry-run missing planned count")
        _assert(backfill_dry_payload.get("applied") == 0, "translation backfill dry-run should not apply changes")

        dry_run = client.post("/api/quality/repair", json={"limit": 1, "dry_run": True})
        _assert(dry_run.status_code == 200, f"quality repair dry-run returned {dry_run.status_code}")
        dry_payload = dry_run.get_json()
        _assert(dry_payload.get("dry_run") is True, "quality repair dry-run flag missing")
        _assert("planned" in dry_payload, "quality repair dry-run missing planned count")

    print(f"PASS webui audit smoke -> {doc_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
