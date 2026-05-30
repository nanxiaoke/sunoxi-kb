#!/usr/bin/env python3
"""
知识库搜索系统
提供全文搜索、分类搜索、实体搜索等功能
"""

import os
import re
import json
import logging
from pathlib import Path
from typing import Dict, List, Set, Tuple, Optional, Any
from collections import defaultdict
import argparse

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 尝试导入jieba（增强中文分词）
try:
    import jieba
    JIEBA_AVAILABLE = True
except ImportError:
    JIEBA_AVAILABLE = False
    logger.warning("jieba未安装，使用简单分词模式（安装: pip install jieba）")

class WikiSearcher:
    """Wiki知识库搜索器"""
    
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.wiki_dir = base_dir / "wiki"
        self.index_file = base_dir / "search_index.json"
        
        # 索引数据结构
        self.doc_index: Dict[str, Dict] = {}  # 文档ID -> 文档信息
        self.title_index: Dict[str, Set[str]] = defaultdict(set)  # 词 -> 文档ID集合
        self.summary_index: Dict[str, Set[str]] = defaultdict(set)  # 词 -> 文档ID集合
        self.entity_index: Dict[str, Set[str]] = defaultdict(set)  # 实体 -> 文档ID集合
        self.fulltext_index: Dict[str, Set[str]] = defaultdict(set)  # 词 -> 文档ID集合
        self.category_index: Dict[str, Set[str]] = defaultdict(set)  # 分类 -> 文档ID集合
        
        # 初始化jieba分词器（如果可用）
        if JIEBA_AVAILABLE:
            # 添加自定义词典（知识库领域术语）
            custom_words = [
                "人工智能", "机器学习", "深度学习", "自然语言处理", "计算机视觉",
                "大语言模型", "检索增强生成", "RAG", "神经网络", "强化学习",
                "大模型", "语言模型", "知识图谱", "向量数据库", "注意力机制",
                "生成式AI", "Transformer", "预训练", "微调", "提示工程",
                "横纵分析法", "横向分析", "纵向分析", "历时分析", "共时分析",
                "Kimi", "Hermes", "OpenClaw", "Claude Code", "CC Switch", "Agent OS",
                "Meta-Harness", "TorchTPU", "PyTorch", "TPU", "AIHOT", "AI热点网站",
                "管理活", "技术活", "模型切换", "六个技巧", "六个神技巧"
            ]
            for word in custom_words:
                jieba.add_word(word)
            logger.info(f"jieba分词器已初始化，添加了{len(custom_words)}个自定义词汇")
        
        # 中文停用词（简化版）
        self.stop_words = set([
            "的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都", "一", "一个",
            "也", "很", "到", "说", "要", "去", "你", "会", "着", "没有", "看", "好", "自己",
            "这", "那", "上", "下", "个", "年", "月", "日", "时", "分", "秒", "与", "或", "而",
            "而且", "但是", "因为", "所以", "如果", "那么", "然后", "并且", "然而", "虽然",
            "this", "that", "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
            "of", "with", "by", "from", "as", "is", "are", "was", "were", "be", "been", "have",
            "has", "had", "do", "does", "did", "will", "would", "can", "could", "should", "may",
            "might", "must",
            "什么", "为什么", "为何", "如何", "怎样", "怎么", "是不是", "有没有",
            "是什么", "这是什么", "什么是",
            "应该", "需要", "问题", "解决", "它", "这个", "那个", "哪些", "主要"
        ])
    
    def _tokenize(self, text: str) -> List[str]:
        """分词函数（支持jieba增强中文分词）"""
        if not text:
            return []
        
        words = []
        
        if JIEBA_AVAILABLE:
            # 使用jieba进行中文分词
            # 我们将中英文混合文本直接抛给jieba，避免切断专有名词
            seg_list = jieba.lcut(text, cut_all=False)  # 精确模式
            for word in seg_list:
                word = word.strip()
                if word and word not in self.stop_words and len(word) >= 2:
                    words.append(word.lower())
            
            # 处理特殊字符（如RAG、AI等缩写）
            special = re.findall(r'\b[A-Z]{2,}\b', text)
            for word in special:
                word_lower = word.lower()
                if word_lower not in words and word_lower not in self.stop_words:
                    words.append(word_lower)
        else:
            # 降级方案：简单正则分词
            # 1. 英文单词（2个字符以上）
            # 2. 连续中文字符（2个字符以上，避免单个字符噪声）
            # 3. 保持专有名词完整
            for word in re.findall(r'[a-zA-Z]{2,}|[\u4e00-\u9fff]{2,}|[^\s\w]', text):
                word_lower = word.lower()
                if word_lower and word_lower not in self.stop_words:
                    if len(word) == 1 and '\u4e00' <= word <= '\u9fff':
                        continue
                    words.append(word_lower)
        
        return list(dict.fromkeys(words))  # 去重但保持顺序
    
    def _tokenize_with_positions(self, text: str) -> Dict[str, List[int]]:
        """分词并记录位置（用于高亮）"""
        tokens = {}
        if JIEBA_AVAILABLE:
            seg_list = jieba.lcut(text, cut_all=False)
            for word in seg_list:
                word = word.strip()
                if word and word not in self.stop_words and len(word) >= 2:
                    word_lower = word.lower()
                    # 查找所有出现位置
                    start = 0
                    positions = []
                    while True:
                        pos = text.lower().find(word_lower, start)
                        if pos == -1:
                            break
                        positions.append(pos)
                        start = pos + 1
                    if positions:
                        if word_lower not in tokens:
                            tokens[word_lower] = positions
                        else:
                            tokens[word_lower].extend(positions)
        else:
            # 降级：简单位置记录
            for word in re.findall(r'[a-zA-Z]{2,}|[\u4e00-\u9fff]{2,}', text):
                word_lower = word.lower()
                if word_lower not in self.stop_words:
                    start = 0
                    positions = []
                    while True:
                        pos = text.lower().find(word_lower, start)
                        if pos == -1:
                            break
                        positions.append(pos)
                        start = pos + 1
                    if positions:
                        tokens[word_lower] = positions
        return tokens

    def _strip_frontmatter(self, content: str) -> str:
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                return parts[2].strip()
        return content

    def _clean_markup(self, text: str) -> str:
        text = text or ""
        text = re.sub(r'\[\[([^\]|]+)\|([^\]]+)\]\]', r'\2', text)
        text = re.sub(r'\[\[([^\]]+)\]\]', r'\1', text)
        text = re.sub(r'`([^`]+)`', r'\1', text)
        text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
        text = re.sub(r'https?://\S+', '', text)
        text = re.sub(r'^#{1,6}\s*', '', text, flags=re.MULTILINE)
        text = re.sub(r'[ \t]+', ' ', text)
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text.strip()

    def _clean_source_body(self, text: str) -> str:
        """Prefer real source content and remove crawler/frontmatter metadata noise."""
        body = self._strip_frontmatter(text or "")
        marker = "## 📄 原始内容预览"
        if marker in body:
            body = body.split(marker, 1)[1]
        body = body.split("*此条目由AI自动生成", 1)[0]
        body = self._strip_frontmatter(body.strip())
        lines = []
        for line in body.splitlines():
            stripped = line.strip()
            if not stripped:
                lines.append("")
                continue
            if stripped in {"---"}:
                continue
            if re.match(r'^>\s*\*\*(来源|抓取时间|作者|发布时间|提取方法|内容长度|文件哈希|处理时间|分类|原始格式)\*\*\s*[:：]', stripped):
                continue
            if re.match(r'^\s*(来源|抓取时间|作者|发布时间|提取方法|内容长度|文件哈希|公众号biz|公众号user_name)\s*[:：]', stripped):
                continue
            lines.append(line)
        return self._clean_markup("\n".join(lines))

    def _expand_query_tokens(self, query: str, tokens: List[str]) -> List[str]:
        expanded = list(tokens)
        compact = re.sub(r'\s+', '', query or '').lower()
        if len(compact) >= 2:
            expanded.insert(0, compact)
        # Keep mixed English phrases such as "cc switch" alongside individual tokens.
        phrase = re.sub(r'\s+', ' ', (query or '').strip().lower())
        if phrase and phrase not in expanded:
            expanded.append(phrase)
        # Chinese compound fallback: jieba may emit a long phrase only; add 2-4 char windows.
        chinese = re.findall(r'[\u4e00-\u9fff]{3,}', compact)
        for seq in chinese:
            for size in (4, 3, 2):
                if len(seq) >= size:
                    for i in range(0, len(seq) - size + 1):
                        expanded.append(seq[i:i + size])
        return list(dict.fromkeys([t for t in expanded if t and t not in self.stop_words]))
    
    def _extract_document_info(self, filepath: Path) -> Optional[Dict]:
        """提取文档信息（支持新旧格式）"""
        try:
            raw_content = filepath.read_text(encoding='utf-8')
            content = self._strip_frontmatter(raw_content)
            relative_path = filepath.relative_to(self.wiki_dir)
            # 使用 wiki 根目录相对路径作为稳定唯一ID，避免不同目录同名文件互相覆盖。
            doc_id = relative_path.as_posix()[:-3] if relative_path.as_posix().endswith('.md') else relative_path.as_posix()
            
            # 提取标题（两种格式通用）
            title_match = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
            title = title_match.group(1).strip() if title_match else doc_id
            
            # 提取分类（支持两种格式）
            category = "未分类"
            
            # 格式1: **分类**: articles（新格式）
            category_match1 = re.search(r'\*\*分类\*\*:\s*(.+?)\s*$', content, re.MULTILINE)
            if category_match1:
                category = category_match1.group(1).strip()
            else:
                # 格式2: > **分类**: 教程（旧格式）
                category_match2 = re.search(r'>\s*\*\*分类\*\*:\s*(.+?)\s*$', content, re.MULTILINE)
                if category_match2:
                    category = category_match2.group(1).strip()
            
            # 提取摘要（支持两种格式）
            summary = ""
            
            # 格式1: ## 摘要（新格式）
            summary_match1 = re.search(r'## 摘要\s*\n(.+?)(?:\n##|$)', content, re.DOTALL)
            if summary_match1:
                summary = summary_match1.group(1).strip()
            else:
                # 格式2: ## 📝 摘要（旧格式）
                summary_match2 = re.search(r'## 📝 摘要\s*\n(.+?)(?:\n##|$)', content, re.DOTALL)
                if summary_match2:
                    summary = summary_match2.group(1).strip()
            
            # 提取关键点（支持两种格式）
            keypoints = []
            
            # 格式1: ## 关键点（新格式）
            keypoints_match1 = re.search(r'## 关键点\s*\n(.+?)(?:\n##|$)', content, re.DOTALL)
            if keypoints_match1:
                keypoints_text = keypoints_match1.group(1)
                # 解析编号列表或项目符号
                for line in keypoints_text.split('\n'):
                    line = line.strip()
                    # 匹配编号列表: 1. xxx, 2. xxx
                    if re.match(r'^\d+\.\s+.+', line):
                        # 移除编号
                        point = re.sub(r'^\d+\.\s*', '', line)
                        keypoints.append(point)
                    # 匹配项目符号: - xxx, * xxx
                    elif re.match(r'^[-*]\s+.+', line):
                        point = re.sub(r'^[-*]\s*', '', line)
                        keypoints.append(point)
            else:
                # 格式2: ## 🔑 关键点（旧格式）
                keypoints_match2 = re.search(r'## 🔑 关键点\s*\n(.+?)(?:\n##|$)', content, re.DOTALL)
                if keypoints_match2:
                    keypoints_text = keypoints_match2.group(1)
                    # 解析编号列表
                    for line in keypoints_text.split('\n'):
                        line = line.strip()
                        if line.startswith(('1.', '2.', '3.', '4.', '5.', '6.', '7.', '8.', '9.', '0.')):
                            # 移除编号
                            point = re.sub(r'^\d+\.\s*', '', line)
                            keypoints.append(point)
            
            # 提取实体
            entities = []
            entity_match = re.search(r'## 🏷️ 实体与概念\s*\n(.+?)(?:\n##|$)', content, re.DOTALL)
            if entity_match:
                raw = entity_match.group(1)
                # 支持两种格式的实体列表：
                # 1. 逗号分隔: Ollama, Gemma4, RAG
                # 2. 逐行排列: Ollama\nGemma4\nRAG
                for line in raw.split('\n'):
                    line = line.strip()
                    if not line:
                        continue
                    # 按逗号分割（中英文逗号都处理）
                    for part in re.split(r'[，,、]', line):
                        part = part.strip()
                        # 过滤掉括号注释如 (AI) → 只保留主名
                        main_name = re.split(r'[（(]', part)[0].strip()
                        if main_name:
                            entities.append(main_name)
            
            # 提取原始内容预览
            original_preview = ""
            
            # 格式1: ## 原始内容（新格式）
            original_match1 = re.search(r'## 原始内容\s*\n```\s*\n(.+?)\n```', content, re.DOTALL)
            if original_match1:
                original_preview = original_match1.group(1).strip()[:500]
            else:
                # 格式2: ## 📄 原始内容（旧格式）
                original_match2 = re.search(r'## 📄 原始内容\s*\n>.*?\n\n(.+?)$', content, re.DOTALL)
                if original_match2:
                    original_preview = original_match2.group(1).strip()[:500]
            
            doc_info = {
                "id": doc_id,
                "path": str(relative_path),
                "full_path": str(filepath),
                "title": title,
                "category": category,
                "summary": self._clean_markup(summary),
                "entities": entities,
                "keypoints": keypoints,
                "original_preview": original_preview,
                "content": self._clean_source_body(raw_content),
                "file_size": filepath.stat().st_size,
                "modified_time": filepath.stat().st_mtime
            }
            
            return doc_info
            
        except Exception as e:
            logger.error(f"提取文档信息失败 {filepath}: {e}")
            return None
    
    def build_index(self, rebuild: bool = False):
        """构建搜索索引"""
        logger.info("开始构建搜索索引...")
        
        # 重建时必须先清空内存索引，避免旧的自动生成索引页残留
        if rebuild:
            self.doc_index = {}
            self.title_index = defaultdict(set)
            self.summary_index = defaultdict(set)
            self.entity_index = defaultdict(set)
            self.fulltext_index = defaultdict(set)
            self.category_index = defaultdict(set)
        
        # 如果索引文件存在且不需要重建，尝试加载
        if not rebuild and self.index_file.exists():
            if self.load_index():
                logger.info(f"从文件加载索引: {len(self.doc_index)} 文档")
                return
        
        # 扫描所有wiki文档
        wiki_files = list(self.wiki_dir.rglob("*.md"))
        logger.info(f"找到 {len(wiki_files)} 个wiki文档")
        
        for filepath in wiki_files:
            # 跳过自动生成的索引页，避免分类页混入搜索结果
            if filepath.name in ["00_INDEX.md", "DOCUMENTS.md"] or filepath.name.startswith("category_"):
                continue
            
            doc_info = self._extract_document_info(filepath)
            if not doc_info:
                continue
            
            doc_id = doc_info["id"]
            self.doc_index[doc_id] = doc_info
            
            # 索引标题
            for word in self._tokenize(doc_info["title"]):
                if word not in self.title_index:
                    self.title_index[word] = set()
                self.title_index[word].add(doc_id)
            
            # 索引全文
            for word in self._tokenize(doc_info["content"]):
                if word not in self.fulltext_index:
                    self.fulltext_index[word] = set()
                self.fulltext_index[word].add(doc_id)
            
            # 索引摘要
            for word in self._tokenize(doc_info["summary"]):
                self.summary_index[word].add(doc_id)
            
            # 索引实体：同时索引完整实体与实体分词，提升中英文混合查询命中率
            for entity in doc_info["entities"]:
                entity_lower = entity.lower().strip()
                if entity_lower:
                    self.entity_index[entity_lower].add(doc_id)
                for word in self._tokenize(entity):
                    self.entity_index[word].add(doc_id)
            
            # 索引分类
            category = doc_info["category"]
            self.category_index[category].add(doc_id)
            
            # 索引全文（标题+摘要+关键点）
            fulltext = f"{doc_info['title']} {doc_info['summary']} {' '.join(doc_info['keypoints'])}"
            for word in self._tokenize(fulltext):
                self.fulltext_index[word].add(doc_id)
        
        # 保存索引
        self.save_index()
        logger.info(f"索引构建完成: {len(self.doc_index)} 文档, {len(self.fulltext_index)} 个索引词")
    
    def _token_weight(self, token: str) -> float:
        """按词特异性调整搜索贡献，降低宽泛AI词噪声。"""
        generic = {"ai", "agent", "模型", "技术", "文章", "系统", "工具", "网站"}
        if token in generic:
            return 0.35
        if len(token) <= 2 and token not in {"cc", "os", "tpu"}:
            return 0.6
        if re.search(r'[A-Za-z].*[A-Za-z]|[0-9]|[+._-]', token):
            return 1.25
        if len(token) >= 4:
            return 1.2
        return 1.0

    def _phrase_bonus(self, query: str, doc_info: Dict, query_tokens: List[str]) -> float:
        """短语/标题命中加分，提升明显标题相关结果。"""
        q = (query or "").lower().strip()
        title = (doc_info.get("title") or "").lower()
        content = (doc_info.get("content") or "").lower()
        bonus = 0.0
        compact_q = re.sub(r'\s+', '', q)
        compact_title = re.sub(r'\s+', '', title)
        if compact_q and compact_q in compact_title:
            bonus += 8.0
        for token in query_tokens:
            if len(token) >= 3 and token in title:
                bonus += 2.5 * self._token_weight(token)
            elif len(token) >= 4 and token in content[:3000]:
                bonus += 0.75 * self._token_weight(token)
        return bonus

    def search(self, query: str, search_type: str = "fulltext", limit: int = 10, 
                offset: int = 0, category_filter: Optional[str] = None,
                highlight: bool = False) -> List[Dict]:
        """
        搜索文档
        
        Args:
            query: 搜索查询
            search_type: 搜索类型 (fulltext, title, summary, entity, category)
            limit: 返回结果数量限制
            offset: 结果偏移量（用于分页）
            category_filter: 分类过滤（只返回指定分类的结果）
            highlight: 是否在摘要中添加高亮标记
        
        Returns:
            搜索结果列表，按相关性排序
        """
        if not self.doc_index:
            logger.warning("索引为空，请先构建索引")
            return []
        
        query_tokens = self._expand_query_tokens(query, self._tokenize(query))
        if not query_tokens:
            return []
        
        # 计算相关度得分
        scores = defaultdict(float)
        
        for token in query_tokens:
            if search_type == "title":
                doc_ids = self.title_index.get(token, set())
            elif search_type == "summary":
                doc_ids = self.summary_index.get(token, set())
            elif search_type == "entity":
                doc_ids = self.entity_index.get(token, set())
            elif search_type == "category":
                doc_ids = self.category_index.get(token, set())
            else:  # fulltext
                # 综合多个索引
                doc_ids = set()
                for idx_type in [self.title_index, self.summary_index, self.entity_index, self.fulltext_index]:
                    doc_ids.update(idx_type.get(token, set()))
            
            # 为匹配的文档增加分数
            weight = self._token_weight(token)
            for doc_id in doc_ids:
                # 根据匹配的索引类型给予不同权重
                if doc_id in self.title_index.get(token, set()):
                    scores[doc_id] += 3.0 * weight  # 标题匹配权重最高
                if doc_id in self.entity_index.get(token, set()):
                    scores[doc_id] += 2.0 * weight  # 实体匹配权重较高
                if doc_id in self.summary_index.get(token, set()):
                    scores[doc_id] += 1.5 * weight  # 摘要匹配权重中等
                if doc_id in self.fulltext_index.get(token, set()):
                    scores[doc_id] += 1.0 * weight  # 全文匹配权重较低
        
        # 准备结果
        results = []
        adjusted_scores = {}
        for doc_id, score in scores.items():
            doc_info = self.doc_index.get(doc_id)
            if doc_info:
                adjusted_scores[doc_id] = score + self._phrase_bonus(query, doc_info, query_tokens)

        seen_titles = set()
        for doc_id, score in sorted(adjusted_scores.items(), key=lambda x: x[1], reverse=True):
            if score <= 0:
                continue
            
            doc_info = self.doc_index.get(doc_id)
            if not doc_info:
                continue
            
            # 分类过滤
            if category_filter and doc_info["category"] != category_filter:
                continue

            title_key = re.sub(r'\s+', '', (doc_info.get("title") or "").lower())
            if title_key and title_key in seen_titles:
                continue
            if title_key:
                seen_titles.add(title_key)
            
            # 计算匹配片段
            highlights = self._get_highlights(doc_info, query_tokens)
            snippets = self._get_matched_snippets(doc_info, query_tokens)
            
            # 如果启用高亮标记，在摘要中标记匹配词
            summary_text = doc_info["summary"]
            if highlight and query_tokens:
                for token in query_tokens:
                    if len(token) >= 2:
                        summary_text = re.sub(
                            re.escape(token), 
                            lambda m: f"**{m.group()}**", 
                            summary_text, 
                            flags=re.IGNORECASE
                        )
            
            result = {
                "id": doc_id,
                "title": doc_info["title"],
                "category": doc_info["category"],
                "summary": summary_text[:200] + "..." if len(summary_text) > 200 else summary_text,
                "path": doc_info["path"],
                "score": round(score, 2),
                "highlights": highlights[:3],  # 最多3个高亮片段
                "matched_snippets": snippets[:3],
                "entities": doc_info["entities"][:5],  # 最多5个实体
                "query_tokens": query_tokens[:12],
                "modified_time": doc_info["modified_time"]
            }
            results.append(result)
        
        # 应用分页
        paginated = results[offset:offset + limit] if offset else results[:limit]
        return paginated

    def _get_matched_snippets(self, doc_info: Dict, query_tokens: List[str], *, max_snippets: int = 3) -> List[str]:
        """Return readable source snippets around matched query terms."""
        content = doc_info.get("content") or ""
        if not content:
            return []
        chunks = re.split(r'\n\s*\n|(?<=。)|(?<=！)|(?<=？)|(?<=；)|(?<=[.!?])\s+', content)
        scored = []
        tokens = [t.lower() for t in query_tokens if len(t) >= 2]
        for idx, chunk in enumerate(chunks):
            chunk = self._clean_markup(chunk.strip())
            if len(chunk) < 12:
                continue
            lower = chunk.lower()
            score = 0
            for token in tokens:
                if token in lower:
                    score += 5 + min(lower.count(token), 3)
            if score:
                scored.append((score, idx, chunk))
        snippets = []
        seen = set()
        for _score, _idx, chunk in sorted(scored, key=lambda x: (-x[0], x[1]))[:max_snippets * 2]:
            snippet = chunk[:240] + ("..." if len(chunk) > 240 else "")
            key = re.sub(r'\W+', '', snippet.lower())[:80]
            if key and key not in seen:
                seen.add(key)
                snippets.append(snippet)
            if len(snippets) >= max_snippets:
                break
        return snippets
    
    def _get_highlights(self, doc_info: Dict, query_tokens: List[str]) -> List[str]:
        """获取匹配的高亮片段"""
        highlights = []
        
        # 检查标题
        title_lower = doc_info["title"].lower()
        for token in query_tokens:
            if token in title_lower:
                highlights.append(f"标题包含: {token}")
                break
        
        # 检查摘要
        summary_lower = doc_info["summary"].lower()
        for token in query_tokens:
            if token in summary_lower:
                # 提取包含关键词的句子
                sentences = re.split(r'[。！？.!?]', doc_info["summary"])
                for sentence in sentences:
                    if token in sentence.lower() and len(sentence) > 10:
                        highlights.append(sentence.strip())
                    break
                if highlights and len(highlights) > 1:
                    break

        # 检查正文片段
        for snippet in self._get_matched_snippets(doc_info, query_tokens, max_snippets=2):
            highlights.append(snippet)
            if len(highlights) >= 3:
                break
        
        # 检查实体
        for entity in doc_info["entities"][:10]:
            entity_lower = entity.lower()
            for token in query_tokens:
                if token in entity_lower:
                    highlights.append(f"实体: {entity}")
                    break
        
        return highlights
    
    def search_by_category(self, category: str) -> List[Dict]:
        """按分类搜索"""
        doc_ids = self.category_index.get(category, set())
        results = []
        
        for doc_id in doc_ids:
            doc_info = self.doc_index.get(doc_id)
            if not doc_info:
                continue
            
            results.append({
                "id": doc_id,
                "title": doc_info["title"],
                "summary": doc_info["summary"][:100] + "..." if len(doc_info["summary"]) > 100 else doc_info["summary"],
                "path": doc_info["path"],
                "category": doc_info["category"]
            })
        
        # 按修改时间排序
        results.sort(key=lambda x: x.get("modified_time", 0), reverse=True)
        return results
    
    def search_by_entity(self, entity: str) -> List[Dict]:
        """按实体搜索"""
        entity_lower = entity.lower()
        doc_ids = self.entity_index.get(entity_lower, set())
        results = []
        
        for doc_id in doc_ids:
            doc_info = self.doc_index.get(doc_id)
            if not doc_info:
                continue
            
            # 实体匹配给予基础分数 2.0（与搜索中的实体匹配权重一致）
            results.append({
                "id": doc_id,
                "title": doc_info["title"],
                "summary": doc_info["summary"][:100] + "..." if len(doc_info["summary"]) > 100 else doc_info["summary"],
                "path": doc_info["path"],
                "category": doc_info["category"],
                "entity": entity,
                "score": 2.0  # 实体匹配基础分数
            })
        
        return results
    
    def get_document(self, doc_id: str) -> Optional[Dict]:
        """获取单个文档详情"""
        return self.doc_index.get(doc_id)
    
    def get_all_categories(self) -> List[str]:
        """获取所有分类"""
        return list(self.category_index.keys())
    
    def get_all_entities(self, min_freq: int = 1) -> List[Tuple[str, int]]:
        """获取所有实体及其频率"""
        entities_with_freq = [(entity, len(doc_ids)) for entity, doc_ids in self.entity_index.items()]
        entities_with_freq.sort(key=lambda x: x[1], reverse=True)
        
        if min_freq > 1:
            entities_with_freq = [(e, f) for e, f in entities_with_freq if f >= min_freq]
        
        return entities_with_freq
    
    def save_index(self):
        """保存索引到文件"""
        index_data = {
            "doc_index": self.doc_index,
            "title_index": {k: list(v) for k, v in self.title_index.items()},
            "summary_index": {k: list(v) for k, v in self.summary_index.items()},
            "entity_index": {k: list(v) for k, v in self.entity_index.items()},
            "fulltext_index": {k: list(v) for k, v in self.fulltext_index.items()},
            "category_index": {k: list(v) for k, v in self.category_index.items()}
        }
        
        try:
            with open(self.index_file, 'w', encoding='utf-8') as f:
                json.dump(index_data, f, ensure_ascii=False, indent=2)
            logger.info(f"索引已保存到: {self.index_file}")
        except Exception as e:
            logger.error(f"保存索引失败: {e}")
    
    def load_index(self) -> bool:
        """从文件加载索引"""
        if not self.index_file.exists():
            return False
        
        try:
            with open(self.index_file, 'r', encoding='utf-8') as f:
                index_data = json.load(f)
            
            self.doc_index = index_data["doc_index"]
            self.title_index = {k: set(v) for k, v in index_data["title_index"].items()}
            self.summary_index = {k: set(v) for k, v in index_data["summary_index"].items()}
            self.entity_index = {k: set(v) for k, v in index_data["entity_index"].items()}
            self.fulltext_index = {k: set(v) for k, v in index_data["fulltext_index"].items()}
            self.category_index = {k: set(v) for k, v in index_data["category_index"].items()}
            
            logger.info(f"从文件加载索引: {len(self.doc_index)} 文档")
            return True
            
        except Exception as e:
            logger.error(f"加载索引失败: {e}")
            return False
    
    def print_stats(self):
        """打印统计信息"""
        print("\n" + "="*60)
        print("🔍 搜索系统统计")
        print("="*60)
        print(f"📄 文档总数: {len(self.doc_index)}")
        print(f"🏷️  分类数量: {len(self.category_index)}")
        print(f"🔤 实体数量: {len(self.entity_index)}")
        print(f"📖 索引词数量: {len(self.fulltext_index)}")
        
        if self.category_index:
            print(f"\n分类统计:")
            for category, doc_ids in sorted(self.category_index.items(), key=lambda x: len(x[1]), reverse=True):
                print(f"  - {category}: {len(doc_ids)} 篇")
        
        top_entities = self.get_all_entities()[:5]
        if top_entities:
            print(f"\n热门实体 (前5):")
            for entity, freq in top_entities:
                print(f"  - {entity}: {freq} 篇")
        
        print(f"\n📁 索引文件: {self.index_file}")
        print("="*60)


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="Wiki知识库搜索系统")
    parser.add_argument("--query", help="搜索查询")
    parser.add_argument("--type", default="fulltext", 
                       choices=["fulltext", "title", "summary", "entity", "category"],
                       help="搜索类型 (默认: fulltext)")
    parser.add_argument("--limit", type=int, default=10, help="返回结果数量")
    parser.add_argument("--rebuild", action="store_true", help="重建索引")
    parser.add_argument("--stats", action="store_true", help="显示统计信息")
    parser.add_argument("--categories", action="store_true", help="列出所有分类")
    parser.add_argument("--entities", action="store_true", help="列出所有实体")
    parser.add_argument("--category", help="按分类搜索")
    parser.add_argument("--entity", help="按实体搜索")
    parser.add_argument("--base-dir", default=".", help="项目基础目录")
    
    args = parser.parse_args()
    
    base_dir = Path(args.base_dir).expanduser()
    if not base_dir.exists():
        print(f"错误: 目录不存在: {base_dir}")
        return 1
    
    searcher = WikiSearcher(base_dir)
    searcher.build_index(rebuild=args.rebuild)
    
    if args.stats:
        searcher.print_stats()
        return 0
    
    if args.categories:
        categories = searcher.get_all_categories()
        print("\n📂 所有分类:")
        for category in sorted(categories):
            doc_count = len(searcher.category_index.get(category, []))
            print(f"  - {category} ({doc_count}篇)")
        return 0
    
    if args.entities:
        entities = searcher.get_all_entities(min_freq=1)
        print(f"\n🔤 所有实体 (共{len(entities)}个):")
        for entity, freq in entities[:20]:  # 显示前20个
            print(f"  - {entity}: {freq}篇")
        if len(entities) > 20:
            print(f"  ... 还有 {len(entities)-20} 个实体")
        return 0
    
    if args.category:
        results = searcher.search_by_category(args.category)
        print(f"\n🏷️  分类 '{args.category}' 的文档 ({len(results)}篇):")
        for i, result in enumerate(results, 1):
            print(f"\n{i}. {result['title']}")
            print(f"   摘要: {result['summary']}")
            print(f"   路径: {result['path']}")
        return 0
    
    if args.entity:
        results = searcher.search_by_entity(args.entity)
        print(f"\n🔤 实体 '{args.entity}' 相关的文档 ({len(results)}篇):")
        for i, result in enumerate(results, 1):
            print(f"\n{i}. {result['title']} ({result['category']})")
            print(f"   摘要: {result['summary']}")
        return 0
    
    if args.query:
        results = searcher.search(args.query, search_type=args.type, limit=args.limit)
        print(f"\n🔍 搜索 '{args.query}' 的结果 ({len(results)}个):")
        
        if not results:
            print("没有找到匹配的文档")
            return 0
        
        for i, result in enumerate(results, 1):
            print(f"\n{i}. {result['title']} (分数: {result['score']})")
            print(f"   分类: {result['category']}")
            print(f"   摘要: {result['summary']}")
            
            if result['highlights']:
                print(f"   匹配: {'; '.join(result['highlights'][:2])}")
            
            if result['entities']:
                print(f"   实体: {', '.join(result['entities'][:3])}")
            
            print(f"   路径: {result['path']}")
        
        return 0
    
    # 如果没有参数，显示帮助
    parser.print_help()
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
