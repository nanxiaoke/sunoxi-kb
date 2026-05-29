#!/usr/bin/env python3
"""
测试Ollama服务是否正常工作
"""
import requests
import time
import sys

def test_ollama():
    """测试Ollama服务"""
    print("测试Ollama服务连接...")
    
    # 测试API连接
    try:
        response = requests.get("http://localhost:11434/api/tags", timeout=10)
        if response.status_code == 200:
            models = response.json().get("models", [])
            print(f"✅ Ollama服务正常，可用模型: {', '.join([m['name'] for m in models])}")
        else:
            print(f"❌ Ollama服务异常: HTTP {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ 连接Ollama服务失败: {e}")
        return False
    
    # 测试简单生成
    print("\n测试Ollama生成功能...")
    try:
        start_time = time.time()
        response = requests.post(
            "http://localhost:11434/api/generate",
            json={
                "model": "gemma4:e4b",
                "prompt": "请用一句话回答：人工智能是什么？",
                "stream": False,
                "options": {
                    "temperature": 0.7,
                    "num_predict": 50
                }
            },
            timeout=60
        )
        elapsed = time.time() - start_time
        
        if response.status_code == 200:
            result = response.json()
            answer = result.get("response", "").strip()
            print(f"✅ Ollama生成成功 ({elapsed:.1f}秒): {answer[:100]}...")
            return True
        else:
            print(f"❌ Ollama生成失败: HTTP {response.status_code} - {response.text[:200]}")
            return False
    except requests.exceptions.Timeout:
        print("❌ Ollama生成超时 (60秒)")
        return False
    except Exception as e:
        print(f"❌ Ollama生成异常: {e}")
        return False

if __name__ == "__main__":
    success = test_ollama()
    sys.exit(0 if success else 1)