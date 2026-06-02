#!/usr/bin/env python3
"""
Karpathy 知识库候选池管理 —— 统一入口

扫描以下候选目录：
  raw/wechat_candidates  — 微信公众号候选
  raw/rss_candidates     — RSS订阅候选
  raw/webpage_candidates — 网页候选（预留）

功能：扫描、去重、质量评分、展示候选、确认导入、跳过。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from translation_policy import (
    detect_language,
    load_translation_policy,
    should_translate_import,
    target_languages_for,
)


class CandidateManager:
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir.resolve()
        self.raw_dir = self.base_dir / "raw"
        self.wiki_dir = self.base_dir / "wiki"
        self.article_dir = self.raw_dir / "wechat_articles"
        self.state_file = self.base_dir / "candidate_state.json"
        self.state = self._load_state()
        self._rss_source_meta = self._load_rss_source_meta()
        self._wiki_title_index = self._load_wiki_title_index()
        self.translation_policy = load_translation_policy(self.base_dir)

    def _candidate_dirs(self) -> List[Path]:
        """所有候选目录，按优先级排序"""
        dirs = [
            self.raw_dir / "wechat_candidates",
            self.raw_dir / "rss_candidates",
            self.raw_dir / "webpage_candidates",
        ]
        return [d for d in dirs if d.exists()]

    def _load_state(self) -> Dict[str, Any]:
        if self.state_file.exists():
            try:
                return json.loads(self.state_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {"version": 1, "items": {}}

    def _save_state(self) -> None:
        self.state_file.write_text(json.dumps(self.state, ensure_ascii=False, indent=2), encoding="utf-8")

    def _state_item(self, cid: str) -> Dict[str, Any]:
        return self.state.setdefault("items", {}).setdefault(cid, {})

    def _edited_meta(self, cid: str) -> Dict[str, Any]:
        item = self.state.get("items", {}).get(cid, {})
        return item.get("edited_metadata") or {}

    def _yaml_quote(self, value: str) -> str:
        return '"' + str(value or "").replace('"', '\"') + '"'

    def _apply_import_frontmatter(self, content: str, item: Dict[str, Any]) -> str:
        edited = item.get("edited_metadata") or {}
        title = edited.get("title") or item.get("translated_title") or item.get("title") or "Untitled"
        category = edited.get("category") or edited.get("preferred_category") or ""
        tags = edited.get("tags") or []
        if isinstance(tags, str):
            tags = [t.strip() for t in re.split(r"[,，;；]", tags) if t.strip()]
        lines = ["---", f"title: {self._yaml_quote(title)}"]
        if category:
            lines.append(f"category: {category}")
            lines.append(f"preferred_category: {category}")
        if tags:
            lines.append("tags:")
            for t in tags:
                lines.append(f"  - {t}")
        lines.extend([
            f"candidate_id: {item.get('id','')}",
            "reviewed: true",
            "---",
            "",
        ])
        return "\n".join(lines) + content.lstrip()

    def _extract_wiki_llm_meta(self, wiki_rel: Optional[str]) -> Dict[str, Any]:
        if not wiki_rel:
            return {}
        path = (self.wiki_dir / wiki_rel).resolve()
        try:
            if not str(path).startswith(str(self.wiki_dir.resolve())) or not path.exists():
                return {}
            text = path.read_text(encoding="utf-8", errors="ignore")
            if not text.startswith("---"):
                return {}
            parts = text.split("---", 2)
            if len(parts) < 3:
                return {}
            import yaml  # type: ignore
            meta = yaml.safe_load(parts[1]) or {}
            llm = meta.get("llm") if isinstance(meta, dict) else {}
            return llm if isinstance(llm, dict) else {}
        except Exception:
            return {}

    def _translation_import_meta(self, *, cid: str, item: Dict[str, Any], translation_result: Optional[Dict[str, Any]], translate: bool, should_full_translate: bool, target_language: str = "zh") -> Dict[str, Any]:
        reason = "disabled"
        if translate:
            reason = "policy_full_translation" if should_full_translate else "preview_only_or_skipped"
        preview_result = (translation_result or {}).get("preview_llm_result") or {}
        full_result = (translation_result or {}).get("full_llm_result") or {}
        full_chunks = (translation_result or {}).get("full_llm_chunks") or []
        suffix = "en" if target_language == "en" else "zh"
        return {
            "enabled": bool(translation_result),
            "requested": bool(translate),
            "full": bool(translation_result and translation_result.get("translated_content")),
            "decision": "full_translation" if should_full_translate else ("preview_only" if translate else "disabled"),
            "reason": reason,
            "target_language": target_language,
            "candidate_type": item.get("candidate_type"),
            "quality_tier": item.get("quality_tier"),
            "path": f"raw/candidate_translations/{cid}_{suffix}.json" if translation_result else None,
            "preview": {
                "flow": preview_result.get("flow", "candidate_preview"),
                "provider": (translation_result or {}).get("preview_provider") or preview_result.get("provider"),
                "model": (translation_result or {}).get("preview_model") or preview_result.get("model"),
                "status": preview_result.get("status"),
                "fallback_from": preview_result.get("fallback_from"),
                "fallback_to": preview_result.get("fallback_to"),
                "duration_sec": preview_result.get("duration_sec"),
            } if translation_result else None,
            "full_translation": {
                "flow": full_result.get("flow", "full_translation"),
                "provider": (translation_result or {}).get("provider") or full_result.get("provider"),
                "model": (translation_result or {}).get("model") or full_result.get("model"),
                "status": full_result.get("status"),
                "fallback_from": full_result.get("fallback_from"),
                "fallback_to": full_result.get("fallback_to"),
                "duration_sec": full_result.get("duration_sec"),
                "chunk_count": len(full_chunks),
                "chunks": full_chunks,
            } if translation_result and translation_result.get("translated_content") else None,
        }

    def _load_rss_source_meta(self) -> Dict[str, Dict[str, Any]]:
        """读取 RSS 源配置，用于来源权重/标签评分。"""
        path = self.base_dir / "rss_feeds.json"
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            result = {}
            for _, cfg in (data or {}).items():
                if not isinstance(cfg, dict):
                    continue
                name = cfg.get("name") or cfg.get("source_name")
                if name:
                    result[name.lower()] = cfg
            return result
        except Exception:
            return {}

    def _normalize_title(self, text: str) -> str:
        text = (text or "").lower()
        text = re.sub(r"[\s\W_]+", "", text, flags=re.UNICODE)
        return text[:160]

    def _load_wiki_title_index(self) -> set:
        """用于识别已入库重复内容。"""
        titles = set()
        if not self.wiki_dir.exists():
            return titles
        for p in self.wiki_dir.rglob("*.md"):
            if p.name in {"00_INDEX.md", "DOCUMENTS.md"} or p.name.startswith("category_"):
                continue
            title = self._read_title(p)
            norm = self._normalize_title(title)
            if norm:
                titles.add(norm)
        return titles

    def _file_hash(self, path: Path) -> str:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()[:16]

    def _candidate_id(self, md_path: Path, meta: Dict[str, Any]) -> str:
        if meta.get("url"):
            return hashlib.sha256(meta["url"].encode("utf-8")).hexdigest()[:16]
        return self._file_hash(md_path)

    def _load_meta_for(self, md_path: Path) -> Dict[str, Any]:
        """尝试从同级目录读取 *_meta.json"""
        suffix = md_path.name.rsplit("_", 1)[-1].replace(".md", "") if "_" in md_path.name else ""
        candidates = []
        if suffix:
            candidates.append(md_path.with_name(f"{suffix}_meta.json"))
        candidates.extend(md_path.parent.glob("*_meta.json"))
        for p in candidates:
            if not p.exists():
                continue
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                if data.get("candidate_path") == str(md_path.relative_to(self.base_dir)) or data.get("title") in md_path.stem:
                    data["_meta_path"] = str(p.relative_to(self.base_dir))
                    return data
            except Exception:
                continue
        return {"_meta_path": None}

    def _read_title(self, md_path: Path) -> str:
        try:
            for line in md_path.read_text(encoding="utf-8", errors="ignore").splitlines()[:20]:
                if line.startswith("# "):
                    return line[2:].strip()
        except Exception:
            pass
        return md_path.stem

    def _parse_datetime(self, value: str) -> Optional[datetime]:
        if not value:
            return None
        try:
            dt = parsedate_to_datetime(value)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            pass
        for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(value[:25], fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc)
            except Exception:
                continue
        return None

    def _content_depth_analysis(self, text: str) -> Dict[str, Any]:
        """内容深度分析：检测点击诱饵、信息密度、列表文章等。"""
        t = text or ""
        lower = t.lower()
        result = {"clickbait": 0, "listicle": 0, "info_density": 0, "signals": []}
        lines = t.strip().split('\n')
        non_empty = [l for l in lines if len(l.strip()) > 5]
        total_lines = len(non_empty)
        avg_line_len = sum(len(l) for l in non_empty) / max(total_lines, 1)

        clickbait_phrases = [
            "you won't believe", "mind blown", "game changer", "the secret", "you need to know",
            "彻底颠覆", "惊为天人", "99%的人不知道", "太震撼了", "没想到", "后悔没早",
            "必看", "手慢无", "再不x就晚了", "一定不能错过", "看完彻底懂了"
        ]
        for phrase in clickbait_phrases:
            if phrase in lower:
                result["clickbait"] += 1
                result["signals"].append(f"clickbait:{phrase}")
        if sum(1 for c in lower if c == '!') >= 5:
            result["clickbait"] += 2
            result["signals"].append("excessive_exclamation")

        list_items = len(re.findall(r'^\d+[.、)\、]\s+|^[-*\u2022]\s+', t, re.MULTILINE))
        if list_items >= 8:
            result["listicle"] += 8
            result["signals"].append(f"listicle:{list_items}items")
        elif list_items >= 4:
            result["listicle"] += 4
            result["signals"].append(f"semi-listicle:{list_items}items")

        sentences = re.split(r'[\u3002\uff01\uff1f.!?]', ''.join(l for l in non_empty if len(l.strip()) > 10)[:5000])
        if sentences:
            avg_sent_len = sum(len(s) for s in sentences) / max(len(sentences), 1)
            if 25 <= avg_sent_len <= 80:
                result["info_density"] = 12
                result["signals"].append(f"good_density:avg{avg_sent_len:.0f}")
            elif avg_sent_len < 18:
                result["info_density"] = -6
                result["signals"].append(f"low_density:avg{avg_sent_len:.0f}")
            elif avg_sent_len > 120:
                result["info_density"] = 4
                result["signals"].append(f"dense:avg{avg_sent_len:.0f}")

        code_blocks = len(re.findall(r'```|`[^`]+`', t))
        if code_blocks >= 3:
            result["info_density"] += 6
            result["signals"].append(f"code_blocks:{code_blocks}")

        first_line = lines[0].strip() if lines else ""
        if len(first_line) < 8:
            result["clickbait"] += 1
            result["signals"].append("short_title")

        return result

    def _kb_relevance(self, content_text: str, title: str) -> Dict[str, Any]:
        """评估候选内容与现有知识库实体的重叠度。"""
        text = f"{title} {content_text[:3000]}".lower()
        score = 0
        matches = []
        try:
            idx_path = self.base_dir / "search_index.json"
            if idx_path.exists():
                idx = json.loads(idx_path.read_text(encoding="utf-8"))
                entity_terms = set(k.lower() for k in idx.get("entity_index", {}).keys() if len(k) >= 3)
                for term in entity_terms:
                    if term in text:
                        score += 2
                        matches.append(term)
                fulltext = idx.get("fulltext_index", {})
                doc_count = len(idx.get("doc_index", {})) or 1
                common = set(k for k, v in fulltext.items() if len(v) > doc_count * 0.3 and len(k) >= 3)
                for term in common:
                    if term in text:
                        score += 1
                        matches.append(term)
        except Exception:
            pass
        if not matches:
            fallback = ["ai", "agent", "llm", "model", "rag", "prompt", "embedding",
                        "mcp", "deepseek", "openai", "anthropic", "knowledge", "data",
                        "\u4eba\u5de5\u667a\u80fd", "\u5927\u6a21\u578b", "\u667a\u80fd\u4f53", "\u77e5\u8bc6\u5e93", "\u63a8\u7406"]
            for term in fallback:
                if term in text:
                    score += 1
                    matches.append(term)
        score = min(score, 30)
        return {"kb_relevance": score, "matched_entities": list(dict.fromkeys(matches))[:12]}

    def _score_candidate(self, item: Dict[str, Any], duplicate_titles: Dict[str, int]) -> Dict[str, Any]:
        """候选质量评分 v2：增加内容深度分析 + KB 实体相关性。"""
        title = item.get("title", "") or ""
        translated_title = item.get("translated_title") or ""
        translated_summary = item.get("translated_summary") or ""
        translated_topics = item.get("translated_topics") or []
        source_name = item.get("source_name", "") or ""
        ctype = item.get("candidate_type", "other")
        length = int(item.get("content_length") or 0)
        text = f"{title} {translated_title} {translated_summary} {' '.join(translated_topics)} {source_name} {item.get('author','')}".lower()

        # 获取正文内容（从path读取）
        content_body = ""
        try:
            rel_path = item.get("path", "")
            if rel_path:
                fp = (self.base_dir / rel_path).resolve()
                if str(fp).startswith(str(self.base_dir)) and fp.exists():
                    content_body = fp.read_text(encoding="utf-8", errors="ignore")[:8000]
        except Exception:
            content_body = ""

        score = 0
        reasons: List[str] = []
        penalties: List[str] = []
        factors = []  # per-factor breakdown for UI
        state = item.get("state") or {}
        if item.get("status") == "imported" or state.get("status") == "imported":
            return {
                "score": 100,
                "tier": "A",
                "recommendation": "已入库/已审核，视为A级基准内容",
                "reasons": ["用户已审核并入库"],
                "penalties": [],
                "factors": [{"name": "已审核入库", "score": 100, "max": 100}],
                "duplicate_risk": "reviewed_imported",
                "source_priority": "reviewed",
                "topic_hits": [],
            }

        # 内容类型基础分：微信公众号一般是人工筛选来源；RSS 噪声更大。
        source_base = 36
        if ctype == "wechat":
            source_base = 58; reasons.append("微信公众号候选：人工来源基础分高")
        elif ctype == "rss":
            source_base = 42; reasons.append("RSS候选：需质量筛选")
        else:
            source_base = 36; reasons.append("其他候选来源")
        score += source_base; factors.append({"name": "来源类型", "score": source_base, "max": 58})

        # 来源优先级。
        source_cfg = self._rss_source_meta.get(source_name.lower(), {})
        priority = (source_cfg.get("priority") or "medium").lower()
        if priority == "high":
            score += 18; reasons.append("高优先级来源"); factors.append({"name": "来源优先级", "score": 18, "max": 18})
        elif priority == "medium":
            score += 10; reasons.append("中优先级来源"); factors.append({"name": "来源优先级", "score": 10, "max": 18})
        elif priority == "low":
            score += 2; reasons.append("低优先级来源"); factors.append({"name": "来源优先级", "score": 2, "max": 18})

        # 内容深度分析：检测点击诱饵、低信息密度、列表文章等。
        if content_body:
            depth = self._content_depth_analysis(content_body)
            if depth["info_density"] != 0:
                score += depth["info_density"]
                if depth["info_density"] > 0:
                    reasons.append(f"信息密度/depth贡献:{depth['info_density']}")
                else:
                    penalties.append(f"低信息密度(depth:{depth['info_density']})")
                factors.append({"name": "内容深度", "score": depth["info_density"], "max": 18})
            if depth["listicle"] > 0:
                score -= min(depth["listicle"], 10)
                penalties.append(f"列表/列举文章 (listicle:{depth['listicle']})")
                factors.append({"name": "列表文章", "score": -min(depth["listicle"], 10), "max": 0})
            if depth["clickbait"] > 0:
                penalty = min(depth["clickbait"], 12)
                score -= penalty
                penalties.append(f"疑似标题党/内容信号 (clickbait:{depth['clickbait']})")
                factors[-1] = {"name": "标题党风险", "score": -penalty, "max": 0}

        # KB 相关性：候选内容与现有知识库的实体/术语重叠度。
        kb = self._kb_relevance(content_body or text, title)
        if kb["kb_relevance"] > 0:
            score += kb["kb_relevance"]
            reasons.append(f"知识库实体相关性: +{kb['kb_relevance']} ({len(kb['matched_entities'])}个术语)")
            factors.append({"name": "KB相关性", "score": kb["kb_relevance"], "max": 30})

        # 内容长度：太短通常只是摘要，不适合直接入库。
        if length < 250:
            score -= 18; penalties.append("正文过短"); factors.append({"name": "正文长度", "score": -18, "max": 14})
        elif length < 800:
            score += 2; reasons.append("短内容，可快速审核"); factors.append({"name": "正文长度", "score": 2, "max": 14})
        elif length < 3000:
            score += 8; reasons.append("正文长度适中"); factors.append({"name": "正文长度", "score": 8, "max": 14})
        elif length < 12000:
            score += 14; reasons.append("长文，知识密度可能较高"); factors.append({"name": "正文长度", "score": 14, "max": 14})
        else:
            score += 10; reasons.append("超长文，建议人工预览后导入"); factors.append({"name": "正文长度", "score": 10, "max": 14})

        # 主题相关性：围绕本知识库当前核心方向。
        topic_terms = [
            "agent", "agents", "llm", "rag", "openai", "anthropic", "claude", "gemini",
            "deepseek", "kimi", "hermes", "openclaw", "langchain", "langgraph",
            "mcp", "prompt", "reasoning", "inference", "embedding", "multimodal",
            "ai", "人工智能", "大模型", "智能体", "多agent", "知识库", "模型", "推理"
        ]
        hits = sorted({t for t in topic_terms if t in text})
        if hits:
            bump = min(20, 4 * len(hits))
            score += bump
            reasons.append(f"主题命中: {', '.join(hits[:6])}")
        else:
            score -= 8; penalties.append("未命中当前知识库核心主题")

        # 配置标签命中也加分。
        tags = [str(t).lower() for t in source_cfg.get("tags", [])]
        tag_hits = [t for t in tags if t and t in text]
        if tag_hits:
            score += min(10, 3 * len(tag_hits)); reasons.append(f"来源标签命中: {', '.join(tag_hits[:4])}")

        # 标题质量。
        if len(title.strip()) < 12:
            score -= 10; penalties.append("标题过短")
        if re.search(r"\b(show hn|ask hn|launch hn)\b", title.lower()):
            score -= 6; penalties.append("社区帖子类标题，需人工判断")
        if any(x in title.lower() for x in ["girl ", "soldier charged", "arrested", "encrypted messaging"]):
            score -= 18; penalties.append("偏泛新闻/低相关内容")

        # 新鲜度。
        dt = self._parse_datetime(item.get("publish_time") or item.get("modified") or "")
        if dt:
            age_days = max(0, (datetime.now(timezone.utc) - dt).days)
            if age_days <= 14:
                score += 8; reasons.append("近期内容")
            elif age_days <= 90:
                score += 4; reasons.append("较新内容")
            elif age_days > 365:
                score -= 5; penalties.append("内容较旧")

        # 重复风险。
        norm_title = self._normalize_title(title)
        duplicate_risk = "none"
        if norm_title and norm_title in self._wiki_title_index:
            score -= 45; duplicate_risk = "imported"; penalties.append("疑似已入库同标题")
        elif norm_title and duplicate_titles.get(norm_title, 0) > 1:
            score -= 20; duplicate_risk = "candidate"; penalties.append("候选池内疑似重复")

        score = max(0, min(100, int(round(score))))
        if score >= 80:
            tier = "A"
        elif score >= 65:
            tier = "B"
        elif score >= 45:
            tier = "C"
        else:
            tier = "D"

        recommendation = {
            "A": f"建议优先导入 (总分{score})：来源可靠+内容深度充足+KB相关",
            "B": f"值得审核 (总分{score})：相关性尚可，需人工确认价值",
            "C": f"低优先级 (总分{score})：来源或内容深度不足，按需审核",
            "D": f"建议跳过或暂缓 (总分{score})：{', '.join(penalties[:3]) if penalties else '低相关'}",
        }[tier]

        return {
            "score": score,
            "tier": tier,
            "recommendation": recommendation,
            "reasons": reasons[:6],
            "penalties": penalties[:6],
            "factors": factors,
            "duplicate_risk": duplicate_risk,
            "source_priority": priority,
            "topic_hits": hits[:10],
            "content_depth": {} if not content_body else None,
            "kb_matches": kb["matched_entities"][:8],
        }

    def list_candidates(self, include_imported: bool = False, include_skipped: bool = False,
                        min_score: int = 0, tier: str = "", candidate_type: str = "",
                        sort: str = "quality") -> List[Dict[str, Any]]:
        """扫描所有候选目录，附带质量评分。"""
        items = []
        for cdir in self._candidate_dirs():
            cdir.mkdir(parents=True, exist_ok=True)
            for md_path in sorted(cdir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True):
                meta = self._load_meta_for(md_path)
                cid = self._candidate_id(md_path, meta)
                state = self.state.get("items", {}).get(cid, {})
                status = state.get("status") or meta.get("status") or "candidate"
                if status == "imported" and not include_imported:
                    continue
                if status == "skipped" and not include_skipped:
                    continue
                st = md_path.stat()
                translation = None
                try:
                    sys.path.insert(0, str(self.base_dir / "scripts"))
                    from translator import CandidateTranslator  # type: ignore
                    translation = CandidateTranslator(self.base_dir).load_translation(cid)
                except Exception:
                    translation = None
                edited = self._edited_meta(cid)
                base_title = meta.get("title") or self._read_title(md_path)
                items.append({
                    "id": cid,
                    "status": status,
                    "title": base_title,
                    "edited_metadata": edited,
                    "review_title": edited.get("title") or "",
                    "review_category": edited.get("category") or edited.get("preferred_category") or "",
                    "review_tags": edited.get("tags") or [],
                    "translated_title": edited.get("title") or (translation or {}).get("translated_title"),
                    "translated_summary": (translation or {}).get("translated_summary"),
                    "translated_topics": (translation or {}).get("topics") or [],
                    "key_terms": (translation or {}).get("key_terms") or [],
                    "translation": translation,
                    "author": meta.get("author") or "",
                    "source_name": meta.get("source_name") or "",
                    "url": meta.get("url") or "",
                    "publish_time": meta.get("publish_time") or "",
                    "content_length": meta.get("content_length") or st.st_size,
                    "path": str(md_path.relative_to(self.base_dir)),
                    "meta_path": meta.get("_meta_path"),
                    "modified": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
                    "state": state,
                    "candidate_type": "rss" if "rss_candidates" in str(md_path.parent) else ("wechat" if "wechat_candidates" in str(md_path.parent) else "other"),
                })

        duplicate_titles: Dict[str, int] = {}
        for item in items:
            norm = self._normalize_title(item.get("title", ""))
            if norm:
                duplicate_titles[norm] = duplicate_titles.get(norm, 0) + 1

        for item in items:
            quality = self._score_candidate(item, duplicate_titles)
            item["quality"] = quality
            item["quality_score"] = quality["score"]
            item["quality_tier"] = quality["tier"]

        if candidate_type:
            items = [i for i in items if i.get("candidate_type") == candidate_type]
        if tier:
            wanted = {t.strip().upper() for t in tier.split(",") if t.strip()}
            items = [i for i in items if i.get("quality_tier") in wanted]
        if min_score:
            items = [i for i in items if int(i.get("quality_score") or 0) >= min_score]

        if sort == "modified":
            items.sort(key=lambda x: x.get("modified", ""), reverse=True)
        elif sort == "source":
            items.sort(key=lambda x: (x.get("source_name", ""), -int(x.get("quality_score") or 0)))
        else:
            items.sort(key=lambda x: (int(x.get("quality_score") or 0), x.get("modified", "")), reverse=True)
        return items

    def get_candidate(self, cid: str) -> Optional[Dict[str, Any]]:
        for item in self.list_candidates(include_imported=True, include_skipped=True, sort="quality"):
            if item["id"] == cid:
                path = self.base_dir / item["path"]
                item["content"] = path.read_text(encoding="utf-8", errors="ignore")
                try:
                    sys.path.insert(0, str(self.base_dir / "scripts"))
                    from translator import CandidateTranslator  # type: ignore
                    trans = CandidateTranslator(self.base_dir).load_translation(cid)
                    if trans:
                        item["translation"] = trans
                        item["translated_title"] = trans.get("translated_title")
                        item["translated_summary"] = trans.get("translated_summary")
                        item["translated_topics"] = trans.get("topics") or []
                        item["key_terms"] = trans.get("key_terms") or []
                        item["translated_content"] = trans.get("translated_content")
                except Exception:
                    pass
                return item
        return None

    def translate_candidate(self, cid: str, *, force: bool = False, preview: bool = False) -> Dict[str, Any]:
        item = self.get_candidate(cid)
        if not item:
            raise ValueError(f"Candidate not found: {cid}")
        sys.path.insert(0, str(self.base_dir / "scripts"))
        from translator import CandidateTranslator  # type: ignore
        translator = CandidateTranslator(self.base_dir)
        if preview:
            return translator.translate_preview_candidate(item, item.get("content", ""), force=force)
        return translator.translate_candidate(item, item.get("content", ""), force=force)

    def update_candidate_metadata(self, cid: str, *, title: str = "", category: str = "", tags: Any = None, notes: str = "") -> Dict[str, Any]:
        item = self.get_candidate(cid)
        if not item:
            raise ValueError(f"Candidate not found: {cid}")
        clean: Dict[str, Any] = {}
        if title is not None and str(title).strip():
            clean["title"] = str(title).strip()
        if category is not None and str(category).strip():
            clean["category"] = str(category).strip()
            clean["preferred_category"] = str(category).strip()
        if tags is not None:
            if isinstance(tags, str):
                tag_list = [t.strip() for t in re.split(r"[,，;；]", tags) if t.strip()]
            elif isinstance(tags, list):
                tag_list = [str(t).strip() for t in tags if str(t).strip()]
            else:
                tag_list = []
            clean["tags"] = tag_list[:20]
        if notes is not None and str(notes).strip():
            clean["notes"] = str(notes).strip()
        st = self._state_item(cid)
        old = st.get("edited_metadata") or {}
        old.update(clean)
        st["edited_metadata"] = old
        st["metadata_updated_at"] = datetime.now(timezone.utc).isoformat()
        self._save_state()
        updated = self.get_candidate(cid) or {"id": cid}
        return {"id": cid, "edited_metadata": old, "candidate": updated}

    def batch_skip(self, *, tier: str = "C,D", candidate_type: str = "", reason: str = "批量跳过低质量候选", confirm: str = "") -> Dict[str, Any]:
        if confirm != "SKIP_LOW_QUALITY":
            raise ValueError("批量跳过需要确认码 SKIP_LOW_QUALITY")
        items = self.list_candidates(include_imported=False, include_skipped=False, tier=tier, candidate_type=candidate_type, sort="quality")
        skipped = []
        for item in items:
            cid = item["id"]
            self.state.setdefault("items", {})[cid] = {
                **self.state.get("items", {}).get(cid, {}),
                "status": "skipped",
                "skipped_at": datetime.now(timezone.utc).isoformat(),
                "reason": reason,
                "batch_skip": True,
                "quality_tier_at_skip": item.get("quality_tier"),
                "quality_score_at_skip": item.get("quality_score"),
            }
            skipped.append({"id": cid, "title": item.get("translated_title") or item.get("title"), "tier": item.get("quality_tier"), "score": item.get("quality_score")})
        self._save_state()
        return {"skipped": len(skipped), "items": skipped}

    def validate_imported_candidate(self, cid: str, imported_to: str) -> Dict[str, Any]:
        """验证候选导入后的核心质量：frontmatter、双语内容、分类标签、可追溯性。"""
        path = self.base_dir / imported_to
        result: Dict[str, Any] = {
            "ok": False,
            "path": imported_to,
            "checks": {},
            "warnings": [],
        }
        if not path.exists():
            result["warnings"].append("导入文件不存在")
            return result
        text = path.read_text(encoding="utf-8", errors="ignore")
        state_item = self.state.get("items", {}).get(cid, {})
        edited = state_item.get("edited_metadata") or self._edited_meta(cid)
        checks = result["checks"]
        checks["has_frontmatter"] = text.startswith("---")
        checks["has_title"] = bool(re.search(r"(?m)^#\s+.+", text))
        checks["has_chinese"] = bool(re.search(r"[\u4e00-\u9fff]", text[:2500]))
        checks["has_english_original"] = "## 英文原文" in text or "原文标题" in text or "Article URL:" in text
        checks["has_candidate_id"] = cid in text or bool(state_item)
        if edited:
            if edited.get("title"):
                checks["edited_title_applied"] = edited.get("title") in text[:1200]
            if edited.get("category") or edited.get("preferred_category"):
                cat = edited.get("category") or edited.get("preferred_category")
                checks["edited_category_applied"] = f"category: {cat}" in text or f"分类**: {cat}" in text or f"分类</span>" in text
            tags = edited.get("tags") or []
            checks["edited_tags_applied"] = all(str(t) in text[:1500] for t in tags[:5]) if tags else True
        required = ["has_title", "has_chinese", "has_candidate_id"]
        # RSS/other 双语导入应保留英文原文；微信中文文章不强制。
        if "rss_" in path.name or "Article URL:" in text or "原文标题" in text:
            required.append("has_english_original")
        result["ok"] = all(bool(checks.get(k)) for k in required)
        return result

    def import_candidate(self, cid: str, *, process: bool = True, run_maintenance: bool = True, translate: bool = True) -> Dict[str, Any]:
        item = self.get_candidate(cid)
        if not item:
            raise ValueError(f"Candidate not found: {cid}")
        item["edited_metadata"] = self._edited_meta(cid)
        src = self.base_dir / item["path"]
        self.article_dir.mkdir(parents=True, exist_ok=True)
        dest = self.article_dir / src.name
        if dest.exists():
            dest = self.article_dir / f"{src.stem}_{self._file_hash(src)[:8]}{src.suffix}"

        translation_result = None
        source_language = detect_language(item.get("content", ""))
        target_languages = target_languages_for(self.translation_policy, source_language)
        target_language = target_languages[0] if target_languages else ("zh" if source_language == "en" else "en")
        policy_key = "wechat_candidate_import" if item.get("candidate_type") == "wechat" else "candidate_import"
        should_full_translate = bool(translate) and should_translate_import(
            self.translation_policy,
            path_key=policy_key,
            source_language=source_language,
            candidate_tier=item.get("quality_tier", ""),
        )
        if translate and item.get("candidate_type") in {"rss", "other"} and target_language == "zh" and not item.get("translation"):
            # 即使不做全文翻译，也尽量保证候选有中文预览，供后续追溯。
            sys.path.insert(0, str(self.base_dir / "scripts"))
            from translator import CandidateTranslator  # type: ignore
            translator = CandidateTranslator(self.base_dir)
            translation_result = translator.translate_preview_candidate(item, item.get("content", ""), force=False)
        if should_full_translate:
            sys.path.insert(0, str(self.base_dir / "scripts"))
            from translator import CandidateTranslator  # type: ignore
            translator = CandidateTranslator(self.base_dir)
            translation_result = translator.translate_candidate(item, item.get("content", ""), force=False, target_language=target_language)
            bilingual = translator.build_bilingual_markdown(item, item.get("content", ""), translation_result)
            dest.write_text(bilingual, encoding="utf-8")
        else:
            # C/D 或非英文候选默认不消耗全文翻译 token。
            if translation_result and item.get("candidate_type") in {"rss", "other"}:
                sys.path.insert(0, str(self.base_dir / "scripts"))
                from translator import CandidateTranslator  # type: ignore
                translator = CandidateTranslator(self.base_dir)
                bilingual = translator.build_bilingual_markdown(item, item.get("content", ""), translation_result)
                dest.write_text(bilingual, encoding="utf-8")
            else:
                shutil.copy2(src, dest)

        # 将审核阶段编辑的标题/分类/标签写入 frontmatter，供 processor 入库时优先使用。
        if item.get("edited_metadata"):
            dest.write_text(self._apply_import_frontmatter(dest.read_text(encoding="utf-8", errors="ignore"), item), encoding="utf-8")

        processed_result = None
        if process:
            sys.path.insert(0, str(self.base_dir / "scripts"))
            from auto_importer import AutoImporter  # type: ignore
            importer = AutoImporter(self.base_dir)
            ok, msg = importer.process_file(dest)
            wiki_rel = None
            if ok and msg:
                try:
                    msg_path = Path(str(msg)).expanduser().resolve()
                    wiki_dir = (self.base_dir / "wiki").resolve()
                    if str(msg_path).startswith(str(wiki_dir)):
                        wiki_rel = msg_path.relative_to(wiki_dir).as_posix()
                except Exception:
                    wiki_rel = None
            processed_result = {"ok": ok, "message": msg, "wiki_path": wiki_rel}
            wiki_llm = self._extract_wiki_llm_meta(wiki_rel)
            if wiki_llm:
                processed_result["llm"] = wiki_llm
            if not ok:
                raise RuntimeError(f"Candidate copied but processing failed: {msg}")

        maintenance_result = None
        if run_maintenance:
            sys.path.insert(0, str(self.base_dir / "scripts"))
            from maintenance import KBMaintenance  # type: ignore
            maint = KBMaintenance(self.base_dir, update_embeddings=False, ollama_model="gemma4:e4b")
            report = maint.run()
            maintenance_result = {"status": report.get("status"), "summary": report.get("summary", {})}

        imported_rel = str(dest.relative_to(self.base_dir))
        validation_result = self.validate_imported_candidate(cid, imported_rel)
        translation_meta = self._translation_import_meta(
            cid=cid,
            item=item,
            translation_result=translation_result,
            translate=bool(translate),
            should_full_translate=should_full_translate,
            target_language=target_language,
        )
        self.state.setdefault("items", {})[cid] = {
            "status": "imported",
            "imported_at": datetime.now(timezone.utc).isoformat(),
            "imported_to": imported_rel,
            "processed": processed_result,
            "translation": translation_meta,
            "edited_metadata": item.get("edited_metadata") or {},
            "validation": validation_result,
        }
        self._save_state()
        return {
            "id": cid,
            "status": "imported",
            "imported_to": imported_rel,
            "processed": processed_result,
            "wiki_path": processed_result.get("wiki_path") if processed_result else None,
            "translation": translation_meta,
            "validation": validation_result,
            "maintenance": maintenance_result,
        }

    def skip_candidate(self, cid: str, reason: str = "") -> Dict[str, Any]:
        if not self.get_candidate(cid):
            raise ValueError(f"Candidate not found: {cid}")
        previous = self.state.get("items", {}).get(cid, {})
        self.state.setdefault("items", {})[cid] = {
            **previous,
            "status": "skipped",
            "skipped_at": datetime.now(timezone.utc).isoformat(),
            "reason": reason,
        }
        self._save_state()
        return {"id": cid, "status": "skipped", "reason": reason}

    def restore_candidate(self, cid: str) -> Dict[str, Any]:
        item = self.get_candidate(cid)
        if not item:
            raise ValueError(f"Candidate not found: {cid}")
        state_item = self.state.setdefault("items", {}).setdefault(cid, {})
        if state_item.get("status") != "skipped":
            return {"id": cid, "status": state_item.get("status") or "candidate", "restored": False, "message": "候选未处于跳过状态"}
        state_item["status"] = "candidate"
        state_item["restored_at"] = datetime.now(timezone.utc).isoformat()
        state_item.pop("skipped_at", None)
        self._save_state()
        return {"id": cid, "status": "candidate", "restored": True}


def summarize_candidates(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    summary = {
        "total": len(items),
        "by_tier": {},
        "by_type": {},
        "avg_score": round(sum(i.get("quality_score", 0) for i in items) / len(items), 1) if items else 0,
    }
    for item in items:
        t = item.get("quality_tier", "?")
        ctype = item.get("candidate_type", "other")
        summary["by_tier"][t] = summary["by_tier"].get(t, 0) + 1
        summary["by_type"][ctype] = summary["by_type"].get(ctype, 0) + 1
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Karpathy 知识库候选池管理")
    parser.add_argument("command", choices=["list", "quality", "show", "translate", "translate-preview-batch", "edit", "import", "skip", "restore", "batch-skip"])
    parser.add_argument("id", nargs="?")
    parser.add_argument("--base-dir", default=str(Path(__file__).resolve().parent.parent))
    parser.add_argument("--include-imported", action="store_true")
    parser.add_argument("--include-skipped", action="store_true")
    parser.add_argument("--no-process", action="store_true")
    parser.add_argument("--no-maintenance", action="store_true")
    parser.add_argument("--no-translate", action="store_true", help="导入英文候选时不生成中文译文")
    parser.add_argument("--force", action="store_true", help="强制重新翻译")
    parser.add_argument("--preview", action="store_true", help="只生成候选池中文预览")
    parser.add_argument("--reason", default="")
    parser.add_argument("--title", default="")
    parser.add_argument("--category", default="")
    parser.add_argument("--tags", default="")
    parser.add_argument("--confirm", default="")
    parser.add_argument("--min-score", type=int, default=0)
    parser.add_argument("--tier", default="", help="质量等级过滤，例如 A,B")
    parser.add_argument("--type", default="", choices=["", "wechat", "rss", "other"], help="候选类型过滤")
    parser.add_argument("--sort", default="quality", choices=["quality", "modified", "source"])
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--batch-size", type=int, default=20, help="批量预翻译数量上限")
    args = parser.parse_args()

    cm = CandidateManager(Path(args.base_dir))
    if args.command in {"list", "quality"}:
        items = cm.list_candidates(
            args.include_imported, args.include_skipped,
            min_score=args.min_score, tier=args.tier, candidate_type=args.type, sort=args.sort,
        )
        if args.limit > 0:
            items = items[:args.limit]
        print(json.dumps({"summary": summarize_candidates(items), "candidates": items}, ensure_ascii=False, indent=2))
    elif args.command == "show":
        if not args.id:
            raise SystemExit("id required")
        print(json.dumps(cm.get_candidate(args.id), ensure_ascii=False, indent=2))
    elif args.command == "translate":
        if not args.id:
            raise SystemExit("id required")
        print(json.dumps(cm.translate_candidate(args.id, force=args.force, preview=args.preview), ensure_ascii=False, indent=2))
    elif args.command == "translate-preview-batch":
        items = cm.list_candidates(
            args.include_imported, args.include_skipped,
            min_score=args.min_score, tier=args.tier, candidate_type=args.type, sort=args.sort,
        )
        done, failed = [], []
        for item in items:
            if len(done) >= args.batch_size:
                break
            if item.get("translated_summary") and not args.force:
                continue
            try:
                result = cm.translate_candidate(item["id"], force=args.force, preview=True)
                done.append({"id": item["id"], "translated_title": result.get("translated_title")})
            except Exception as e:
                failed.append({"id": item.get("id"), "error": str(e)})
        print(json.dumps({"translated": len(done), "failed": failed, "items": done}, ensure_ascii=False, indent=2))
    elif args.command == "edit":
        if not args.id:
            raise SystemExit("id required")
        print(json.dumps(cm.update_candidate_metadata(args.id, title=args.title, category=args.category, tags=args.tags, notes=args.reason), ensure_ascii=False, indent=2))
    elif args.command == "import":
        if not args.id:
            raise SystemExit("id required")
        print(json.dumps(cm.import_candidate(args.id, process=not args.no_process, run_maintenance=not args.no_maintenance, translate=not args.no_translate), ensure_ascii=False, indent=2))
    elif args.command == "batch-skip":
        print(json.dumps(cm.batch_skip(tier=args.tier or "C,D", candidate_type=args.type, reason=args.reason or "批量跳过低质量候选", confirm=args.confirm), ensure_ascii=False, indent=2))
    elif args.command == "skip":
        if not args.id:
            raise SystemExit("id required")
        print(json.dumps(cm.skip_candidate(args.id, args.reason), ensure_ascii=False, indent=2))
    elif args.command == "restore":
        if not args.id:
            raise SystemExit("id required")
        print(json.dumps(cm.restore_candidate(args.id), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
