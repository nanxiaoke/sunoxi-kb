#!/usr/bin/env python3
"""快速测试gemma4的核心行为"""

import requests
import time

BASE_URL = "http://localhost:11434"
MODEL = "gemma4:e4b"

def test_prompt(prompt, options=None, test_name=""):
    """测试单个提示词"""
    url = f"{BASE_URL}/api/generate"
    
    if options is None:
        options = {"temperature": 0.7, "num_predict": 30}
    
    payload = {
        "model": MODEL,
        "prompt": prompt,
        "stream": False,
        "options": options
    }
    
    try:
        print(f"🔍 {test_name}: '{prompt}'")
        start = time.time()
        resp = requests.post(url, json=payload, timeout=10)
        elapsed = time.time() - start
        
        if resp.status_code == 200:
            result = resp.json()
            response = result.get("response", "").strip()
            
            if response:
                print(f"  ✅ 响应: '{response[:80]}...' ({elapsed:.1f}s)")
                print(f"    eval_count: {result.get('eval_count')}, done_reason: {result.get('done_reason')}")
                return True, response
            else:
                print(f"  ❌ 空响应 ({elapsed:.1f}s)")
                print(f"    eval_count: {result.get('eval_count')}, done_reason: {result.get('done_reason')}")
                return False, ""
        else:
            print(f"  ❌ HTTP错误: {resp.status_code} ({elapsed:.1f}s)")
            return False, ""
            
    except Exception as e:
        print(f"  ❌ 异常: {e}")
        return False, ""

print("🔬 快速测试gemma4:e4b核心行为")
print("="*60)

# 测试1: 已知能工作的提示
print("\n📋 测试1: 已知能工作的提示")
test_prompt("Hello", test_name="简单问候")
test_prompt("TEST", test_name="确定响应")
test_prompt("2+2=", test_name="数学计算")
test_prompt("Repeat: OK", test_name="重复指令")

# 测试2: 填空式提示
print("\n📋 测试2: 填空式提示")
test_prompt("Artificial intelligence is ______.", test_name="填空定义")
test_prompt("AI stands for ______.", test_name="填空缩写")
test_prompt("The capital of France is ______.", test_name="填空事实")
test_prompt("The color of the sky is ______.", test_name="填空常识")

# 测试3: 选择式提示
print("\n📋 测试3: 选择式提示")
test_prompt("Choose one: AI is (a) technology (b) philosophy (c) both", test_name="选择答案")
test_prompt("Is AI technology? Answer yes or no.", test_name="是/否问题")
test_prompt("Select: red, blue, or green?", test_name="选择颜色")
test_prompt("True or false: AI is a field of computer science.", test_name="真/假问题")

# 测试4: 命令式提示
print("\n📋 测试4: 命令式提示")
test_prompt("Say 'AI'", test_name="命令说")
test_prompt("Output the word 'test'", test_name="命令输出")
test_prompt("Write the number 42", test_name="命令写数字")
test_prompt("Copy this: hello world", test_name="命令复制")

# 测试5: 补全式提示
print("\n📋 测试5: 补全式提示")
test_prompt("Once upon a time", test_name="故事开头")
test_prompt("In the beginning", test_name="开头补全")
test_prompt("To summarize", test_name="总结开头")
test_prompt("The main idea is", test_name="主要观点开头")

# 测试6: 极简提示
print("\n📋 测试6: 极简提示")
test_prompt("AI:", test_name="冒号提示")
test_prompt("Artificial intelligence:", test_name="冒号提示2")
test_prompt("What is AI?", {"temperature": 0.1, "num_predict": 10}, "低温简短")
test_prompt("Explain AI", {"temperature": 0.1, "num_predict": 10}, "低温解释")

# 测试7: 特殊格式
print("\n📋 测试7: 特殊格式")
test_prompt("Q: What is AI?\nA:", test_name="Q/A格式")
test_prompt("### Question: What is AI?\n### Answer:", test_name="Markdown格式")
test_prompt("<question>What is AI?</question>\n<answer>", test_name="XML格式")
test_prompt("```\nWhat is AI?\n```\nAnswer:", test_name="代码块格式")

print("\n" + "="*60)
print("测试完成")