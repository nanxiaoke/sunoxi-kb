#!/usr/bin/env python3
"""Smoke checks for knowledge association and cleanup reporting."""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from association_report import build_report  # noqa: E402


def _write_doc(path: Path, title: str, source: str, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""---
title: "{title}"
source: "{source}"
category: "技术"
---

# {title}

> **来源**: {source}
> **分类**: 技术

## 📝 摘要
{body[:120]}

## 🔑 关键点
- {body[:80]}

## 🏷️ 实体与概念
OpenClaw, Agent, 知识库

## 📄 原始内容预览
{body}
""",
        encoding="utf-8",
    )


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="kb-association-smoke-"))
    try:
        body = "OpenClaw 知识库导入链路需要记录来源、模型和维护状态，用于后续质量检查。" * 8
        _write_doc(tmp / "wiki" / "articles" / "duplicate-a.md", "重复导入测试", "https://example.com/a", body)
        _write_doc(tmp / "wiki" / "articles" / "duplicate-b.md", "重复导入测试", "https://example.com/a", body)
        _write_doc(
            tmp / "wiki" / "articles" / "unique.md",
            "独立维护测试",
            "https://example.com/unique",
            "这是另一篇知识维护文章，主题不同，用来避免所有文档都被判为重复。" * 8,
        )

        report = build_report(tmp)
        groups = report.get("duplicate_groups", [])
        if not groups:
            raise AssertionError("expected duplicate groups")
        if report.get("summary", {}).get("duplicate_groups", 0) < 1:
            raise AssertionError("summary duplicate_groups not updated")
        if report.get("summary", {}).get("duplicate_docs", 0) < 2:
            raise AssertionError("summary duplicate_docs not updated")
        first = groups[0]
        if first.get("doc_count") != 2:
            raise AssertionError(f"expected 2 duplicate docs, got {first.get('doc_count')}")
        if first.get("type") not in {"content", "source", "title"}:
            raise AssertionError(f"unexpected duplicate type: {first.get('type')}")
        if not first.get("keep_suggestion"):
            raise AssertionError("missing keep suggestion")
        print("PASS association report smoke -> duplicate groups detected")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
