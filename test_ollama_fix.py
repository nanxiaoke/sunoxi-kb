#!/usr/bin/env python3
"""
Ollama修复效果完整测试脚本
测试processor.py参数修复后的效果
"""

import sys
import os
import time
import json
import requests
from pathlib import Path

# 添加scripts目录到路径
sys.path.insert(0, str(Path.home() / 'karpathy-kb' / 'scripts'))

def test_basic_api():
    """测试基础API调用"""
    print("=" * 60)
    print("测试1: 基础API调用")
    print("=" * 60)
    
    tests = [
        {"name": "英文简单输入", "prompt": "Hello", "expected": True},
        {"name": "中文简单输入", "prompt": "你好", "expected": True},
        {"name": "中文问题", "prompt": "请用一句话回答：人工智能是什么？", "expected": True},
        {"name": "英文问题", "prompt": "What is artificial intelligence?", "expected": True},
    ]
    
    url = 'http://localhost:11434/api/generate'
    
    for test in tests:
        print(f"\n测试: {test['name']}")
        print(f"输入: {test['prompt']}")
        
        payload = {
            'model': 'gemma4:e4b',
            'prompt': test['prompt'],
            'stream': False,
            'options': {
                'temperature': 0.5,
                'top_p': 0.95,
                'num_predict': 200,
            }
        }
        
        start_time = time.time()
        try:
            response = requests.post(url, json=payload, timeout=30)
            elapsed = time.time() - start_time
            
            print(f"响应时间: {elapsed:.2f}秒")
            print(f"状态码: {response.status_code}")
            
            if response.status_code == 200:
                result = response.json()
                response_text = result.get('response', '').strip()
                done_reason = result.get('done_reason', '')
                
                if response_text:
                    print(f"✅ 成功: {response_text[:100]}...")
                    print(f"完成原因: {done_reason}")
                    print(f"生成长度: {len(response_text)}字符")
                else:
                    print(f"❌ 空响应 (完成原因: {done_reason})")
            else:
                print(f"❌ 错误: {response.text[:200]}")
                
        except Exception as e:
            print(f"❌ 异常: {e}")
            elapsed = time.time() - start_time
            print(f"耗时: {elapsed:.2f}秒")

def test_processor_client():
    """测试processor.py中的OllamaClient"""
    print("\n" + "=" * 60)
    print("测试2: processor.py OllamaClient")
    print("=" * 60)
    
    try:
        from processor import OllamaClient
        
        print("初始化OllamaClient...")
        client = OllamaClient()
        
        tests = [
            {"name": "英文生成", "prompt": "Hello", "options": {"think": False}},
            {"name": "中文生成", "prompt": "你好", "options": {"think": False}},
            {"name": "中文问题生成", "prompt": "请解释什么是机器学习", "options": {"think": False}},
        ]
        
        for test in tests:
            print(f"\n测试: {test['name']}")
            print(f"输入: {test['prompt']}")
            
            start_time = time.time()
            response = client.generate(test['prompt'], options=test['options'])
            elapsed = time.time() - start_time
            
            if response and response.strip():
                print(f"✅ 成功 (耗时: {elapsed:.2f}秒)")
                print(f"响应: {response[:100]}...")
                print(f"长度: {len(response)}字符")
            else:
                print(f"❌ 空响应 (耗时: {elapsed:.2f}秒)")
                
    except Exception as e:
        print(f"❌ 导入或初始化失败: {e}")
        import traceback
        traceback.print_exc()

def test_qa_system():
    """测试问答系统"""
    print("\n" + "=" * 60)
    print("测试3: 问答系统 (qa.py)")
    print("=" * 60)
    
    try:
        from qa import KnowledgeBaseQA
        from pathlib import Path
        
        base_dir = Path.home() / 'karpathy-kb'
        print(f"初始化问答系统 (基础目录: {base_dir})...")
        
        qa = KnowledgeBaseQA(base_dir)
        
        # 测试问题
        questions = [
            "什么是人工智能？",
            "横纵分析法是什么？",
            "机器学习的基本概念",
        ]
        
        for question in questions:
            print(f"\n测试问题: {question}")
            
            start_time = time.time()
            try:
                result = qa.answer_question(question, max_docs=2)
                elapsed = time.time() - start_time
                
                answer = result.get('answer', '')
                documents = result.get('documents', [])
                
                if answer and answer.strip():
                    print(f"✅ 成功 (耗时: {elapsed:.2f}秒)")
                    print(f"答案: {answer[:150]}...")
                    print(f"参考文档: {len(documents)}个")
                else:
                    print(f"❌ 空答案 (耗时: {elapsed:.2f}秒)")
                    
            except Exception as e:
                elapsed = time.time() - start_time
                print(f"❌ 异常 (耗时: {elapsed:.2f}秒): {e}")
                
    except Exception as e:
        print(f"❌ 导入或初始化失败: {e}")
        import traceback
        traceback.print_exc()

def test_document_processing():
    """测试文档处理"""
    print("\n" + "=" * 60)
    print("测试4: 文档处理 (processor.py)")
    print("=" * 60)
    
    try:
        from processor import process_document
        
        # 测试文档路径
        test_doc_path = Path.home() / 'karpathy-kb' / 'raw' / 'articles' / 'test_rag.md'
        
        if not test_doc_path.exists():
            print(f"❌ 测试文档不存在: {test_doc_path}")
            print("创建测试文档...")
            
            test_doc_path.parent.mkdir(parents=True, exist_ok=True)
            test_doc_path.write_text("""# 测试文档 - RAG技术

检索增强生成（RAG）是一种结合检索系统和生成式AI的技术。

## 核心优势
1. 基于事实信息生成回答
2. 可以访问最新信息
3. 答案可追溯来源
4. 减少模型幻觉

## 应用场景
- 知识库问答系统
- 文档摘要和解释
- 技术支持助手""")
            print(f"✅ 已创建测试文档: {test_doc_path}")
        
        print(f"处理测试文档: {test_doc_path}")
        
        start_time = time.time()
        try:
            # 调用processor.py的处理函数
            result = process_document(str(test_doc_path))
            elapsed = time.time() - start_time
            
            if result:
                print(f"✅ 文档处理成功 (耗时: {elapsed:.2f}秒)")
                print(f"处理结果: {result}")
            else:
                print(f"❌ 文档处理失败 (耗时: {elapsed:.2f}秒)")
                
        except Exception as e:
            elapsed = time.time() - start_time
            print(f"❌ 处理异常 (耗时: {elapsed:.2f}秒): {e}")
            import traceback
            traceback.print_exc()
            
    except Exception as e:
        print(f"❌ 导入失败: {e}")
        import traceback
        traceback.print_exc()

def test_edge_cases():
    """测试边缘情况"""
    print("\n" + "=" * 60)
    print("测试5: 边缘情况")
    print("=" * 60)
    
    url = 'http://localhost:11434/api/generate'
    
    edge_cases = [
        {"name": "空输入", "prompt": "", "expected": False},
        {"name": "超长输入", "prompt": "测试" * 1000, "expected": True},
        {"name": "特殊字符", "prompt": "Hello! @#$%^&*() 你好！", "expected": True},
        {"name": "混合语言", "prompt": "Hello 你好 Bonjour こんにちは", "expected": True},
    ]
    
    for case in edge_cases:
        print(f"\n测试: {case['name']}")
        print(f"输入长度: {len(case['prompt'])}字符")
        
        payload = {
            'model': 'gemma4:e4b',
            'prompt': case['prompt'],
            'stream': False,
            'options': {
                'temperature': 0.5,
                'top_p': 0.95,
                'num_predict': 100,
            }
        }
        
        start_time = time.time()
        try:
            response = requests.post(url, json=payload, timeout=30)
            elapsed = time.time() - start_time
            
            print(f"响应时间: {elapsed:.2f}秒")
            print(f"状态码: {response.status_code}")
            
            if response.status_code == 200:
                result = response.json()
                response_text = result.get('response', '').strip()
                
                if response_text:
                    print(f"✅ 成功: {response_text[:80]}...")
                else:
                    print(f"⚠️ 空响应 (可能正常)")
            else:
                print(f"❌ 错误: {response.text[:100]}")
                
        except Exception as e:
            print(f"❌ 异常: {e}")

def main():
    """主测试函数"""
    print("Ollama修复效果完整测试")
    print("开始时间:", time.strftime("%Y-%m-%d %H:%M:%S"))
    print()
    
    # 检查Ollama服务
    print("检查Ollama服务状态...")
    try:
        response = requests.get('http://localhost:11434/', timeout=5)
        if response.text.strip() == 'Ollama is running':
            print("✅ Ollama服务运行正常")
        else:
            print(f"⚠️ Ollama服务响应异常: {response.text}")
    except Exception as e:
        print(f"❌ 无法连接Ollama服务: {e}")
        print("请确保Ollama服务正在运行")
        return
    
    # 检查模型
    print("\n检查可用模型...")
    try:
        response = requests.get('http://localhost:11434/api/tags', timeout=10)
        if response.status_code == 200:
            models = response.json().get('models', [])
            model_names = [m['name'] for m in models]
            print(f"✅ 可用模型: {', '.join(model_names)}")
            
            if 'gemma4:e4b' in model_names:
                print("✅ 目标模型 gemma4:e4b 可用")
            else:
                print("❌ 目标模型 gemma4:e4b 不可用")
                return
        else:
            print(f"❌ 获取模型列表失败: {response.status_code}")
            return
    except Exception as e:
        print(f"❌ 获取模型列表异常: {e}")
        return
    
    print("\n" + "=" * 60)
    print("开始完整测试套件")
    print("=" * 60)
    
    # 执行测试
    test_basic_api()
    test_processor_client()
    test_qa_system()
    test_document_processing()
    test_edge_cases()
    
    print("\n" + "=" * 60)
    print("测试完成")
    print("结束时间:", time.strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 60)

if __name__ == '__main__':
    main()