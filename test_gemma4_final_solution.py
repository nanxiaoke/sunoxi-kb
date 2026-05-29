#!/usr/bin/env python3
"""验证gemma4最终解决方案"""

import requests
import time
import json

BASE_URL = "http://localhost:11434"

def test_gemma4_solution():
    """测试gemma4解决方案"""
    print("🔬 验证gemma4:e4b最终解决方案")
    print("="*60)
    
    test_cases = [
        # 测试1: 简单问候（基准）
        ("Hello", "generate", {"options": {"num_predict": 10}}, "简单问候"),
        
        # 测试2: 标准"What is AI?"（预期失败）
        ("What is AI?", "generate", {"options": {"num_predict": 30}}, "标准问题-生成API"),
        
        # 测试3: 聊天API - 无系统提示（预期失败）
        (
            "",
            "chat",
            {
                "messages": [{"role": "user", "content": "What is AI?"}],
                "options": {"num_predict": 30}
            },
            "聊天API-无系统提示"
        ),
        
        # 测试4: 聊天API - 禁用思考系统提示（预期成功）
        (
            "",
            "chat",
            {
                "messages": [
                    {"role": "system", "content": "Do not think. Just answer directly without showing your thinking process."},
                    {"role": "user", "content": "What is AI?"}
                ],
                "options": {"num_predict": 30}
            },
            "聊天API-禁用思考"
        ),
        
        # 测试5: 聊天API - 简洁指令系统提示（预期成功）
        (
            "",
            "chat",
            {
                "messages": [
                    {"role": "system", "content": "Provide direct answers without explanation or thinking."},
                    {"role": "user", "content": "What is AI?"}
                ],
                "options": {"num_predict": 30}
            },
            "聊天API-简洁指令"
        ),
        
        # 测试6: 知识库摘要任务（实际用例）
        (
            "",
            "chat",
            {
                "messages": [
                    {
                        "role": "system", 
                        "content": "Do not think. Just answer directly without showing your thinking process."
                    },
                    {
                        "role": "user",
                        "content": "Please summarize this text for a knowledge base. Text: Artificial intelligence is technology that enables machines to think and learn like humans. Please provide a clear summary in under 50 words."
                    }
                ],
                "options": {"num_predict": 50}
            },
            "摘要任务-禁用思考"
        ),
        
        # 测试7: 关键点提取任务（实际用例）
        (
            "",
            "chat",
            {
                "messages": [
                    {
                        "role": "system", 
                        "content": "Provide direct answers without explanation or thinking."
                    },
                    {
                        "role": "user",
                        "content": "Extract 3 key points from this text: Artificial intelligence (AI) refers to systems that can perform tasks typically requiring human intelligence. These include learning, reasoning, and problem-solving. AI is used in many fields including healthcare, finance, and transportation. Provide a numbered list starting with '1.'"
                    }
                ],
                "options": {"num_predict": 50}
            },
            "关键点提取-简洁指令"
        ),
        
        # 测试8: 分类任务（实际用例）
        (
            "",
            "chat",
            {
                "messages": [
                    {
                        "role": "system", 
                        "content": "Do not think. Just answer directly without showing your thinking process."
                    },
                    {
                        "role": "user",
                        "content": "Classify this document: technology, academic_paper, notes, code, article, news, tutorial, other. Document: This is a document about artificial intelligence and machine learning algorithms. Category:"
                    }
                ],
                "options": {"num_predict": 20}
            },
            "分类任务-禁用思考"
        ),
        
        # 测试9: 实体提取任务（实际用例）
        (
            "",
            "chat",
            {
                "messages": [
                    {
                        "role": "system", 
                        "content": "Provide direct answers without explanation or thinking."
                    },
                    {
                        "role": "user",
                        "content": "Extract named entities from: Artificial intelligence was developed by researchers at Stanford University and MIT. Entities:"
                    }
                ],
                "options": {"num_predict": 30}
            },
            "实体提取-简洁指令"
        ),
    ]
    
    results = []
    
    for prompt, endpoint, params, test_name in test_cases:
        print(f"\n🔍 测试: {test_name}")
        print(f"  方法: {endpoint}")
        
        url = f"{BASE_URL}/api/{endpoint}"
        
        if endpoint == "generate":
            payload = {
                "model": "gemma4:e4b",
                "prompt": prompt,
                "stream": False,
                **params
            }
        else:  # chat
            payload = {
                "model": "gemma4:e4b",
                "stream": False,
                **params
            }
        
        try:
            start_time = time.time()
            response = requests.post(url, json=payload, timeout=30)
            elapsed = time.time() - start_time
            
            if response.status_code == 200:
                result = response.json()
                
                if endpoint == "chat":
                    response_text = result.get("message", {}).get("content", "").strip()
                    thinking = result.get("message", {}).get("thinking", "")
                else:
                    response_text = result.get("response", "").strip()
                    thinking = ""
                
                success = bool(response_text)
                
                if success:
                    print(f"  ✅ 成功 ({elapsed:.1f}s)")
                    print(f"    响应: {response_text[:100]}...")
                else:
                    print(f"  ❌ 空响应 ({elapsed:.1f}s)")
                    if thinking:
                        print(f"    思考过程: {thinking[:100]}...")
                    print(f"    done_reason: {result.get('done_reason', 'unknown')}")
                    print(f"    eval_count: {result.get('eval_count', 0)}")
                
                results.append({
                    "test_name": test_name,
                    "success": success,
                    "response": response_text,
                    "thinking": thinking,
                    "elapsed": elapsed,
                    "done_reason": result.get("done_reason", ""),
                    "eval_count": result.get("eval_count", 0)
                })
            else:
                print(f"  ❌ HTTP错误: {response.status_code} ({elapsed:.1f}s)")
                results.append({
                    "test_name": test_name,
                    "success": False,
                    "error": f"HTTP {response.status_code}",
                    "elapsed": elapsed
                })
                
        except Exception as e:
            print(f"  ❌ 异常: {e}")
            results.append({
                "test_name": test_name,
                "success": False,
                "error": str(e)
            })
        
        time.sleep(2)
    
    # 分析结果
    print(f"\n{'='*60}")
    print("📊 结果分析")
    print("="*60)
    
    total = len(results)
    success = sum(1 for r in results if r["success"])
    
    print(f"总测试数: {total}")
    print(f"成功数: {success} ({success/total*100:.1f}%)")
    
    # 按测试类型分组
    print(f"\n🔍 详细结果:")
    for result in results:
        status = "✅" if result["success"] else "❌"
        print(f"  {status} {result['test_name']}: ", end="")
        if result["success"]:
            print(f"\"{result['response'][:60]}...\"")
        else:
            error = result.get("error", "空响应")
            print(f"{error}")
    
    # 关键发现
    print(f"\n🔑 关键发现:")
    
    # 检查"禁用思考"策略的成功率
    disable_thinking_tests = [r for r in results if "禁用思考" in r["test_name"]]
    if disable_thinking_tests:
        dt_success = sum(1 for r in disable_thinking_tests if r["success"])
        dt_total = len(disable_thinking_tests)
        print(f"  1. '禁用思考'策略成功率: {dt_success}/{dt_total} ({dt_success/dt_total*100:.1f}%)")
    
    # 检查"简洁指令"策略的成功率
    direct_answer_tests = [r for r in results if "简洁指令" in r["test_name"]]
    if direct_answer_tests:
        da_success = sum(1 for r in direct_answer_tests if r["success"])
        da_total = len(direct_answer_tests)
        print(f"  2. '简洁指令'策略成功率: {da_success}/{da_total} ({da_success/da_total*100:.1f}%)")
    
    # 检查标准问题失败率
    standard_tests = [r for r in results if "标准问题" in r["test_name"] or ("聊天API" in r["test_name"] and "无系统" in r["test_name"])]
    if standard_tests:
        st_failed = sum(1 for r in standard_tests if not r["success"])
        st_total = len(standard_tests)
        print(f"  3. 标准问题失败率: {st_failed}/{st_total} ({st_failed/st_total*100:.1f}%)")
    
    # 检查实际任务成功率
    task_tests = [r for r in results if any(task in r["test_name"] for task in ["摘要", "关键点", "分类", "实体"])]
    if task_tests:
        task_success = sum(1 for r in task_tests if r["success"])
        task_total = len(task_tests)
        print(f"  4. 知识库任务成功率: {task_success}/{task_total} ({task_success/task_total*100:.1f}%)")
    
    print(f"\n💡 解决方案有效性评估:")
    if success >= total * 0.7:
        print("  ✅ 解决方案有效！gemma4在添加'禁用思考'系统提示后能正常工作")
    elif success >= total * 0.4:
        print("  ⚠️ 解决方案部分有效，需要进一步优化系统提示词")
    else:
        print("  ❌ 解决方案效果有限，可能需要更换模型")
    
    print(f"\n🎯 对processor.py的修改验证:")
    
    # 检查processor.py是否已经包含这些策略
    try:
        with open("/home/sunoxi/karpathy-kb/scripts/processor.py", "r", encoding="utf-8") as f:
            content = f.read()
            
        if "Do not think. Just answer directly" in content:
            print("  ✅ processor.py已包含'禁用思考'策略")
        else:
            print("  ❌ processor.py未包含'禁用思考'策略")
            
        if "Provide direct answers without explanation" in content:
            print("  ✅ processor.py已包含'简洁指令'策略")
        else:
            print("  ❌ processor.py未包含'简洁指令'策略")
            
    except Exception as e:
        print(f"  ⚠️ 无法检查processor.py: {e}")
    
    print(f"\n{'='*60}")

def test_processor_integration():
    """测试处理器集成"""
    print("\n🔧 测试处理器集成验证")
    print("="*60)
    
    # 模拟processor.py中的方法
    def test_summary():
        """测试摘要功能"""
        print("🔍 测试摘要功能...")
        
        url = f"{BASE_URL}/api/chat"
        payload = {
            "model": "gemma4:e4b",
            "messages": [
                {
                    "role": "system",
                    "content": "Do not think. Just answer directly without showing your thinking process."
                },
                {
                    "role": "user",
                    "content": "Please summarize this text for a knowledge base. Text: Artificial intelligence is technology that enables machines to think and learn like humans. It includes machine learning, natural language processing, and computer vision. AI is transforming many industries. Please provide a clear summary in under 50 words.\n\nSummary:"
                }
            ],
            "stream": False,
            "options": {"num_predict": 100}
        }
        
        try:
            response = requests.post(url, json=payload, timeout=30)
            if response.status_code == 200:
                result = response.json()
                content = result.get("message", {}).get("content", "").strip()
                if content:
                    print(f"  ✅ 摘要成功: {content[:100]}...")
                    return True
                else:
                    print(f"  ❌ 摘要失败: 空响应")
                    return False
            else:
                print(f"  ❌ HTTP错误: {response.status_code}")
                return False
        except Exception as e:
            print(f"  ❌ 异常: {e}")
            return False
    
    def test_categorization():
        """测试分类功能"""
        print("🔍 测试分类功能...")
        
        url = f"{BASE_URL}/api/chat"
        payload = {
            "model": "gemma4:e4b",
            "messages": [
                {
                    "role": "system",
                    "content": "Provide direct answers without explanation or thinking."
                },
                {
                    "role": "user",
                    "content": "Classify this document: technology, academic_paper, notes, code, article, news, tutorial, other. Document: This document explains machine learning algorithms and their applications in healthcare.\n\nCategory:"
                }
            ],
            "stream": False,
            "options": {"num_predict": 30}
        }
        
        try:
            response = requests.post(url, json=payload, timeout=30)
            if response.status_code == 200:
                result = response.json()
                content = result.get("message", {}).get("content", "").strip()
                if content:
                    print(f"  ✅ 分类成功: {content}")
                    return True
                else:
                    print(f"  ❌ 分类失败: 空响应")
                    return False
            else:
                print(f"  ❌ HTTP错误: {response.status_code}")
                return False
        except Exception as e:
            print(f"  ❌ 异常: {e}")
            return False
    
    # 运行测试
    summary_success = test_summary()
    time.sleep(2)
    category_success = test_categorization()
    
    print(f"\n📊 集成测试结果:")
    print(f"  摘要: {'✅' if summary_success else '❌'}")
    print(f"  分类: {'✅' if category_success else '❌'}")
    
    if summary_success and category_success:
        print(f"\n🎉 集成测试通过！processor.py可以正常使用gemma4")
    else:
        print(f"\n⚠️ 集成测试失败，需要进一步调试")

if __name__ == "__main__":
    # 检查Ollama服务
    print("🔍 检查Ollama服务状态...")
    try:
        response = requests.get(f"{BASE_URL}/api/tags", timeout=5)
        if response.status_code == 200:
            print("✅ Ollama服务正常")
        else:
            print(f"❌ Ollama服务异常: HTTP {response.status_code}")
            exit(1)
    except Exception as e:
        print(f"❌ 无法连接Ollama: {e}")
        exit(1)
    
    # 运行主测试
    test_gemma4_solution()
    
    # 运行集成测试
    test_processor_integration()
    
    print(f"\n{'='*60}")
    print("🚀 测试完成")
    print("="*60)