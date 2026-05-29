#!/usr/bin/env python3
"""
诊断问答系统搜索问题
"""

import sys
import re
from pathlib import Path

# 添加脚本目录
sys.path.insert(0, str(Path(__file__).parent / "scripts"))

from search import WikiSearcher

def test_qa_search_logic():
    """测试问答系统的搜索逻辑"""
    print("🔍 诊断问答系统搜索问题")
    print("="*60)
    
    base_dir = Path("/home/sunoxi/karpathy-kb")
    searcher = WikiSearcher(base_dir)
    searcher.build_index(rebuild=False)
    
    question = "横纵分析法是什么？"
    max_docs = 3
    
    print(f"问题: {question}")
    print(f"最大文档数: {max_docs}")
    
    # 模拟问答系统的搜索逻辑
    search_results = []
    
    # 策略1: 全文搜索
    print("\n1. 🔍 全文搜索策略:")
    results = searcher.search(question, search_type="fulltext", limit=max_docs*2)
    print(f"   结果数量: {len(results)}")
    
    if results:
        for i, r in enumerate(results, 1):
            print(f"   {i}. {r.get('title', '无标题')} (分数: {r.get('score', 0):.2f})")
            print(f"      摘要: {r.get('summary', '')[:80]}...")
    else:
        print("   没有结果")
    
    search_results.extend(results)
    
    # 策略2: 实体搜索
    print("\n2. 🔤 实体提取和搜索:")
    question_words = re.findall(r'[A-Z][a-z]+|[A-Z]+|[a-z]+|[\u4e00-\u9fff]+', question)
    print(f"   提取的实体词: {question_words}")
    
    filtered_words = [w for w in question_words if len(w) > 2]
    print(f"   过滤后(长度>2): {filtered_words}")
    
    for word in filtered_words[:5]:
        print(f"\n   搜索实体: '{word}'")
        entity_results = searcher.search_by_entity(word)
        print(f"   结果数量: {len(entity_results)}")
        
        if entity_results:
            for i, r in enumerate(entity_results, 1):
                print(f"     {i}. {r.get('title', '无标题')} (分类: {r.get('category', '无分类')})")
                # 检查是否有score字段
                if 'score' in r:
                    print(f"        分数: {r.get('score', 0):.2f}")
                else:
                    print(f"        无分数字段")
        else:
            print("    没有结果")
        
        search_results.extend(entity_results)
    
    # 检查所有结果的分数
    print("\n3. 📊 所有搜索结果统计:")
    print(f"   总结果数: {len(search_results)}")
    
    # 检查哪些结果有分数
    with_score = [r for r in search_results if r.get('score', 0) > 0]
    without_score = [r for r in search_results if r.get('score', 0) <= 0]
    
    print(f"   有分数的结果: {len(with_score)}")
    print(f"   无分数的结果: {len(without_score)}")
    
    # 模拟问答系统的去重和排序
    print("\n4. 🔄 模拟问答系统的去重排序:")
    seen_ids = set()
    unique_results = []
    for result in sorted(search_results, key=lambda x: x.get("score", 0), reverse=True):
        doc_id = result.get("id")
        if doc_id and doc_id not in seen_ids:
            seen_ids.add(doc_id)
            unique_results.append(result)
        
        if len(unique_results) >= max_docs:
            break
    
    print(f"   去重后结果数: {len(unique_results)}")
    
    if unique_results:
        for i, r in enumerate(unique_results, 1):
            print(f"   {i}. {r.get('title', '无标题')} (分数: {r.get('score', 0):.2f})")
    else:
        print("   最终结果为空!")
    
    # 检查分词
    print("\n5. 🔡 分词检查:")
    print(f"   搜索系统的分词: {searcher._tokenize(question)}")
    
    # 检查实体索引
    print(f"\n6. 📋 实体索引检查:")
    for word in filtered_words:
        if word.lower() in searcher.entity_index:
            doc_ids = searcher.entity_index[word.lower()]
            print(f"   实体 '{word}' 在索引中，关联文档: {list(doc_ids)}")
        else:
            print(f"   实体 '{word}' 不在实体索引中")
    
    print("\n" + "="*60)
    print("✅ 诊断完成")

if __name__ == "__main__":
    test_qa_search_logic()