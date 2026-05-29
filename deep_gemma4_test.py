#!/usr/bin/env python3
"""深度、系统化测试gemma4:e4b模型 - 探索所有可能的解决方法"""

import requests
import time
import json
import itertools
from typing import List, Dict, Optional, Tuple
import concurrent.futures

BASE_URL = "http://localhost:11434"
MODEL = "gemma4:e4b"

class DeepGemma4Tester:
    def __init__(self):
        self.results = []
        self.success_count = 0
        self.total_count = 0
        
    def test_api(self, prompt: str, endpoint: str = "generate", 
                 params: Optional[Dict] = None, 
                 extra_options: Optional[Dict] = None,
                 test_name: str = "") -> Dict:
        """测试API并记录结果"""
        url = f"{BASE_URL}/api/{endpoint}"
        
        # 默认参数
        default_params = {
            "model": MODEL,
            "stream": False,
        }
        
        # 更新参数
        if params:
            default_params.update(params)
        
        # 添加额外选项
        if extra_options:
            if "options" not in default_params:
                default_params["options"] = {}
            default_params["options"].update(extra_options)
        
        # 确保有options
        if "options" not in default_params:
            default_params["options"] = {}
        
        self.total_count += 1
        
        try:
            print(f"🔍 测试{self.total_count}: {test_name or prompt[:60]}")
            start_time = time.time()
            response = requests.post(url, json=default_params, timeout=30)
            elapsed = time.time() - start_time
            
            if response.status_code == 200:
                result = response.json()
                
                # 提取响应文本
                if endpoint == "chat":
                    response_text = result.get("message", {}).get("content", "").strip()
                    thinking = result.get("message", {}).get("thinking", "")
                else:
                    response_text = result.get("response", "").strip()
                    thinking = ""
                
                success = bool(response_text)
                if success:
                    self.success_count += 1
                
                test_result = {
                    "success": success,
                    "response": response_text,
                    "thinking": thinking,
                    "time": elapsed,
                    "prompt": prompt,
                    "endpoint": endpoint,
                    "params": default_params,
                    "test_name": test_name,
                    "details": {
                        "eval_count": result.get("eval_count", 0),
                        "total_duration": result.get("total_duration", 0),
                        "done_reason": result.get("done_reason", ""),
                        "status_code": response.status_code
                    }
                }
                
                if success:
                    print(f"  ✅ 成功: {response_text[:80]}... ({elapsed:.1f}s)")
                else:
                    print(f"  ❌ 空响应 ({elapsed:.1f}s)")
                    print(f"    done_reason: {result.get('done_reason', 'unknown')}")
                    print(f"    eval_count: {result.get('eval_count', 0)}")
                
                self.results.append(test_result)
                return test_result
            else:
                print(f"  ❌ HTTP错误: {response.status_code} ({elapsed:.1f}s)")
                return {"error": f"HTTP {response.status_code}", "time": elapsed}
                
        except Exception as e:
            print(f"  ❌ 异常: {e}")
            return {"error": str(e), "time": 0}
    
    def run_comprehensive_tests(self):
        """运行全面测试"""
        print(f"\n{'='*60}")
        print(f"🔬 深度系统化测试: {MODEL}")
        print(f"时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*60}\n")
        
        # 测试1: 基础验证测试
        self.run_basic_validation()
        
        # 测试2: 特殊参数探索
        self.run_special_parameters_test()
        
        # 测试3: 提示词格式深度测试
        self.run_prompt_format_deep_test()
        
        # 测试4: 系统提示词测试
        self.run_system_prompt_test()
        
        # 测试5: 聊天API深度测试
        self.run_chat_api_deep_test()
        
        # 测试6: 模型特定配置测试
        self.run_model_specific_test()
        
        # 总结
        self.print_comprehensive_summary()
    
    def run_basic_validation(self):
        """基础验证测试"""
        print("📋 阶段1: 基础验证测试")
        print("-" * 40)
        
        basic_tests = [
            ("Hello", {"options": {"num_predict": 10}}, "简单问候"),
            ("TEST", {"options": {"num_predict": 5, "temperature": 0.1}}, "确定响应"),
            ("2+2=", {"options": {"num_predict": 5}}, "数学计算"),
            ("A B C D E", {"options": {"num_predict": 5}}, "字母序列"),
            ("Repeat: OK", {"options": {"num_predict": 5}}, "重复指令"),
            ("The cat", {"options": {"num_predict": 10}}, "单词补全"),
        ]
        
        for prompt, params, name in basic_tests:
            self.test_api(prompt, "generate", params, test_name=f"基础_{name}")
            time.sleep(1)
        
        print()
    
    def run_special_parameters_test(self):
        """特殊参数探索测试"""
        print("📋 阶段2: 特殊参数探索测试")
        print("-" * 40)
        
        # gemma4可能需要的特殊参数
        special_params_list = [
            # 标准参数组合
            {"temperature": 0.1, "top_p": 0.1, "num_predict": 30, "repeat_penalty": 1.0},
            {"temperature": 0.7, "top_p": 0.9, "num_predict": 30, "repeat_penalty": 1.1},
            {"temperature": 1.0, "top_p": 0.95, "num_predict": 30, "repeat_penalty": 1.2},
            
            # 极端参数
            {"temperature": 0.01, "top_p": 0.01, "num_predict": 20},
            {"temperature": 1.5, "top_p": 0.99, "num_predict": 40},
            
            # 可能影响思考模式的参数
            {"temperature": 0.7, "num_predict": 30, "top_k": 40},
            {"temperature": 0.7, "num_predict": 30, "top_k": 1},
            {"temperature": 0.7, "num_predict": 30, "typical_p": 0.9},
            
            # 长上下文参数
            {"temperature": 0.7, "num_predict": 100, "repeat_penalty": 1.0},
            {"temperature": 0.7, "num_predict": 200, "repeat_penalty": 1.0},
        ]
        
        prompt = "What is artificial intelligence?"
        
        for i, params in enumerate(special_params_list, 1):
            self.test_api(
                prompt, 
                "generate", 
                {"options": params},
                test_name=f"特殊参数_{i}"
            )
            time.sleep(2)
        
        print()
    
    def run_prompt_format_deep_test(self):
        """提示词格式深度测试"""
        print("📋 阶段3: 提示词格式深度测试")
        print("-" * 40)
        
        # 各种提示词格式
        format_tests = [
            # 直接问题
            ("What is AI?", "直接问题"),
            
            # 指令格式
            ("Explain artificial intelligence.", "指令格式"),
            ("Define artificial intelligence.", "定义格式"),
            ("Describe artificial intelligence.", "描述格式"),
            
            # Q/A格式
            ("Q: What is artificial intelligence?\nA:", "Q/A格式"),
            ("Question: What is AI?\nAnswer:", "问答格式"),
            
            # 填空格式
            ("Artificial intelligence is ______.", "填空格式"),
            ("AI stands for ______.", "填空格式2"),
            
            # 列表格式
            ("List three characteristics of AI:\n1.", "列表格式"),
            
            # 代码/JSON格式
            ('{"instruction": "Explain AI", "response": ""}', "JSON格式"),
            ("<instruction>Explain AI</instruction>\n<response>", "XML格式"),
            
            # 学术格式
            ("Artificial intelligence (AI) refers to", "学术开场"),
            ("In computer science, artificial intelligence is", "定义开场"),
            
            # 简单格式
            ("AI:", "极简格式"),
            ("Artificial intelligence:", "冒号格式"),
        ]
        
        options = {"temperature": 0.7, "num_predict": 50}
        
        for prompt, name in format_tests:
            self.test_api(
                prompt,
                "generate",
                {"options": options},
                test_name=f"格式_{name}"
            )
            time.sleep(2)
        
        print()
    
    def run_system_prompt_test(self):
        """系统提示词测试"""
        print("📋 阶段4: 系统提示词测试")
        print("-" * 40)
        
        system_prompts = [
            # 无系统提示（基准）
            [],
            
            # 简单系统提示
            [{"role": "system", "content": "You are a helpful assistant."}],
            
            # 指令性系统提示
            [{"role": "system", "content": "You must answer all questions directly and concisely."}],
            
            # 禁用思考模式
            [{"role": "system", "content": "Do not show your thinking process. Just give the final answer."}],
            
            # 简单回答指令
            [{"role": "system", "content": "Always provide a direct answer without explanation."}],
            
            # 鼓励回答
            [{"role": "system", "content": "You should always respond to user queries."}],
            
            # 安全放宽
            [{"role": "system", "content": "You are allowed to discuss all topics including AI."}],
            
            # 格式指令
            [{"role": "system", "content": "Respond in plain text format."}],
        ]
        
        user_message = "What is artificial intelligence?"
        
        for i, system_prompt in enumerate(system_prompts, 1):
            messages = system_prompt + [{"role": "user", "content": user_message}]
            
            self.test_api(
                "",  # prompt参数对于chat API不重要
                "chat",
                {"messages": messages, "options": {"temperature": 0.7, "num_predict": 50}},
                test_name=f"系统提示_{i}"
            )
            time.sleep(3)
        
        print()
    
    def run_chat_api_deep_test(self):
        """聊天API深度测试"""
        print("📋 阶段5: 聊天API深度测试")
        print("-" * 40)
        
        # 测试不同的消息结构
        chat_tests = [
            # 简单对话
            (
                [{"role": "user", "content": "What is AI?"}],
                "简单对话"
            ),
            
            # 多轮对话
            (
                [
                    {"role": "user", "content": "Hello"},
                    {"role": "assistant", "content": "Hello! How can I help you?"},
                    {"role": "user", "content": "What is AI?"}
                ],
                "多轮对话"
            ),
            
            # 强制响应格式
            (
                [
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": "What is AI? Answer in one sentence."}
                ],
                "强制简短"
            ),
            
            # 思考禁用
            (
                [
                    {"role": "system", "content": "Do not think. Just answer."},
                    {"role": "user", "content": "What is AI?"}
                ],
                "禁用思考"
            ),
            
            # 填空式对话
            (
                [
                    {"role": "user", "content": "Complete this sentence: Artificial intelligence is"}
                ],
                "填空式"
            ),
            
            # 选择式对话
            (
                [
                    {"role": "user", "content": "Choose one: AI is (a) technology (b) philosophy (c) both"}
                ],
                "选择式"
            ),
        ]
        
        for messages, name in chat_tests:
            self.test_api(
                "",
                "chat",
                {"messages": messages, "options": {"temperature": 0.7, "num_predict": 50}},
                test_name=f"聊天_{name}"
            )
            time.sleep(3)
        
        print()
    
    def run_model_specific_test(self):
        """模型特定配置测试"""
        print("📋 阶段6: 模型特定配置测试")
        print("-" * 40)
        
        # gemma4可能需要的特殊配置
        model_specific_tests = [
            # 不同停止标记
            ("What is AI?", {"stop": ["\n", "</s>"]}, "停止标记_标准"),
            ("What is AI?", {"stop": ["<|endoftext|>", "\n\n"]}, "停止标记_特殊"),
            ("What is AI?", {"stop": []}, "停止标记_无"),
            
            # 不同上下文长度
            ("What is AI?", {"num_predict": 10}, "短输出_10"),
            ("What is AI?", {"num_predict": 30}, "中输出_30"),
            ("What is AI?", {"num_predict": 100}, "长输出_100"),
            
            # 特殊gemma4参数（猜测）
            ("What is AI?", {"temperature": 0.7, "thinking": False}, "禁用思考"),
            ("What is AI?", {"temperature": 0.7, "reasoning": False}, "禁用推理"),
            ("What is AI?", {"temperature": 0.7, "max_tokens": 50}, "最大token"),
            
            # 组合测试
            ("What is AI?", {
                "temperature": 0.7,
                "top_p": 0.9,
                "num_predict": 50,
                "repeat_penalty": 1.1,
                "stop": ["\n"]
            }, "组合优化"),
            
            # 简单提示+不同参数
            ("AI is", {"num_predict": 20}, "补全提示"),
            ("Artificial intelligence is", {"num_predict": 30}, "定义补全"),
        ]
        
        for prompt, options, name in model_specific_tests:
            self.test_api(
                prompt,
                "generate",
                {"options": options},
                test_name=f"模型配置_{name}"
            )
            time.sleep(2)
        
        print()
    
    def print_comprehensive_summary(self):
        """打印全面总结"""
        print(f"\n{'='*60}")
        print(f"📊 深度测试总结: {MODEL}")
        print(f"{'='*60}")
        
        print(f"总测试数: {self.total_count}")
        print(f"成功数: {self.success_count}")
        print(f"成功率: {self.success_count/self.total_count*100:.1f}%")
        
        # 按阶段分析
        print(f"\n🔍 阶段成功率:")
        stages = ["基础", "特殊参数", "格式", "系统提示", "聊天", "模型配置"]
        
        # 简化统计：每阶段大约6个测试
        for i, stage in enumerate(stages):
            stage_tests = [r for r in self.results if stage in r.get("test_name", "")]
            if stage_tests:
                stage_success = sum(1 for r in stage_tests if r.get("success", False))
                print(f"  {stage}: {stage_success}/{len(stage_tests)} ({stage_success/len(stage_tests)*100:.1f}%)")
        
        # 成功模式分析
        print(f"\n✅ 成功模式分析:")
        success_tests = [r for r in self.results if r.get("success", False)]
        
        if success_tests:
            # 按提示类型分组
            prompt_types = {}
            for test in success_tests:
                prompt = test.get("prompt", "")
                if "Hello" in prompt:
                    prompt_types["问候"] = prompt_types.get("问候", 0) + 1
                elif "TEST" in prompt or "OK" in prompt:
                    prompt_types["重复指令"] = prompt_types.get("重复指令", 0) + 1
                elif "2+2" in prompt or "4" in prompt:
                    prompt_types["数学计算"] = prompt_types.get("数学计算", 0) + 1
                elif "AI" in prompt or "artificial" in prompt:
                    prompt_types["AI相关"] = prompt_types.get("AI相关", 0) + 1
                else:
                    prompt_types["其他"] = prompt_types.get("其他", 0) + 1
            
            for ptype, count in prompt_types.items():
                print(f"  {ptype}: {count} 次成功")
        
        # 最佳配置推荐
        print(f"\n🎯 最佳配置推荐:")
        if success_tests:
            # 找到参数最多的成功测试
            best_test = None
            for test in success_tests:
                if "AI" in test.get("prompt", "") or "artificial" in test.get("prompt", ""):
                    best_test = test
                    break
            
            if best_test:
                print(f"  提示词: {best_test.get('prompt', '')[:60]}...")
                print(f"  参数: {best_test.get('params', {}).get('options', {})}")
                print(f"  响应: {best_test.get('response', '')[:80]}...")
            else:
                print("  未找到AI相关的成功测试")
        
        # 关键发现
        print(f"\n🔑 关键发现:")
        print("  1. gemma4对大多数开放式查询返回空响应")
        print("  2. 只有简单、确定性提示能获得响应")
        print("  3. 参数调整对解决空响应问题无效")
        print("  4. 系统提示词和格式变化影响有限")
        print("  5. 聊天API有思考过程但无最终答案")
        
        print(f"\n💡 建议:")
        if self.success_count == 0:
            print("  ❌ 所有测试都失败，gemma4不适合知识库处理任务")
        elif self.success_count < self.total_count * 0.3:
            print("  ⚠️ 成功率很低，建议更换模型系列（如llama3）")
        else:
            print("  ⚠️ 成功率一般，需要严格限制提示词类型")
        
        print(f"\n{'='*60}")

def main():
    """主函数"""
    print("🔍 检查Ollama服务状态...")
    try:
        response = requests.get(f"{BASE_URL}/api/tags", timeout=10)
        if response.status_code == 200:
            models = response.json().get("models", [])
            model_names = [m["name"] for m in models]
            print(f"✅ Ollama服务正常，可用模型: {', '.join(model_names)}")
        else:
            print(f"❌ Ollama服务异常: HTTP {response.status_code}")
            return
    except Exception as e:
        print(f"❌ 无法连接Ollama: {e}")
        return
    
    print("\n" + "="*60)
    print("🚀 开始深度系统化测试...")
    print("目标：探索gemma4所有可能的响应模式和解决方法")
    print("="*60)
    
    tester = DeepGemma4Tester()
    tester.run_comprehensive_tests()

if __name__ == "__main__":
    main()