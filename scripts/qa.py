#!/usr/bin/env python3
"""
知识库问答系统
基于检索的生成式问答（Retrieval-Augmented Generation）
"""

import os
import re
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 导入本地模块
try:
    from search import WikiSearcher
    from llm_service import LLMService
except ImportError:
    # 尝试相对导入
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from search import WikiSearcher
    from llm_service import LLMService

# 导入优化模块（轻量级）
try:
    from optimizer import LRUCache, MetricsTracker, ModelWarmup
    _OPT = True
except ImportError:
    _OPT = False


class KnowledgeBaseQA:
    """知识库问答系统"""
    
    def __init__(self, base_dir: Path):
        from pathlib import Path
        self.base_dir = Path(base_dir) if not isinstance(base_dir, Path) else base_dir
        self.wiki_dir = self.base_dir / "wiki"
        self.searcher = WikiSearcher(self.base_dir)
        self.llm = None
        self.last_llm_result = None
        
        # 缓存与性能追踪
        if _OPT:
            self.cache = LRUCache(capacity=50)
            self.cache.load(self.base_dir / "qa_cache.json")
            self.metrics = MetricsTracker()
        else:
            self.cache = None
            self.metrics = None
        
        # 初始化搜索索引
        logger.info("初始化问答系统...")
        self.searcher.build_index(rebuild=False)
        
        # 初始化统一 LLM 服务。默认 extractive 答案不调用模型；
        # 仅 answer_mode=llm 时使用 qa FlowPolicy。
        self._init_llm()
    
    def _init_llm(self):
        """初始化统一 LLM 服务。"""
        try:
            self.llm = LLMService()
            flow = self.llm.config.flow("qa")
            logger.info(f"LLMService初始化成功（qa flow providers={flow.providers}）")
        except Exception as e:
            logger.warning(f"LLMService初始化失败: {e}")
            self.llm = None
    
    def _clean_query(self, question: str) -> str:
        """清理查询：移除疑问词和标点，提取核心内容"""
        # 常见中文停用词和疑问词
        stop_words = [
            "什么", "为什么", "为何", "如何", "怎样", "怎么", "吗", "呢", "吧", "啊", "呀",
            "是不是", "有没有", "可否", "能否", "何时", "哪里", "谁", "多少", "几", "哪个",
            "是", "的", "了", "在", "和", "与", "或", "及", "等", "着", "过", "来", "去",
            "就", "都", "也", "还", "又", "再", "不", "没", "没有", "很", "非常", "特别",
            "可以", "能够", "可能", "应该", "需要", "必须", "要", "想", "希望", "打算",
            "它", "这个", "那个", "哪些", "主要", "问题", "解决", "说", "而", "但是", "因为"
        ]
        
        cleaned = question
        
        # 移除所有标点符号
        cleaned = re.sub(r'[\?？!！。，,；;：:\"\'（）()\[\]{}《》<>「」『』【】〖〗]', ' ', cleaned)
        
        # 移除停用词
        for word in sorted(stop_words, key=len, reverse=True):
            cleaned = cleaned.replace(word, ' ')
        
        # 移除多余空格
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        
        # 如果没有内容了，返回原始问题
        if not cleaned:
            return question
        
        return cleaned
    
    def search_relevant_documents(self, question: str, max_docs: int = 3) -> List[Dict]:
        """搜索相关问题相关文档"""
        # 尝试多种搜索策略
        search_results = []
        
        # 策略0: 清理查询后搜索
        cleaned_question = self._clean_query(question)
        if cleaned_question != question:
            logger.info(f"🤖 查询清理: '{question}' -> '{cleaned_question}'")
            cleaned_results = self.searcher.search(cleaned_question, search_type="fulltext", limit=max_docs*2)
            logger.info(f"  清理查询结果: {len(cleaned_results)} 个")
            search_results.extend(cleaned_results)
        
        # 策略1: 全文搜索原始问题
        results = self.searcher.search(question, search_type="fulltext", limit=max_docs*2)
        logger.info(f"  原始查询结果: {len(results)} 个")
        search_results.extend(results)
        
        # 策略2: 实体搜索
        # 提取问题中的实体词
        entity_count = 0
        
        # 优先使用清理后的查询进行实体提取
        if cleaned_question != question:
            cleaned_question_words = re.findall(r'[A-Z][a-z]+|[A-Z]+|[a-z]+|[\u4e00-\u9fff]+', cleaned_question)
            logger.info(f"  清理后实体提取: {cleaned_question_words}")
            for word in cleaned_question_words[:5]:
                if len(word) > 2:
                    entity_results = self.searcher.search_by_entity(word)
                    entity_count += len(entity_results)
                    search_results.extend(entity_results)
        
        # 也尝试原始查询的实体提取（作为后备）
        original_question_words = re.findall(r'[A-Z][a-z]+|[A-Z]+|[a-z]+|[\u4e00-\u9fff]+', question)
        logger.info(f"  原始实体提取: {original_question_words}")
        for word in original_question_words[:5]:
            if len(word) > 2:
                entity_results = self.searcher.search_by_entity(word)
                entity_count += len(entity_results)
                search_results.extend(entity_results)
        
        logger.info(f"  实体搜索结果: {entity_count} 个")
        
        # 去重，按分数排序；过滤低相关文档，避免无关上下文污染答案
        sorted_results = sorted(search_results, key=lambda x: x.get("score", 0), reverse=True)
        top_score = sorted_results[0].get("score", 0) if sorted_results else 0
        min_score = max(0.1, top_score * 0.6) if top_score >= 1.5 else 0.1
        
        seen_ids = set()
        seen_titles = set()
        unique_results = []
        for result in sorted_results:
            if result.get("score", 0) < min_score:
                continue
            doc_id = result.get("id")
            title_key = re.sub(r'\s+', '', (result.get("title") or "").lower())
            # 同一篇文章可能同时存在于 articles/ 与 technologies/，QA上下文只保留最高分版本
            if doc_id and doc_id not in seen_ids and title_key not in seen_titles:
                seen_ids.add(doc_id)
                if title_key:
                    seen_titles.add(title_key)
                unique_results.append(result)
            
            if len(unique_results) >= max_docs:
                break
        
        logger.info(f"  最终去重结果: {len(unique_results)} 个")
        if unique_results:
            for i, r in enumerate(unique_results, 1):
                logger.info(f"    文档{i}: {r.get('title', '无标题')} (分数: {r.get('score', 0):.2f})")
        
        return unique_results
    
    def _clean_answer_text(self, text: str) -> str:
        """清理用于极速答案的 Markdown/Wiki 噪声。"""
        text = text or ""
        text = re.sub(r'\[\[([^\]|]+)\|([^\]]+)\]\]', r'\2', text)
        text = re.sub(r'\[\[([^\]]+)\]\]', r'\1', text)
        text = re.sub(r'`([^`]+)`', r'\1', text)
        text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
        text = re.sub(r'^\s*[#>\-]*\s*(候选来源|作者|公众号\w*|发布时间|原文链接|抓取时间|状态|建议分类|来源|处理时间|分类|原始格式)\s*[:：].*$', '', text, flags=re.MULTILINE)
        text = re.sub(r'^\s*[#>\-]*\s*(公众号biz|公众号user_name)\s*[:：].*$', '', text, flags=re.MULTILINE)
        text = re.sub(r'https?://\S+', '', text)
        text = re.sub(r'^#{1,6}\s*', '', text, flags=re.MULTILINE)
        text = re.sub(r'（AI生成的摘要）|（AI提取的关键点）|（未提取到实体）', '', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    def _is_placeholder(self, text: str) -> bool:
        text = (text or '').strip()
        return (not text) or ('AI生成的摘要' in text) or ('AI提取的关键点' in text) or ('未提取到' in text)

    def _is_noisy_text(self, text: str) -> bool:
        text = text or ""
        noise_patterns = [
            "提取方法", "内容长度", "文件哈希", "抓取时间", "公众号biz", "公众号user_name",
            "原文标题:", "来源:", "发布时间:", "此条目由AI自动生成"
        ]
        return any(p in text for p in noise_patterns)

    def _qa_content(self, content: str) -> str:
        """优先使用真实原文内容，跳过自动生成的相关文档/元数据区域。"""
        content = content or ""
        marker = "## 📄 原始内容预览"
        if marker in content:
            content = content.split(marker, 1)[1]
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                content = parts[2].strip()
        # 去掉尾部自动生成标记
        content = content.split("*此条目由AI自动生成", 1)[0]
        cleaned_lines = []
        for line in content.splitlines():
            stripped = line.strip()
            if not stripped:
                cleaned_lines.append("")
                continue
            if stripped == "---":
                continue
            if re.match(r'^>\s*\*\*(来源|抓取时间|作者|发布时间|提取方法|内容长度|文件哈希|处理时间|分类|原始格式)\*\*\s*[:：]', stripped):
                continue
            if re.match(r'^\s*(来源|抓取时间|作者|发布时间|提取方法|内容长度|文件哈希|公众号biz|公众号user_name)\s*[:：]', stripped):
                continue
            cleaned_lines.append(line)
        content = "\n".join(cleaned_lines)
        return self._clean_answer_text(content)

    def _split_content_chunks(self, content: str) -> List[str]:
        """将长文切成可检索片段，兼容 Markdown 段落和超长中文段落。"""
        raw_parts = re.split(r'\n\s*\n|(?<=。)|(?<=！)|(?<=？)|(?<=；)', content or "")
        chunks = []
        for part in raw_parts:
            part = part.strip()
            if len(part) < 4:
                continue
            # 微信文章经常是一整段超长文本，继续按固定窗口切开，避免只取开头。
            if len(part) > 900:
                step = 650
                size = 900
                for start in range(0, len(part), step):
                    chunk = part[start:start + size].strip()
                    if len(chunk) >= 4:
                        chunks.append(chunk)
            else:
                chunks.append(part)
        return chunks

    def _extract_relevant_content(self, content: str, query_tokens: List[str], max_chars: int = 1800) -> str:
        """基于查询词提取最相关正文片段，而不是机械截取文章开头。"""
        chunks = self._split_content_chunks(content)
        if not chunks:
            return (content or "")[:max_chars]
        
        tokens = [t.lower() for t in (query_tokens or []) if len(t.strip()) >= 2]
        scored = []
        for idx, chunk in enumerate(chunks):
            lower = chunk.lower()
            score = 0
            for token in tokens:
                if token in lower:
                    score += 5 + min(lower.count(token), 3)
                # 对“横纵分析法”这类组合词，允许子词命中
                if len(token) >= 4:
                    for sub in re.findall(r'[\u4e00-\u9fff]{2,}|[a-zA-Z0-9]{2,}', token):
                        if sub.lower() in lower:
                            score += 1
            if score > 0:
                scored.append((score, idx, chunk))
        
        if not scored:
            return content[:max_chars]
        
        # 取高分片段，并保留相邻片段作为上下文，最后按原文顺序输出。
        selected = set()
        for _, idx, _ in sorted(scored, key=lambda x: (-x[0], x[1]))[:5]:
            # 命中片段前后都保留一些邻接句子，避免只拿到标题/术语而漏掉定义说明
            for near in range(idx - 3, idx + 20):
                if 0 <= near < len(chunks):
                    selected.add(near)
        
        result_parts = []
        current_len = 0
        for idx in sorted(selected):
            chunk = chunks[idx]
            if current_len + len(chunk) + 8 > max_chars:
                break
            result_parts.append(chunk)
            current_len += len(chunk) + 8
        return "\n...\n".join(result_parts)

    def extract_context_from_documents(self, documents: List[Dict], query_tokens: List[str] = None, max_context_length: int = 6500) -> str:
        """从相关文档中提取上下文信息（优化版：支持基于 Query 提取相关段落）"""
        context_parts = []
        total_length = 0
        query_tokens = query_tokens or []
        
        for i, doc in enumerate(documents, 1):
            doc_id = doc.get("id")
            doc_info = self.searcher.get_document(doc_id)
            if not doc_info:
                continue
            
            # 提取文档内容
            title = doc_info.get("title", "未知标题")
            category = doc_info.get("category", "")
            summary = doc_info.get("summary", "")
            keypoints = doc_info.get("keypoints", [])
            entities = doc_info.get("entities", [])
            content = self._qa_content(doc_info.get("content", ""))
            
            # 构建结构化文档上下文
            doc_context = f"[文档{i}: {title}]"
            if category:
                doc_context += f" (分类: {category})"
            doc_context += "\n"
            
            if summary:
                # 完整摘要（不截断300字，让模型看到更多内容）
                doc_context += f"摘要: {summary}\n"
            
            if keypoints and isinstance(keypoints, list):
                doc_context += "关键点:\n"
                for j, point in enumerate(keypoints[:5], 1):  # 最多5个关键点
                    doc_context += f"  {j}. {point[:150]}\n"
            
            if entities and isinstance(entities, list):
                relevant_entities = [e for e in entities[:8] if len(e) > 1]
                if relevant_entities:
                    doc_context += f"实体: {', '.join(relevant_entities)}\n"
            
            # 如果内容存在，基于 query 提取最相关的正文片段，避免只截取文章开头
            if content and len(content) > 200:
                content_snippet = self._extract_relevant_content(content, query_tokens, max_chars=1800)
                doc_context += f"相关正文片段:\n{content_snippet}\n"
            
            # 检查是否会超出上下文长度限制
            if total_length + len(doc_context) > max_context_length:
                if context_parts:
                    break
                doc_context = doc_context[:max_context_length]
                context_parts.append(doc_context)
                break
            
            context_parts.append(doc_context)
            total_length += len(doc_context)
        
        return "\n\n".join(context_parts)
    
    def generate_extractive_answer(self, question: str, documents: List[Dict], query_tokens: List[str]) -> Tuple[str, List[Dict]]:
        """极速可追溯答案：不调用LLM，基于摘要/关键点/相关片段生成。适合Web交互默认路径。"""
        if not documents:
            return "抱歉，知识库中没有找到相关文档来回答这个问题。", []

        citations = [
            {
                "document_index": i,
                "title": doc.get("title", "未知标题"),
                "path": doc.get("path", ""),
                "score": doc.get("score", 0),
            }
            for i, doc in enumerate(documents, 1)
        ]

        points: List[str] = []
        conclusion_bits: List[str] = []
        for i, doc in enumerate(documents, 1):
            doc_info = self.searcher.get_document(doc.get("id")) or {}
            title = doc_info.get("title") or doc.get("title", "未知标题")
            summary = self._clean_answer_text((doc_info.get("summary") or doc.get("summary") or "").strip())
            keypoints = doc_info.get("keypoints") or []
            content = self._qa_content(doc_info.get("content") or "")

            if i == 1:
                if summary and not self._is_placeholder(summary) and not self._is_noisy_text(summary):
                    first_summary = re.split(r'[。！？.!?]\s*', summary)[0].strip()
                    conclusion_bits.append(first_summary or title)
                else:
                    conclusion_bits.append(f"《{title}》是知识库中与问题最相关的文档")

            snippet = self._extract_relevant_content(content, query_tokens, max_chars=900) if content else ""
            # 选择含查询词的短句补充，避免整段堆砌
            sentences = [x.strip() for x in re.split(r'(?<=[。！？.!?])\s*|\n+', snippet) if len(x.strip()) >= 2]
            anchor_seen = False
            for sent in sentences[:30]:
                sent = self._clean_answer_text(sent)
                low = sent.lower()
                if any(bad in sent for bad in ["公众号", "候选来源", "原文链接", "抓取时间", "建议分类", "Mz", "gh_"]):
                    continue
                matched = any(t.lower() in low for t in query_tokens if len(t) >= 2)
                if matched:
                    anchor_seen = True
                min_len = 6 if (i == 1 and anchor_seen) else 12
                if matched and len(sent) <= max(len(t) for t in query_tokens if len(t) >= 2) + 2:
                    continue
                if len(sent) >= min_len and (matched or (i == 1 and anchor_seen)):
                    points.append(f"- {sent[:180]} [文档{i}]")
                if len(points) >= 12:
                    break
            if len(points) >= 12:
                break

            if not self._is_placeholder(" ".join(map(str, keypoints))):
                for kp in keypoints[:4]:
                    kp = self._clean_answer_text(str(kp).strip().lstrip('-•0123456789.、 '))
                    if kp and len(kp) >= 6 and not self._is_noisy_text(kp):
                        points.append(f"- {kp[:180]} [文档{i}]")
                if len(points) >= 12:
                    break

        # 去重并限制长度
        deduped = []
        seen = set()
        for p in points:
            key = re.sub(r'\W+', '', p.lower())[:80]
            if key and key not in seen:
                seen.add(key)
                deduped.append(p)
            if len(deduped) >= 10:
                break

        conclusion = conclusion_bits[0] if conclusion_bits else documents[0].get("title", "相关文档")
        if len(conclusion) > 180:
            conclusion = conclusion[:180] + "…"
        answer = f"**结论**\n{conclusion} [文档1]\n\n**要点**\n"
        answer += "\n".join(deduped or [f"- 可参考《{documents[0].get('title', '相关文档')}》的摘要和正文片段。 [文档1]"])
        answer += f"\n\n**总结**\n以上回答基于检索到的 {len(documents)} 篇相关文档；如需更完整解释，可以打开参考来源继续阅读。"
        return self._format_answer(answer, citations), citations

    def generate_answer(self, question: str, context: str, documents: List[Dict]) -> Tuple[str, List[Dict]]:
        """生成答案（使用 LLMService 的 qa FlowPolicy）"""
        if not self.llm:
            return "抱歉，AI模型服务暂时不可用。", documents
        
        try:
            # 短提示 + 强约束，减少 Gemma 思考和冗长输出，提高 Web 交互速度。
            system_prompt = """Do not think. 你是知识库QA助手。只基于给定文档中文回答，不编造；必须引用[文档N]；信息不足就说“文档中未提及”。答案分为：结论、要点、总结。控制在220-360字。"""
            
            # 准备用户消息
            user_message = f"""问题：{question}

文档：
{context}

请直接给出中文答案，引用相关文档。"""
            
            logger.info(f"生成答案（上下文长度: {len(context)}字符）...")
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ]
            result = self.llm.chat(
                "qa",
                messages,
                options={"think": False, "temperature": 0.2, "top_p": 0.8, "num_predict": 520, "repeat_penalty": 1.08},
            )
            self.last_llm_result = result.to_dict()
            if result.status != "ok":
                logger.error(f"QA LLM调用失败: {result.error}")
                return f"抱歉，生成答案时出现错误: {result.error}", []
            logger.info(
                "QA LLM provider: %s / %s%s",
                result.provider,
                result.model,
                f" (fallback from {result.fallback_from})" if result.fallback_from else "",
            )
            response = result.content
            
            if response:
                answer = response.strip()
                
                # 清理思考残留
                answer = re.sub(r'^[.。、，,\s]+', '', answer)
                if 'done thinking' in answer:
                    parts = answer.split('done thinking')
                    answer = parts[-1].strip()
                
                # 提取引用信息；如果模型没有显式写出 [文档N]，仍按检索上下文补充参考文档，
                # 避免 QA 输出没有可追溯来源。
                citations = self._extract_citations(answer, documents)
                if not citations and documents:
                    citations = [
                        {
                            "document_index": i,
                            "title": doc.get("title", "未知标题"),
                            "path": doc.get("path", ""),
                            "score": doc.get("score", 0),
                        }
                        for i, doc in enumerate(documents, 1)
                    ]
                
                # 格式化答案
                formatted_answer = self._format_answer(answer, citations)
                
                return formatted_answer, citations
            else:
                return "抱歉，生成答案时出现错误。", []
                
        except Exception as e:
            logger.error(f"生成答案失败: {e}")
            return f"抱歉，生成答案时出现错误: {str(e)}", []
    
    def _extract_citations(self, answer: str, documents: List[Dict]) -> List[Dict]:
        """从答案中提取引用信息"""
        citations = []
        
        # 查找文档引用模式 [文档1]、[文档2]等
        citation_pattern = r'\[文档(\d+)\]'
        matches = re.findall(citation_pattern, answer)
        
        for match in matches:
            try:
                doc_index = int(match) - 1  # 转换为0-based索引
                if 0 <= doc_index < len(documents):
                    doc = documents[doc_index]
                    citations.append({
                        "document_index": doc_index + 1,
                        "title": doc.get("title", "未知标题"),
                        "path": doc.get("path", ""),
                        "score": doc.get("score", 0)
                    })
            except (ValueError, IndexError):
                continue
        
        # 去重
        unique_citations = []
        seen_titles = set()
        for citation in citations:
            title = citation.get("title")
            if title not in seen_titles:
                seen_titles.add(title)
                unique_citations.append(citation)
        
        return unique_citations
    
    def _format_answer(self, answer: str, citations: List[Dict]) -> str:
        """格式化答案，添加引用信息（优化版：更清晰简洁）"""
        if not citations:
            return answer
        
        # 提取纯答案部分（去掉可能的思考过程）
        clean_answer = answer
        
        # 添加参考文档
        formatted = f"{clean_answer}\n\n"
        formatted += "📚 参考文档:\n"
        
        for citation in citations:
            title = citation.get("title", "未知标题")
            doc_index = citation.get("document_index", 0)
            score = citation.get("score", 0)
            
            # 分数高的文档排在前面，显示相关度
            relevance = ""
            if score >= 3:
                relevance = " 🔥高相关"
            elif score >= 1.5:
                relevance = " 中相关"
            
            formatted += f"  {doc_index}. {title}{relevance}\n"
        
        return formatted
    
    def _cache_key(self, question: str, max_docs: int, answer_mode: str = "auto") -> str:
        """缓存键包含索引mtime，避免新增/重建文档后命中过期答案。"""
        index_file = self.base_dir / "search_index.json"
        try:
            index_sig = str(int(index_file.stat().st_mtime))
        except Exception:
            index_sig = "noindex"
        return f"v4:{index_sig}:{max_docs}:{answer_mode}:{question.strip().lower()}"

    def answer_question(self, question: str, max_docs: int = 4, use_cache: bool = True, answer_mode: str = "auto") -> Dict[str, Any]:
        """回答问题（主接口，含缓存）。

        use_cache=False 用于 QA 质量验证，避免新增文档后命中过期答案。
        answer_mode: auto|extractive|llm。auto 默认极速答案；llm 为请求级模型生成。
        """
        answer_mode = (answer_mode or "auto").lower().strip()
        if answer_mode not in {"auto", "extractive", "llm"}:
            answer_mode = "auto"
        effective_mode = "llm" if answer_mode == "llm" else "extractive"
        logger.info(f"回答问题: {question} (mode={effective_mode})")
        
        # 缓存命中检查
        cache_key = self._cache_key(question, max_docs, effective_mode)
        if use_cache and self.cache:
            cached = self.cache.get(cache_key)
            if cached:
                logger.info(f"🔁 缓存命中: {cache_key[:40]}...")
                try:
                    result = json.loads(cached)
                    result["cache_hit"] = True
                    return result
                except Exception:
                    pass
        
        start_time = __import__('time').time()
        
        # 1. 搜索相关文档
        documents = self.search_relevant_documents(question, max_docs=max_docs)
        logger.info(f"找到 {len(documents)} 个相关文档")
        
        # 2. 提取上下文：使用清理后的查询词指导片段选择，避免长文截断错过答案
        cleaned_question = self._clean_query(question)
        query_tokens = []
        try:
            query_tokens.extend(self.searcher._tokenize(cleaned_question))
            query_tokens.extend(self.searcher._tokenize(question))
        except Exception:
            query_tokens.extend(re.findall(r'[A-Za-z0-9]+|[\u4e00-\u9fff]{2,}', cleaned_question + " " + question))
        # 保留完整清理查询本身，优先匹配“横纵分析法”等组合词
        if cleaned_question:
            query_tokens.insert(0, cleaned_question)
        query_tokens = list(dict.fromkeys([t for t in query_tokens if t]))
        context = self.extract_context_from_documents(documents, query_tokens=query_tokens)
        
        if not context or not documents:
            elapsed = __import__('time').time() - start_time
            if self.metrics:
                self.metrics.record_qa(elapsed, False, len(question))
            return {
                "question": question,
                "answer": "抱歉，知识库中没有找到相关文档来回答这个问题。",
                "documents": [],
                "context": "",
                "latency": round(elapsed, 2),
                "timestamp": datetime.now().isoformat(),
                "cache_hit": False,
                "answer_mode": "none"
            }
        
        # 3. 生成答案。请求级模式：extractive 极速答案 / llm 模型生成。
        if effective_mode == "llm":
            answer, citations = self.generate_answer(question, context, documents)
        else:
            answer, citations = self.generate_extractive_answer(question, documents, query_tokens)
        
        # 4. 构建结果
        elapsed = __import__('time').time() - start_time
        result = {
            "question": question,
            "answer": answer,
            "documents": [
                {
                    "title": doc.get("title", ""),
                    "summary": doc.get("summary", "")[:150],
                    "path": doc.get("path", ""),
                    "score": doc.get("score", 0),
                    "matched_snippets": (doc.get("matched_snippets") or [])[:3],
                }
                for doc in documents
            ],
            "citations": citations,
            "diagnostics": {
                "query_tokens": query_tokens[:12],
                "document_count": len(documents),
                "top_score": documents[0].get("score", 0) if documents else 0,
            },
            "context_preview": context[:500] + "..." if len(context) > 500 else context,
            "latency": round(elapsed, 2),
            "timestamp": datetime.now().isoformat(),
            "cache_hit": False,
            "answer_mode": effective_mode
        }
        if effective_mode == "llm" and self.last_llm_result:
            result["llm"] = {
                k: v for k, v in self.last_llm_result.items()
                if k in {"flow", "provider", "model", "duration_sec", "status", "fallback_from", "fallback_to", "error"}
            }
        
        # 5. 缓存与指标
        if use_cache and self.cache:
            self.cache.put(cache_key, json.dumps(result, ensure_ascii=False))
            self.cache.save(self.base_dir / "qa_cache.json")
        
        if self.metrics:
            self.metrics.record_qa(elapsed, True, len(question))
        
        return result
    
    def interactive_mode(self):
        """交互式问答模式"""
        print("\n" + "="*60)
        print("🤖 Karpathy知识库问答系统")
        print("="*60)
        print("输入 'exit' 或 'quit' 退出")
        print("输入 'help' 查看帮助")
        print("="*60)
        
        while True:
            try:
                question = input("\n❓ 问题: ").strip()
                
                if question.lower() in ['exit', 'quit', '退出']:
                    print("👋 再见!")
                    break
                
                if question.lower() in ['help', '帮助']:
                    print("\n📖 帮助:")
                    print("  - 输入问题，系统会基于知识库回答")
                    print("  - 示例问题:")
                    print("    * '什么是人工智能？'")
                    print("    * '横纵分析法是什么？'")
                    print("    * '有哪些AI相关的文档？'")
                    continue
                
                if not question:
                    continue
                
                # 回答问题
                result = self.answer_question(question)
                
                # 显示答案
                print("\n" + "="*60)
                print("💡 答案:")
                print("="*60)
                print(result["answer"])
                
                # 显示参考文档
                if result["documents"]:
                    print("\n📚 参考文档:")
                    for i, doc in enumerate(result["documents"], 1):
                        print(f"  {i}. {doc['title']} (分数: {doc.get('score', 0):.2f})")
                        if doc.get('summary'):
                            print(f"     摘要: {doc['summary']}")
                
                print("="*60)
                
            except KeyboardInterrupt:
                print("\n\n👋 再见!")
                break
            except Exception as e:
                print(f"❌ 错误: {e}")


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description="知识库问答系统")
    parser.add_argument("--question", "-q", help="要回答的问题")
    parser.add_argument("--interactive", "-i", action="store_true", help="交互式模式")
    parser.add_argument("--max-docs", type=int, default=3, help="最大参考文档数")
    parser.add_argument("--base-dir", default=".", help="项目基础目录")
    
    args = parser.parse_args()
    
    base_dir = Path(args.base_dir).expanduser()
    if not base_dir.exists():
        print(f"错误: 目录不存在: {base_dir}")
        return 1
    
    try:
        qa_system = KnowledgeBaseQA(base_dir)
        
        if args.interactive:
            qa_system.interactive_mode()
        elif args.question:
            result = qa_system.answer_question(args.question, max_docs=args.max_docs)
            
            # 输出JSON格式结果
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            parser.print_help()
            
    except Exception as e:
        print(f"❌ 系统错误: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
