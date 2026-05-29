# Karpathy 知识库 — 用户指南

## 📋 概述

Karpathy 知识库是一个基于本地 AI 的个人知识管理系统。
使用 Ollama + Gemma4 模型进行文档处理、智能搜索和问答。

## 🚀 快速开始

### 环境要求
- Python 3.8+
- Ollama (本地运行)
- Gemma4:e4b 模型

### 目录结构
```
~/karpathy-kb/
├── raw/              ← 原始文档（放这里等待处理）
│   ├── articles/
│   ├── notes/
│   ├── technologies/
│   └── ...
├── wiki/             ← AI处理后的结构化知识
│   ├── articles/
│   ├── notes/
│   └── ...
├── scripts/          ← 核心工具脚本
│   ├── kb_cli.py        命令行工具
│   ├── web_ui.py        Web界面
│   ├── batch_processor.py  批量处理
│   ├── auto_importer.py   自动导入管道
│   ├── optimizer.py      性能优化+健康检查
│   ├── search.py         搜索引擎
│   ├── qa.py             问答系统
│   └── processor.py      AI文档处理器
├── search_index.json  ← 搜索索引
└── guides/           ← 使用指南
```

---

## 🔧 核心功能

### 1️⃣ 命令行工具 (`kb_cli.py`)

#### 交互式模式
```bash
python3 kb_cli.py
```
启动后支持 Tab 自动补全和彩色输出：
```
kb ➜ search RAG           # 搜索
kb ➜ qa 什么是Transformer？ # 提问
kb ➜ stats                # 统计
kb ➜ entities 2            # 列出高频实体(≥2篇)
kb ➜ categories            # 分类分布
kb ➜ health                # 健康检查
kb ➜ reindex               # 重建索引
kb ➜ help                  # 帮助
kb ➜ exit                  # 退出
```

#### 单次命令模式
```bash
kb_cli.py search <关键词>
kb_cli.py qa "<问题>"
kb_cli.py stats
kb_cli.py list [分类名]
kb_cli.py entities [最小频率]
kb_cli.py categories
kb_cli.py health
kb_cli.py reindex
kb_cli.py warmup    # 预热Ollama模型
```

### 2️⃣ Web界面 (`web_ui.py`)

```bash
python3 web_ui.py
# 默认 http://localhost:8765
```

包含：
- 搜索模式：全文搜索 + 分类过滤
- 问答模式：AI生成回答 + 引用来源
- 统计面板：文档数、索引词、实体、问答次数

### 3️⃣ 自动文档导入 (`auto_importer.py`)

```bash
# 扫描待处理文件
python3 auto_importer.py scan

# 预演模式（看哪些文件会被处理）
python3 auto_importer.py dry-run

# 正式导入
python3 auto_importer.py import [--limit N] [--category notes]

# 监控模式（每300秒扫描一次）
python3 auto_importer.py --watch
```

支持格式：
| 格式 | 引擎 | 说明 |
|------|------|------|
| .md / .txt | 直接读取 | Markdown/纯文本 |
| .pdf | pdfplumber → pdfminer | 含表格增强，自动降级 |
| .docx | python-docx | 段落+标题提取 |
| .py / .js / .go | 直接读取 | 代码文件直接处理 |

### 4️⃣ 批量处理 (`batch_processor.py`)

```bash
# 处理所有未处理的raw文档
python3 batch_processor.py

# 指定分类
python3 batch_processor.py --category articles

# 限制数量
python3 batch_processor.py --limit 5

# 预演模式
python3 batch_processor.py --dry-run
```

### 5️⃣ 性能优化 (`optimizer.py`)

```bash
# 一键健康检查 + 模型预热 + 性能仪表盘
python3 optimizer.py
```

输出示例：
```
✅ ollama: ok  模型: gemma4:26b, gemma4:e4b
✅ disk: ok    808GB 空闲/1006GB 总计
✅ model: ok   已加载: ['gemma4:e4b']
✅ index: ok   13 文档
✅ wiki: ok

[QA] 5 次请求
  延迟: 127020ms (min: 300, max: 127020)
  成功率: 100.0%
```

---

## 📥 添加新文档

### 方式1：直接放入raw目录
```bash
cp my_doc.md ~/karpathy-kb/raw/notes/
python3 auto_importer.py import
```

### 方式2：手动触发处理
```bash
cd ~/karpathy-kb/scripts
python3 batch_processor.py --limit 1
```

### 方式3：通过命令行导入
```bash
kb_cli.py import my_doc.md
```

### 方式4：RSS订阅自动同步
```bash
# 添加订阅源
kb_cli.py rss add https://example.com/rss "源名称"

# 手动同步
kb_cli.py rss sync

# 查看订阅源列表
kb_cli.py rss list
```

RSS文章会自动抓取到 `raw/rss/` 目录，然后自动调用 `auto_importer.py` 处理并导入知识库。

---

## 🔍 搜索技巧

- **实体搜索**: 搜索关键词包含知识库中的实体名，自动提升相关度
- **分类过滤**: 使用 `list <分类名>` 浏览分类内容
- **多策略搜索**: 系统同时执行全文搜索 + 实体搜索 + 清理查询
- **索引实时更新**: 导入新文档后索引自动重建

---

## 🧠 问答系统

### 工作原理
1. **检索**: 搜索知识库中相关的文档（多策略：全文+实体+清理查询）
2. **上下文提取**: 从匹配文档中提取结构化信息（摘要+关键点+实体）
3. **生成**: 使用 Gemma4:e4b 模型生成带有引用的回答

### 性能说明
- **首次查询**: ~90秒（含模型加载+思考模式）
- **缓存命中**: <1秒（LRU缓存50条，持久化到磁盘）
- **第二次起**: 首次后模型常驻内存，后续查询约60-80秒

### 查询优化
- 系统会自动清理疑问词（"什么是RAG" → "RAG"）
- 同时执行原始查询和清理后查询的实体搜索
- 参考文档会去重并按相关度排序

---

## 🛠️ 维护操作

### 重建搜索索引
```bash
python3 kb_cli.py reindex
```

### 健康检查
```bash
python3 optimizer.py
```
自动检测：Ollama服务、模型加载、磁盘空间、索引完整性、Wiki文件

### 模型预热
```bash
python3 kb_cli.py warmup
```

### 清理测试文件
raw目录中的 `test_import_*.pdf` / `test_import_*.docx` 是测试文件，可删除：
```bash
rm ~/karpathy-kb/raw/notes/test_import_*
rm ~/karpathy-kb/wiki/notes/test_import_*
```

---

## ⚡ 常见问题

### Q: 模型为什么返回空响应？
这是 Gemma4 模型的已知 API bug（thinking mode 在中文场景下过长导致 API 崩溃）。
已通过使用 `ollama run` 子进程代替 API 调用解决。

### Q: 为什么首次查询特别慢？
第一次启动 Ollama 需要加载模型到 GPU 内存（~12GB），约17秒。
之后每次查询约60-80秒（因 Gemma4 思考模式不可关闭）。

### Q: 如何处理 PDF 中文文档？
系统默认使用 pdfplumber 提取文本。中文 PDF 需要系统中文字体支持。
如果没有中文字体，提取的文本可能为空，系统会自动降级显示占位信息。

### Q: 索引文件在哪里？
`~/karpathy-kb/search_index.json` — 包含全部索引数据，可随时重建。

---

## 📦 依赖

```bash
# Python包
pip3 install --user --break-system-packages \
  pdfplumber python-docx fpdf2   # 文档处理
  flask flask-cors                # Web界面
  jieba                           # 中文分词

# 系统依赖
ollama pull gemma4:e4b  # AI模型
```

---

## 📝 版本历史

| 版本 | 日期 | 更新内容 |
|------|------|----------|
| v2.0 | 2026-04-24 | 交互式CLI v2 + 自动补全 + 彩色输出 + Web界面 + 性能优化 |
| v1.1 | 2026-04-20 | QAA增强、缓存、PDF/Word支持 |
| v1.0 | 2026-04-17 | MVP发布，搜索+问答+OpenClaw集成 |
