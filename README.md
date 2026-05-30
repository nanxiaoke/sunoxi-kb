# Karpathy知识库MVP
路径A最小可行产品

## 目录结构
- `raw/`: 原始资料
  - `articles/`: 文章
  - `papers/`: 论文  
  - `notes/`: 笔记
  - `codes/`: 代码
  - `webpages/`: 网页存档
- `wiki/`: AI编译的结构化知识
  - `concepts/`: 概念解释
  - `people/`: 人物介绍
  - `projects/`: 项目说明
  - `technologies/`: 技术文档
  - `notes/`: 整理笔记
- `outputs/`: 衍生输出（报告、幻灯片、图表等）
- `scripts/`: 处理脚本
- `config/`: 配置文件
- `logs/`: 运行日志
- `tests/`: 测试文件

## 核心工作流
```
raw/原始资料 → scripts/处理脚本 → wiki/结构化知识
    ↓
用户查询 → 检索wiki → 生成outputs/
```

## 技术栈
- **LLM引擎**: Ollama + gemma4:e4b (本地模型)
- **网页抓取**: webfetch-md (OpenClaw Skill，网页→Markdown转换)
- **处理语言**: Python 3.9+
- **知识格式**: Markdown
- **查看工具**: Obsidian (可选)

## 开发进度
- 第1天：基础架构搭建
- 第2天：AI处理核心开发
- 第3天：wiki系统构建
- 第4天：查询功能实现
- 第5天：测试与优化

## 快速开始

### Git 部署（Windows / Linux）

当前推荐方式是开发机用 git 管理代码，部署机器直接拉取源码运行。知识库文章数据、索引、缓存、日志、备份和密钥不会进入 git。

前提：

- Windows：安装 Python 3.11+ 和 Git Bash
- Linux：安装 Python 3.11+ 和 `sh`
- 在线模式需要网络访问

部署命令：

```bash
git clone <repo> karpathy-kb
cd karpathy-kb
./packaging/common/install_deps.sh
./packaging/common/configure_key.sh --key "your_key_here"
./packaging/common/start_webui.sh
```

Windows 兼容入口：

```bash
./packaging/windows/install_deps.sh
./packaging/windows/configure_key.sh --key "your_key_here"
./packaging/windows/start_webui.sh
```

说明：`packaging/common/` 是跨平台主入口，`packaging/windows/` 只保留兼容包装。首次启动是空知识库，需要通过 WebUI 或脚本导入文章。

完整部署、更新和排错说明见 [docs/git-deployment.md](docs/git-deployment.md)。

默认依赖只覆盖 WebUI、在线模型、候选池、RSS/URL/文件导入等核心功能。语义向量依赖较大，需要时再安装：

```bash
./packaging/common/install_deps.sh --with-embeddings
```

### 在线模型密钥

在线模型 API Key 不保存在 WebUI 或 `llm_runtime.yaml` 中。默认使用用户级环境文件：

```bash
~/.config/karpathy-kb/llm.env
```

一键配置：

```bash
cd /path/to/karpathy-kb
DEEPSEEK_API_KEY=your_key_here ./scripts/install_llm_env.sh
```

详细迁移和维护说明见 [docs/llm-secret-setup.md](docs/llm-secret-setup.md)。

### 基础流程

```bash
# 1. 检查环境
cd /path/to/karpathy-kb && python3 scripts/setup.py

# 2. 添加原始资料到 raw/ 目录

# 3. 网页抓取（可选）
python3 scripts/web_collector.py --url "https://example.com"
python3 scripts/web_collector.py --file tests/test_urls.txt

# 4. 运行处理脚本
python3 scripts/processor.py --input raw/articles/ --output wiki/

# 5. 查看结果
ls -la wiki/concepts/
```

## 命令行工具使用

### 搜索文档
```bash
python3 scripts/kb_cli.py search --query "人工智能"
python3 scripts/kb_cli.py search --query "横纵分析法" --rebuild
python3 scripts/kb_cli.py search --categories  # 列出所有分类
python3 scripts/kb_cli.py search --entities    # 列出所有实体
```

### 问答系统
```bash
python3 scripts/kb_cli.py qa --question "什么是人工智能？"
python3 scripts/kb_cli.py qa --question "横纵分析法是什么？" --max-docs 2
```

### 统计信息
```bash
python3 scripts/kb_cli.py stats
python3 scripts/kb_cli.py list --details
```

## OpenClaw技能使用

已集成OpenClaw技能，可通过自然语言访问知识库：

```
知识库 搜索 人工智能
知识库 问答 横纵分析法是什么？
知识库 统计
知识库 列表
知识库 帮助
```

## 当前功能状态

| 功能 | 状态 | 说明 |
|------|------|------|
| 数据采集 | ✅ 正常 | 支持网页抓取、微信公众号文章、本地文件 |
| AI文档处理 | ⚠️ 部分正常 | Ollama服务不稳定，有时挂起 |
| 搜索系统 | ✅ 正常 | 全文、标题、实体、分类多维搜索 |
| 问答系统 | ⚠️ 部分正常 | 依赖Ollama，时好时坏 |
| 命令行接口 | ✅ 正常 | 完整的CLI工具 |
| OpenClaw集成 | ✅ 正常 | 自然语言技能 |

## 故障排除

### Ollama服务问题
```bash
# 检查Ollama服务状态
curl http://localhost:11434/api/tags

# 测试简单生成
curl -X POST http://localhost:11434/api/generate -d '{"model": "gemma4:e4b", "prompt": "Hello"}'

# 重启Ollama服务（需要权限）
sudo systemctl restart ollama
```

### 搜索索引问题
```bash
# 强制重建索引
python3 scripts/kb_cli.py search --query "test" --rebuild
```

### 路径错误
确保所有脚本使用正确的路径转换：
```python
from pathlib import Path
base_dir = Path(__file__).resolve().parent.parent
```

## 后续开发计划

### 短期（1-2周）
1. 修复Ollama配置问题
2. 导入更多文档
3. 优化搜索性能

### 中期（1个月）
1. 定期同步机制
2. 多模型支持
3. Web界面

### 长期（3个月）
1. 知识图谱可视化
2. 多用户协作
3. 移动端支持

## 项目结构更新

```
📂 Karpathy知识库项目
├── scripts/                     # 核心脚本
│   ├── kb_cli.py               # 命令行接口
│   ├── search.py               # 搜索系统
│   ├── qa.py                   # 问答系统
│   ├── processor.py            # 文档处理器
│   ├── web_collector.py        # 网页收集器
│   ├── wechat_fetcher.py       # 微信公众号抓取器
│   └── model_adapter.py        # 模型自适应层
├── wiki/                       # 结构化知识库
├── raw/                        # 原始文档存储
├── outputs/                    # 处理输出
├── logs/                       # 运行日志
├── config/                     # 配置文件
└── PROGRESS.md                 # 详细开发进度
```

## 贡献与反馈

项目基于Karpathy的LLM Wiki理念，旨在构建个人知识管理系统。

**核心价值**：
- 100%本地处理，数据隐私保障
- 模块化设计，易于扩展和维护
- 自然语言接口，降低使用门槛
- 持续生长，知识复利效应

**立即使用**：`知识库 搜索 [关键词]` / `知识库 统计` / `知识库 列表` / `知识库 帮助`
