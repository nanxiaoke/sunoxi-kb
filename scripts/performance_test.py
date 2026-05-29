#!/usr/bin/env python3
"""
性能测试脚本
测量Karpathy知识库各组件性能
"""

import time
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from search import WikiSearcher
from qa import KnowledgeBaseQA
from processor import OllamaClient

def test_search_performance():
    """测试搜索性能"""
    print("🔍 测试搜索性能...")
    base_dir = Path.home() / "karpathy-kb"
    searcher = WikiSearcher(base_dir)
    
    # 构建索引
    start = time.time()
    searcher.build_index(rebuild=False)
    index_time = time.time() - start
    print(f"  ✓ 索引加载时间: {index_time:.2f}秒")
    
    # 测试不同搜索类型
    queries = [
        "横纵分析法",
        "人工智能",
        "RAG",
        "Ollama",
        "深度学习"
    ]
    
    for query in queries:
        start = time.time()
        results = searcher.search(query, search_type='fulltext', limit=5)
        search_time = time.time() - start
        print(f"  ✓ 查询 '{query}': {search_time:.2f}秒, {len(results)} 结果")

def test_ollama_performance():
    """测试Ollama连接和简单响应性能"""
    print("🤖 测试Ollama性能...")
    
    try:
        start = time.time()
        ollama = OllamaClient(model="gemma4:e4b")
        init_time = time.time() - start
        print(f"  ✓ Ollama客户端初始化: {init_time:.2f}秒")
        print(f"  ✓ 当前模型: {ollama.model}")
        print(f"  ✓ 可用模型: {ollama.available_models}")
        
        # 测试简单对话
        messages = [
            {"role": "system", "content": "请用中文简短回答。"},
            {"role": "user", "content": "你是谁？"}
        ]
        
        print("  ⏳ 测试简单对话响应...")
        start = time.time()
        response = ollama.chat(messages, timeout=30)
        chat_time = time.time() - start
        
        if response:
            print(f"  ✓ 聊天响应时间: {chat_time:.2f}秒")
            print(f"  ✓ 响应长度: {len(response)} 字符")
            print(f"  ✓ 响应预览: {response[:100]}...")
        else:
            print("  ✗ 无响应")
            
    except Exception as e:
        print(f"  ✗ Ollama测试失败: {e}")

def test_qa_performance():
    """测试问答系统性能"""
    print("❓ 测试问答系统性能...")
    
    base_dir = Path.home() / "karpathy-kb"
    
    try:
        # 初始化问答系统（不包含Ollama的延迟加载）
        start = time.time()
        qa = KnowledgeBaseQA(base_dir)
        init_time = time.time() - start
        print(f"  ✓ 问答系统初始化: {init_time:.2f}秒")
        
        # 测试简单问题
        questions = [
            "横纵分析法是什么？",
            "什么是人工智能？",
            "RAG是什么？"
        ]
        
        for question in questions:
            print(f"\n  🔍 测试问题: '{question}'")
            
            # 只测试搜索部分（不生成答案）
            start = time.time()
            documents = qa.search_relevant_documents(question, max_docs=3)
            search_time = time.time() - start
            print(f"    ✓ 搜索时间: {search_time:.2f}秒")
            print(f"    ✓ 找到文档: {len(documents)} 个")
            
            if documents:
                # 提取上下文但不生成答案
                start = time.time()
                context = qa.extract_context_from_documents(documents)
                context_time = time.time() - start
                print(f"    ✓ 上下文提取: {context_time:.2f}秒")
                print(f"    ✓ 上下文长度: {len(context)} 字符")
                
    except Exception as e:
        print(f"  ✗ 问答系统测试失败: {e}")
        import traceback
        traceback.print_exc()

def main():
    """主函数"""
    print("=" * 60)
    print("🧪 Karpathy知识库性能测试")
    print("=" * 60)
    
    try:
        # 测试1: 搜索性能
        test_search_performance()
        
        print("\n" + "-" * 60)
        
        # 测试2: Ollama性能
        test_ollama_performance()
        
        print("\n" + "-" * 60)
        
        # 测试3: 问答系统性能（不包含完整答案生成）
        test_qa_performance()
        
    except KeyboardInterrupt:
        print("\n测试被用户中断")
    except Exception as e:
        print(f"\n测试过程中出现错误: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "=" * 60)
    print("测试完成")

if __name__ == "__main__":
    main()