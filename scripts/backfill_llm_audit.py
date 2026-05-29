#!/usr/bin/env python3
"""Backfill legacy wiki pages with inferred LLM audit frontmatter.

This does not call any model. It only infers metadata from existing markdown
footers such as "*此条目由AI自动生成 (...)*" and "> 翻译模型: ...".
Unknown legacy pages are marked explicitly as legacy_unknown.
"""

from __future__ import annotations

import argparse
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Tuple

import yaml


KB_DIR = Path(__file__).resolve().parent.parent


def is_generated_page(rel: Path) -> bool:
    return rel.name in {"00_INDEX.md", "DOCUMENTS.md"} or rel.name.startswith("category_")


def split_frontmatter(text: str) -> Tuple[Dict[str, Any], str]:
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    try:
        meta = yaml.safe_load(parts[1]) or {}
        if not isinstance(meta, dict):
            meta = {}
    except Exception:
        meta = {}
    return meta, parts[2]


def write_frontmatter(meta: Dict[str, Any], body: str) -> str:
    body = body if body.startswith("\n") else "\n" + body
    return "---\n" + yaml.safe_dump(meta, allow_unicode=True, sort_keys=False).strip() + "\n---" + body


def provider_for_model(model: str) -> str:
    m = (model or "").lower()
    if "gemma4" in m:
        return "local_gemma4"
    if "deepseek" in m and "flash" in m:
        return "deepseek_flash"
    if "deepseek" in m:
        return "deepseek_pro"
    return "legacy_unknown"


def infer_llm(text: str, rel: Path) -> Dict[str, Any]:
    model = ""
    for pattern in [
        r"\*此条目由AI自动生成\s*\(([^)]+)\)\*",
        r"(?m)^>\s*\*\*AI模型\*\*:\s*(.+?)\s*$",
    ]:
        m = re.search(pattern, text)
        if m:
            model = m.group(1).strip()
            break
    status = "legacy_inferred" if model else "legacy_unknown"
    return {
        "flow": "legacy_import_structure" if model else "legacy_unknown",
        "provider": provider_for_model(model) if model else "legacy_unknown",
        "model": model or "legacy_unknown",
        "status": status,
        "duration_sec": None,
        "fallback_from": "",
        "fallback_to": "",
        "generated_at": datetime.fromtimestamp((KB_DIR / "wiki" / rel).stat().st_mtime, tz=timezone.utc).isoformat(),
        "backfilled_at": datetime.now(timezone.utc).isoformat(),
        "source": "legacy_markdown_footer" if model else "legacy_missing_footer",
    }


def infer_translation(text: str) -> Dict[str, Any] | None:
    m = re.search(r"(?m)^>\s*翻译模型:\s*(.+?)\s*$", text)
    if not m:
        m = re.search(r"(?m)^>\s*\*\*翻译模型\*\*:\s*(.+?)\s*$", text)
    if not m:
        return None
    model = m.group(1).strip()
    return {
        "flow": "legacy_full_translation",
        "provider": provider_for_model(model),
        "model": model,
        "status": "legacy_inferred",
        "duration_sec": None,
        "chunk_count": None,
        "chunks": [],
        "generated_at": None,
        "backfilled_at": datetime.now(timezone.utc).isoformat(),
        "source": "legacy_translation_model_line",
    }


def run(apply: bool) -> Dict[str, int]:
    wiki_dir = KB_DIR / "wiki"
    stats = {"scanned": 0, "updated": 0, "existing_llm": 0, "translation_legacy": 0, "unknown": 0}
    for path in sorted(wiki_dir.rglob("*.md")):
        rel = path.relative_to(wiki_dir)
        if is_generated_page(rel):
            continue
        stats["scanned"] += 1
        text = path.read_text(encoding="utf-8", errors="ignore")
        meta, body = split_frontmatter(text)
        changed = False
        if isinstance(meta.get("llm"), dict) and meta["llm"]:
            stats["existing_llm"] += 1
        else:
            llm = infer_llm(text, rel)
            meta["llm"] = llm
            if llm["status"] == "legacy_unknown":
                stats["unknown"] += 1
            changed = True
        if "llm_translation_legacy" not in meta:
            translation = infer_translation(text)
            if translation:
                meta["llm_translation_legacy"] = translation
                stats["translation_legacy"] += 1
                changed = True
        if changed:
            stats["updated"] += 1
            if apply:
                path.write_text(write_frontmatter(meta, body), encoding="utf-8")
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill legacy LLM audit metadata")
    parser.add_argument("--apply", action="store_true", help="write changes")
    args = parser.parse_args()
    print(run(apply=args.apply))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
