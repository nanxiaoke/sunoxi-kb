#!/usr/bin/env python3
"""Non-network smoke checks for import metadata normalization."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from processor import DocumentProcessor  # noqa: E402
from batch_processor import BatchProcessor  # noqa: E402
from import_quality import clean_import_title, safe_import_stem  # noqa: E402


class DirtyLLM:
    model = "dirty-smoke-model"

    def summarize(self, text: str, max_length: int = 300) -> str:
        return "摘要：  这是一篇关于导入质量、分类规范化和实体抽取稳定性的测试文章。\n第二行不应破坏 frontmatter。"

    def extract_keypoints(self, text: str, num_points: int = 5) -> str:
        return "1. 导入流程需要稳定分类\n2. 生成的实体需要去重\n3. YAML frontmatter 不能被特殊字符破坏"

    def categorize(self, text: str) -> str:
        return "分类：技术文章 / AI 工具"

    def extract_entities(self, text: str) -> str:
        return "DeepSeek, Gemma, DeepSeek，Ollama / YAML; 导入质量"


def main() -> int:
    failures = []
    title = clean_import_title("标题：  DeepSeek 新能力 - 微信公众平台", fallback="x")
    if title != "DeepSeek 新能力":
        failures.append(f"shared title cleanup failed: {title}")
    if safe_import_stem("DeepSeek 新能力 - 微信公众平台", fallback="x") != "DeepSeek_新能力":
        failures.append("shared filename stem cleanup failed")

    with tempfile.TemporaryDirectory(prefix="kb-import-quality-") as tmp:
        base = Path(tmp)
        raw = base / "raw" / "uploads" / "dirty.txt"
        raw.parent.mkdir(parents=True)
        raw.write_text(
            "导入质量测试\n这篇文章提到 DeepSeek、Gemma、Ollama，以及 YAML frontmatter。",
            encoding="utf-8",
        )

        processor = DocumentProcessor(DirtyLLM())
        processor.base_dir = base
        processor.wiki_dir = base / "wiki"
        processor.outputs_dir = base / "outputs"
        processor.wiki_dir.mkdir(parents=True)
        processor.outputs_dir.mkdir(parents=True)

        doc_info = processor.read_document(raw)
        result = processor.process_document(doc_info)
        wiki_path = processor.save_to_wiki(result)
        text = wiki_path.read_text(encoding="utf-8")
        frontmatter = text.split("---", 2)[1]
        meta = yaml.safe_load(frontmatter)

        if result["category"] != "技术":
            failures.append(f"category not normalized: {result['category']}")
        if result["entities"].count("DeepSeek") != 1:
            failures.append(f"entities not deduped: {result['entities']}")
        if "技术" not in result["tags"]:
            failures.append(f"category tag missing: {result['tags']}")
        if meta.get("category") != "技术":
            failures.append(f"frontmatter category invalid: {meta.get('category')}")
        if "文件哈希" in text or "提取方法" in text:
            failures.append("metadata noise leaked into wiki")

    with tempfile.TemporaryDirectory(prefix="kb-batch-import-quality-") as tmp:
        base = Path(tmp)
        raw = base / "raw" / "webpages" / "dirty-web.md"
        raw.parent.mkdir(parents=True)
        (base / "wiki").mkdir(parents=True)
        raw.write_text(
            "# 标题：  Dirty Web Title - 微信公众平台\n\nDeepSeek、Gemma、Ollama 的导入质量测试。",
            encoding="utf-8",
        )
        bp = BatchProcessor(base)
        bp._llm_chat = lambda flow, prompt: (
            """## 摘要
摘要：  这是批处理导入的质量测试。

## 关键点
1. 需要稳定分类
2. 需要实体去重

## 分类
分类：技术文章 / AI 工具

## 实体
DeepSeek, Gemma, DeepSeek，Ollama""",
            {"flow": flow, "provider": "fake", "model": "fake-model", "status": "ok", "duration_sec": 0.01},
        )
        wiki_path = bp.process_file({"path": raw, "category": "webpages", "size": raw.stat().st_size})
        text = wiki_path.read_text(encoding="utf-8") if wiki_path else ""
        meta = yaml.safe_load(text.split("---", 2)[1]) if text else {}
        if meta.get("category") != "技术":
            failures.append(f"batch category not normalized: {meta.get('category')}")
        if text.count("DeepSeek") < 1 or "DeepSeek，" in text:
            failures.append("batch entities not normalized")
        if "微信公众平台" in text.splitlines()[2]:
            failures.append("batch title suffix not cleaned")

    if failures:
        print("FAIL import quality smoke")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    print("PASS import quality smoke -> normalized processor/batch metadata and frontmatter")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
