#!/usr/bin/env python3
"""
Karpathy知识库批量文档处理器
将raw/目录下所有未处理的文档批量转换为wiki/结构化知识

使用统一 LLMService + FlowPolicy 处理文档

使用方法:
  python3 batch_processor.py [--dry-run] [--limit N] [--category CAT] [--force]
"""

import os
import sys
import json
import time
import re
import logging
import argparse
import subprocess
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Set, Any
from collections import Counter

from llm_service import LLMService
from translation_policy import (
    load_translation_policy,
    section_title_for,
    should_translate_import,
    target_languages_for,
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

ALLOWED_CATEGORIES = ["技术", "学术论文", "笔记", "代码", "教程", "新闻", "文章", "其他"]
CATEGORY_ALIASES = {
    "tech": "技术",
    "technology": "技术",
    "technologies": "技术",
    "技术文章": "技术",
    "工具": "技术",
    "开源项目": "技术",
    "paper": "学术论文",
    "papers": "学术论文",
    "论文": "学术论文",
    "research": "学术论文",
    "note": "笔记",
    "notes": "笔记",
    "代码片段": "代码",
    "code": "代码",
    "tutorial": "教程",
    "guide": "教程",
    "指南": "教程",
    "news": "新闻",
    "资讯": "新闻",
    "article": "文章",
    "articles": "文章",
}


class BatchProcessor:
    """批量文档处理器（使用统一 LLMService 处理）"""
    
    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir)
        self.raw_dir = self.base_dir / "raw"
        self.wiki_dir = self.base_dir / "wiki"
        self.progress_file = self.base_dir / "batch_progress.json"
        self.llm = LLMService()
        self.model = self.llm.config.provider(self.llm.config.flow("file_import_structure").providers[0]).model
        self.last_error: Optional[str] = None
        self.translation_policy = load_translation_policy(self.base_dir)
        
        # 加载处理进度
        self.processed_files = self._load_progress()
        
        # 仅做轻量状态记录；具体本地/在线可用性由每条 FlowPolicy 决定。
        self._check_llm_runtime()
        
        logger.info(f"批量处理器初始化完成")
        logger.info(f"  Raw目录: {self.raw_dir}")
        logger.info(f"  Wiki目录: {self.wiki_dir}")
        logger.info(f"  模型: {self.model}")
        logger.info(f"  已处理: {len(self.processed_files)} 个文件")
    
    def _check_llm_runtime(self):
        """记录 LLM provider 状态，不在纯在线配置下强制依赖 Ollama。"""
        for provider in self.llm.config.provider_status():
            secret = "configured" if provider.get("secret_configured") else "missing-secret"
            logger.info(f"LLM provider: {provider['name']} ({provider['model']}) {secret}")
        try:
            result = subprocess.run(
                ['ollama', 'ps'],
                capture_output=True, text=True, timeout=10
            )
            if 'gemma4' in result.stdout:
                logger.info("✅ Ollama运行中，模型已加载")
            else:
                logger.warning("⚠️ 模型未加载，首次处理需要~17秒加载时间")
        except FileNotFoundError:
            logger.warning("⚠️ ollama命令未找到；如果当前 FlowPolicy 需要本地模型，处理时会失败并按策略降级")
        except Exception as e:
            logger.warning(f"⚠️ Ollama检测异常: {e}")
    
    def _load_progress(self) -> Set[str]:
        if self.progress_file.exists():
            try:
                data = json.loads(self.progress_file.read_text(encoding='utf-8'))
                return set(data.get("processed_files", []))
            except Exception as e:
                logger.warning(f"加载进度文件失败: {e}")
        return set()
    
    def _save_progress(self):
        try:
            data = {
                "processed_files": list(self.processed_files),
                "total": len(self.processed_files),
                "updated_at": datetime.now().isoformat()
            }
            self.progress_file.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding='utf-8'
            )
        except Exception as e:
            logger.warning(f"保存进度失败: {e}")
    
    def _strip_ansi(self, text: str) -> str:
        """移除终端ANSI转义码"""
        ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
        text = ansi_escape.sub('', text)
        text = re.sub(r'[\r\x00\x08]', '', text)
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = text.strip()
        return text
    
    def _llm_chat(self, flow_name: str, prompt: str) -> tuple[Optional[str], Dict[str, Any]]:
        """通过统一 LLMService 执行业务流调用。"""
        messages = [
            {"role": "system", "content": "你是技术知识库的信息架构助手，输出严格遵循用户给定格式。"},
            {"role": "user", "content": prompt},
        ]
        result = self.llm.chat(flow_name, messages)
        meta = result.to_dict()
        if result.status != "ok":
            logger.error(f"  ❌ LLM处理失败: {result.error}")
            return None, meta
        logger.info(
            "  LLM provider: %s / %s%s",
            result.provider,
            result.model,
            f" (fallback from {result.fallback_from})" if result.fallback_from else "",
        )
        return result.content, meta

    def _chunks(self, text: str, max_chars: int) -> List[str]:
        text = (text or "").strip()
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
        final: List[str] = []
        for chunk in chunks:
            if len(chunk) <= max_chars:
                final.append(chunk)
            else:
                final.extend(chunk[i:i + max_chars] for i in range(0, len(chunk), max_chars))
        return final

    def _translate_full_content(self, content: str, *, title: str, source_language: str, target_language: str) -> tuple[str, Dict[str, Any]]:
        """Generate policy-controlled full translation for direct URL/file imports."""
        flow_name = "full_translation"
        policy = self.llm.config.flow(flow_name)
        cfg = policy.options
        chunk_chars = int(self.translation_policy.get("max_chunk_chars") or policy.chunk_chars or cfg.get("chunk_chars") or 3500)
        target_name = "中文" if target_language == "zh" else "English"
        source_name = "英文" if source_language == "en" else "中文"
        system = (
            "你是专业的 AI/软件工程技术翻译。输出忠实、准确、自然、可检索的中文。"
            if target_language == "zh"
            else "You are a professional AI/software engineering translator. Produce faithful, accurate, natural, searchable English."
        )
        outputs: List[str] = []
        chunks_meta: List[Dict[str, Any]] = []
        for idx, chunk in enumerate(self._chunks(content, chunk_chars), 1):
            prompt = f"""请把下面{source_name}技术内容翻译成{target_name}。

要求：
1. 忠实翻译，不总结、不扩写、不删减事实。
2. 保留 Markdown 结构、列表、链接、代码、命令和配置项。
3. 产品名、模型名、公司名、论文名、项目名、URL、版本号不翻译。
4. 技术术语首次出现尽量中英并列，后续保持术语一致。

标题：{title}
分片：{idx}

待翻译内容：
{chunk}

只输出{target_name}译文，不要解释。"""
            result = self.llm.chat(flow_name, [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ], options={
                "temperature": cfg.get("temperature", 0.1),
                "think": bool(cfg.get("think", False)),
                **({"num_predict": int(cfg.get("num_predict"))} if cfg.get("num_predict") else {}),
            })
            meta = result.to_dict()
            if result.status != "ok":
                raise RuntimeError(result.error or f"{flow_name} chunk {idx} failed")
            outputs.append((result.content or "").strip())
            meta.pop("content", None)
            meta["chunk_index"] = idx
            meta["chunk_chars"] = len(chunk)
            chunks_meta.append(meta)
        first = chunks_meta[0] if chunks_meta else {}
        return "\n\n".join(x for x in outputs if x), {
            "flow": flow_name,
            "provider": first.get("provider") or (policy.providers[0] if policy.providers else ""),
            "model": first.get("model") or "",
            "status": first.get("status", "ok") if chunks_meta else "skipped",
            "target_language": target_language,
            "source_language": source_language,
            "chunk_count": len(chunks_meta),
            "chunks": chunks_meta,
        }
    
    def _detect_language(self, text: str) -> str:
        """检测文本语言"""
        chinese_chars = len(re.findall(r'[一-鿿]', text))
        total_chars = len(text.strip())
        if total_chars == 0:
            return "unknown"
        ratio = chinese_chars / total_chars
        return "zh" if ratio > 0.1 else "en"

    def _yaml_quote(self, value: Any) -> str:
        """Quote a scalar for simple generated YAML frontmatter."""
        text = "" if value is None else str(value)
        return json.dumps(text, ensure_ascii=False)

    def _clean_single_line(self, value: Any, *, fallback: str = "", max_len: int = 180) -> str:
        text = str(value or "").strip()
        text = re.sub(r"^```(?:\w+)?|```$", "", text).strip()
        text = re.sub(r"^\s*[-*•\d.、]+", "", text).strip()
        text = re.sub(r"^(标题|title|分类|category|摘要|summary|实体|entities|标签|tags)\s*[:：]\s*", "", text, flags=re.I)
        text = re.sub(r"\s+", " ", text).strip(" \t\r\n\"'`")
        return (text or fallback)[:max_len].strip()

    def _clean_title(self, raw: Any, fallback: str) -> str:
        title = self._clean_single_line(raw, fallback=fallback, max_len=120)
        title = re.sub(r"\s*[-|_]\s*(微信公众号|微信公众平台|知乎专栏|掘金|CSDN博客)\s*$", "", title)
        return title or fallback

    def _normalize_category(self, raw: Any, raw_category: str = "") -> str:
        text = self._clean_single_line(raw, fallback="")
        lowered = text.lower()
        if text in ALLOWED_CATEGORIES:
            return text
        if lowered in CATEGORY_ALIASES:
            return CATEGORY_ALIASES[lowered]
        for key, category in CATEGORY_ALIASES.items():
            if key and (key in lowered or key in text):
                return category
        for category in ALLOWED_CATEGORIES:
            if category in text:
                return category
        if raw_category == "codes":
            return "代码"
        if raw_category in {"articles", "webpages", "wechat_articles"}:
            return "文章"
        if raw_category == "notes":
            return "笔记"
        if raw_category == "papers":
            return "学术论文"
        return "其他"

    def _normalize_list(self, raw: Any, *, max_items: int = 12, max_len: int = 40) -> List[str]:
        if raw is None:
            return []
        if isinstance(raw, list):
            parts = raw
        else:
            text = str(raw)
            text = re.sub(r"^```(?:\w+)?|```$", "", text.strip()).strip()
            lines = []
            for line in text.splitlines():
                line = re.sub(r"^\s*[-*•\d.、]+", "", line).strip()
                if line:
                    lines.append(line)
            parts = []
            for line in lines or [text]:
                parts.extend(re.split(r"[,，;；、/|]", line))
        result = []
        seen = set()
        for item in parts:
            clean = self._clean_single_line(item, max_len=max_len)
            if not clean or clean in {"无", "无实体", "未提取到实体", "（未提取到实体）", "none", "null"}:
                continue
            key = clean.lower()
            if key not in seen:
                seen.add(key)
                result.append(clean)
            if len(result) >= max_items:
                break
        return result

    def _parse_simple_frontmatter(self, content: str) -> tuple[Dict[str, Any], str]:
        """轻量解析 YAML frontmatter，支持 title/category/tags/preferred_category。"""
        if not content.startswith('---'):
            return {}, content
        parts = content.split('---', 2)
        if len(parts) < 3:
            return {}, content
        meta_text, body = parts[1], parts[2].lstrip('\n')
        meta: Dict[str, Any] = {}
        current_key = None
        for raw in meta_text.splitlines():
            line = raw.rstrip()
            if not line.strip():
                continue
            if line.startswith('  - ') and current_key:
                meta.setdefault(current_key, []).append(line[4:].strip().strip('"'))
                continue
            if ':' in line:
                key, val = line.split(':', 1)
                key = key.strip()
                val = val.strip().strip('"')
                if val == '':
                    meta[key] = []
                    current_key = key
                else:
                    meta[key] = val
                    current_key = key
        return meta, body
    
    def scan_raw_files(self, category_filter: Optional[str] = None) -> List[Dict]:
        """扫描raw目录下的所有文件"""
        files = []
        
        raw_dirs = {
            "articles": self.raw_dir / "articles",
            "codes": self.raw_dir / "codes",
            "notes": self.raw_dir / "notes",
            "papers": self.raw_dir / "papers",
            "webpages": self.raw_dir / "webpages",
            "wechat_articles": self.raw_dir / "wechat_articles",
        }
        
        for cat_name, cat_path in raw_dirs.items():
            if category_filter and cat_name != category_filter:
                continue
            if not cat_path.exists():
                continue
            
            for f in sorted(cat_path.iterdir()):
                if not f.is_file() or f.suffix.lower() not in ['.md', '.txt', '.py', '.markdown']:
                    continue
                if f.name.endswith('_meta.json'):
                    continue
                
                wiki_exists = self._wiki_file_exists(f)
                files.append({
                    "path": f,
                    "category": cat_name,
                    "stem": f.stem,
                    "wiki_exists": wiki_exists,
                    "size": f.stat().st_size,
                })
        
        return files
    
    def _wiki_file_exists(self, raw_file: Path) -> bool:
        """检查raw文件是否已有对应的wiki文件"""
        stem = raw_file.stem
        for wiki_subdir in self.wiki_dir.iterdir():
            if wiki_subdir.is_dir():
                for wiki_file in wiki_subdir.iterdir():
                    if stem in wiki_file.name:
                        return True
        return False
    
    def _get_wiki_category(self, raw_category: str) -> str:
        """根据raw目录名推断wiki分类"""
        mapping = {
            "articles": "articles",
            "codes": "codes",
            "notes": "notes",
            "papers": "concepts",
            "webpages": "articles",
            "wechat_articles": "articles",
        }
        return mapping.get(raw_category, "concepts")
    
    def process_file(self, file_info: Dict) -> Optional[Path]:
        """处理单个raw文件"""
        self.last_error = None
        filepath = file_info["path"]
        file_key = str(filepath)
        
        logger.info(f"📄 [{file_info['category']}] {filepath.name} ({file_info['size']} bytes)")
        
        # 1. 读取文件内容（支持多格式）
        try:
            ext = filepath.suffix.lower()
            if ext == '.pdf':
                try:
                    import pdfplumber
                    parts = []
                    with pdfplumber.open(str(filepath)) as pdf:
                        for page in pdf.pages:
                            t = page.extract_text()
                            if t:
                                parts.append(t)
                    content = '\n\n'.join(parts)
                except ImportError:
                    logger.warning("  pdfplumber未安装，尝试文本读取...")
                    content = filepath.read_text(encoding='utf-8', errors='ignore')
            elif ext == '.docx':
                try:
                    from docx import Document
                    doc = Document(str(filepath))
                    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
                    content = '\n\n'.join(paragraphs)
                except ImportError:
                    logger.warning("  python-docx未安装，尝试文本读取...")
                    content = filepath.read_text(encoding='utf-8', errors='ignore')
            else:
                content = filepath.read_text(encoding='utf-8')
        except Exception as e:
            self.last_error = f"读取失败: {e}"
            logger.error(f"  {self.last_error}")
            return None
        
        metadata, content_body = self._parse_simple_frontmatter(content)
        content_for_title = content_body or content
        # 提取标题：审核 frontmatter 优先，其次正文 H1，最后文件名。
        title = metadata.get('title') or filepath.stem
        lines = content_for_title.split('\n')
        if not metadata.get('title'):
            for line in lines[:8]:
                m = re.match(r'^#\s+(.+)$', line)
                if m:
                    title = m.group(1).strip()
                    break
        title = self._clean_title(title, filepath.stem)
        preferred_category = (metadata.get('preferred_category') or metadata.get('category') or '').strip()
        review_tags = metadata.get('tags') or []
        if isinstance(review_tags, str):
            review_tags = [t.strip() for t in re.split(r'[,，;；]', review_tags) if t.strip()]
        
        # 检测语言
        lang = self._detect_language(content)
        logger.info(f"  标题: {title}")
        logger.info(f"  内容: {len(content)} 字符, 语言: {lang}")
        
        # 截断长内容
        max_chars = 8000
        content_for_ai = content[:max_chars]
        if len(content) > max_chars:
            content_for_ai += "\n\n[...内容过长，已截断...]"
        
        # 2. 构建处理提示词
        wiki_category = self._get_wiki_category(file_info["category"])
        
        if lang == "zh":
            prompt = f"""请分析以下文档，输出结构化的知识条目。要求：

1. 用中文写一段150-300字的摘要
2. 提取3-5个关键要点
3. 分类（从以下选择：技术、学术论文、笔记、代码、教程、新闻、其他）
4. 列出文档中提到的核心实体/概念

文档标题：{title}
文档内容：
{content_for_ai}

请按以下格式输出：

## 摘要
（摘要内容）

## 关键点
1. ...
2. ...
3. ...

## 分类
（分类名称）

## 实体
（实体名称，逗号分隔）"""
        else:
            prompt = f"""请把以下英文文档翻译并整理成中文知识库条目。要求：

1. 标题必须保留原文，不要翻译标题
2. 用中文写一段150-300字摘要
3. 用中文提取3-5个关键要点
4. 分类（从以下选择：技术、学术论文、笔记、代码、教程、新闻、其他）
5. 列出文档中提到的核心实体/概念
6. 给出中文翻译，保留原文主要结构；长文可压缩到1200-2500字，但不要只写摘要

原文标题：{title}
原文内容：
{content_for_ai}

请严格按以下格式输出：

## 摘要
（中文摘要）

## 关键点
1. ...
2. ...
3. ...

## 分类
（分类名称）

## 实体
（实体名称，逗号分隔）

## 中文翻译
（中文翻译正文）"""
        
        # 3. LLMService处理
        flow_name = "url_import_structure" if file_info["category"] == "webpages" else "file_import_structure"
        logger.info(f"  AI处理中... flow={flow_name}")
        start_time = time.time()
        result_text, llm_meta = self._llm_chat(flow_name, prompt)
        elapsed = time.time() - start_time
        
        if not result_text:
            detail = llm_meta.get("error") or llm_meta.get("status") or "无响应"
            self.last_error = f"AI处理失败: {detail}"
            logger.error(f"  ❌ {self.last_error}")
            return None
        
        logger.info(f"  ✅ AI响应: {len(result_text)} 字符 (耗时{elapsed:.1f}秒)")
        
        # 4. 解析结果
        summary = self._extract_section(result_text, "摘要", "Summary", default=f"（AI生成的摘要）")
        keypoints = self._extract_section(result_text, "关键点", "Key Points", default=f"（AI提取的关键点）")
        category = self._extract_section(result_text, "分类", "Category", default=wiki_category)
        entities = self._extract_section(result_text, "实体", "Entities", default="")
        translated_body = ""
        if lang != "zh":
            translated_body = self._extract_section(result_text, "中文翻译", "Chinese Translation", default="").strip()
        if preferred_category:
            logger.info(f"  使用审核指定分类: {preferred_category}")
            category = preferred_category
        if review_tags:
            tag_entities = ", ".join(str(t) for t in review_tags)
            entities = f"{entities}, {tag_entities}" if entities else tag_entities
        
        # 清理生成元数据
        category = self._normalize_category(category, file_info["category"])
        summary = self._clean_single_line(summary, fallback="（AI生成的摘要）", max_len=700)
        entities_list = self._normalize_list(entities)
        tags = self._normalize_list(review_tags)
        if category not in tags:
            tags.insert(0, category)

        policy_path_key = "url_import" if file_info["category"] == "webpages" else "file_upload"
        already_bilingual = bool(re.search(
            r"(?m)^##\s*(?:🌐\s*中文翻译|中文译文|🌍\s*English Translation|English Translation|英文原文|中文原文|English Original)",
            content,
        ))
        full_translation_body = ""
        full_translation_target = ""
        full_translation_meta: Dict[str, Any] = {}
        target_languages = target_languages_for(self.translation_policy, lang)
        if not already_bilingual and target_languages and should_translate_import(self.translation_policy, path_key=policy_path_key, source_language=lang):
            full_translation_target = target_languages[0]
            try:
                logger.info(f"  全文翻译中... {lang} -> {full_translation_target}")
                full_translation_body, full_translation_meta = self._translate_full_content(
                    content_body or content,
                    title=title,
                    source_language=lang,
                    target_language=full_translation_target,
                )
                if full_translation_target == "zh":
                    translated_body = full_translation_body or translated_body
            except Exception as e:
                logger.warning(f"  全文翻译失败，按策略处理: {e}")
                full_translation_meta = {
                    "flow": "full_translation",
                    "status": "error",
                    "error": str(e),
                    "source_language": lang,
                    "target_language": full_translation_target,
                }
                if str(self.translation_policy.get("fallback_on_failure") or "preview_only") == "fail_import":
                    self.last_error = f"全文翻译失败: {e}"
                    return None

        # 映射到wiki分类目录
        cat_map = {
            "技术": "technologies",
            "学术论文": "concepts",
            "笔记": "notes", "notes": "notes",
            "代码": "codes",
            "教程": "technologies",
            "新闻": "articles",
            "其他": "concepts",
            "文章": "articles",
        }
        target_category = cat_map.get(category, wiki_category)
        
        # 5. 生成wiki文件名
        safe_title = re.sub(r'[^\w\s-]', '', title).strip()[:50] or "untitled"
        file_hash = hashlib.md5(content.encode()).hexdigest()[:8]
        wiki_filename = f"{safe_title}_{file_hash}.md"
        
        wiki_dir = self.wiki_dir / target_category
        wiki_dir.mkdir(parents=True, exist_ok=True)
        wiki_path = wiki_dir / wiki_filename
        
        tag_lines = "\n".join([f"  - {self._yaml_quote(t)}" for t in tags]) or f"  - {self._yaml_quote(category)}"
        entities_text = "\n".join([f"- {entity}" for entity in entities_list]) if entities_list else "（未提取到实体）"
        translation_section = ""
        section_target = full_translation_target or ("zh" if translated_body else "")
        section_body = full_translation_body or translated_body
        if section_body and section_target:
            translation_section = f"""
## {section_title_for(section_target)}

{section_body}

"""
        full_translation_meta_yaml = ""
        if full_translation_meta:
            full_translation_meta_yaml = f"""llm_full_translation:
  flow: {self._yaml_quote(full_translation_meta.get('flow', 'full_translation'))}
  provider: {self._yaml_quote(full_translation_meta.get('provider', ''))}
  model: {self._yaml_quote(full_translation_meta.get('model', ''))}
  status: {self._yaml_quote(full_translation_meta.get('status', ''))}
  source_language: {self._yaml_quote(full_translation_meta.get('source_language', lang))}
  target_language: {self._yaml_quote(full_translation_meta.get('target_language', full_translation_target))}
  chunk_count: {int(full_translation_meta.get('chunk_count') or 0)}
  error: {self._yaml_quote(full_translation_meta.get('error', ''))}
"""
        # 6. 构建wiki内容
        wiki_content = f"""---
title: {self._yaml_quote(title)}
category: {self._yaml_quote(category)}
source: {self._yaml_quote(str(filepath))}
tags:
{tag_lines}
llm:
  flow: {self._yaml_quote(llm_meta.get('flow', flow_name))}
  provider: {self._yaml_quote(llm_meta.get('provider', 'unknown'))}
  model: {self._yaml_quote(llm_meta.get('model', self.model))}
  status: {self._yaml_quote(llm_meta.get('status', 'unknown'))}
  duration_sec: {llm_meta.get('duration_sec', round(elapsed, 3))}
  fallback_from: {self._yaml_quote(llm_meta.get('fallback_from') or '')}
  fallback_to: {self._yaml_quote(llm_meta.get('fallback_to') or '')}
  generated_at: {self._yaml_quote(datetime.now().isoformat())}
{full_translation_meta_yaml.rstrip()}
---

# {title}

> **来源**: {filepath}
> **处理时间**: {datetime.now().isoformat()}
> **分类**: {category}
> **原始格式**: {filepath.suffix[1:] or 'text'}

## 📝 摘要

{summary}

## 🔑 关键点

{keypoints}

## 🏷️ 实体与概念

{entities_text}

{translation_section}## 📄 原始内容预览

{content[:2000]}...

---

*此条目由AI自动生成 ({llm_meta.get('provider', 'unknown')} / {llm_meta.get('model', self.model)})*
"""
        
        # 7. 保存
        wiki_path.write_text(wiki_content, encoding='utf-8')
        logger.info(f"  ✅ 已保存: wiki/{target_category}/{wiki_filename}")
        
        self.processed_files.add(file_key)
        self._save_progress()
        
        return wiki_path
    
    def _extract_section(self, text: str, zh_header: str, en_header: str,
                         default: str = "") -> str:
        """从结构化输出中提取指定章节"""
        # 尝试多种格式
        patterns = [
            rf'##\s*{zh_header}\s*\n(.*?)(?=\n##|\Z)',
            rf'##\s*{en_header}\s*\n(.*?)(?=\n##|\Z)',
        ]
        
        for pattern in patterns:
            m = re.search(pattern, text, re.DOTALL)
            if m:
                result = m.group(1).strip()
                # 移除可能的嵌套markdown
                result = re.sub(r'^-\s+', '', result, flags=re.MULTILINE)
                result = re.sub(r'\n{3,}', '\n\n', result)
                return result
        
        return default
    
    def run(self, dry_run: bool = False, limit: Optional[int] = None,
            category_filter: Optional[str] = None, force: bool = False):
        """运行批量处理"""
        files = self.scan_raw_files(category_filter)
        
        # 过滤
        if force:
            pending = [f for f in files]
        else:
            pending = [f for f in files if not f["wiki_exists"] or str(f["path"]) not in self.processed_files]
        
        pending = [f for f in pending if not f["path"].name.endswith('_meta.json')]
        
        logger.info(f"扫描结果: 总{len(files)}, 待处理{len(pending)}, 已处理{len(files)-len(pending)}")
        
        cat_counts = Counter(f["category"] for f in pending)
        for cat, count in sorted(cat_counts.items()):
            logger.info(f"  {cat}: {count}")
        
        if not pending:
            logger.info("✅ 所有文件已处理！")
            return
        
        if dry_run:
            for i, f in enumerate(pending, 1):
                sz = f["size"] / 1024
                logger.info(f"  {i:3d}. ⏳ {f['category']}/{f['path'].name} ({sz:.1f}KB)")
            logger.info(f"共 {len(pending)} 个文件待处理")
            return
        
        if limit:
            pending = pending[:limit]
        
        logger.info(f"\n开始批量处理 {len(pending)} 个文件...\n")
        
        success = 0
        fail = 0
        
        for i, file_info in enumerate(pending, 1):
            logger.info(f"\n[{i}/{len(pending)}]")
            result = self.process_file(file_info)
            if result:
                success += 1
            else:
                fail += 1
            
            if i < len(pending):
                logger.info(f"  冷却3秒...")
                time.sleep(3)
        
        logger.info(f"\n{'='*50}")
        logger.info(f"批量处理完成: 成功{success}, 失败{fail}")
        logger.info(f"{'='*50}")


def main():
    parser = argparse.ArgumentParser(description="批量处理raw文档到wiki")
    parser.add_argument("--dry-run", action="store_true", help="仅显示待处理文件")
    parser.add_argument("--limit", type=int, default=0, help="最多处理N个文件")
    parser.add_argument("--category", type=str, default="", help="仅处理指定分类")
    parser.add_argument("--force", action="store_true", help="强制重新处理")
    parser.add_argument("--base-dir", type=str, default=str(Path(__file__).resolve().parent.parent),
                        help="项目根目录")
    
    args = parser.parse_args()
    base_dir = Path(args.base_dir).expanduser()
    if not base_dir.exists():
        print(f"错误: 目录不存在: {base_dir}")
        return 1
    
    processor = BatchProcessor(base_dir)
    processor.run(
        dry_run=args.dry_run,
        limit=args.limit,
        category_filter=args.category or None,
        force=args.force
    )
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
