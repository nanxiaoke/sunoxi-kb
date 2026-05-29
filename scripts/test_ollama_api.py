#!/usr/bin/env python3
"""
测试Ollama API连通性
"""

import requests
import time
import sys

def test_api():
    print("🔌 测试Ollama API连通性...")
    
    # 测试1: /api/tags
    try:
        start = time.time()
        resp = requests.get("http://localhost:11434/api/tags", timeout=10)
        elapsed = time.time() - start
        
        if resp.status_code == 200:
            models = resp.json().get("models", [])
            print(f"✅ /api/tags 响应时间: {elapsed:.2f}秒")
            print(f"✅ 可用模型: {len(models)} 个")
            for m in models[:3]:  # 显示前3个
                print(f"   - {m.get('name')}")
            if len(models) > 3:
                print(f"   ... 和 {len(models)-3} 个其他模型")
        else:
            print(f"❌ /api/tags 错误: HTTP {resp.status_code}")
            print(f"   响应: {resp.text[:200]}")
    except Exception as e:
        print(f"❌ /api/tags 失败: {e}")
    
    # 测试2: /api/generate (简单请求)
    print("\n🔄 测试简单生成请求...")
    payload = {
        "model": "gemma4:e4b",
        "prompt": "你好",
        "stream": False,
        "options": {
            "think": False,
            "num_predict": 10
        }
    }
    
    try:
        start = time.time()
        resp = requests.post("http://localhost:11434/api/generate", 
                           json=payload, timeout=30)
        elapsed = time.time() - start
        
        if resp.status_code == 200:
            result = resp.json()
            response = result.get("response", "")
            print(f"✅ /api/generate 响应时间: {elapsed:.2f}秒")
            print(f"✅ 响应: '{response}'")
            print(f"✅ 总token数: {result.get('total_duration', 0)/1e9:.2f}秒")
        else:
            print(f"❌ /api/generate 错误: HTTP {resp.status_code}")
            print(f"   响应: {resp.text[:200]}")
    except Exception as e:
        print(f"❌ /api/generate 失败: {e}")
    
    # 测试3: 模型加载状态
    print("\n📊 检查模型加载状态...")
    try:
        resp = requests.get("http://localhost:11434/api/ps", timeout=10)
        if resp.status_code == 200:
            processes = resp.json().get("models", [])
            if processes:
                print(f"✅ 已加载模型: {len(processes)} 个")
                for p in processes:
                    print(f"   - {p.get('name')} (已加载 {p.get('size_vram', 0)/1e9:.1f}GB VRAM)")
            else:
                print("ℹ️  没有已加载的模型（首次调用需要加载时间）")
        else:
            print(f"ℹ️  /api/ps 不可用: HTTP {resp.status_code}")
    except Exception as e:
        print(f"ℹ️  /api/ps 检查失败: {e}")

if __name__ == "__main__":
    test_api()