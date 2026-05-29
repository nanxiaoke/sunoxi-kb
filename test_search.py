#!/usr/bin/env python3
"""
测试搜索功能
"""

import sys
sys.path.insert(0, '/home/sunoxi/karpathy-kb/scripts')

from search import WikiSearcher
from pathlib import Path

def test_search():
    """测试搜索功能"""
    base_dir = Path("/home/sunoxi/karpathy-kb")
    searcher = WikiSearcher(base_dir)
    
    # 构建索引
    print("🔧 构建搜索索引...")
    searcher.build_index(rebuild=False)
    
    # 显示统计
    searcher.print_stats()
    
    # 测试搜索
    test_queries = [
        ("AI", "fulltext"),
        ("人工智能", "fulltext"),
        ("机器学习", "fulltext"),
        ("教程", "category"),
        ("横纵分析法", "entity"),
    ]
    
    print("\n🔍 搜索测试:")
    for query, search_type in test_queries:
        print(f"\n搜索 '{query}' (类型: {search_type}):")
        results = searcher.search(query, search_type=search_type, limit=5)
        
        if results:
            for i, result in enumerate(results, 1):
                print(f"  {i}. {result['title']} (分数: {result['score']:.2f})")
                if result['highlights']:
                    print(f"     匹配: {result['highlights'][0]}")
        else:
            print("  没有结果")
    
    # 测试分类搜索
    print("\n🏷️  分类搜索测试:")
    categories = searcher.get_all_categories()
    for category in categories:
        results = searcher.search_by_category(category)
        print(f"  {category}: {len(results)} 篇文档")
    
    # 测试实体搜索
    print("\n🔤 实体搜索测试:")
    top_entities = searcher.get_all_entities(min_freq=1)[:5]
    for entity, freq in top_entities:
        results = searcher.search_by_entity(entity)
        print(f"  {entity}: {freq} 篇文档")
    
    print("\n✅ 搜索测试完成!")

if __name__ == "__main__":
    test_search()