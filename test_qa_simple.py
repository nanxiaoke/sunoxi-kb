#!/usr/bin/env python3
"""
简单问答系统测试脚本
直接测试Ollama API，不依赖搜索系统
"""

import json
import time
import requests

def test_qa_api():
    """直接测试问答API"""
    print("🧪 问答系统API直接测试")
    print("=" * 60)
    
    # 模拟的文档内容（从实际文档中提取）
    context = """人工智能（AI）是计算机科学的一个分支，旨在构建能够执行通常需要人类智能的任务的系统。

**核心构成与技术**
AI的实现依赖于多个关键分支和技术。其中，机器学习使计算机能够从数据中自动学习；深度学习则通过神经网络模拟人脑结构；自然语言处理（NLP）赋予计算机理解人类语言的能力；计算机视觉则使机器能够"看懂"图像和视频。

**应用领域**
AI已广泛应用于多个领域，包括语音助手（如Siri、Alexa）、推荐系统（如Netflix、Amazon）、自动驾驶汽车、医疗诊断等。"""
    
    question = "什么是人工智能？"
    
    system_prompt = """你是一个知识库助手，基于提供的文档内容回答问题。

规则：
1. 只基于提供的文档内容回答，不编造信息
2. 引用文档时使用[文档1]格式
3. 答案要简洁、准确、有帮助
4. 使用中文回答，不要显示思考过程

文档内容："""
    
    user_message = f"""问题：{question}

请基于以下文档内容回答问题：

{context}

请用中文回答，并引用相关文档。"""
    
    # 测试不同模型和参数
    test_cases = [
        {
            "name": "e4b模型 (默认参数)",
            "model": "gemma4:e4b",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ],
            "options": {"temperature": 0.5, "top_p": 0.95}
        },
        {
            "name": "e4b模型 (无系统提示)",
            "model": "gemma4:e4b",
            "messages": [
                {"role": "user", "content": user_message}
            ],
            "options": {"temperature": 0.5}
        },
        {
            "name": "e4b-it模型",
            "model": "gemma4:e4b-it-q8_0",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ],
            "options": {"temperature": 0.5}
        },
        {
            "name": "26b模型",
            "model": "gemma4:26b",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ],
            "options": {"temperature": 0.5}
        }
    ]
    
    for test_case in test_cases:
        print(f"\n📋 测试: {test_case['name']}")
        print(f"   模型: {test_case['model']}")
        print(f"   消息数量: {len(test_case['messages'])}")
        
        payload = {
            "model": test_case["model"],
            "messages": test_case["messages"],
            "stream": False,
            "options": test_case["options"]
        }
        
        start_time = time.time()
        try:
            response = requests.post(
                "http://localhost:11434/api/chat",
                json=payload,
                timeout=45
            )
            elapsed = time.time() - start_time
            
            if response.status_code == 200:
                result = response.json()
                answer = result.get("message", {}).get("content", "").strip()
                
                if answer:
                    print(f"   ✅ 成功 (耗时: {elapsed:.2f}秒)")
                    print(f"      回答预览: {answer[:150]}...")
                    
                    # 检查是否包含引用
                    if "[文档" in answer:
                        print(f"      包含文档引用: 是")
                    else:
                        print(f"      包含文档引用: 否")
                else:
                    print(f"   ❌ 空响应 (耗时: {elapsed:.2f}秒)")
            else:
                print(f"   ❌ API错误: HTTP {response.status_code}")
                if response.text:
                    print(f"      错误信息: {response.text[:100]}")
                    
        except requests.exceptions.Timeout:
            elapsed = time.time() - start_time
            print(f"   ❌ 请求超时 (耗时: {elapsed:.2f}秒)")
        except Exception as e:
            elapsed = time.time() - start_time
            print(f"   ❌ 异常: {e} (耗时: {elapsed:.2f}秒)")
    
    print("\n" + "=" * 60)
    print("简单聊天功能测试")
    print("=" * 60)
    
    # 测试简单聊天
    simple_tests = [
        {"message": "Hello", "lang": "英文"},
        {"message": "你好", "lang": "中文"},
        {"message": "What is AI?", "lang": "英文"},
        {"message": "什么是人工智能？", "lang": "中文"},
    ]
    
    for test in simple_tests:
        print(f"\n💬 简单聊天: {test['lang']} '{test['message']}'")
        
        payload = {
            "model": "gemma4:e4b",
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
                    print(f"   ✅ 成功 (耗时: {elapsed:.2f}秒)")
                    print(f"      回答: {answer[:80]}...")
                else:
                    print(f"   ❌ 空响应 (耗时: {elapsed:.2f}秒)")
            else:
                print(f"   ❌ API错误: HTTP {response.status_code}")
                
        except requests.exceptions.Timeout:
            elapsed = time.time() - start_time
            print(f"   ❌ 超时 (耗时: {elapsed:.2f}秒)")
        except Exception as e:
            elapsed = time.time() - start_time
            print(f"   ❌ 异常: {e} (耗时: {elapsed:.2f}秒)")

if __name__ == "__main__":
    test_qa_api()