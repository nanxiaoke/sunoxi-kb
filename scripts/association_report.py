#!/usr/bin/env python3
"""知识关联增强报告。

输出：reports/knowledge-associations-latest.json
- 每篇真实文档的相关文档推荐
- 孤立文档
- 弱关联文档
- 热门实体/分类统计
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

KB_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KB_DIR / "scripts"))

from wiki_linker import WikiLinker  # type: ignore
from linter import KBLinter  # type: ignore

GENERATED_NAMES = {"00_INDEX.md", "DOCUMENTS.md"}

GENERIC_RELATION_TERMS = {
    "AI", "人工智能", "模型", "LLM", "Agent", "AI Agent", "工作流",
    "技术", "文章", "教程", "Google", "Claude", "OpenClaw",
}


def classify_link_suggestion(suggestion: Dict[str, Any]) -> Dict[str, Any]:
    """把候选补链分成自动补链/推荐展示/低置信。

    原则：自动写入正文必须保守，只接受高分且有具体共享主题的关系；
    仅共享 AI/Agent/模型 这类大词的关系只做 UI 推荐，不污染正文内链。
    """
    shared = [str(x).strip() for x in suggestion.get("shared_entities", []) if str(x).strip()]
    specific_shared = [x for x in shared if x not in GENERIC_RELATION_TERMS and len(x) >= 3]
    score = int(suggestion.get("score", 0) or 0)

    enriched = dict(suggestion)
    enriched["specific_shared_entities"] = specific_shared

    if score >= 10 and specific_shared:
        enriched["action"] = "auto_link"
        enriched["confidence"] = "high"
        enriched["reason"] = "高分且存在具体共享实体，适合写入相关文档/正文内链"
    elif score >= 5 or specific_shared:
        enriched["action"] = "recommend_only"
        enriched["confidence"] = "medium"
        enriched["reason"] = "有关联但证据不足以自动写入正文，适合在 UI 中推荐"
    else:
        enriched["action"] = "low_confidence"
        enriched["confidence"] = "low"
        enriched["reason"] = "主要由宽泛主题词触发，暂不建议补链"
    return enriched



def is_real_doc(path: str) -> bool:
    name = Path(path).name
    return name not in GENERATED_NAMES and not name.startswith("category_")


def normalize_related(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": doc.get("id"),
        "path": doc.get("path"),
        "title": doc.get("title"),
        "category": doc.get("category"),
        "score": doc.get("score", 0),
        "shared_entities": doc.get("shared_entities", []),
    }


def build_outgoing_map(linter: KBLinter) -> Dict[str, set[str]]:
    """从 lint 链接结果生成 src -> target_rel_path 集合。

    只统计解析成功的内部链接，用于识别“高相关但尚未互链”的建议。
    """
    outgoing: Dict[str, set[str]] = {rel: set() for rel in linter.rel_paths}
    for link in linter.links:
        src = link.get("src")
        raw_target = str(link.get("target_raw") or "").strip().lstrip("/")
        if not src or not raw_target:
            continue
        candidates = [raw_target]
        if not raw_target.endswith(".md"):
            candidates.append(f"{raw_target}.md")
        src_path = Path(src)
        candidates.extend([
            (src_path.parent / raw_target).as_posix(),
            (src_path.parent / f"{raw_target}.md").as_posix() if not raw_target.endswith(".md") else raw_target,
        ])
        for cand in candidates:
            if cand in linter.rel_paths:
                outgoing.setdefault(src, set()).add(cand)
                break
    return outgoing


def build_report(base_dir: Path = KB_DIR, max_related: int = 8) -> Dict[str, Any]:
    linker = WikiLinker(base_dir)
    linker.build_index()
    linker.save_index()

    linter = KBLinter(base_dir)
    linter._collect_files()
    linter._scan_links()
    linter._analyze()

    outgoing_map = build_outgoing_map(linter)

    docs = []
    weak_docs = []
    missing_cross_links = []
    auto_link_candidates = []
    recommendation_only_links = []
    low_confidence_links = []
    for doc_id, info in sorted(linker.doc_index.items(), key=lambda kv: kv[1].get("title", "")):
        if not is_real_doc(info.get("path", "")):
            continue
        related = [normalize_related(r) for r in linker.find_related_documents(doc_id, max_related=max_related)]
        incoming = sorted(linter.incoming.get(info.get("path", ""), []))
        outgoing = outgoing_map.get(info.get("path", ""), set())
        raw_suggestions = [
            r for r in related
            if r.get("path") not in outgoing and r.get("score", 0) >= 3
        ][:5]
        suggestions = []
        for suggestion in raw_suggestions[:3]:
            enriched = classify_link_suggestion({
                "source_path": info.get("path"),
                "source_title": info.get("title"),
                "target_path": suggestion.get("path"),
                "target_title": suggestion.get("title"),
                "score": suggestion.get("score", 0),
                "shared_entities": suggestion.get("shared_entities", []),
            })
            suggestions.append(enriched)
            missing_cross_links.append(enriched)
            if enriched["action"] == "auto_link":
                auto_link_candidates.append(enriched)
            elif enriched["action"] == "recommend_only":
                recommendation_only_links.append(enriched)
            else:
                low_confidence_links.append(enriched)

        row = {
            "id": doc_id,
            "path": info.get("path"),
            "title": info.get("title"),
            "category": info.get("category"),
            "entities": info.get("entities", [])[:20],
            "tags": info.get("tags", [])[:20],
            "incoming_count": len(incoming),
            "incoming": incoming[:20],
            "outgoing_count": len(outgoing),
            "related_count": len(related),
            "related": related,
            "link_suggestions": suggestions,
        }
        docs.append(row)
        # 弱关联只标记真正需要处理的文档：完全没人指向，或没有任何出入链/推荐。
        # 对小型知识库，不强行要求每篇文档至少有2个语义近邻，否则会把独立主题误判为问题。
        if len(incoming) == 0:
            weak_docs.append(row)

    orphans = []
    for rel_path, sources in linter.incoming.items():
        if not is_real_doc(rel_path):
            continue
        if len(sources) == 0:
            info = next((d for d in docs if d["path"] == rel_path), None)
            orphans.append(info or {"path": rel_path, "incoming_count": 0})

    entity_stats = sorted(
        [{"entity": k, "doc_count": len(v), "docs": sorted(v)[:10]} for k, v in linker.entity_index.items()],
        key=lambda x: x["doc_count"],
        reverse=True,
    )[:50]

    category_stats = sorted(
        [{"category": k, "doc_count": len(v)} for k, v in linker.category_index.items()],
        key=lambda x: x["doc_count"],
        reverse=True,
    )

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "base_dir": str(base_dir),
        "summary": {
            "docs": len(docs),
            "orphans": len(orphans),
            "weak_docs": len(weak_docs),
            "broken_links": len(linter.broken_links),
            "internal_links": len(linter.links),
            "entities": len(linker.entity_index),
            "categories": len(linker.category_index),
            "missing_cross_links": len(missing_cross_links),
            "auto_link_candidates": len(auto_link_candidates),
            "recommendation_only_links": len(recommendation_only_links),
            "low_confidence_links": len(low_confidence_links),
        },
        "orphans": orphans,
        "weak_docs": weak_docs,
        "docs": docs,
        "entity_stats": entity_stats,
        "category_stats": category_stats,
        "missing_cross_links": sorted(missing_cross_links, key=lambda x: x.get("score", 0), reverse=True)[:50],
        "auto_link_candidates": sorted(auto_link_candidates, key=lambda x: x.get("score", 0), reverse=True)[:50],
        "recommendation_only_links": sorted(recommendation_only_links, key=lambda x: x.get("score", 0), reverse=True)[:50],
        "low_confidence_links": sorted(low_confidence_links, key=lambda x: x.get("score", 0), reverse=True)[:50],
        "broken_links": linter.broken_links,
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="生成知识关联报告")
    parser.add_argument("--base-dir", default=str(KB_DIR))
    parser.add_argument("--max-related", type=int, default=8)
    args = parser.parse_args()
    base_dir = Path(args.base_dir).expanduser().resolve()
    report = build_report(base_dir, max_related=args.max_related)
    out_dir = base_dir / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "knowledge-associations-latest.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": "ok", "report": str(out), "summary": report["summary"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
