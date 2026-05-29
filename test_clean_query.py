#!/usr/bin/env python3
"""
测试清理查询函数
"""

import sys
import re
from pathlib import Path

# 添加脚本目录
sys.path.insert(0, str(Path(__file__).parent / "scripts"))

from qa import KnowledgeBaseQA

def test_clean_query():
    qa = KnowledgeBaseQA(Path('/home/sunoxi/karpathy-kb'))
    
    test_cases = [
        "横纵分析法是什么？",
        "什么是人工智能？",
        "如何学习机器学习？",
        "为什么天空是蓝色的？",
        "横纵分析法怎么用？",
        "横纵分析法吗？",
        "横纵分析法",
    ]
    
    print("🔍 测试清理查询函数")
    print("="*60)
    
    for question in test_cases:
        cleaned = qa._clean_query(question)
        print(f"'{question}' → '{cleaned}'")
        
        # 测试分词
        # 导入搜索模块的分词函数
        sys.path.insert(0, str(Path(__file__).parent / "scripts"))
        from search import WikiSearcher
        searcher = WikiSearcher(Path('.'))
        
        original_tokens = searcher._tokenize(question)
        cleaned_tokens = searcher._tokenize(cleaned)
        
        print(f"   原始分词: {original_tokens}")
        print(f"   清理分词: {cleaned_tokens}")
        
        # 测试实体提取
        question_words = re.findall(r'[A-Z][a-z]+|[A-Z]+|[a-z]+|[\u4e00-\u9fff]+', question)
        print(f"   实体提取: {question_words}")
        
        print()

if __name__ == "__main__":
    test_clean_query()