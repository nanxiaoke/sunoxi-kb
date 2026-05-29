#!/usr/bin/env python3
"""
诊断问答系统找不到"横纵分析法"的问题
"""

import sys
import json
from pathlib import Path

# 添加脚本目录到路径
sys.path.insert(0, str(Path(__file__).parent / "scripts"))

try:
    from search import WikiSearcher
    print("✅ 成功导入WikiSearcher")
except ImportError as e:
    print(f"❌ 导入失败: {e}")
    sys.exit(1)

def test_search_directly():
    """直接测试搜索功能"""
    print("\n🔍 直接测试搜索功能")
    print("="*60)
    
    base_dir = Path("/home/sunoxi/karpathy-kb")
    searcher = WikiSearcher(base_dir)
    
    # 构建索引
    print("构建搜索索引...")
    searcher.build_index(rebuild=False)
    
    # 测试搜索"横纵分析法"
    query = "横纵分析法"
    print(f"\n搜索查询: '{query}'")
    
    # 测试不同搜索类型
    search_types = ["fulltext", "title", "summary", "entity", "category"]
    
    for search_type in search_types:
        print(f"\n🔧 搜索类型: {search_type}")
        results = searcher.search(query, search_type=search_type, limit=5)
        
        if results:
            print(f"  找到 {len(results)} 个结果:")
            for i, result in enumerate(results, 1):
                print(f"  {i}. {result['title']} (分数: {result['score']:.2f})")
                if result.get('highlights'):
                    print(f"     匹配: {result['highlights'][0]}")
        else:
            print("  没有结果")
    
    # 测试实体搜索
    print(f"\n🔤 直接实体搜索: '{query}'")
    entity_results = searcher.search_by_entity(query)
    if entity_results:
        print(f"  找到 {len(entity_results)} 个实体匹配:")
        for i, result in enumerate(entity_results, 1):
            print(f"  {i}. {result['title']} ({result['category']})")
    else:
        print("  没有实体匹配")
    
    # 检查实体索引
    print(f"\n📋 检查实体索引中是否有 '{query}':")
    if query.lower() in searcher.entity_index:
        doc_ids = searcher.entity_index[query.lower()]
        print(f"  实体 '{query}' 存在于索引中，关联文档: {list(doc_ids)}")
    else:
        print(f"  实体 '{query}' 不在实体索引中")
        
        # 列出所有包含"横纵"的实体
        print(f"\n  包含'横纵'的实体:")
        for entity in searcher.entity_index.keys():
            if "横纵" in entity:
                print(f"  - {entity}: {len(searcher.entity_index[entity])} 篇文档")
    
    # 检查文档索引
    print(f"\n📄 文档索引统计:")
    print(f"  总文档数: {len(searcher.doc_index)}")
    print(f"  实体数量: {len(searcher.entity_index)}")
    print(f"  分类数量: {len(searcher.category_index)}")

def check_index_file():
    """检查索引文件内容"""
    print("\n📁 检查索引文件")
    print("="*60)
    
    index_file = Path("/home/sunoxi/karpathy-kb/search_index.json")
    if not index_file.exists():
        print("索引文件不存在")
        return
    
    with open(index_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # 检查文档数量
    doc_count = len(data.get("doc_index", {}))
    print(f"索引文件中的文档数: {doc_count}")
    
    # 检查实体索引
    entity_index = data.get("entity_index", {})
    print(f"实体索引中的实体数: {len(entity_index)}")
    
    # 检查"横纵分析法"是否存在
    query = "横纵分析法"
    if query in entity_index:
        doc_ids = entity_index[query]
        print(f"✅ 实体 '{query}' 存在于索引中，关联文档: {doc_ids}")
    else:
        print(f"❌ 实体 '{query}' 不在实体索引中")
        
        # 查找包含"横纵"的实体
        print(f"\n查找包含'横纵'的实体:")
        for entity, docs in entity_index.items():
            if "横纵" in entity:
                print(f"  - {entity}: {docs}")
    
    # 检查标题索引
    title_index = data.get("title_index", {})
    print(f"\n标题索引中的词条数: {len(title_index)}")
    
    # 检查全文索引
    fulltext_index = data.get("fulltext_index", {})
    print(f"全文索引中的词条数: {len(fulltext_index)}")

def main():
    print("🔧 诊断问答系统问题")
    print("="*60)
    
    check_index_file()
    test_search_directly()
    
    print("\n" + "="*60)
    print("📋 诊断完成")
    print("="*60)

if __name__ == "__main__":
    main()