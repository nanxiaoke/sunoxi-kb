#!/usr/bin/env python3
"""系统化测试gemma4:e4b模型和提示词"""

import requests
import time
import json
from typing import List, Dict, Tuple

BASE_URL = "http://localhost:11434"
MODEL = "gemma4:e4b"

def test_single_prompt(prompt: str, options: Dict = None, max_wait: int = 30) -> Dict:
    """测试单个提示词"""
    url = f"{BASE_URL}/api/generate"
    payload = {
        "model": MODEL,
        "prompt": prompt,
        "stream": False,
        "options": options or {
            "temperature": 0.7,
            "top_p": 0.9,
            "num_predict": 100
        }
    }
    
    try:
        print(f"测试: {prompt[:60]}...")
        start_time = time.time()
        response = requests.post(url, json=payload, timeout=max_wait)
        elapsed = time.time() - start_time
        
        if response.status_code == 200:
            result = response.json()
            response_text = result.get("response", "").strip()
            
            if response_text:
                return {
                    "success": True,
                    "response": response_text,
                    "time": elapsed,
                    "prompt": prompt,
                    "model": MODEL,
                    "details": {
                        "eval_count": result.get("eval_count", 0),
                        "total_duration": result.get("total_duration", 0),
                        "done_reason": result.get("done_reason", "")
                    }
                }
            else:
                return {
                    "success": False,
                    "error": "空响应",
                    "time": elapsed,
                    "prompt": prompt,
                    "model": MODEL,
                    "details": result
                }
        else:
            return {
                "success": False,
                "error": f"HTTP {response.status_code}",
                "time": elapsed,
                "prompt": prompt,
                "model": MODEL,
                "details": response.text[:200] if response.text else ""
            }
            
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "time": 0,
            "prompt": prompt,
            "model": MODEL
        }

def test_chat(messages: List[Dict], options: Dict = None, max_wait: int = 30) -> Dict:
    """测试聊天API"""
    url = f"{BASE_URL}/api/chat"
    payload = {
        "model": MODEL,
        "messages": messages,
        "stream": False,
        "options": options or {
            "temperature": 0.7,
            "top_p": 0.9,
            "num_predict": 100
        }
    }
    
    try:
        user_content = messages[-1]["content"] if messages else ""
        print(f"测试聊天: {user_content[:60]}...")
        start_time = time.time()
        response = requests.post(url, json=payload, timeout=max_wait)
        elapsed = time.time() - start_time
        
        if response.status_code == 200:
            result = response.json()
            response_text = result.get("message", {}).get("content", "").strip()
            
            if response_text:
                return {
                    "success": True,
                    "response": response_text,
                    "time": elapsed,
                    "messages": messages,
                    "model": MODEL,
                    "details": {
                        "eval_count": result.get("eval_count", 0),
                        "total_duration": result.get("total_duration", 0),
                        "done_reason": result.get("done_reason", "")
                    }
                }
            else:
                return {
                    "success": False,
                    "error": "空响应",
                    "time": elapsed,
                    "messages": messages,
                    "model": MODEL,
                    "details": result
                }
        else:
            return {
                "success": False,
                "error": f"HTTP {response.status_code}",
                "time": elapsed,
                "messages": messages,
                "model": MODEL,
                "details": response.text[:200] if response.text else ""
            }
            
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "time": 0,
            "messages": messages,
            "model": MODEL
        }

def run_systematic_tests():
    """运行系统化测试"""
    print(f"=== 系统化测试 gemma4:e4b ===")
    print(f"时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # 测试1: 基础提示词测试
    print("1. 基础提示词测试")
    print("-" * 40)
    
    basic_prompts = [
        "Hello",
        "Hi there",
        "你好",
        "What is your name?",
        "How are you?",
        "What is AI?",
        "What is artificial intelligence?",
        "Explain artificial intelligence",
        "Summarize the concept of AI",
        "Tell me about machine learning",
    ]
    
    for prompt in basic_prompts:
        result = test_single_prompt(prompt)
        if result["success"]:
            print(f"✅ {prompt[:40]:<40} → {result['response'][:40]}... ({result['time']:.1f}s)")
        else:
            print(f"❌ {prompt[:40]:<40} → {result['error']} ({result['time']:.1f}s)")
        time.sleep(1)  # 避免请求过快
    
    print()
    
    # 测试2: 聊天API测试
    print("2. 聊天API测试")
    print("-" * 40)
    
    chat_scenarios = [
        [{"role": "user", "content": "Hello"}],
        [{"role": "system", "content": "You are a helpful assistant."}, {"role": "user", "content": "What is AI?"}],
        [{"role": "system", "content": "You are a research assistant."}, {"role": "user", "content": "Explain artificial intelligence"}],
        [{"role": "user", "content": "I need to understand AI. Can you explain?"}],
    ]
    
    for messages in chat_scenarios:
        result = test_chat(messages)
        if result["success"]:
            user_msg = messages[-1]["content"][:30]
            print(f"✅ 聊天 → {result['response'][:40]}... ({result['time']:.1f}s)")
        else:
            user_msg = messages[-1]["content"][:30] if messages else ""
            print(f"❌ 聊天 → {result['error']} ({result['time']:.1f}s)")
        time.sleep(1)
    
    print()
    
    # 测试3: 参数调整测试
    print("3. 参数调整测试")
    print("-" * 40)
    
    param_tests = [
        ("默认参数", "What is AI?", {"temperature": 0.7, "top_p": 0.9, "num_predict": 50}),
        ("高温参数", "What is AI?", {"temperature": 1.2, "top_p": 0.95, "num_predict": 50}),
        ("低温参数", "What is AI?", {"temperature": 0.2, "top_p": 0.7, "num_predict": 50}),
        ("短输出", "What is AI?", {"temperature": 0.7, "top_p": 0.9, "num_predict": 20}),
        ("长输出", "What is AI?", {"temperature": 0.7, "top_p": 0.9, "num_predict": 200}),
    ]
    
    for test_name, prompt, options in param_tests:
        result = test_single_prompt(prompt, options)
        if result["success"]:
            print(f"✅ {test_name:<15} → {result['response'][:40]}... ({result['time']:.1f}s)")
        else:
            print(f"❌ {test_name:<15} → {result['error']} ({result['time']:.1f}s)")
        time.sleep(1)
    
    print()
    
    # 测试4: 实际处理器提示词测试
    print("4. 实际处理器提示词测试")
    print("-" * 40)
    
    processor_prompts = [
        # 摘要提示词
        "Please summarize the following text in under 300 words, be objective and accurate:\n\nThis is a test document about artificial intelligence. AI is the simulation of human intelligence in machines.\n\nSummary:",
        # 关键点提取提示词
        "Please extract 5 key points from the following text, return as a numbered list:\n\nThis is a test document about artificial intelligence. AI is the simulation of human intelligence in machines.\n\nKey points:\n1.",
        # 分类提示词
        "Please classify the following document content into one of these categories: technology, academic_paper, notes, code, article, news, tutorial, other\n\nDocument excerpt:\nThis is a test document about artificial intelligence.\n\nReturn only the category name in English, no explanation:",
        # 实体提取提示词
        "Please extract important entities (people, organizations, concepts, technologies, etc.) from the following text, one per line:\n\nThis is a test document about artificial intelligence.\n\nImportant entities:",
    ]
    
    for i, prompt in enumerate(processor_prompts):
        test_name = ["摘要", "关键点", "分类", "实体"][i]
        result = test_single_prompt(prompt, {"num_predict": 100})
        if result["success"]:
            print(f"✅ {test_name:<10} → {result['response'][:40]}... ({result['time']:.1f}s)")
        else:
            print(f"❌ {test_name:<10} → {result['error']} ({result['time']:.1f}s)")
        time.sleep(2)  # 给模型更多时间处理复杂提示
    
    print()
    print("=== 测试完成 ===")

def debug_ollama_status():
    """调试Ollama状态"""
    print("=== Ollama状态调试 ===")
    
    # 检查API可用性
    try:
        tags_response = requests.get(f"{BASE_URL}/api/tags", timeout=5)
        print(f"API状态: HTTP {tags_response.status_code}")
        if tags_response.status_code == 200:
            models = tags_response.json().get("models", [])
            print(f"可用模型: {', '.join([m['name'] for m in models])}")
    except Exception as e:
        print(f"API检查失败: {e}")
    
    # 检查模型是否加载
    try:
        generate_response = requests.post(
            f"{BASE_URL}/api/generate",
            json={"model": MODEL, "prompt": "test", "stream": False},
            timeout=10
        )
        print(f"生成测试: HTTP {generate_response.status_code}")
    except Exception as e:
        print(f"生成测试失败: {e}")

if __name__ == "__main__":
    debug_ollama_status()
    print()
    run_systematic_tests()