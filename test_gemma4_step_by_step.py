#!/usr/bin/env python3
"""系统化、逐步测试gemma4:e4b模型"""

import requests
import time
import json
from typing import List, Dict, Optional

BASE_URL = "http://localhost:11434"

class Gemma4Tester:
    def __init__(self, model: str = "gemma4:e4b"):
        self.model = model
        self.results = []
    
    def test_prompt(self, prompt: str, options: Optional[Dict] = None, test_name: str = "") -> Dict:
        """测试单个提示词"""
        url = f"{BASE_URL}/api/generate"
        default_options = {
            "temperature": 0.7,
            "top_p": 0.9,
            "num_predict": 50
        }
        
        if options:
            default_options.update(options)
        
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": default_options
        }
        
        try:
            print(f"🔍 测试: {test_name or prompt[:60]}")
            start_time = time.time()
            response = requests.post(url, json=payload, timeout=30)
            elapsed = time.time() - start_time
            
            if response.status_code == 200:
                result = response.json()
                response_text = result.get("response", "").strip()
                
                result_info = {
                    "success": bool(response_text),
                    "response": response_text,
                    "time": elapsed,
                    "prompt": prompt,
                    "model": self.model,
                    "options": default_options,
                    "test_name": test_name,
                    "details": {
                        "eval_count": result.get("eval_count", 0),
                        "total_duration": result.get("total_duration", 0),
                        "done_reason": result.get("done_reason", ""),
                        "status_code": response.status_code
                    }
                }
                
                if response_text:
                    print(f"  ✅ 成功: {response_text[:80]}... ({elapsed:.1f}s)")
                else:
                    print(f"  ❌ 空响应 ({elapsed:.1f}s)")
                    print(f"    done_reason: {result.get('done_reason', 'unknown')}")
                    print(f"    eval_count: {result.get('eval_count', 0)}")
                
                return result_info
            else:
                error_info = {
                    "success": False,
                    "error": f"HTTP {response.status_code}",
                    "time": elapsed,
                    "prompt": prompt,
                    "model": self.model,
                    "test_name": test_name,
                    "details": response.text[:200] if response.text else ""
                }
                print(f"  ❌ 错误: {error_info['error']} ({elapsed:.1f}s)")
                return error_info
                
        except Exception as e:
            error_info = {
                "success": False,
                "error": str(e),
                "time": 0,
                "prompt": prompt,
                "model": self.model,
                "test_name": test_name
            }
            print(f"  ❌ 异常: {e}")
            return error_info
    
    def run_step_by_step_tests(self):
        """运行逐步测试"""
        print(f"\n{'='*60}")
        print(f"🔬 系统化测试: {self.model}")
        print(f"时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*60}\n")
        
        # 阶段1: 基础响应测试
        print("📋 阶段1: 基础响应测试")
        print("-" * 40)
        
        basic_tests = [
            ("简单问候", "Hello"),
            ("简单问候2", "Hi"),
            ("中文问候", "你好"),
            ("确定响应", "Say the word 'TEST'"),
            ("数学计算", "2+2="),
            ("字母序列", "ABC"),
            ("重复测试", "Repeat after me: OK"),
        ]
        
        for test_name, prompt in basic_tests:
            result = self.test_prompt(prompt, test_name=test_name)
            self.results.append(result)
            time.sleep(1)
        
        print()
        
        # 阶段2: 参数调整测试
        print("📋 阶段2: 参数调整测试 (针对'What is AI?')")
        print("-" * 40)
        
        param_tests = [
            ("默认参数", {"temperature": 0.7, "top_p": 0.9, "num_predict": 30}),
            ("低温确定", {"temperature": 0.1, "top_p": 0.5, "num_predict": 30}),
            ("高温随机", {"temperature": 1.2, "top_p": 0.95, "num_predict": 30}),
            ("短输出", {"temperature": 0.7, "num_predict": 10}),
            ("长输出", {"temperature": 0.7, "num_predict": 100}),
            ("极低top_p", {"temperature": 0.7, "top_p": 0.1, "num_predict": 30}),
        ]
        
        for test_name, options in param_tests:
            result = self.test_prompt("What is AI?", options, test_name=f"参数_{test_name}")
            self.results.append(result)
            time.sleep(2)
        
        print()
        
        # 阶段3: 提示词格式测试
        print("📋 阶段3: 提示词格式测试")
        print("-" * 40)
        
        format_tests = [
            ("直接问题", "What is AI?"),
            ("礼貌请求", "Please tell me what AI is."),
            ("Q/A格式", "Q: What is AI?\nA:"),
            ("指令格式", "Explain what artificial intelligence is."),
            ("系统角色", "You are a helpful assistant. What is AI?"),
            ("简化指令", "Define AI."),
            ("完整句子", "Can you explain what artificial intelligence is?"),
            ("填空格式", "Artificial intelligence is __________."),
        ]
        
        for test_name, prompt in format_tests:
            result = self.test_prompt(prompt, test_name=f"格式_{test_name}")
            self.results.append(result)
            time.sleep(2)
        
        print()
        
        # 阶段4: 实际处理器提示词测试
        print("📋 阶段4: 实际处理器提示词测试")
        print("-" * 40)
        
        processor_tests = [
            ("摘要提示", "Please summarize the following text in under 100 words:\n\nThis is a test document about AI.\n\nSummary:"),
            ("关键点提示", "Please extract 3 key points from the following text:\n\nThis is a test document.\n\nKey points:\n1."),
            ("分类提示", "Please classify this document: technology, article, news, tutorial, other\n\nDocument: This is about AI.\n\nCategory:"),
            ("实体提取", "Extract entities from: This is about AI and machine learning.\n\nEntities:"),
        ]
        
        for test_name, prompt in processor_tests:
            result = self.test_prompt(prompt, test_name=f"处理器_{test_name}")
            self.results.append(result)
            time.sleep(3)  # 给复杂提示更多时间
        
        print()
        
        # 阶段5: 聊天API测试
        print("📋 阶段5: 聊天API测试")
        print("-" * 40)
        
        self.test_chat_api()
        
        # 总结
        self.print_summary()
    
    def test_chat_api(self):
        """测试聊天API"""
        url = f"{BASE_URL}/api/chat"
        
        chat_tests = [
            ("简单聊天", [{"role": "user", "content": "What is AI?"}]),
            ("带系统提示", [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "What is AI?"}
            ]),
            ("研究助手", [
                {"role": "system", "content": "You are a research assistant."},
                {"role": "user", "content": "Explain artificial intelligence"}
            ]),
        ]
        
        for test_name, messages in chat_tests:
            print(f"🔍 聊天测试: {test_name}")
            
            payload = {
                "model": self.model,
                "messages": messages,
                "stream": False,
                "options": {"temperature": 0.7, "num_predict": 50}
            }
            
            try:
                start_time = time.time()
                response = requests.post(url, json=payload, timeout=30)
                elapsed = time.time() - start_time
                
                if response.status_code == 200:
                    result = response.json()
                    response_text = result.get("message", {}).get("content", "").strip()
                    thinking = result.get("message", {}).get("thinking", "")
                    
                    if response_text:
                        print(f"  ✅ 成功: {response_text[:80]}... ({elapsed:.1f}s)")
                    elif thinking:
                        print(f"  ⚠️ 有思考但无响应: {thinking[:80]}... ({elapsed:.1f}s)")
                    else:
                        print(f"  ❌ 空响应 ({elapsed:.1f}s)")
                    
                    self.results.append({
                        "test_name": f"聊天_{test_name}",
                        "success": bool(response_text),
                        "response": response_text,
                        "thinking": thinking,
                        "time": elapsed,
                        "model": self.model
                    })
                else:
                    print(f"  ❌ HTTP错误: {response.status_code} ({elapsed:.1f}s)")
                    
            except Exception as e:
                print(f"  ❌ 异常: {e}")
            
            time.sleep(2)
    
    def print_summary(self):
        """打印测试总结"""
        print(f"\n{'='*60}")
        print(f"📊 测试总结: {self.model}")
        print(f"{'='*60}")
        
        total = len(self.results)
        success = sum(1 for r in self.results if r.get("success", False))
        failed = total - success
        
        print(f"总测试数: {total}")
        print(f"成功: {success} ({success/total*100:.1f}%)")
        print(f"失败: {failed} ({failed/total*100:.1f}%)")
        
        # 分析失败模式
        print(f"\n🔍 失败分析:")
        failed_tests = [r for r in self.results if not r.get("success", False)]
        
        failure_types = {}
        for test in failed_tests:
            test_type = test.get("test_name", "未知").split("_")[0]
            failure_types[test_type] = failure_types.get(test_type, 0) + 1
        
        for test_type, count in failure_types.items():
            print(f"  {test_type}: {count} 次失败")
        
        # 显示成功案例
        print(f"\n✅ 成功案例 (前5个):")
        success_tests = [r for r in self.results if r.get("success", False)][:5]
        for test in success_tests:
            print(f"  {test.get('test_name', '未知')}: {test.get('response', '')[:60]}...")
        
        # 显示典型失败
        print(f"\n❌ 典型失败案例 (前3个):")
        failed_tests = [r for r in self.results if not r.get("success", False)][:3]
        for test in failed_tests:
            print(f"  {test.get('test_name', '未知')}: {test.get('error', '空响应')}")
        
        # 建议
        print(f"\n💡 建议:")
        if success == 0:
            print("  ⚠️ 所有测试都失败，需要检查模型加载或配置")
        elif success < total * 0.3:
            print("  ⚠️ 成功率很低，需要调整提示词格式或参数")
        elif success < total * 0.7:
            print("  ⚠️ 成功率一般，某些类型的提示词需要优化")
        else:
            print("  ✅ 成功率良好，可以继续优化")
        
        print(f"\n{'='*60}")

def compare_models():
    """比较两个模型版本"""
    models = ["gemma4:e4b", "gemma4:e4b-it-q8_0"]
    
    print(f"\n{'='*60}")
    print(f"🔬 模型对比测试")
    print(f"{'='*60}")
    
    test_prompts = [
        ("简单问候", "Hello"),
        ("定义问题", "What is AI?"),
        ("摘要测试", "Please summarize this: AI is technology."),
    ]
    
    for model in models:
        print(f"\n📋 测试模型: {model}")
        print("-" * 40)
        
        tester = Gemma4Tester(model)
        for test_name, prompt in test_prompts:
            result = tester.test_prompt(prompt, test_name=test_name)
            time.sleep(1)

if __name__ == "__main__":
    # 首先检查Ollama服务
    print("🔍 检查Ollama服务状态...")
    try:
        response = requests.get(f"{BASE_URL}/api/tags", timeout=5)
        if response.status_code == 200:
            models = response.json().get("models", [])
            model_names = [m["name"] for m in models]
            print(f"✅ Ollama服务正常，可用模型: {', '.join(model_names)}")
        else:
            print(f"❌ Ollama服务异常: HTTP {response.status_code}")
            exit(1)
    except Exception as e:
        print(f"❌ 无法连接Ollama: {e}")
        exit(1)
    
    print()
    
    # 主测试
    tester = Gemma4Tester("gemma4:e4b")
    tester.run_step_by_step_tests()
    
    print("\n" + "="*60)
    print("🔄 开始模型对比测试...")
    print("="*60)
    compare_models()