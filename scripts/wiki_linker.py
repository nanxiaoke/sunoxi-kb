#!/usr/bin/env python3
"""
Wiki内部链接系统
为知识库文档建立语义链接和导航结构
"""

import os
import re
import json
import logging
from pathlib import Path
from typing import Dict, List, Set, Tuple, Optional
from collections import defaultdict

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class WikiLinker:
    """Wiki链接系统"""
    
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.wiki_dir = base_dir / "wiki"
        self.outputs_dir = base_dir / "outputs"
        self.index_file = base_dir / "wiki_index.json"
        
        # 确保目录存在
        self.wiki_dir.mkdir(parents=True, exist_ok=True)
        self.outputs_dir.mkdir(parents=True, exist_ok=True)
        
        # 索引数据结构
        self.doc_index: Dict[str, Dict] = {}  # 文档ID -> 文档信息
        self.entity_index: Dict[str, Set[str]] = defaultdict(set)  # 实体 -> 文档ID集合
        self.category_index: Dict[str, Set[str]] = defaultdict(set)  # 分类 -> 文档ID集合
        
    def scan_wiki_documents(self) -> List[Path]:
        """扫描所有wiki文档"""
        wiki_files = list(self.wiki_dir.rglob("*.md"))
        logger.info(f"找到 {len(wiki_files)} 个wiki文档")
        return wiki_files
    
    def _doc_id_for_path(self, filepath: Path) -> str:
        """生成稳定且唯一的文档ID。

        不能只用 filepath.stem：不同目录下可能存在同名文档，
        例如 articles/foo.md 与 technologies/foo.md，会导致索引覆盖。
        """
        rel = filepath.relative_to(self.wiki_dir).as_posix()
        return rel[:-3] if rel.endswith('.md') else rel

    def _is_generated_doc(self, filepath: Path) -> bool:
        """判断是否为自动生成的索引/分类页。"""
        name = filepath.name
        return name in {"00_INDEX.md", "DOCUMENTS.md"} or name.startswith("category_")

    def _strip_wikilinks(self, text: str) -> str:
        """把 Obsidian wikilink 还原成可读文本。

        主要用于标题、元数据和链接展示名，避免出现
        [[foo.md|[[bar.md|标题]]]] 这种嵌套污染。
        """
        pattern = re.compile(r'\[\[([^\]|]+)(?:\|([^\]]+))?\]\]')
        previous = None
        current = text
        for _ in range(10):
            if current == previous:
                break
            previous = current
            current = pattern.sub(lambda m: m.group(2) or m.group(1), current)
        return current

    def _sanitize_protected_sections(self, filepath: Path) -> bool:
        """修复既有自动内链对受保护区域造成的污染。

        Auto-backlink 只能作用在正文知识内容上，不应该修改：
        - 文档主标题
        - 顶部元数据引用块
        - 相关文档区块（由 linker 统一重建）
        - 原始内容预览（应尽量保持原文可追溯）
        """
        try:
            content = filepath.read_text(encoding='utf-8')
        except Exception as e:
            logger.error(f"读取文档失败 {filepath.name}: {e}")
            return False

        original = content
        h1_match = re.search(r'^#\s+(.+)$', content, flags=re.MULTILINE)
        clean_h1_title = self._strip_wikilinks(h1_match.group(1)).strip() if h1_match else ""
        source_match = re.search(r'^>\s*\*\*来源\*\*:\s*(.+?)\s*$', content, flags=re.MULTILINE)
        clean_source = self._strip_wikilinks(source_match.group(1)).strip() if source_match else ""

        def clean_frontmatter(match):
            lines = match.group(0).split('\n')
            cleaned = []
            for line in lines:
                if line.startswith('title:') and clean_h1_title:
                    quote = '"' if '"' not in clean_h1_title else "'"
                    cleaned.append(f"title: {quote}{clean_h1_title}{quote}")
                elif line.startswith('source:') and clean_source:
                    cleaned.append(f"source: {clean_source}")
                elif re.match(r'^(title|source):\s+', line):
                    cleaned.append(self._strip_wikilinks(line))
                else:
                    cleaned.append(line)
            return '\n'.join(cleaned)

        content = re.sub(
            r'^---\n[\s\S]*?\n---\n',
            clean_frontmatter,
            content,
            count=1,
            flags=re.MULTILINE,
        )

        content = re.sub(
            r'^(#\s+)(.+)$',
            lambda m: m.group(1) + self._strip_wikilinks(m.group(2)).strip(),
            content,
            count=1,
            flags=re.MULTILINE,
        )

        first_h2 = re.search(r'^##\s+', content, flags=re.MULTILINE)
        if first_h2:
            head = content[:first_h2.start()]
            tail = content[first_h2.start():]
            head = '\n'.join(
                self._strip_wikilinks(line) if line.lstrip().startswith('>') else line
                for line in head.split('\n')
            )
            content = head + tail

        raw_match = re.search(
            r'(^## 📄 原始内容预览\s*\n)([\s\S]*?)(?=\n---\n\n\*此条目由AI自动生成|\Z)',
            content,
            flags=re.MULTILINE,
        )
        if raw_match:
            raw_body = self._strip_wikilinks(raw_match.group(2))
            content = content[:raw_match.start(2)] + raw_body + content[raw_match.end(2):]

        if content != original:
            filepath.write_text(content, encoding='utf-8')
            logger.info(f"🧽 已清理受保护区域链接污染: {filepath.name}")
            return True
        return False

    def parse_wiki_document(self, filepath: Path) -> Optional[Dict]:
        """解析wiki文档，提取元数据、实体和内容"""
        try:
            content = filepath.read_text(encoding='utf-8')
            
            # 提取基本信息
            doc_id = self._doc_id_for_path(filepath)
            relative_path = filepath.relative_to(self.wiki_dir)
            
            # 解析frontmatter和内容部分
            title = self._extract_title(content)
            category = self._normalize_category(self._extract_category(content))
            entities = self._extract_entities(content)
            summary = self._extract_summary(content)
            
            # 计算文档标签（基于标题和实体）
            tags = self._extract_tags(content, entities)
            
            doc_info = {
                "id": doc_id,
                "path": str(relative_path),
                "full_path": str(filepath),
                "title": title,
                "category": category,
                "entities": entities,
                "tags": tags,
                "summary": summary,
                "file_size": filepath.stat().st_size,
                "modified_time": filepath.stat().st_mtime
            }
            
            logger.debug(f"解析文档: {title} ({doc_id}), {len(entities)} 个实体")
            return doc_info
            
        except Exception as e:
            logger.error(f"解析文档 {filepath} 失败: {e}")
            return None
    
    def _extract_title(self, content: str) -> str:
        """从文档内容提取标题"""
        # 提取第一个 # 标题
        match = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
        if match:
            return self._strip_wikilinks(match.group(1)).strip()
        
        # 回退：使用文件名
        return "未知标题"
    
    def _extract_category(self, content: str) -> str:
        """从文档内容提取分类"""
        # 查找分类行
        match = re.search(r'>\s*\*\*分类\*\*:\s*(.+?)\s*$', content, re.MULTILINE)
        if match:
            return self._strip_wikilinks(match.group(1)).strip()
        
        # 根据文件路径推断分类
        return "未分类"
    
    def _extract_entities(self, content: str) -> List[str]:
        """从文档内容提取实体"""
        entities = []
        
        # 查找实体部分（🏷️ 实体与概念）
        entity_section_match = re.search(r'## 🏷️ 实体与概念\s*\n(.+?)\n##', content, re.DOTALL)
        if entity_section_match:
            entity_text = entity_section_match.group(1)
            # 兼容多种格式：逗号分隔或列表
            # 首先移除列表符号 `- ` 或 `* `
            entity_text = re.sub(r'^\s*[-*]\s+', '', entity_text, flags=re.MULTILINE)
            # 按逗号或换行分割
            raw_entities = re.split(r'[,，、;；\n]', entity_text)
            entities = []
            for e in raw_entities:
                clean = self._strip_wikilinks(e).strip()
                if not clean or clean in {"（未提取到实体）", "未提取到实体", "相关主题"}:
                    continue
                entities.append(clean)
        
        # 如果没有实体部分，从摘要和内容中提取关键词
        if not entities:
            # 简单关键词提取（可以后续优化）
            summary = self._extract_summary(content)
            if summary:
                # 提取看起来像实体的词（大写字母开头、专有名词等）
                words = re.findall(r'\b[A-Z][a-zA-Z]{2,}\b', summary)
                entities = list(set(words))[:10]  # 限制数量
        
        return entities
    
    def _extract_summary(self, content: str) -> str:
        """从文档内容提取摘要"""
        # 查找摘要部分（📝 摘要）
        summary_match = re.search(r'## 📝 摘要\s*\n(.+?)\n##', content, re.DOTALL)
        if summary_match:
            return summary_match.group(1).strip()[:200]  # 截断
        
        return ""

    def _normalize_category(self, category: str) -> str:
        clean = self._strip_wikilinks(category).strip().lower()
        mapping = {
            "technology": "技术",
            "technologies": "技术",
            "教程": "技术",
            "tutorial": "技术",
            "articles": "文章",
            "article": "文章",
        }
        return mapping.get(clean, category.strip())

    def _knowledge_text(self, content: str) -> str:
        """返回用于抽取主题的知识正文，排除自动链接区和原文快照。"""
        text = content
        for marker in ["## 🔗 相关文档", "## 📄 原始内容预览"]:
            idx = text.find(marker)
            if idx >= 0:
                text = text[:idx]
        lines = []
        for line in text.splitlines():
            if line.lstrip().startswith('>'):
                continue
            lines.append(line)
        return "\n".join(lines)

    def _extract_topic_terms(self, text: str) -> List[str]:
        """抽取轻量主题词，用于非LLM关联兜底。"""
        vocabulary = [
            "AI Agent", "Multi-Agent", "Agent", "Hermes", "OpenClaw", "Claude Code", "Ollama",
            "LLM", "RAG", "Prompt", "Deep Research", "深度研究", "横纵分析法",
            "PyTorch", "TorchTPU", "TPU", "GPU", "Google", "deep learning", "深度学习",
            "Anthropic", "Claude", "Agent OS", "LangGraph", "MCP", "工作流",
            "TCP", "网络", "性能调优", "AI", "人工智能", "模型",
        ]
        found = []
        lower = text.lower()
        for term in vocabulary:
            if term.lower() in lower:
                found.append(term)
        generic_stop = {
            "Scale", "Native", "Integration", "Enhanced", "Efficiency", "Lowered", "Processing", "Units",
            "Window", "Fast", "Retransmit", "Sending", "Scale", "Step", "Profile", "Session",
        }
        for word in re.findall(r'\b[A-Z][A-Za-z0-9+._-]{2,}\b', text):
            if word in generic_stop:
                continue
            if word not in found and len(word) <= 30:
                found.append(word)
        return list(dict.fromkeys(found))[:20]
    
    def _extract_tags(self, content: str, entities: List[str]) -> List[str]:
        """从文档内容提取标签"""
        tags = []

        def add(tag: str):
            tag = self._strip_wikilinks(tag).strip()
            if not tag or tag in {"（未提取到实体）", "未提取到实体", "相关主题"}:
                return
            generic_stop = {"Scale", "Native", "Integration", "Enhanced", "Efficiency", "Lowered", "Processing", "Units", "Window", "Fast", "Retransmit", "Sending", "Step", "Profile", "Session", "Wi"}
            if tag in generic_stop:
                return
            if len(tag) < 2 or len(tag) > 60:
                return
            if tag not in tags:
                tags.append(tag)

        for entity in entities[:8]:
            add(entity)

        title = self._extract_title(content)
        summary = self._extract_summary(content)
        knowledge_text = self._knowledge_text(content)
        for term in self._extract_topic_terms(title + "\n" + summary + "\n" + knowledge_text[:4000]):
            add(term)

        title_words = re.findall(r'\b[a-zA-Z][a-zA-Z0-9+._-]{3,}\b', title)
        for word in title_words[:5]:
            add(word)

        return tags[:20]
    
    def build_index(self):
        """构建文档索引"""
        logger.info("开始构建wiki索引...")
        
        wiki_files = self.scan_wiki_documents()
        
        for filepath in wiki_files:
            if self._is_generated_doc(filepath):
                continue
            doc_info = self.parse_wiki_document(filepath)
            if not doc_info:
                continue
            
            doc_id = doc_info["id"]
            self.doc_index[doc_id] = doc_info
            
            # 更新实体索引
            for entity in doc_info["entities"]:
                self.entity_index[entity].add(doc_id)
            
            # 更新分类索引
            category = doc_info["category"]
            self.category_index[category].add(doc_id)
        
        logger.info(f"索引构建完成: {len(self.doc_index)} 文档, {len(self.entity_index)} 实体, {len(self.category_index)} 分类")
    
    def find_related_documents(self, doc_id: str, max_related: int = 5) -> List[Dict]:
        """查找相关文档"""
        if doc_id not in self.doc_index:
            return []

        doc_info = self.doc_index[doc_id]
        doc_entities = set(doc_info.get("entities", []))
        doc_tags = set(doc_info.get("tags", []))
        doc_category = self._normalize_category(doc_info.get("category", ""))
        doc_terms = doc_entities | doc_tags
        generic_relation_terms = {"AI", "人工智能", "模型", "LLM", "Agent", "AI Agent", "工作流", "技术", "文章", "教程"}
        doc_specific_terms = {t for t in doc_terms if t not in generic_relation_terms}

        scores = {}

        for other_id, other_info in self.doc_index.items():
            if other_id == doc_id:
                continue

            score = 0
            reasons = []

            other_entities = set(other_info.get("entities", []))
            other_tags = set(other_info.get("tags", []))
            other_category = self._normalize_category(other_info.get("category", ""))
            other_terms = other_entities | other_tags
            other_specific_terms = {t for t in other_terms if t not in generic_relation_terms}

            entity_intersection = {t for t in doc_entities.intersection(other_entities) if t not in generic_relation_terms}
            if entity_intersection:
                score += len(entity_intersection) * 3
                reasons.extend(sorted(entity_intersection)[:5])

            tag_intersection = {t for t in doc_tags.intersection(other_tags) if t not in generic_relation_terms}
            if tag_intersection:
                score += len(tag_intersection) * 2
                reasons.extend(sorted(tag_intersection)[:5])

            # 标题/主题词包含关系，例如 Kimi+Hermes 与 Hermes 多 Agent。
            title_a = doc_info.get("title", "")
            title_b = other_info.get("title", "")
            for term in sorted(doc_specific_terms, key=len, reverse=True):
                if len(term) >= 3 and term in title_b:
                    score += 2
                    reasons.append(term)
            for term in sorted(other_specific_terms, key=len, reverse=True):
                if len(term) >= 3 and term in title_a:
                    score += 2
                    reasons.append(term)

            if other_category == doc_category and doc_category not in {"未分类", ""}:
                # 同一规范化分类是弱信号：只在已有主题/实体交集时补分，避免强行关联。
                score += 1 if score > 0 else 0

            # 不再使用 AI/Agent/模型 等宽泛词作为得分依据；这些词只用于展示/搜索，
            # 避免把所有 AI 文章互相关联成噪声网。

            if score > 0:
                clean_reasons = []
                for r in reasons:
                    r = self._strip_wikilinks(str(r)).strip()
                    if r and r not in clean_reasons:
                        clean_reasons.append(r)
                scores[other_id] = {
                    "score": score,
                    "title": other_info["title"],
                    "category": other_info["category"],
                    "shared_entities": clean_reasons[:5],
                }

        sorted_docs = sorted(scores.items(), key=lambda x: x[1]["score"], reverse=True)

        related = []
        for other_id, info in sorted_docs[:max_related]:
            info["id"] = other_id
            info["path"] = self.doc_index[other_id]["path"]
            related.append(info)

        return related


    def _valid_link_keyword(self, keyword: str) -> bool:
        keyword = self._strip_wikilinks(keyword).strip()
        if not keyword:
            return False
        if keyword in {"（未提取到实体）", "未提取到实体", "相关主题", "未知标题"}:
            return False
        # 过短词容易误伤；过长标题作为正文关键词价值也低，且容易生成嵌套链接。
        if len(keyword) < 3 or len(keyword) > 80:
            return False
        # 避免把普通英文碎片、URL片段、元数据字段当关键词。
        if keyword.lower() in {"user", "name", "source", "title", "date", "status"}:
            return False
        return True

    def _is_protected_line(self, line: str, current_section: str) -> bool:
        stripped = line.lstrip()
        if stripped.startswith(("#", ">", "- **[[")):
            return True
        if current_section in {"links", "raw"}:
            return True
        return False

    def inject_cross_references(self, filepath: Path) -> bool:
        """自动扫描正文知识内容并将关键词替换为交叉链接。

        只处理摘要/关键点/实体等知识区块；跳过标题、元数据、相关文档区块和原始内容预览，
        防止自动内链污染可追溯原文和展示标题。
        """
        try:
            content = filepath.read_text(encoding='utf-8')
            doc_id = self._doc_id_for_path(filepath)

            if doc_id not in self.doc_index or self._is_generated_doc(filepath):
                return False

            keyword_targets = {}

            # 1. 短标题可作为关键词；长标题不做全文替换，避免误伤。
            for other_id, other_info in self.doc_index.items():
                if other_id == doc_id:
                    continue
                title = self._strip_wikilinks(other_info.get("title", "")).strip()
                if self._valid_link_keyword(title) and len(title) <= 40:
                    keyword_targets[title] = other_info.get("path")

            # 2. 独占实体作为关键词。
            for entity, docs in self.entity_index.items():
                clean_entity = self._strip_wikilinks(entity).strip()
                if len(docs) == 1 and self._valid_link_keyword(clean_entity):
                    target_id = next(iter(docs))
                    if target_id != doc_id and clean_entity not in keyword_targets:
                        keyword_targets[clean_entity] = self.doc_index[target_id].get("path")

            if not keyword_targets:
                return False

            sorted_keywords = sorted(keyword_targets.keys(), key=len, reverse=True)
            pattern = re.compile('(' + '|'.join(map(re.escape, sorted_keywords)) + ')')
            protected_inline = re.compile(r'(^---[\s\S]*?^---\n|```[\s\S]*?```|`[^`]*`|\[\[.*?\]\]|\[.*?\]\(.*?\))', flags=re.MULTILINE)

            def replace_inline(text: str) -> str:
                parts = protected_inline.split(text)
                out = []
                for part in parts:
                    if not part:
                        continue
                    if part.startswith('---') or part.startswith('`') or part.startswith('['):
                        out.append(part)
                        continue
                    out.append(pattern.sub(lambda m: f"[[{keyword_targets[m.group(1)]}|{m.group(1)}]]", part))
                return ''.join(out)

            new_lines = []
            current_section = ""
            in_frontmatter = False
            changed = False
            for idx, line in enumerate(content.split('\n')):
                if idx == 0 and line.strip() == '---':
                    in_frontmatter = True
                    new_lines.append(line)
                    continue
                if in_frontmatter:
                    new_lines.append(line)
                    if line.strip() == '---':
                        in_frontmatter = False
                    continue

                if line.startswith('## 🔗 相关文档'):
                    current_section = "links"
                elif line.startswith('## 📄 原始内容预览'):
                    current_section = "raw"
                elif line.startswith('## '):
                    current_section = "body"

                if self._is_protected_line(line, current_section):
                    new_lines.append(line)
                    continue

                new_line = replace_inline(line)
                if new_line != line:
                    changed = True
                new_lines.append(new_line)

            if changed:
                filepath.write_text('\n'.join(new_lines), encoding='utf-8')
                logger.info(f"✨ 成功注入交叉链接: {filepath.name}")
                return True
            return False

        except Exception as e:
            logger.error(f"注入交叉链接失败 {filepath.name}: {e}")
            return False

    def add_links_to_document(self, filepath: Path):
        """为文档添加相关链接部分"""
        try:
            self._sanitize_protected_sections(filepath)
            content = filepath.read_text(encoding='utf-8')
            doc_id = self._doc_id_for_path(filepath)
            
            if doc_id not in self.doc_index or self._is_generated_doc(filepath):
                logger.warning(f"文档 {doc_id} 不在索引中，跳过链接添加")
                return False
            
            # 查找相关文档
            related_docs = self.find_related_documents(doc_id)
            
            if not related_docs:
                logger.debug(f"文档 {doc_id} 没有找到相关文档")
                if "## 🔗 相关文档" in content:
                    new_content = re.sub(r'\n*## 🔗 相关文档.*?(?=\n## |\Z)', '\n', content, flags=re.DOTALL).rstrip() + '\n'
                    if new_content != content:
                        filepath.write_text(new_content, encoding='utf-8')
                        logger.info(f"已移除文档 {doc_id} 的过期相关链接区块")
                        return True
                return False
            
            # 构建链接部分
            links_section = self._create_links_section(related_docs)
            
            # 检查是否已有链接部分
            if "## 🔗 相关文档" in content:
                # 替换现有链接部分
                pattern = r'## 🔗 相关文档.*?(?=## |\Z)'
                new_content = re.sub(pattern, links_section, content, flags=re.DOTALL)
            else:
                # 在实体部分后添加链接部分
                # 查找实体部分的位置
                entity_pattern = r'(## 🏷️ 实体与概念.*?\n)##'
                if re.search(entity_pattern, content, re.DOTALL):
                    # 在实体部分后添加
                    new_content = re.sub(entity_pattern, r'\1\n' + links_section + '\n##', content, flags=re.DOTALL)
                else:
                    # 在摘要后添加
                    summary_pattern = r'(## 📝 摘要.*?\n)##'
                    if re.search(summary_pattern, content, re.DOTALL):
                        new_content = re.sub(summary_pattern, r'\1\n' + links_section + '\n##', content, flags=re.DOTALL)
                    else:
                        # 添加到文档末尾
                        new_content = content.rstrip() + '\n\n' + links_section
            
            # 写回文件
            filepath.write_text(new_content, encoding='utf-8')
            logger.info(f"已为文档 {doc_id} 添加 {len(related_docs)} 个相关链接")
            return True
            
        except Exception as e:
            logger.error(f"为文档 {filepath} 添加链接失败: {e}")
            return False
    
    def _create_links_section(self, related_docs: List[Dict]) -> str:
        """创建链接部分内容"""
        lines = ["## 🔗 相关文档", ""]
        
        for doc in related_docs:
            # Obsidian 双链格式 [[vault/path.md|Display Name]]
            link_path = doc['path']
            title = self._strip_wikilinks(doc["title"])
            category = self._strip_wikilinks(doc["category"])
            shared = ", ".join(doc["shared_entities"]) if doc["shared_entities"] else "相关主题"
            
            lines.append(f"- **[[{link_path}|{title}]]** ({category})")
            lines.append(f"  - *关联: {shared}*")
        
        lines.append("")
        return '\n'.join(lines)
    
    def generate_category_index(self) -> Dict[str, str]:
        """生成分类索引页面"""
        logger.info("生成分类索引页面...")
        
        category_pages = {}

        # 清理旧分类页，避免分类重命名后残留并被后续扫描纳入图谱。
        for old_page in self.wiki_dir.glob("category_*.md"):
            try:
                old_page.unlink()
            except Exception as e:
                logger.warning(f"删除旧分类页失败 {old_page}: {e}")
        
        for category, doc_ids in self.category_index.items():
            if not doc_ids:
                continue
            
            # 构建分类页面内容
            lines = [
                f"# {category} 知识库",
                "",
                f"本分类包含 {len(doc_ids)} 个文档：",
                ""
            ]
            
            for doc_id in sorted(doc_ids):
                doc_info = self.doc_index.get(doc_id)
                if not doc_info:
                    continue
                
                title = doc_info["title"]
                summary = doc_info.get("summary", "")[:100]
                if summary:
                    lines.append(f"### [[{doc_info['path']}|{title}]]")
                    lines.append(f"> {summary}...")
                    lines.append("")
                else:
                    lines.append(f"- [[{doc_info['path']}|{title}]]")
            
            # 保存分类页面
            safe_category = re.sub(r'[^\w\-]', '_', category)
            category_file = self.wiki_dir / f"category_{safe_category}.md"
            category_file.write_text('\n'.join(lines), encoding='utf-8')
            
            category_pages[category] = str(category_file.relative_to(self.wiki_dir))
        
        # 创建主索引页面
        self._create_main_index(category_pages)
        
        logger.info(f"生成 {len(category_pages)} 个分类索引页面")
        return category_pages
    
    def _create_main_index(self, category_pages: Dict[str, str]):
        """创建主索引页面"""
        lines = [
            "# Karpathy知识库索引",
            "",
            "## 分类浏览",
            ""
        ]
        
        for category, page_path in sorted(category_pages.items()):
            doc_count = len(self.category_index.get(category, []))
            lines.append(f"- [[{page_path}|{category} ({doc_count}篇)]]")
        
        lines.extend([
            "",
            "## 最新文档",
            ""
        ])
        
        # 按修改时间排序，取最新5篇
        all_docs = sorted(self.doc_index.values(), key=lambda x: x["modified_time"], reverse=True)
        for doc in all_docs[:5]:
            lines.append(f"- [[{doc['path']}|{doc['title']}]] - {doc['category']}")
        
        lines.extend([
            "",
            "## 实体索引",
            ""
        ])
        
        # 按频率排序，取前20个实体
        sorted_entities = sorted(self.entity_index.items(), key=lambda x: len(x[1]), reverse=True)
        for entity, doc_ids in sorted_entities[:20]:
            lines.append(f"- **{entity}** ({len(doc_ids)}篇)")
        
        # 保存主索引
        index_file = self.wiki_dir / "00_INDEX.md"
        index_file.write_text('\n'.join(lines), encoding='utf-8')
        
        logger.info(f"主索引已保存: {index_file}")
    
    def save_index(self):
        """保存索引到文件"""
        index_data = {
            "doc_index": self.doc_index,
            "entity_index": {k: list(v) for k, v in self.entity_index.items()},
            "category_index": {k: list(v) for k, v in self.category_index.items()},
            "stats": {
                "total_docs": len(self.doc_index),
                "total_entities": len(self.entity_index),
                "total_categories": len(self.category_index)
            }
        }
        
        with open(self.index_file, 'w', encoding='utf-8') as f:
            json.dump(index_data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"索引已保存到: {self.index_file}")
    
    def load_index(self):
        """从文件加载索引"""
        if not self.index_file.exists():
            logger.warning(f"索引文件不存在: {self.index_file}")
            return False
        
        try:
            with open(self.index_file, 'r', encoding='utf-8') as f:
                index_data = json.load(f)
            
            self.doc_index = index_data["doc_index"]
            self.entity_index = {k: set(v) for k, v in index_data["entity_index"].items()}
            self.category_index = {k: set(v) for k, v in index_data["category_index"].items()}
            
            logger.info(f"从文件加载索引: {len(self.doc_index)} 文档")
            return True
            
        except Exception as e:
            logger.error(f"加载索引失败: {e}")
            return False
    
    def run(self, rebuild_index: bool = False):
        """运行链接系统"""
        logger.info("开始运行Wiki链接系统...")
        
        # 构建或加载索引
        if rebuild_index or not self.index_file.exists():
            self.build_index()
            self.save_index()
        else:
            if not self.load_index():
                self.build_index()
                self.save_index()
        
        # 为所有文档添加链接
        wiki_files = self.scan_wiki_documents()
        linked_count = 0
        
        for filepath in wiki_files:
            # 首先注入文本内的交叉链接
            if self._is_generated_doc(filepath):
                continue

            self._sanitize_protected_sections(filepath)
            self.inject_cross_references(filepath)
            
            # 然后添加底部的相关文档区块
            if self.add_links_to_document(filepath):
                linked_count += 1
        
        # 生成分类索引
        category_pages = self.generate_category_index()
        
        logger.info(f"Wiki链接系统完成: {linked_count}/{len(wiki_files)} 文档已添加链接")
        
        # 显示统计信息
        self.print_stats()
    
    def print_stats(self):
        """打印统计信息"""
        print("\n" + "="*60)
        print("📊 Wiki链接系统统计")
        print("="*60)
        
        print(f"📄 文档总数: {len(self.doc_index)}")
        
        if self.category_index:
            print(f"🏷️  分类统计:")
            for category, doc_ids in sorted(self.category_index.items(), key=lambda x: len(x[1]), reverse=True):
                print(f"   - {category}: {len(doc_ids)} 篇")
        
        if self.entity_index:
            top_entities = sorted(self.entity_index.items(), key=lambda x: len(x[1]), reverse=True)[:5]
            print(f"🔤 热门实体 (前5):")
            for entity, doc_ids in top_entities:
                print(f"   - {entity}: {len(doc_ids)} 篇")
        
        print(f"📁 索引文件: {self.index_file}")
        print(f"🌐 主索引页面: wiki/00_INDEX.md")
        print("="*60)


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Wiki内部链接系统")
    parser.add_argument("--rebuild", action="store_true", help="重建索引")
    parser.add_argument("--base-dir", default=".", help="项目基础目录")
    
    args = parser.parse_args()
    
    base_dir = Path(args.base_dir).expanduser()
    if not base_dir.exists():
        print(f"错误: 目录不存在: {base_dir}")
        return 1
    
    linker = WikiLinker(base_dir)
    linker.run(rebuild_index=args.rebuild)
    
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
