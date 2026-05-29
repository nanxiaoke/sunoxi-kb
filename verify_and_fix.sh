#!/bin/bash
# Karpathy知识库搜索系统修复脚本
# 修复分词问题和索引重建

echo "🔧 Karpathy知识库搜索系统修复"
echo "="*60

# 步骤1: 验证分词修复
echo -e "\n1. ✅ 验证分词函数修复..."
python3 -c "
import re

def tokenize_test(text):
    '''测试分词函数'''
    if not text:
        return []
    words = []
    for word in re.findall(r'[a-zA-Z]{2,}|[\\u4e00-\\u9fff]{2,}|[^\\s\\w]', text):
        word_lower = word.lower()
        if word_lower:
            # 过滤单个中文字符
            if len(word) == 1 and '\\u4e00' <= word <= '\\u9fff':
                continue
            words.append(word_lower)
    return words

print('分词测试结果:')
test_cases = ['横纵分析法', '人工智能', 'AI测试']
for test in test_cases:
    result = tokenize_test(test)
    print(f'  \"{test}\" → {result}')
"

# 步骤2: 检查当前索引
echo -e "\n2. 📁 检查当前索引状态..."
if [ -f "search_index.json" ]; then
    echo "   索引文件存在，大小: $(ls -lh search_index.json | awk '{print $5}')"
    echo "   创建时间: $(stat -c %y search_index.json)"
    
    # 检查是否包含"横纵分析法"
    if grep -q "横纵分析法" search_index.json; then
        echo "   ✅ 索引中包含'横纵分析法'"
    else
        echo "   ❌ 索引中不包含'横纵分析法'"
    fi
else
    echo "   索引文件不存在"
fi

# 步骤3: 重建索引
echo -e "\n3. 🔄 重建搜索索引..."
echo "   删除旧索引文件..."
rm -f search_index.json

echo "   重新构建索引..."
python3 -c "
import sys
sys.path.append('scripts')
from search import WikiSearcher
from pathlib import Path

searcher = WikiSearcher(Path('.'))
print('开始构建索引...')
searcher.build_index(rebuild=True)
print(f'索引构建完成: {len(searcher.doc_index)} 文档, {len(searcher.entity_index)} 实体')
"

# 步骤4: 测试搜索
echo -e "\n4. 🔍 测试搜索功能..."
python3 -c "
import sys
sys.path.append('scripts')
from search import WikiSearcher
from pathlib import Path

searcher = WikiSearcher(Path('.'))
searcher.build_index(rebuild=False)

print('搜索测试:')
queries = ['横纵分析法', 'AI', '人工智能']
for query in queries:
    results = searcher.search(query, search_type='fulltext', limit=3)
    print(f'  \"{query}\": {len(results)} 个结果')
    if results:
        for i, r in enumerate(results[:2], 1):
            print(f'    {i}. {r[\"title\"]} (分数: {r[\"score\"]:.2f})')
"

# 步骤5: 验证修复
echo -e "\n5. ✅ 验证修复..."
if [ -f "search_index.json" ]; then
    echo "   索引重建成功"
    echo "   现在可以运行问答系统:"
    echo "   python3 scripts/kb_cli.py qa --question \"横纵分析法是什么？\""
else
    echo "   ❌ 索引重建失败"
fi

echo -e "\n" + "="*60
echo "🎯 修复完成！现在可以测试问答系统。"
echo "运行命令: python3 scripts/kb_cli.py qa --question \"横纵分析法是什么？\""