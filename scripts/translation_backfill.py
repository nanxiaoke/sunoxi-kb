#!/usr/bin/env python3
"""Audit and safely backfill missing opposite-language full translations.

Dry-run mode never calls an LLM. Apply mode is intentionally limited and only
updates selected wiki documents with missing policy-required translation
sections.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import yaml

KB_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KB_DIR / "scripts"))

from llm_service import LLMService  # type: ignore
from translation_policy import (  # type: ignore
    detect_language,
    load_translation_policy,
    section_title_for,
    target_languages_for,
)


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


def section_body(markdown: str, title: str) -> str:
    pattern = rf"(?ms)^##\s*{re.escape(title)}\s*\n(.*?)(?=^##\s+|\Z)"
    match = re.search(pattern, markdown)
    return match.group(1).strip() if match else ""


def has_translation_section(markdown: str, target_language: str) -> bool:
    body = section_body(markdown, section_title_for(target_language))
    return len(body) >= 80


def strip_known_translation_sections(markdown: str) -> str:
    text = markdown
    for title in [section_title_for("zh"), section_title_for("en"), "中文译文", "英文翻译", "English Translation"]:
        pattern = rf"(?ms)^##\s*{re.escape(title)}\s*\n.*?(?=^##\s+|\Z)"
        text = re.sub(pattern, "", text).strip()
    return text


def source_file_for(meta: Dict[str, Any], body: str, base_dir: Path) -> Optional[Path]:
    raw = str(meta.get("source") or "").strip()
    if not raw:
        match = re.search(r"(?m)^>\s*\*\*来源\*\*:\s*(.+?)\s*$", body)
        raw = match.group(1).strip() if match else ""
    if not raw:
        return None
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = base_dir / raw
    try:
        path = path.resolve()
        if str(path).startswith(str(base_dir.resolve())) and path.exists() and path.is_file():
            return path
    except Exception:
        return None
    return None


def source_text_for(meta: Dict[str, Any], body: str, base_dir: Path) -> str:
    source_file = source_file_for(meta, body, base_dir)
    if source_file:
        return source_file.read_text(encoding="utf-8", errors="ignore")
    return strip_known_translation_sections(body)


def title_for(meta: Dict[str, Any], body: str, fallback: str) -> str:
    if meta.get("title"):
        return str(meta["title"])
    match = re.search(r"(?m)^#\s+(.+?)\s*$", body)
    return match.group(1).strip() if match else fallback


def iter_wiki_files(base_dir: Path, paths: Optional[Iterable[str]] = None) -> Iterable[Tuple[Path, Path]]:
    wiki_dir = base_dir / "wiki"
    if paths:
        for item in paths:
            path = (wiki_dir / item).resolve()
            if str(path).startswith(str(wiki_dir.resolve())) and path.exists() and path.is_file():
                yield path, path.relative_to(wiki_dir)
        return
    for path in sorted(wiki_dir.rglob("*.md")):
        rel = path.relative_to(wiki_dir)
        if not is_generated_page(rel):
            yield path, rel


def audit_backfill(base_dir: Path = KB_DIR, *, limit: int = 50, paths: Optional[List[str]] = None) -> Dict[str, Any]:
    policy = load_translation_policy(base_dir)
    items: List[Dict[str, Any]] = []
    stats = {
        "scanned": 0,
        "eligible": 0,
        "missing": 0,
        "already_translated": 0,
        "unknown_language": 0,
    }
    for path, rel in iter_wiki_files(base_dir, paths):
        stats["scanned"] += 1
        text = path.read_text(encoding="utf-8", errors="ignore")
        meta, body = split_frontmatter(text)
        source_text = source_text_for(meta, body, base_dir)
        source_language = detect_language(source_text)
        targets = target_languages_for(policy, source_language)
        if not targets:
            stats["unknown_language"] += 1
            continue
        stats["eligible"] += 1
        missing_targets = [target for target in targets if not has_translation_section(body, target)]
        if not missing_targets:
            stats["already_translated"] += 1
            continue
        stats["missing"] += 1
        item = {
            "path": str(rel),
            "title": title_for(meta, body, rel.stem),
            "source_language": source_language,
            "target_languages": targets,
            "missing_targets": missing_targets,
            "source_chars": len(source_text),
            "has_llm_full_translation": isinstance(meta.get("llm_full_translation"), dict),
            "modified": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(),
        }
        if len(items) < limit:
            items.append(item)
    return {
        "policy": {
            "mode": policy.get("mode"),
            "targets": policy.get("targets"),
            "fallback_on_failure": policy.get("fallback_on_failure"),
        },
        "stats": stats,
        "total": len(items),
        "items": items,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def chunks(text: str, max_chars: int) -> List[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]
    parts = re.split(r"(\n\n+)", text)
    out: List[str] = []
    cur = ""
    for part in parts:
        if len(cur) + len(part) > max_chars and cur.strip():
            out.append(cur.strip())
            cur = part
        else:
            cur += part
    if cur.strip():
        out.append(cur.strip())
    final: List[str] = []
    for part in out:
        if len(part) <= max_chars:
            final.append(part)
        else:
            final.extend(part[i:i + max_chars] for i in range(0, len(part), max_chars))
    return final


def translate_source(
    source_text: str,
    *,
    title: str,
    target_language: str,
    provider_name: str = "",
    chunk_chars: int = 3500,
) -> Tuple[str, List[Dict[str, Any]]]:
    llm = LLMService()
    flow = llm.config.flow("full_translation")
    max_chars = int(chunk_chars or flow.chunk_chars or 3500)
    target_name = "中文" if target_language == "zh" else "English"
    source_name = "英文" if target_language == "zh" else "中文"
    system = (
        "你是专业的 AI/软件工程技术翻译。输出忠实、准确、自然、可检索的中文。"
        if target_language == "zh"
        else "You are a professional AI/software engineering translator. Produce faithful, accurate, natural, searchable English."
    )
    outputs: List[str] = []
    meta: List[Dict[str, Any]] = []
    for index, chunk in enumerate(chunks(source_text, max_chars), 1):
        prompt = f"""请把下面{source_name}技术内容翻译成{target_name}。

要求：
- 忠实翻译，不总结、不扩写、不删减事实。
- 保留 Markdown 结构、代码、命令、URL、产品名、模型名和配置项。
- 只输出{target_name}译文，不要解释。

文章标题：{title}
分片：{index}

待翻译内容：
{chunk}
"""
        result = llm.chat(
            "full_translation",
            [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            provider_name=provider_name or None,
            options={"temperature": 0.1, "think": False},
        )
        if result.status != "ok":
            raise RuntimeError(result.error or f"translation chunk {index} failed")
        outputs.append((result.content or "").strip())
        item = result.to_dict()
        item.pop("content", None)
        item["chunk_index"] = index
        item["chunk_chars"] = len(chunk)
        meta.append(item)
    return "\n\n".join(part for part in outputs if part), meta


def upsert_translation_section(body: str, target_language: str, translated: str) -> str:
    title = section_title_for(target_language)
    stamp = f"> **Backfill translation time**: {datetime.now(timezone.utc).isoformat()}"
    section = f"## {title}\n\n{stamp}\n\n{translated.strip()}\n"
    pattern = rf"(?ms)^##\s*{re.escape(title)}\s*\n.*?(?=^##\s+|\Z)"
    if re.search(pattern, body):
        return re.sub(pattern, section.rstrip() + "\n\n", body, count=1)
    return body.rstrip() + "\n\n" + section


def run_backfill(
    base_dir: Path = KB_DIR,
    *,
    limit: int = 5,
    dry_run: bool = True,
    provider_name: str = "",
    paths: Optional[List[str]] = None,
) -> Dict[str, Any]:
    limit = max(1, min(int(limit or 5), 20))
    audit = audit_backfill(base_dir, limit=limit, paths=paths)
    results: List[Dict[str, Any]] = []
    if dry_run:
        return {
            "dry_run": True,
            "planned": len(audit["items"]),
            "applied": 0,
            "audit": audit,
            "results": [],
        }

    policy = load_translation_policy(base_dir)
    chunk_chars = int(policy.get("max_chunk_chars") or 3500)
    wiki_dir = base_dir / "wiki"
    for item in audit["items"][:limit]:
        rel = item["path"]
        target_language = item["missing_targets"][0]
        path = (wiki_dir / rel).resolve()
        text = path.read_text(encoding="utf-8", errors="ignore")
        meta, body = split_frontmatter(text)
        source_text = source_text_for(meta, body, base_dir)
        translated, chunk_meta = translate_source(
            source_text,
            title=item["title"],
            target_language=target_language,
            provider_name=provider_name,
            chunk_chars=chunk_chars,
        )
        new_body = upsert_translation_section(body, target_language, translated)
        first_chunk = chunk_meta[0] if chunk_meta else {}
        meta["llm_full_translation"] = {
            "flow": "full_translation",
            "provider": first_chunk.get("provider", provider_name),
            "model": first_chunk.get("model", ""),
            "status": first_chunk.get("status", "ok"),
            "source_language": item["source_language"],
            "target_language": target_language,
            "chunk_count": len(chunk_meta),
            "chunks": chunk_meta,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source": "translation_backfill",
        }
        path.write_text(write_frontmatter(meta, new_body), encoding="utf-8")
        results.append({
            "path": rel,
            "target_language": target_language,
            "provider": meta["llm_full_translation"]["provider"],
            "model": meta["llm_full_translation"]["model"],
            "chunk_count": len(chunk_meta),
            "changed": True,
        })
    return {
        "dry_run": False,
        "planned": len(audit["items"]),
        "applied": len(results),
        "audit": audit,
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit or backfill missing full translations")
    parser.add_argument("--base-dir", default=str(KB_DIR))
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--path", action="append", dest="paths", help="wiki-relative document path")
    parser.add_argument("--provider", default="", help="configured LLM provider id")
    parser.add_argument("--apply", action="store_true", help="call LLM and write changes")
    args = parser.parse_args()
    result = run_backfill(
        Path(args.base_dir).expanduser(),
        limit=args.limit,
        dry_run=not args.apply,
        provider_name=args.provider,
        paths=args.paths,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
