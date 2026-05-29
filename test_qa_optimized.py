#!/usr/bin/env python3
"""
优化的问答系统测试脚本
直接测试问答功能，避免模型选择问题
"""

import os
import sys
import json
import time
import requests
from pathlib import Path

# 添加脚本目录到路径
script_dir = Path(__file__).parent
sys.path.insert(0, str(script_dir / "scripts"))

from search import WikiSearcher

def test_qa_direct():
    """直接测试问答功能"""
    print("🔧 初始化搜索系统...")
    
    # 初始化搜索
    base_dir = Path("/home/sunoxi/karpathy-kb")
    searcher = WikiSearcher(base_dir)
    searcher.build_index(rebuild=False)
    
    # 测试问题
    question = "什么是人工智能？"
    print(f"\n❓ 问题: {question}")
    
    # 搜索相关文档
    print("🔍 搜索相关文档...")
    results = searcher.search(question, search_type="fulltext", limit=1)
    
    if not results:
        print("❌ 没有找到相关文档")
        return
    
    print(f"✅ 找到 {len(results)} 个相关文档")
    for i, doc in enumerate(results, 1):
        print(f"  {i}. {doc['title']} (分类: {doc['category']})")
        print(f"     摘要: {doc['summary'][:150]}...")
    
    # 准备上下文
    context = ""
    for doc in results:
        context += f"文档标题: {doc['title']}\n"
        context += f"摘要: {doc['summary']}\n"
        if doc.get('keypoints'):
            context += f"关键点: {'; '.join(doc['keypoints'][:3])}\n"
        context += "\n"
    
    # 直接调用Ollama API（使用e4b模型）
    system_prompt = """你是一个知识库助手，基于提供的文档内容回答问题。

规则：
1. 只基于提供的文档内容回答，不编造信息
2. 引用文档时使用[文档1]、[文档2]格式
3. 答案要简洁、准确、有帮助
4. 使用中文回答，不要显示思考过程

文档内容："""
    
    user_message = f"""问题：{question}

请基于以下文档内容回答问题：

{context}

请用中文回答，并引用相关文档。"""
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message}
    ]
    
    payload = {
        "model": "gemma4:e4b",  # 强制使用e4b模型
        "messages": messages,
        "stream": False,
        "options": {
            "temperature": 0.5,
            "top_p": 0.95,
            "num_predict": 200,
            "repeat_penalty": 1.1
        }
    }
    
    print(f"\n🤖 调用Ollama API (模型: gemma4:e4b)...")
    print(f"   上下文长度: {len(context)} 字符")
    print(f"   超时设置: 120秒")
    
    start_time = time.time()
    try:
        response = requests.post(
            "http://localhost:11434/api/chat",
            json=payload,
            timeout=120
        )
        elapsed = time.time() - start_time
        
        if response.status_code == 200:
            result = response.json()
            answer = result.get("message", {}).get("content", "").strip()
            
            if answer:
                print(f"\n✅ 成功生成答案 (耗时: {elapsed:.2f}秒)")
                print("=" * 60)
                print(answer)
                print("=" * 60)
                
                # 提取引用
                import re
                citations = re.findall(r'\[文档(\d+)\]', answer)
                if citations:
                    print(f"\n📚 引用文档: {', '.join(citations)}")
            else:
                print(f"\n❌ 空响应 (耗时: {elapsed:.2f}秒)")
        else:
            print(f"\n❌ API错误: HTTP {response.status_code}")
            print(f"   响应: {response.text[:200]}")
            
    except requests.exceptions.Timeout:
        elapsed = time.time() - start_time
        print(f"\n❌ 请求超时 (耗时: {elapsed:.2f}秒)")
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"\n❌ 异常: {e} (耗时: {elapsed:.2f}秒)")

def test_simple_chat():
    """测试简单聊天功能"""
    print("\n" + "=" * 60)
    print("测试简单聊天功能")
    print("=" * 60)
    
    tests = [
        {"model": "gemma4:e4b", "message": "Hello", "lang": "英文"},
        {"model": "gemma4:e4b", "message": "你好", "lang": "中文"},
        {"model": "gemma4:e4b", "message": "What is AI?", "lang": "英文"},
        {"model": "gemma4:e4b", "message": "什么是人工智能？", "lang": "中文"},
    ]
    
    for test in tests:
        print(f"\n测试: {test['lang']}消息 '{test['message']}' (模型: {test['model']})")
        
        payload = {
            "model": test["model"],
            "messages": [{"role": "user", "content": test["message"]}],
            "stream": False,
            "options": {"temperature": 0.5}
        }
        
        start_time = time.time()
        try:
            response = requests.post(
                "http://localhost:11434/api/chat",
                json=payload,
                timeout=30
            )
            elapsed = time.time() - start_time
            
            if response.status_code == 200:
                result = response.json()
                answer = result.get("message", {}).get("content", "").strip()
                
                if answer:
                    print(f"  ✅ 成功 (耗时: {elapsed:.2f}秒)")
                    print(f"     回答: {answer[:100]}...")
                else:
                    print(f"  ❌ 空响应 (耗时: {elapsed:.2f}秒)")
            else:
                print(f"  ❌ API错误: HTTP {response.status_code}")
                
        except requests.exceptions.Timeout:
            elapsed = time.time() - start_time
            print(f"  ❌ 超时 (耗时: {elapsed:.2f}秒)")
        except Exception as e:
            elapsed = time.time() - start_time
            print(f"  ❌ 异常: {e} (耗时: {elapsed:.2f}秒)")

if __name__ == "__main__":
    print("🧪 Karpathy知识库问答系统优化测试")
    print("=" * 60)
    
    # 首先测试简单聊天
    test_simple_chat()
    
    # 然后测试完整问答
    print("\n" + "=" * 60)
    print("测试完整问答功能")
    print("=" * 60)
    test_qa_direct()