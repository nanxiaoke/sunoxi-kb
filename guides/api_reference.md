# Karpathy 知识库 — API 参考

## 📂 模块总览

| 文件 | 类/函数 | 说明 |
|------|---------|------|
| `search.py` | `WikiSearcher` | 搜索引擎（jieba分词、全文/实体/分类搜索） |
| `qa.py` | `KnowledgeBaseQA` | 问答系统（检索+生成、缓存、指标追踪） |
| `processor.py` | `DocumentProcessor`, `OllamaClient` | AI文档处理、Ollama接口 |
| `batch_processor.py` | `BatchProcessor` | 批量AI文档处理（ollama run子进程） |
| `optimizer.py` | `LRUCache`, `MetricsTracker`, `ModelWarmup`, `IncrementalIndex`, `SystemHealth` | 性能优化、监控运维 |
| `auto_importer.py` | `AutoImporter` | 自动文档导入管道 |
| `kb_cli.py` | `KnowledgeBaseCLI`, `InteractiveCLI` | 命令行接口 |
| `web_ui.py` | Flask应用 | Web界面 |

---

## 🔍 search.py — 搜索引擎

### WikiSearcher(base_dir)

核心搜索类，管理文档索引和多种搜索策略。

#### 初始化
```python
from pathlib import Path
from search import WikiSearcher

searcher = WikiSearcher(Path("~/karpathy-kb"))
searcher.build_index(rebuild=False)  # 从文件加载或全量重建
```

#### 搜索方法

| 方法 | 参数 | 返回 | 说明 |
|------|------|------|------|
| `search(query, type="fulltext", limit=10)` | query: str, type: str, limit: int | `List[Dict]` | 多类型搜索（fulltext/title/summary/entity） |
| `search_by_category(category)` | category: str | `List[Dict]` | 按分类搜索 |
| `search_by_entity(entity)` | entity: str | `List[Dict]` | 按实体搜索 |
| `get_document(doc_id)` | doc_id: str | `Dict or None` | 按ID获取完整文档 |
| `get_all_categories()` | — | `List[str]` | 列出所有分类 |
| `get_all_entities(min_freq=1)` | min_freq: int | `List[Tuple[str,int]]` | 按频率列出实体 |
| `build_index(rebuild=False)` | rebuild: bool | — | 构建/加载索引 |
| `print_stats()` | — | — | 打印索引统计 |

#### 返回文档格式 (Dict)
```json
{
  "id": "rag_notes_3e5a52f5",
  "title": "RAG笔记",
  "category": "notes",
  "summary": "RAG（检索增强生成）是一种...",
  "entities": ["RAG", "向量数据库", "ChromaDB"],
  "content": "完整文档内容...",
  "path": "notes/rag_notes_3e5a52f5.md",
  "score": 4.5,
  "highlights": ["包含关键词的上下文片段..."],
  "modified_time": 1776961679.97
}
```

---

## 💡 qa.py — 问答系统

### KnowledgeBaseQA(base_dir)

检索增强生成（RAG）问答系统，集成LRU缓存和性能指标。

#### 初始化
```python
from qa import KnowledgeBaseQA

qa = KnowledgeBaseQA(Path("~/karpathy-kb"))
```

#### 核心方法

| 方法 | 参数 | 返回 | 说明 |
|------|------|------|------|
| `answer_question(question, max_docs=4)` | question: str, max_docs: int | `Dict` | 回答问题（主接口） |
| `search_relevant_documents(question, max_docs=3)` | question: str, max_docs: int | `List[Dict]` | 搜索相关文档 |
| `extract_context_from_documents(documents, max_len=4000)` | documents: List, max_len: int | `str` | 提取上下文 |
| `generate_answer(question, context, documents)` | question, context, documents | `Tuple[str, List]` | AI生成答案 |
| `interactive_mode()` | — | — | 交互式问答 |

#### 返回格式
```json
{
  "question": "什么是RAG？",
  "answer": "RAG（Retrieval-Augmented Generation）是一种...\n\n[文档1][文档2]",
  "documents": [
    {"title": "RAG笔记", "summary": "...", "score": 4.5}
  ],
  "citations": [
    {"document_index": 1, "title": "RAG笔记", "score": 4.5}
  ],
  "latency": 127.02,
  "cache_hit": false,
  "timestamp": "2026-04-23T17:54:00"
}
```

#### 缓存机制
- LRU缓存，容量50条
- 持久化到 `qa_cache.json`
- 相同问题直接返回缓存（<1ms）
- 缓存key：问题的小写+strip

---

## 🔧 processor.py — 文档处理

### DocumentProcessor(ollama_client=None)
AI文档处理器，负责格式识别、内容提取、AI处理。

```python
from processor import DocumentProcessor, OllamaClient

# 初始化
client = OllamaClient(model="gemma4:e4b")
proc = DocumentProcessor(client)

# 读取文档
doc_info = proc.read_document(Path("doc.pdf"))

# AI处理
result = proc.process_document(doc_info)
```

### OllamaClient(model="gemma4:e4b")
Ollama模型访问层。

```python
client = OllamaClient()

# 方法（均返回文本）
summary = client.summarize(content)       # 生成摘要
keypoints = client.extract_keypoints(content)  # 提取关键点
category = client.categorize(content)     # 分类

# 底层子进程API
text = client._generate_via_subprocess(prompt)
```

---

## 📦 batch_processor.py — 批量处理

### BatchProcessor(base_dir)
使用 `ollama run` 子进程的批量文档处理器（绕过API bug）。

```python
from batch_processor import BatchProcessor

bp = BatchProcessor(Path("~/karpathy-kb"))
bp.run(dry_run=False, limit=5, category_filter="articles")
```

| 方法 | 说明 |
|------|------|
| `scan_raw_files(category)` | 扫描待处理文件 |
| `process_file(file_info)` | 处理单个文件（ollama run → wiki） |
| `run(dry_run, limit, category, force)` | 批量处理入口 |

---

## 🚀 数据流

```
raw/*.md/.pdf/.docx
        │
        ▼
batch_processor.py  ──→  ollama run gemma4:e4b
auto_importer.py           │
        │                  ▼
        │           wiki/*.md
        │                  │
        ▼                  ▼
  搜索索引            knowledgebaseqa
  (search_index.json)      │
        │                  │
        ▼                  ▼
   kb_cli search       kb_cli qa
   web_ui search       web_ui qa
```

### 导入流程
```
新文件放入raw/ → auto_importer扫描 → batch_processor处理 → wiki结构化 → 索引重建
```

### 问答流程
```
用户问题 → 多策略搜索 → 上下文提取 → ollama生成 → 缓存 → 格式化输出
   (全文+实体+   (摘要+关键点   (带引用的   (LRU 50条)   (彩色/HTML)
    清理查询)      +实体)        回答)
```
