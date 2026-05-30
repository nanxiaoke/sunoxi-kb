#!/usr/bin/env python3
"""Focused smoke checks for search and extractive QA quality.

The checks use the current wiki corpus and do not call any LLM provider.
They are intended to catch regressions in keyword recall, matched snippets,
metadata cleanup, and extractive answer grounding.
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

from qa import KnowledgeBaseQA  # noqa: E402
from search import WikiSearcher  # noqa: E402


@dataclass(frozen=True)
class SmokeCase:
    query: str
    title_any: tuple[str, ...]
    answer_all: tuple[str, ...] = ()
    answer_any: tuple[str, ...] = ()
    forbidden: tuple[str, ...] = ()
    require_snippet: bool = True
    min_score: float = 1.0
    max_docs: int = 4


CASES = [
    SmokeCase(
        query="什么是harness",
        title_any=("Agent Harness", "Harness Engineering"),
        answer_any=("Harness", "harness", "支架"),
        forbidden=("文件哈希", "提取方法", "公众号biz"),
    ),
    SmokeCase(
        query="横纵分析法是什么",
        title_any=("深度研究Prompt", "深度研究 Prompt"),
        answer_all=("两条轴", "纵向", "横向"),
        forbidden=("文件哈希", "提取方法", "公众号biz", "抓取时间"),
    ),
    SmokeCase(
        query="CC Switch 是什么",
        title_any=("CC Switch", "51K星标", "一键切换所有模型"),
        answer_any=("CC Switch", "模型", "切换"),
        forbidden=("文件哈希", "提取方法", "公众号biz"),
    ),
    SmokeCase(
        query="模型切换问题",
        title_any=("CC Switch", "51K星标", "一键切换所有模型"),
        answer_any=("模型", "切换", "provider", "路由"),
        forbidden=("文件哈希", "提取方法", "公众号biz"),
    ),
]


def _contains_any(text: str, terms: Iterable[str]) -> bool:
    lower = text.lower()
    return any(term.lower() in lower for term in terms)


def _missing_all(text: str, terms: Iterable[str]) -> list[str]:
    lower = text.lower()
    return [term for term in terms if term.lower() not in lower]


def _compact(text: str, limit: int = 130) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text[:limit] + ("..." if len(text) > limit else "")


def check_search(searcher: WikiSearcher, case: SmokeCase) -> list[str]:
    errors: list[str] = []
    results = searcher.search(case.query, limit=5)
    if not results:
        return [f"{case.query}: no search results"]

    top = results[0]
    title = top.get("title", "")
    if not _contains_any(title, case.title_any):
        errors.append(
            f"{case.query}: unexpected top title {title!r}; expected one of {case.title_any}"
        )
    if float(top.get("score", 0)) < case.min_score:
        errors.append(f"{case.query}: top score too low: {top.get('score')}")

    snippets = top.get("matched_snippets") or []
    if case.require_snippet and not snippets:
        errors.append(f"{case.query}: top result has no matched snippets")
    if snippets:
        leaked = [term for term in case.forbidden if term in " ".join(snippets)]
        if leaked:
            errors.append(f"{case.query}: snippets leaked metadata terms: {leaked}")

    return errors


def check_qa(qa: KnowledgeBaseQA, case: SmokeCase) -> list[str]:
    errors: list[str] = []
    result = qa.answer_question(
        case.query,
        max_docs=case.max_docs,
        use_cache=False,
        answer_mode="extractive",
    )
    answer = result.get("answer", "")
    docs = result.get("documents") or []

    if result.get("answer_mode") != "extractive":
        errors.append(f"{case.query}: answer_mode={result.get('answer_mode')!r}")
    if not result.get("diagnostics", {}).get("query_tokens"):
        errors.append(f"{case.query}: QA diagnostics missing query tokens")
    if not docs:
        errors.append(f"{case.query}: QA returned no documents")
    elif not _contains_any(docs[0].get("title", ""), case.title_any):
        errors.append(
            f"{case.query}: unexpected QA top doc {docs[0].get('title')!r}; "
            f"expected one of {case.title_any}"
        )
    elif case.require_snippet and not docs[0].get("matched_snippets"):
        errors.append(f"{case.query}: QA document missing matched snippets")

    if case.answer_all:
        missing = _missing_all(answer, case.answer_all)
        if missing:
            errors.append(f"{case.query}: answer missing required terms: {missing}")
    if case.answer_any and not _contains_any(answer, case.answer_any):
        errors.append(f"{case.query}: answer missing any of {case.answer_any}")

    leaked = [term for term in case.forbidden if term in answer]
    if leaked:
        errors.append(f"{case.query}: answer leaked metadata terms: {leaked}")

    return errors


def run(base_dir: Path, rebuild: bool) -> int:
    searcher = WikiSearcher(base_dir)
    searcher.build_index(rebuild=rebuild)
    if not searcher.doc_index:
        print(f"FAIL: no indexed wiki documents under {base_dir / 'wiki'}")
        return 1

    qa = KnowledgeBaseQA(base_dir)

    failures: list[str] = []
    for case in CASES:
        search_errors = check_search(searcher, case)
        qa_errors = check_qa(qa, case)
        if search_errors or qa_errors:
            failures.extend(search_errors + qa_errors)
            print(f"FAIL {case.query}")
            for err in search_errors + qa_errors:
                print(f"  - {err}")
        else:
            top = searcher.search(case.query, limit=1)[0]
            print(f"PASS {case.query} -> {top.get('title')} (score={top.get('score')})")

    if failures:
        print(f"\n{len(failures)} search/QA smoke check(s) failed.")
        return 1

    print(f"\nAll {len(CASES)} search/QA smoke cases passed.")
    return 0


def run_synthetic_upload_case() -> int:
    """Check that newly imported/upload-style wiki pages are searchable and answerable."""
    with tempfile.TemporaryDirectory(prefix="kb-search-qa-") as tmp:
        base_dir = Path(tmp)
        wiki_dir = base_dir / "wiki" / "uploads"
        wiki_dir.mkdir(parents=True)
        (wiki_dir / "uploaded_model_routing_note.md").write_text(
            """---
title: Uploaded Model Routing Note
category: uploads
---
# Uploaded Model Routing Note

> **来源**: uploaded-test.txt
> **提取方法**: synthetic smoke
> **文件哈希**: deadbeef

## 摘要
上传文档说明 online_only 环境必须走 DeepSeek provider，不能回退到本地 Gemma。

## 关键点
1. online_only 模式只允许在线 provider。
2. 维护和上传处理都不能触发本地 Gemma。

## 📄 原始内容预览

在纯在线部署里，上传文件后的结构化处理需要使用 DeepSeek provider。
如果环境配置为 online_only，系统必须阻止 Gemma 或 Ollama 被调用。
这个规则用于避免没有本地模型的服务器在上传文件时卡住。
""",
            encoding="utf-8",
        )

        searcher = WikiSearcher(base_dir)
        searcher.build_index(rebuild=True)
        qa = KnowledgeBaseQA(base_dir)
        case = SmokeCase(
            query="上传文档 online_only 会不会调用 Gemma",
            title_any=("Uploaded Model Routing Note",),
            answer_all=("online_only", "DeepSeek", "Gemma"),
            forbidden=("文件哈希", "提取方法", "deadbeef"),
        )

        failures = check_search(searcher, case) + check_qa(qa, case)
        if failures:
            print("FAIL synthetic-upload")
            for failure in failures:
                print(f"  - {failure}")
            return 1
        print("PASS synthetic-upload -> Uploaded Model Routing Note")
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-dir", type=Path, default=BASE_DIR, help="KB project root")
    parser.add_argument("--rebuild", action="store_true", help="rebuild search_index.json before checks")
    parser.add_argument("--skip-synthetic", action="store_true", help="skip synthetic uploaded-document case")
    parser.add_argument("--verbose", action="store_true", help="show underlying search/QA logs")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    logging.getLogger().setLevel(logging.INFO if args.verbose else logging.WARNING)
    logging.getLogger("jieba").setLevel(logging.WARNING)
    status = run(args.base_dir.resolve(), rebuild=args.rebuild)
    if not args.skip_synthetic:
        status = max(status, run_synthetic_upload_case())
    return status


if __name__ == "__main__":
    raise SystemExit(main())
