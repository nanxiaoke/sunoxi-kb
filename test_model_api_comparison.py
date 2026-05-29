#!/usr/bin/env python3
"""对比测试：不同模型和API调用方式对响应的影响"""

import requests
import time
import json
from typing import Dict, Optional, List

BASE_URL = "http://localhost:11434"

class APITester:
    def __init__(self):
        self.results = []
    
    def test_stream_vs_non_stream(self, model: str, prompt: str, system_prompt: str = "") -> Dict:
        """测试流式与非流式调用的区别"""
        print(f"\n🔬 测试模型: {model}")
        print(f"  提示: {prompt[:60]}...")
        
        results = {}
        
        # 测试1: 非流式调用 (stream=False)
        print(f"  1. 非流式调用 (stream=False)...")
        start_time = time.time()
        
        payload = {
            "model": model,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "stream": False,
            "options": {"num_predict": 50}
        }
        
        if system_prompt:
            payload["messages"].insert(0, {"role": "system", "content": system_prompt})
        
        try:
            response = requests.post(
                f"{BASE_URL}/api/chat",
                json=payload,
                timeout=30
            )
            elapsed = time.time() - start_time
            
            if response.status_code == 200:
                result = response.json()
                content = result.get("message", {}).get("content", "").strip()
                thinking = result.get("message", {}).get("thinking", "")
                
                results["non_stream"] = {
                    "success": bool(content),
                    "content": content,
                    "thinking": thinking,
                    "time": elapsed,
                    "done_reason": result.get("done_reason", ""),
                    "eval_count": result.get("eval_count", 0)
                }
                
                if content:
                    print(f"    ✅ 成功: {content[:60]}... ({elapsed:.1f}s)")
                    print(f"      thinking: {'有' if thinking else '无'}")
                else:
                    print(f"    ❌ 空响应 ({elapsed:.1f}s)")
                    if thinking:
                        print(f"      思考: {thinking[:60]}...")
            else:
                print(f"    ❌ HTTP错误: {response.status_code} ({elapsed:.1f}s)")
                
        except Exception as e:
            print(f"    ❌ 异常: {e}")
        
        time.sleep(2)
        
        # 测试2: 流式调用 (stream=True)
        print(f"  2. 流式调用 (stream=True)...")
        start_time = time.time()
        
        payload["stream"] = True
        
        try:
            response = requests.post(
                f"{BASE_URL}/api/chat",
                json=payload,
                timeout=30,
                stream=True
            )
            
            full_content = ""
            thinking_detected = False
            
            if response.status_code == 200:
                for line in response.iter_lines():
                    if line:
                        line_str = line.decode('utf-8')
                        if line_str.startswith('data: '):
                            data_str = line_str[6:]
                            if data_str.strip() == '[DONE]':
                                break
                            
                            try:
                                data = json.loads(data_str)
                                if 'message' in data:
                                    message = data['message']
                                    if 'content' in message and message['content']:
                                        full_content += message['content']
                                    if 'thinking' in message and message['thinking']:
                                        thinking_detected = True
                                elif 'content' in data and data['content']:
                                    full_content += data['content']
                            except json.JSONDecodeError:
                                continue
                
                elapsed = time.time() - start_time
                
                results["stream"] = {
                    "success": bool(full_content.strip()),
                    "content": full_content.strip(),
                    "thinking": thinking_detected,
                    "time": elapsed,
                    "done_reason": "stream_complete"
                }
                
                if full_content.strip():
                    print(f"    ✅ 成功: {full_content.strip()[:60]}... ({elapsed:.1f}s)")
                    print(f"      thinking: {'有' if thinking_detected else '无'}")
                else:
                    print(f"    ❌ 空响应 ({elapsed:.1f}s)")
            else:
                elapsed = time.time() - start_time
                print(f"    ❌ HTTP错误: {response.status_code} ({elapsed:.1f}s)")
                
        except Exception as e:
            print(f"    ❌ 异常: {e}")
        
        return results
    
    def test_different_system_prompts(self, model: str, prompt: str) -> Dict:
        """测试不同系统提示的影响"""
        print(f"\n🔬 测试不同系统提示 (模型: {model})")
        print(f"  用户提示: {prompt[:60]}...")
        
        system_prompts = [
            ("无系统提示", ""),
            ("标准助手", "You are a helpful assistant."),
            ("研究助手", "You are a research assistant."),
            ("禁用思考", "Do not think. Just answer directly without showing your thinking process."),
            ("简洁指令", "Provide direct answers without explanation or thinking."),
            ("思考模式", "Please think through your answer before responding."),
        ]
        
        results = {}
        
        for name, system_content in system_prompts:
            print(f"  系统提示: {name}...")
            
            payload = {
                "model": model,
                "messages": [],
                "stream": False,
                "options": {"num_predict": 50}
            }
            
            if system_content:
                payload["messages"].append({"role": "system", "content": system_content})
            
            payload["messages"].append({"role": "user", "content": prompt})
            
            start_time = time.time()
            
            try:
                response = requests.post(
                    f"{BASE_URL}/api/chat",
                    json=payload,
                    timeout=30
                )
                elapsed = time.time() - start_time
                
                if response.status_code == 200:
                    result = response.json()
                    content = result.get("message", {}).get("content", "").strip()
                    thinking = result.get("message", {}).get("thinking", "")
                    
                    success = bool(content)
                    results[name] = {
                        "success": success,
                        "content": content,
                        "thinking": thinking,
                        "time": elapsed,
                        "done_reason": result.get("done_reason", ""),
                        "eval_count": result.get("eval_count", 0)
                    }
                    
                    if success:
                        print(f"    ✅ 成功 ({elapsed:.1f}s)")
                    else:
                        print(f"    ❌ 空响应 ({elapsed:.1f}s)")
                        if thinking:
                            print(f"      思考: {thinking[:60]}...")
                else:
                    print(f"    ❌ HTTP错误: {response.status_code} ({elapsed:.1f}s)")
                    
            except Exception as e:
                print(f"    ❌ 异常: {e}")
            
            time.sleep(2)
        
        return results
    
    def test_different_models(self, prompt: str, system_prompt: str = "") -> Dict:
        """测试不同模型的行为"""
        print(f"\n🔬 测试不同模型")
        print(f"  提示: {prompt[:60]}...")
        if system_prompt:
            print(f"  系统提示: {system_prompt[:60]}...")
        
        # 获取可用模型
        try:
            response = requests.get(f"{BASE_URL}/api/tags", timeout=5)
            if response.status_code == 200:
                models_data = response.json().get("models", [])
                model_names = [m["name"] for m in models_data]
                print(f"  可用模型: {', '.join(model_names)}")
            else:
                print(f"  ❌ 无法获取模型列表: HTTP {response.status_code}")
                return {}
        except Exception as e:
            print(f"  ❌ 无法连接Ollama: {e}")
            return {}
        
        results = {}
        
        for model in model_names:
            print(f"  测试模型: {model}...")
            
            payload = {
                "model": model,
                "messages": [],
                "stream": False,
                "options": {"num_predict": 50}
            }
            
            if system_prompt:
                payload["messages"].append({"role": "system", "content": system_prompt})
            
            payload["messages"].append({"role": "user", "content": prompt})
            
            start_time = time.time()
            
            try:
                response = requests.post(
                    f"{BASE_URL}/api/chat",
                    json=payload,
                    timeout=30
                )
                elapsed = time.time() - start_time
                
                if response.status_code == 200:
                    result = response.json()
                    content = result.get("message", {}).get("content", "").strip()
                    thinking = result.get("message", {}).get("thinking", "")
                    
                    results[model] = {
                        "success": bool(content),
                        "content": content,
                        "thinking": thinking,
                        "time": elapsed,
                        "done_reason": result.get("done_reason", ""),
                        "eval_count": result.get("eval_count", 0)
                    }
                    
                    if content:
                        print(f"    ✅ 成功: {content[:60]}... ({elapsed:.1f}s)")
                    else:
                        print(f"    ❌ 空响应 ({elapsed:.1f}s)")
                        if thinking:
                            print(f"      思考: {thinking[:60]}...")
                else:
                    print(f"    ❌ HTTP错误: {response.status_code} ({elapsed:.1f}s)")
                    
            except Exception as e:
                print(f"    ❌ 异常: {e}")
            
            time.sleep(3)
        
        return results
    
    def print_summary(self, test_name: str, results: Dict):
        """打印测试总结"""
        print(f"\n{'='*60}")
        print(f"📊 {test_name} 总结")
        print(f"{'='*60}")
        
        if not results:
            print("  无结果")
            return
        
        # 计算成功率
        success_count = sum(1 for r in results.values() if isinstance(r, dict) and r.get("success", False))
        total_count = len(results)
        
        print(f"  总测试数: {total_count}")
        print(f"  成功数: {success_count} ({success_count/total_count*100:.1f}%)")
        
        # 详细结果
        print(f"\n  🔍 详细结果:")
        for key, result in results.items():
            if isinstance(result, dict):
                status = "✅" if result.get("success", False) else "❌"
                content = result.get("content", "")
                thinking = result.get("thinking", "")
                time_val = result.get("time", 0)
                
                print(f"    {status} {key}: ", end="")
                if content:
                    print(f"\"{content[:50]}...\" ({time_val:.1f}s)")
                else:
                    print(f"空响应 ({time_val:.1f}s)", end="")
                    if thinking:
                        print(f" [有思考过程]")
                    else:
                        print()
            else:
                print(f"    ⚠️ {key}: 结果格式异常")

def main():
    """主测试函数"""
    print("🔬 模型和API调用方式对比测试")
    print("="*60)
    
    # 检查Ollama服务
    print("🔍 检查Ollama服务状态...")
    try:
        response = requests.get(f"{BASE_URL}/api/tags", timeout=5)
        if response.status_code == 200:
            print("✅ Ollama服务正常")
        else:
            print(f"❌ Ollama服务异常: HTTP {response.status_code}")
            return
    except Exception as e:
        print(f"❌ 无法连接Ollama: {e}")
        return
    
    tester = APITester()
    
    # 测试参数
    test_prompt = "What is artificial intelligence? Explain in simple terms."
    test_model = "gemma4:e4b"
    
    # 测试1: 流式 vs 非流式
    print(f"\n{'='*60}")
    print("测试1: 流式与非流式调用对比")
    print(f"{'='*60}")
    
    stream_results = tester.test_stream_vs_non_stream(
        model=test_model,
        prompt=test_prompt,
        system_prompt="You are a helpful assistant."
    )
    
    tester.print_summary("流式 vs 非流式", stream_results)
    
    # 测试2: 不同系统提示
    print(f"\n{'='*60}")
    print("测试2: 不同系统提示的影响")
    print(f"{'='*60}")
    
    system_results = tester.test_different_system_prompts(
        model=test_model,
        prompt=test_prompt
    )
    
    tester.print_summary("不同系统提示", system_results)
    
    # 测试3: 不同模型
    print(f"\n{'='*60}")
    print("测试3: 不同模型的行为")
    print(f"{'='*60}")
    
    model_results = tester.test_different_models(
        prompt=test_prompt,
        system_prompt="You are a helpful assistant."
    )
    
    tester.print_summary("不同模型", model_results)
    
    # 测试4: gemma4专用测试
    print(f"\n{'='*60}")
    print("测试4: gemma4思考模式问题验证")
    print(f"{'='*60}")
    
    gemma4_prompts = [
        ("简单问题", "What is AI?"),
        ("复杂问题", "Explain the difference between machine learning and deep learning."),
        ("创作任务", "Write a short poem about technology."),
        ("分析任务", "Analyze the benefits and risks of artificial intelligence."),
    ]
    
    for prompt_name, prompt_text in gemma4_prompts:
        print(f"\n🔍 测试提示: {prompt_name}")
        
        # 有系统提示
        with_system = tester.test_stream_vs_non_stream(
            model=test_model,
            prompt=prompt_text,
            system_prompt="Do not think. Just answer directly."
        )
        
        # 无系统提示
        without_system = tester.test_stream_vs_non_stream(
            model=test_model,
            prompt=prompt_text,
            system_prompt=""
        )
        
        print(f"  {'有系统提示' if with_system.get('non_stream', {}).get('success', False) else '无系统提示'}: ", end="")
        if with_system.get('non_stream', {}).get('success', False):
            print("✅ 成功")
        else:
            print("❌ 失败")
    
    print(f"\n{'='*60}")
    print("🎯 关键发现总结")
    print(f"{'='*60}")
    
    print("1. **流式 vs 非流式**:")
    print("   - 流式调用通常用于实时显示响应")
    print("   - 非流式调用返回完整JSON响应")
    print("   - 两者在内容生成上应该没有本质区别")
    
    print("\n2. **系统提示的影响**:")
    print("   - gemma4对系统提示非常敏感")
    print("   - '禁用思考'提示可以解决空响应问题")
    print("   - 标准提示可能导致思考过程但不输出答案")
    
    print("\n3. **模型差异**:")
    print("   - 不同模型对相同提示可能有不同响应")
    print("   - gemma4系列可能有特殊的行为模式")
    print("   - 其他模型(如llama3)可能没有这个问题")
    
    print("\n4. **关于DeepSeek和其他在线模型**:")
    print("   - 在线模型通常通过API密钥访问")
    print("   - 行为取决于模型提供商的配置")
    print("   - 需要具体测试每个模型的行为")
    
    print(f"\n{'='*60}")
    print("🚀 测试完成")
    print(f"{'='*60}")

if __name__ == "__main__":
    main()