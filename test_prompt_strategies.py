#!/usr/bin/env python3
"""测试不同的提示策略"""

import requests
import time
import json

BASE_URL = "http://localhost:11434"

def test_prompt(prompt, model="gemma4:e4b-it-q8_0", options=None):
    """测试单个提示"""
    url = f"{BASE_URL}/api/generate"
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": options or {
            "temperature": 0.7,
            "top_p": 0.9,
            "num_predict": 50
        }
    }
    
    try:
        start = time.time()
        response = requests.post(url, json=payload, timeout=30)
        elapsed = time.time() - start
        
        if response.status_code == 200:
            result = response.json()
            response_text = result.get("response", "").strip()
            return {
                "success": bool(response_text),
                "response": response_text,
                "time": elapsed,
                "prompt": prompt[:50] + "..." if len(prompt) > 50 else prompt
            }
        else:
            return {
                "success": False,
                "error": f"HTTP {response.status_code}",
                "time": elapsed,
                "prompt": prompt[:50] + "..." if len(prompt) > 50 else prompt
            }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "time": 0,
            "prompt": prompt[:50] + "..." if len(prompt) > 50 else prompt
        }

def main():
    """测试不同的提示策略"""
    test_prompts = [
        # 原始提示
        "What is artificial intelligence?",
        # 添加指令前缀
        "Please answer the following question: What is artificial intelligence?",
        # 更友好的格式
        "Q: What is artificial intelligence?\nA:",
        # 带上下文的格式
        "I'm learning about technology. Can you explain what artificial intelligence is?",
        # 中文测试
        "什么是人工智能？",
        # 简化版
        "Explain AI in simple terms.",
        # 学术版
        "Provide a concise definition of artificial intelligence.",
        # 对话版
        "Hey, I was wondering if you could tell me what artificial intelligence is?",
    ]
    
    print("测试不同的提示策略...")
    print("=" * 60)
    
    for i, prompt in enumerate(test_prompts):
        print(f"\n测试 {i+1}/{len(test_prompts)}: {prompt[:50]}...")
        result = test_prompt(prompt)
        
        if result["success"]:
            print(f"✅ 成功: {result['response'][:80]}...")
            print(f"   时间: {result['time']:.1f}秒")
        else:
            print(f"❌ 失败: {result.get('error', '空响应')}")
            print(f"   时间: {result['time']:.1f}秒")
        
        time.sleep(1)  # 避免请求过快

if __name__ == "__main__":
    main()