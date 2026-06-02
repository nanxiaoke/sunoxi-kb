#!/usr/bin/env python3
"""候选内容翻译与双语入库工具。

核心策略：
- 候选入池阶段先生成中文预览（标题/摘要/主题），用于质量评级和人工审核。
- A/B 候选入库前生成完整中文译文。
- 原文永不覆盖；译文 sidecar 缓存；入库时中文在前、英文在后。
- 通过 llm_runtime.yaml 的 FlowPolicy 决定本地/在线/fallback 策略。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

KB_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KB_DIR / "scripts"))

from llm_service import LLMService  # type: ignore
from translation_policy import (
    detect_language,
    section_title_for,
    source_label_for,
)

DEFAULT_TERM_GUIDE = """
翻译规则：
1. 忠实翻译，不总结、不扩写、不删减事实。
2. 技术术语首次出现尽量中英并列；后续保持术语一致。
3. 产品名、模型名、公司名、论文名、项目名、URL、代码、命令、配置项、版本号不翻译。
4. 保留 Markdown 结构、列表、引用和链接；不要把链接改坏。
5. RSS 摘要只按摘要逐句翻译，不补充原文没有的信息。
""".strip()


class CandidateTranslator:
    def __init__(self, base_dir: Path = KB_DIR):
        self.base_dir = base_dir.resolve()
        self.translation_dir = self.base_dir / "raw" / "candidate_translations"
        self.translation_dir.mkdir(parents=True, exist_ok=True)
        self.terms = self._load_json(self.base_dir / "translation_terms.json", {})
        self.llm = LLMService()

    def _load_json(self, path: Path, default: Any) -> Any:
        try:
            if path.exists():
                return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
        return default

    def _term_guide(self) -> str:
        terms = self.terms.get("terms", {}) if isinstance(self.terms, dict) else {}
        protected = self.terms.get("do_not_translate", []) if isinstance(self.terms, dict) else []
        lines = [DEFAULT_TERM_GUIDE]
        if terms:
            lines.append("\n术语表（必须尽量遵守）：")
            for k, v in list(terms.items())[:80]:
                lines.append(f"- {k} => {v}")
        if protected:
            lines.append("\n以下专名不要翻译：" + ", ".join(protected[:80]))
        return "\n".join(lines)

    def _flow_options(self, flow_name: str, defaults: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        policy = self.llm.config.flow(flow_name)
        options = dict(defaults or {})
        options.update(policy.options)
        return options

    def translation_path(self, cid: str, target_language: str = "zh") -> Path:
        suffix = "en" if target_language == "en" else "zh"
        return self.translation_dir / f"{cid}_{suffix}.json"

    def load_translation(self, cid: str, target_language: str = "zh") -> Optional[Dict[str, Any]]:
        p = self.translation_path(cid, target_language)
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _save_translation(self, cid: str, data: Dict[str, Any], target_language: str = "zh") -> Dict[str, Any]:
        self.translation_path(cid, target_language).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return data

    def _hash_text(self, text: str) -> str:
        return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]

    def _strip_candidate_header(self, content: str) -> str:
        text = content.strip()
        text = re.sub(r"^#\s+.*?\n", "", text, count=1).strip()
        text = re.sub(r"^日期:.*?\n\n---\n\n", "", text, count=1, flags=re.S).strip()
        return text

    def _chunks(self, text: str, max_chars: int) -> List[str]:
        text = text.strip()
        if not text:
            return []
        if len(text) <= max_chars:
            return [text]
        parts = re.split(r"(\n\n+)", text)
        chunks, cur = [], ""
        for part in parts:
            if len(cur) + len(part) > max_chars and cur.strip():
                chunks.append(cur.strip())
                cur = part
            else:
                cur += part
        if cur.strip():
            chunks.append(cur.strip())
        final = []
        for c in chunks:
            if len(c) <= max_chars:
                final.append(c)
            else:
                for i in range(0, len(c), max_chars):
                    final.append(c[i:i + max_chars])
        return final

    def _chat_json(self, section: str, messages: List[Dict[str, str]], options: Dict[str, Any]) -> Dict[str, Any]:
        result = self.llm.json_chat(section, messages, options=options)
        if result.status != "ok":
            raise RuntimeError(result.error or f"LLM call failed for {section}")
        text = result.content
        cleaned = (text or "").strip()
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.S).strip()
        return json.loads(cleaned)

    def _translate_text_detailed(self, text: str, *, title: str = "", section: str = "full_translation", target_language: str = "zh") -> tuple[str, List[Dict[str, Any]]]:
        policy = self.llm.config.flow(section)
        cfg = policy.options
        chunk_chars = int(policy.chunk_chars or cfg.get("chunk_chars") or cfg.get("max_chars") or 3500)
        target_name = "中文" if target_language == "zh" else "English"
        source_name = "英文" if target_language == "zh" else "中文"
        system = (
            "你是专业的 AI/软件工程技术翻译，输出忠实、准确、自然、可检索的中文。"
            if target_language == "zh"
            else "You are a professional AI/software engineering translator. Produce faithful, accurate, natural, searchable English."
        )
        outputs = []
        chunk_meta = []
        for i, chunk in enumerate(self._chunks(text, chunk_chars), 1):
            prompt = f"""请把下面{source_name}技术内容翻译成{target_name}。严格遵守规则：

{self._term_guide()}

文章标题：{title}
分片：{i}

待翻译内容：
{chunk}

请只输出{target_name}译文，不要输出解释。"""
            messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ]
            options = {
                "temperature": cfg.get("temperature", 0.1),
                "think": bool(cfg.get("think", False)),
            }
            if cfg.get("num_predict"):
                options["num_predict"] = int(cfg.get("num_predict"))
            result = self.llm.chat(section, messages, options=options)
            if result.status != "ok":
                raise RuntimeError(result.error or f"LLM call failed for {section}")
            translated = result.content
            outputs.append((translated or "").strip())
            meta = result.to_dict()
            meta.pop("content", None)
            meta["chunk_index"] = i
            meta["chunk_chars"] = len(chunk)
            chunk_meta.append(meta)
        return "\n\n".join(o for o in outputs if o), chunk_meta

    def _translate_text(self, text: str, *, title: str = "", section: str = "full_translation", target_language: str = "zh") -> str:
        translated, _chunk_meta = self._translate_text_detailed(text, title=title, section=section, target_language=target_language)
        return translated

    def translate_preview_candidate(self, item: Dict[str, Any], content: str, *, force: bool = False) -> Dict[str, Any]:
        """候选入池阶段轻量翻译：中文标题、中文摘要、中文主题，用于质量评级。"""
        cid = item["id"]
        source_hash = self._hash_text(content)
        existing = self.load_translation(cid)
        if existing and existing.get("source_hash") == source_hash and existing.get("preview") and not force:
            return existing

        body = self._strip_candidate_header(content)
        policy = self.llm.config.flow("candidate_preview")
        cfg = policy.options
        max_chars = int(policy.chunk_chars or cfg.get("max_chars", 1600))
        prompt = f"""请为下面英文候选内容生成中文审核预览，用于知识库候选池质量评级。

{self._term_guide()}

必须输出 JSON，不要输出 Markdown 代码块。字段：
- translated_title: 中文标题，保留关键英文术语/产品名
- translated_summary: 中文摘要，忠实翻译/概括原文已有信息，不添加原文没有的信息，80-200字
- topics: 3-8个中文主题标签，数组
- key_terms: 3-10个关键术语，数组，尽量中英并列
- language: 原文语言

原始标题：{item.get('title','')}
来源：{item.get('source_name','')}
原文内容：
{body[:max_chars]}
"""
        messages = [
            {"role": "system", "content": "你是技术知识库的候选内容翻译与审核助手，只输出严格 JSON。"},
            {"role": "user", "content": prompt},
        ]
        try:
            options = {
                "temperature": cfg.get("temperature", 0.1),
                "think": bool(cfg.get("think", False)),
                "num_predict": int(cfg.get("num_predict", 700)),
            }
            preview_result = self.llm.json_chat("candidate_preview", messages, options=options)
            if preview_result.status != "ok":
                raise RuntimeError(preview_result.error or "candidate preview translation failed")
            preview = json.loads(preview_result.content)
            preview_model = preview_result.model
            preview_provider = preview_result.provider
            preview_fallback = preview_result.to_dict()
        except Exception:
            # 兜底：普通翻译，避免候选池完全无中文
            summary = self._translate_text(body[:max_chars], title=item.get("title", ""), section="candidate_preview", target_language="zh")
            title_zh = self._translate_text(item.get("title", ""), title=item.get("title", ""), section="candidate_preview", target_language="zh")
            preview = {
                "translated_title": title_zh,
                "translated_summary": summary,
                "topics": [],
                "key_terms": [],
                "language": "en",
            }
            preview_model = self.llm.config.provider(policy.providers[0]).model if policy.providers else "unknown"
            preview_provider = policy.providers[0] if policy.providers else "unknown"
            preview_fallback = {"status": "fallback_plain_translation"}

        result = existing or {}
        result.update({
            "id": cid,
            "source_hash": source_hash,
            "preview_translated_at": datetime.now(timezone.utc).isoformat(),
            "preview_provider": preview_provider,
            "preview_model": preview_model,
            "preview_llm_result": preview_fallback,
            "translation_policy": self._term_guide(),
            "original_title": item.get("title", ""),
            "translated_title": (preview.get("translated_title") or item.get("title", "")).strip().lstrip("# "),
            "translated_summary": (preview.get("translated_summary") or "").strip(),
            "topics": preview.get("topics") or [],
            "key_terms": preview.get("key_terms") or [],
            "original_language": preview.get("language") or "en",
            "target_language": "zh-CN",
            "preview": True,
        })
        return self._save_translation(cid, result, "zh")

    def translate_candidate(self, item: Dict[str, Any], content: str, *, force: bool = False, target_language: str = "zh") -> Dict[str, Any]:
        """完整正文翻译。入库阶段复用 preview，并补齐 translated_content。"""
        cid = item["id"]
        source_hash = self._hash_text(content)
        target_language = "en" if target_language == "en" else "zh"
        existing = self.load_translation(cid, target_language)
        if existing and existing.get("source_hash") == source_hash and existing.get("translated_content") and not force:
            return existing
        if target_language == "zh" and (not existing or existing.get("source_hash") != source_hash):
            existing = self.translate_preview_candidate(item, content, force=force)
        elif not existing:
            existing = {
                "id": cid,
                "source_hash": source_hash,
                "original_title": item.get("title", ""),
                "original_language": detect_language(content),
                "target_language": "en",
                "preview": False,
            }

        body = self._strip_candidate_header(content)
        translated_content, full_chunks = self._translate_text_detailed(body, title=item.get("title", ""), section="full_translation", target_language=target_language)
        policy = self.llm.config.flow("full_translation")
        first_chunk = full_chunks[0] if full_chunks else {}
        provider_name = first_chunk.get("provider") or (policy.providers[0] if policy.providers else "")
        model_name = first_chunk.get("model") or (self.llm.config.provider(provider_name).model if provider_name else "unknown")
        existing.update({
            "source_hash": source_hash,
            "translated_at": datetime.now(timezone.utc).isoformat(),
            "provider": provider_name,
            "model": model_name,
            "full_llm_result": first_chunk,
            "full_llm_chunks": full_chunks,
            "translated_content": translated_content,
            "full": True,
            "target_language": "zh-CN" if target_language == "zh" else "en",
        })
        return self._save_translation(cid, existing, target_language)

    def build_bilingual_markdown(self, item: Dict[str, Any], original_content: str, translation: Dict[str, Any]) -> str:
        target_language = "en" if str(translation.get("target_language") or "").lower().startswith("en") else "zh"
        source_language = detect_language(original_content)
        title_main = translation.get("translated_title") if target_language == "zh" else item.get("title")
        title_main = title_main or item.get("title") or translation.get("original_title") or "Untitled"
        title_original = item.get("title") or translation.get("original_title") or "Untitled"
        source = item.get("source_name") or item.get("author") or "unknown"
        url = item.get("url") or ""
        publish_time = item.get("publish_time") or ""
        translated_content = translation.get("translated_content") or translation.get("translated_summary") or ""
        topics = translation.get("topics") or []
        key_terms = translation.get("key_terms") or []
        section_title = section_title_for(target_language)
        original_title_label = "原文标题" if target_language == "zh" else "Original title"
        source_label = source_label_for(source_language)
        language_label = "中文译文 + 英文原文" if target_language == "zh" else "English translation + 中文原文"
        return f"""# {title_main}

> {original_title_label}: {title_original}
> 来源: {source}
> 发布时间: {publish_time}
> 链接: {url}
> 语言: {language_label}
> 翻译模型: {translation.get('model') or translation.get('preview_model') or 'unknown'}
> 中文主题: {', '.join(topics)}
> 关键术语: {', '.join(key_terms)}

## {section_title}

{translated_content}

## {source_label}

{original_content.strip()}
""".strip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="候选内容翻译工具")
    parser.add_argument("candidate_id")
    parser.add_argument("--base-dir", default=str(KB_DIR))
    parser.add_argument("--preview", action="store_true", help="只生成候选池中文预览")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    from candidate_manager import CandidateManager  # type: ignore
    base_dir = Path(args.base_dir).expanduser()
    cm = CandidateManager(base_dir)
    item = cm.get_candidate(args.candidate_id)
    if not item:
        raise SystemExit(f"candidate not found: {args.candidate_id}")
    translator = CandidateTranslator(base_dir)
    if args.preview:
        result = translator.translate_preview_candidate(item, item.get("content", ""), force=args.force)
    else:
        result = translator.translate_candidate(item, item.get("content", ""), force=args.force)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
