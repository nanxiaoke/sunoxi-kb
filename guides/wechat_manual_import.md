# 微信公众号文章手动导入指南

## 概述

当自动抓取失败或不可用时，可以使用手动导入方式将微信公众号文章添加到知识库。手动导入方案**100%可靠**，无技术风险，适合所有类型的微信公众号文章。

## 导入步骤

### 步骤1：在微信中复制文章内容
1. 在微信中打开目标文章
2. 点击右上角"..."菜单
3. 选择"复制链接"（可选，用于记录来源）
4. 再次点击"..."菜单
5. 选择"复制全文"或手动选择全部文本复制

### 步骤2：创建导入文件
1. 进入项目目录：
   ```bash
   cd ~/karpathy-kb
   ```

2. 创建新文件（建议使用有意义的文件名）：
   ```bash
   # 格式：raw/wechat_articles/文章标题_日期.md
   touch raw/wechat_articles/横纵分析法_20260417.md
   ```

3. 使用文本编辑器打开文件并粘贴内容：
   ```bash
   nano raw/wechat_articles/横纵分析法_20260417.md
   ```

### 步骤3：使用标准模板格式
将以下模板复制到文件中，替换相应内容：

```markdown
# [文章标题]

> **来源**: [微信公众号名称]
> **作者**: [作者名称]
> **发布时间**: [发布时间]
> **导入方式**: 手动复制
> **导入时间**: 2026-04-17

[在此处粘贴文章正文]

---

**补充信息**:
- 原文链接: [文章URL]
- 关键词: [关键词1, 关键词2, ...]
- 分类建议: [技术/商业/方法/...]
```

### 步骤4：运行AI处理
```bash
cd ~/karpathy-kb
python3 scripts/processor.py --input raw/wechat_articles/横纵分析法_20260417.md
```

## 模板示例

```markdown
# 横纵分析法：AI时代的深度研究方法论

> **来源**: 数字生命卡兹克
> **作者**: 卡兹克
> **发布时间**: 2026-04-15
> **导入方式**: 手动复制
> **导入时间**: 2026-04-17

前两天办完大会，然后昨天周末跟一个朋友吃饭，聊着聊着他突然放下筷子看着我说了一句，不是哥们，你怎么什么都懂一点？

[...文章正文...]

---

**补充信息**:
- 原文链接: https://mp.weixin.qq.com/s/Y_uRMYBmdLWUPnz_ac7jWA
- 关键词: AI研究, 方法论, 横纵分析法, 深度研究
- 分类建议: 研究方法/人工智能
```

## 批量导入

如果有多个文章需要导入：

1. 创建批处理脚本 `batch_import.sh`:
```bash
#!/bin/bash
# 批量处理微信公众号文章
for file in raw/wechat_articles/*.md; do
    echo "处理: $file"
    python3 scripts/processor.py --input "$file"
    sleep 10  # 避免请求过快
done
```

2. 授予执行权限并运行：
```bash
chmod +x batch_import.sh
./batch_import.sh
```

## 最佳实践

### 文件命名规范
- 使用英文或拼音，避免特殊字符
- 包含文章主题和日期：`主题_YYYYMMDD.md`
- 示例：`hengzong_analysis_20260417.md`, `ai_research_method_20260417.md`

### 内容清洗建议
1. **移除广告和无关内容**：删除文章开头/结尾的推广内容
2. **保留格式**：保持段落、列表、代码块等原始格式
3. **添加元数据**：尽可能填写完整的元数据字段
4. **分段处理**：超长文章可适当分段，但保持逻辑连贯

### 质量检查
导入后检查生成的文件：
```bash
# 查看生成的wiki文档
ls -la wiki/*/*.md | grep -i "横纵分析"

# 查看处理日志
tail -f logs/processor.log
```

## 故障排除

### 问题1：处理速度慢
- **原因**: Ollama模型首次加载需要时间
- **解决**: 等待或使用更轻量模型（如gemma4:e4b）

### 问题2：内容提取不完整
- **原因**: 复制的文本可能丢失格式
- **解决**: 检查原始文章，确保复制了全部内容

### 问题3：分类不准确
- **原因**: AI分类可能有偏差
- **解决**: 手动调整分类或添加明确的分类建议

### 问题4：重复导入
- **原因**: 同一篇文章多次导入
- **解决**: 检查文件哈希，删除重复文件

## 自动化辅助工具

### 快速导入脚本
创建 `scripts/quick_import.py`：
```python
#!/usr/bin/env python3
"""
快速导入工具 - 辅助手动导入流程
"""
import sys
import os
from datetime import datetime

def create_import_file(title, content, author="", source=""):
    """创建导入文件模板"""
    filename = f"{title[:50]}_{datetime.now().strftime('%Y%m%d')}.md"
    filepath = os.path.join("raw", "wechat_articles", filename)
    
    template = f"""# {title}

> **来源**: {source}
> **作者**: {author}
> **发布时间**: 
> **导入方式**: 手动复制
> **导入时间**: {datetime.now().strftime('%Y-%m-%d')}

{content}

---

**补充信息**:
- 原文链接: {source}
- 关键词: 
- 分类建议: 
"""
    
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(template)
    
    print(f"✅ 创建成功: {filepath}")
    return filepath

if __name__ == "__main__":
    # 使用示例
    title = input("文章标题: ")
    author = input("作者: ")
    source = input("原文链接: ")
    print("粘贴文章内容（Ctrl+D结束）:")
    content = sys.stdin.read()
    
    create_import_file(title, content, author, source)
```

## 与自动抓取结合

### 混合工作流
```
尝试自动抓取（wechat_fetcher.py）
    ↓ 成功 → 自动处理
    ↓ 失败 → 提示手动导入 → 使用本指南
```

### 统一处理
无论手动还是自动导入，最终都使用相同的AI处理管道：
```
原始文章 → processor.py → wiki知识条目
```

## 扩展功能

### 1. 添加标签系统
在文章末尾添加标签：
```markdown
---
tags: [AI, 研究方法, 横纵分析, 深度研究]
category: 技术方法
importance: 高
read_time: 15分钟
```

### 2. 生成摘要预览
处理后可生成简短摘要：
```bash
# 查看生成的摘要
cat wiki/*/横纵分析法*.md | head -20
```

### 3. 定期整理
建议每周整理一次导入的文章：
```bash
# 整理脚本
python3 scripts/organize_imports.py --dir raw/wechat_articles
```

---

## 更新记录
- **2026-04-17**: 创建初始版本，包含完整手动导入流程
- **计划更新**: 添加更多自动化工具和模板

## 获取帮助
如有问题，请查看：
1. `PROGRESS.md` - 项目进度和最新动态
2. `logs/` 目录 - 处理日志和错误信息
3. `scripts/processor.py --help` - 处理器使用说明

---

**手动导入虽然需要一些人工操作，但保证了100%的成功率和内容完整性，是最可靠的微信公众号文章获取方案。**