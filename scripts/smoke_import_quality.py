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
from candidate_manager import CandidateManager  # noqa: E402
from import_quality import clean_import_title, safe_import_stem  # noqa: E402
from translation_policy import load_translation_policy, should_translate_import, target_languages_for  # noqa: E402


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
        bp._translate_full_content = lambda content, title, source_language, target_language: (
            "Full English translation for bilingual search.",
            {
                "flow": "full_translation",
                "provider": "fake",
                "model": "fake-model",
                "status": "ok",
                "source_language": source_language,
                "target_language": target_language,
                "chunk_count": 1,
            },
        )
        wiki_path = bp.process_file({"path": raw, "category": "webpages", "size": raw.stat().st_size})
        text = wiki_path.read_text(encoding="utf-8") if wiki_path else ""
        meta = yaml.safe_load(text.split("---", 2)[1]) if text else {}
        if meta.get("category") != "技术":
            failures.append(f"batch category not normalized: {meta.get('category')}")
        if "## 🌍 English Translation" not in text:
            failures.append("batch bilingual English translation section missing")
        if meta.get("llm_full_translation", {}).get("target_language") != "en":
            failures.append(f"batch full translation meta invalid: {meta.get('llm_full_translation')}")
        if text.count("DeepSeek") < 1 or "DeepSeek，" in text:
            failures.append("batch entities not normalized")
        if "微信公众平台" in text.splitlines()[2]:
            failures.append("batch title suffix not cleaned")

    with tempfile.TemporaryDirectory(prefix="kb-translation-policy-") as tmp:
        base = Path(tmp)
        policy = load_translation_policy(base)
        if target_languages_for(policy, "zh") != ["en"]:
            failures.append("default policy should translate Chinese source to English")
        if target_languages_for(policy, "en") != ["zh"]:
            failures.append("default policy should translate English source to Chinese")
        if not should_translate_import(policy, path_key="url_import", source_language="zh"):
            failures.append("default policy should enable URL bilingual translation")
        if should_translate_import(policy, path_key="rss_candidate_preview", source_language="en"):
            failures.append("RSS candidate preview should not full-translate by default")
        if not should_translate_import(policy, path_key="candidate_import", source_language="en", candidate_tier="A"):
            failures.append("A-tier candidate import should full-translate by default")
        if should_translate_import(policy, path_key="candidate_import", source_language="en", candidate_tier="D"):
            failures.append("D-tier candidate import should not full-translate by default")

    with tempfile.TemporaryDirectory(prefix="kb-bilingual-skip-") as tmp:
        base = Path(tmp)
        raw = base / "raw" / "wechat_articles" / "already-bilingual.md"
        raw.parent.mkdir(parents=True)
        (base / "wiki").mkdir(parents=True)
        raw.write_text(
            "# 已双语\n\n## 🌍 English Translation\n\nAlready translated.\n\n## 中文原文\n\n这篇已经有英文译文。",
            encoding="utf-8",
        )
        bp = BatchProcessor(base)
        bp._llm_chat = lambda flow, prompt: (
            """## 摘要
这是已有双语内容。

## 关键点
1. 不应重复全文翻译

## 分类
技术

## 实体
Translation Policy""",
            {"flow": flow, "provider": "fake", "model": "fake-model", "status": "ok", "duration_sec": 0.01},
        )

        def fail_translate(*args, **kwargs):
            raise AssertionError("already bilingual import should not call full translation")

        bp._translate_full_content = fail_translate
        wiki_path = bp.process_file({"path": raw, "category": "wechat_articles", "size": raw.stat().st_size})
        if not wiki_path or "llm_full_translation" in wiki_path.read_text(encoding="utf-8"):
            failures.append("already bilingual raw content should skip full translation metadata")

    with tempfile.TemporaryDirectory(prefix="kb-candidate-policy-") as tmp:
        base = Path(tmp)
        cdir = base / "raw" / "wechat_candidates"
        cdir.mkdir(parents=True)
        (base / "wiki").mkdir(parents=True)
        md = cdir / "wechat-test.md"
        md.write_text(
            "# 中文候选\n\n这是一篇关于 AI Agent 和知识库检索的中文文章，需要英文用户也能搜索到。",
            encoding="utf-8",
        )
        meta = cdir / "wechat-test_meta.json"
        meta.write_text(
            """{
  "status": "candidate",
  "source_name": "smoke",
  "url": "https://example.com/wechat",
  "title": "中文候选",
  "candidate_path": "raw/wechat_candidates/wechat-test.md"
}""",
            encoding="utf-8",
        )

        import translator as translator_module  # noqa: E402

        original_translator = translator_module.CandidateTranslator

        class FakeCandidateTranslator:
            def __init__(self, base_dir: Path):
                self.base_dir = base_dir

            def translate_candidate(self, item, content, *, force=False, target_language="zh"):
                return {
                    "id": item["id"],
                    "source_hash": "fake",
                    "original_title": item.get("title"),
                    "original_language": "zh",
                    "target_language": target_language,
                    "translated_content": "English full translation for Chinese candidate search.",
                    "provider": "fake",
                    "model": "fake-model",
                    "full_llm_result": {"flow": "full_translation", "provider": "fake", "model": "fake-model", "status": "ok"},
                    "full_llm_chunks": [{"provider": "fake", "model": "fake-model", "status": "ok"}],
                    "full": True,
                }

            def build_bilingual_markdown(self, item, original_content, translation):
                return original_translator(self.base_dir).build_bilingual_markdown(item, original_content, translation)

        translator_module.CandidateTranslator = FakeCandidateTranslator
        try:
            cm = CandidateManager(base)
            cm.translation_policy["candidate_tiers"] = ["all"]
            item = cm.list_candidates(include_imported=False, include_skipped=False)[0]
            result = cm.import_candidate(item["id"], process=False, run_maintenance=False, translate=True)
            imported_text = (base / result["imported_to"]).read_text(encoding="utf-8")
            if "## 🌍 English Translation" not in imported_text:
                failures.append("wechat candidate import did not apply English full translation")
            if result.get("translation", {}).get("target_language") != "en":
                failures.append(f"wechat candidate translation meta target invalid: {result.get('translation')}")
        finally:
            translator_module.CandidateTranslator = original_translator

    if failures:
        print("FAIL import quality smoke")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    print("PASS import quality smoke -> normalized processor/batch metadata and frontmatter")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
