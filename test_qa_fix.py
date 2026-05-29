#!/usr/bin/env python3
"""
测试qa.py修复效果
"""

import sys
import time
from pathlib import Path

# 添加scripts目录到路径
sys.path.insert(0, str(Path.home() / 'karpathy-kb' / 'scripts'))

def test_qa_initialization():
    """测试问答系统初始化"""
    print("=" * 60)
    print("测试1: 问答系统初始化")
    print("=" * 60)
    
    try:
        from qa import KnowledgeBaseQA
        
        base_dir = Path.home() / 'karpathy-kb'
        print(f"初始化问答系统 (基础目录: {base_dir})...")
        
        start_time = time.time()
        qa = KnowledgeBaseQA(base_dir)
        elapsed = time.time() - start_time
        
        print(f"✅ 问答系统初始化成功 (耗时: {elapsed:.2f}秒)")
        return qa
    except Exception as e:
        print(f"❌ 问答系统初始化失败: {e}")
        import traceback
        traceback.print_exc()
        return None

def test_simple_question(qa):
    """测试简单问题"""
    print("\n" + "=" * 60)
    print("测试2: 简单问题回答")
    print("=" * 60)
    
    questions = [
        "什么是人工智能？",
        "横纵分析法是什么？",
        "机器学习的基本概念",
    ]
    
    for question in questions:
        print(f"\n测试问题: {question}")
        
        start_time = time.time()
        try:
            result = qa.answer_question(question, max_docs=1)
            elapsed = time.time() - start_time
            
            answer = result.get('answer', '')
            documents = result.get('documents', [])
            
            if answer and answer.strip():
                print(f"✅ 成功 (耗时: {elapsed:.2f}秒)")
                print(f"答案长度: {len(answer)}字符")
                print(f"答案预览: {answer[:150]}...")
                print(f"参考文档: {len(documents)}个")
                
                # 检查是否包含引用
                if '[文档' in answer:
                    print("✅ 答案包含文档引用")
                else:
                    print("⚠️ 答案不包含文档引用")
            else:
                print(f"❌ 空答案 (耗时: {elapsed:.2f}秒)")
                
        except Exception as e:
            elapsed = time.time() - start_time
            print(f"❌ 异常 (耗时: {elapsed:.2f}秒): {e}")

def test_complex_question(qa):
    """测试复杂问题"""
    print("\n" + "=" * 60)
    print("测试3: 复杂问题回答")
    print("=" * 60)
    
    complex_questions = [
        "请解释人工智能的发展历史",
        "比较机器学习和深度学习的区别",
        "什么是神经网络？它如何工作？",
    ]
    
    for question in complex_questions:
        print(f"\n测试问题: {question}")
        
        start_time = time.time()
        try:
            result = qa.answer_question(question, max_docs=2)
            elapsed = time.time() - start_time
            
            answer = result.get('answer', '')
            
            if answer and answer.strip():
                print(f"✅ 成功 (耗时: {elapsed:.2f}秒)")
                print(f"答案长度: {len(answer)}字符")
                print(f"答案预览: {answer[:100]}...")
            else:
                print(f"❌ 空答案 (耗时: {elapsed:.2f}秒)")
                
        except Exception as e:
            elapsed = time.time() - start_time
            print(f"❌ 异常 (耗时: {elapsed:.2f}秒): {e}")

def test_error_handling(qa):
    """测试错误处理"""
    print("\n" + "=" * 60)
    print("测试4: 错误处理")
    print("=" * 60)
    
    # 测试空问题
    print("\n测试空问题...")
    result = qa.answer_question("", max_docs=1)
    answer = result.get('answer', '')
    if answer and "抱歉" in answer:
        print("✅ 空问题处理正常")
    else:
        print("⚠️ 空问题处理可能有问题")
    
    # 测试无意义问题
    print("\n测试无意义问题...")
    result = qa.answer_question("asdfghjkl123456", max_docs=1)
    answer = result.get('answer', '')
    if answer:
        print(f"✅ 无意义问题有响应: {answer[:50]}...")
    else:
        print("❌ 无意义问题无响应")

def main():
    """主测试函数"""
    print("qa.py修复效果测试")
    print("开始时间:", time.strftime("%Y-%m-%d %H:%M:%S"))
    print()
    
    # 测试初始化
    qa = test_qa_initialization()
    if not qa:
        print("\n❌ 初始化失败，无法继续测试")
        return
    
    # 执行测试
    test_simple_question(qa)
    test_complex_question(qa)
    test_error_handling(qa)
    
    print("\n" + "=" * 60)
    print("测试完成")
    print("结束时间:", time.strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 60)

if __name__ == '__main__':
    main()