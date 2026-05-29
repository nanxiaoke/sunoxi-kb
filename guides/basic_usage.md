# Karpathy知识库基础使用指南

## 概述

Karpathy知识库是一个基于LLM的个人知识管理系统，遵循Karpathy提出的"LLM是程序员，Wiki是代码库"理念。系统将原始文档编译为结构化wiki，支持搜索、问答和知识管理。

## 系统架构

### 三层结构
1. **Raw层** (`raw/`): 原始文档来源，LLM只读不改
2. **Wiki层** (`wiki/`): AI编译的结构化知识，持续更新
3. **SCHEMA层** (`SCHEMA.md`): 规则契约，定义Wiki结构和处理规则

### 核心组件
- **文档处理器**: 将raw文档转换为wiki页面
- **搜索系统**: 多维搜索（全文、标题、实体、分类）
- **问答系统**: 基于检索的生成式问答（RAG）
- **命令行接口**: 统一CLI工具
- **OpenClaw技能**: 自然语言访问接口

## 快速开始

### 1. 环境准备
```bash
# 检查环境
cd ~/karpathy-kb
python3 scripts/setup.py

# 确保Ollama服务运行
curl http://localhost:11434/api/tags
```

### 2. 添加文档
```bash
# 方式1: 直接复制文件到raw目录
cp my_document.md ~/karpathy-kb/raw/articles/

# 方式2: 网页抓取
python3 scripts/web_collector.py --url "https://example.com/article"

# 方式3: 微信公众号文章
python3 scripts/wechat_fetcher.py --url "https://mp.weixin.qq.com/s/..."
```

### 3. 处理文档
```bash
# 处理单个文件
python3 scripts/processor.py --input raw/articles/my_document.md

# 处理整个目录
python3 scripts/processor.py --input raw/articles/ --pattern "*.md"

# 指定模型（如果默认模型有问题）
python3 scripts/processor.py --input raw/articles/ --model gemma4:e4b-it-q8_0
```

### 4. 使用知识库
```bash
# 搜索文档
python3 scripts/kb_cli.py search --query "关键词"
python3 scripts/kb_cli.py search --categories  # 查看所有分类
python3 scripts/kb_cli.py search --entities    # 查看所有实体

# 问答
python3 scripts/kb_cli.py qa --question "问题内容"

# 统计信息
python3 scripts/kb_cli.py stats
python3 scripts/kb_cli.py list --details
```

## OpenClaw技能使用

### 自然语言命令
```
知识库 搜索 [关键词]
知识库 问答 [问题]
知识库 统计
知识库 列表
知识库 帮助
```

### 示例
```
知识库 搜索 人工智能
知识库 问答 横纵分析法是什么？
知识库 统计
知识库 列表 --details
```

## 目录结构说明

### raw/ 原始文档
```
raw/
├── articles/      # 文章
├── papers/        # 论文
├── notes/         # 笔记
├── codes/         # 代码
├── webpages/      # 网页存档
└── wechat_articles/  # 微信公众号文章
```

### wiki/ 结构化知识
```
wiki/
├── concepts/      # 概念解释
├── people/        # 人物介绍
├── projects/      # 项目说明
├── technologies/  # 技术文档
├── notes/         # 整理笔记
├── 00_INDEX.md    # 总目录
├── DOCUMENTS.md   # 文档列表
└── category_*.md  # 分类索引
```

## 最佳实践

### 文档管理
1. **质量优于数量**: 优先添加自己生产的内容（文章、笔记、项目文档）
2. **定期整理**: 每周检查raw目录，处理新文档
3. **分类清晰**: 根据内容类型放入正确的raw子目录

### 知识维护
1. **定期搜索**: 使用搜索功能验证知识库覆盖范围
2. **问答测试**: 测试常见问题，确保答案质量
3. **索引重建**: 添加大量新文档后重建搜索索引

### 故障排除
1. **Ollama问题**: 检查服务状态，尝试不同模型
2. **搜索问题**: 使用--rebuild参数重建索引
3. **路径问题**: 确保使用绝对路径或正确的工作目录

## 高级功能

### 模型自适应
系统包含模型自适应层，自动检测模型类型并选择最佳配置：
- Gemma4系列: 禁用思考模式，使用简洁系统提示
- DeepSeek系列: 支持推理模式
- 多模型回退: 主模型失败时自动切换

### 降级策略
当AI服务不可用时，系统提供降级功能：
- 问答降级: 返回相关文档列表而非生成答案
- 处理降级: 跳过AI处理，创建基本wiki页面
- 搜索保障: 搜索功能始终可用

### 性能优化
- 索引缓存: 搜索索引内存缓存，避免重复构建
- 懒加载: Ollama客户端按需初始化
- 流式处理: 大文档分块处理

## 后续扩展

### 计划功能
1. **lint命令**: Wiki健康度检查（矛盾、孤儿页、过时内容）
2. **链接抓取**: 支持任意URL投喂，自动抓取和编译
3. **Obsidian集成**: 输出Obsidian友好格式，支持双向链接
4. **定期同步**: 自动抓取指定来源，保持知识库更新

### 自定义开发
系统采用模块化设计，易于扩展：
- 添加新的文档处理器
- 集成新的AI模型
- 扩展搜索算法
- 添加输出格式

## 技术支持

### 常见问题
Q: Ollama服务连接失败怎么办？
A: 检查Ollama是否运行：`curl http://localhost:11434/api/tags`，确保配置文件正确。

Q: 搜索找不到新添加的文档？
A: 使用`--rebuild`参数重建索引：`python3 scripts/kb_cli.py search --query "test" --rebuild`

Q: 问答功能返回错误或超时？
A: Ollama可能不稳定，尝试使用搜索功能获取相关文档。

### 获取帮助
- 查看完整文档：`python3 scripts/kb_cli.py help`
- 检查日志文件：`logs/`目录
- 查看进度记录：`PROGRESS.md`

---

**版本**: 1.0.0  
**更新日期**: 2026-04-22  
**项目状态**: MVP完成，核心功能可用，AI服务部分正常