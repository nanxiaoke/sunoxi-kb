#!/usr/bin/env python3
"""
测试优化效果
"""

import time
import sys
import signal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

class TimeoutException(Exception):
    pass

def timeout_handler(signum, frame):
    raise TimeoutException("测试超时")

def test_qa_with_timeout():
    """测试问答系统（带超时）"""
    print("🧪 测试优化后的问答系统...")
    
    from qa import KnowledgeBaseQA
    
    # 设置超时（45秒）
    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(45)
    
    try:
        base_dir = Path.home() / "karpathy-kb"
        qa = KnowledgeBaseQA(base_dir)
        
        # 测试问题
        question = "横纵分析法是什么？"
        print(f"  问题: {question}")
        
        # 测试搜索部分
        start = time.time()
        documents = qa.search_relevant_documents(question, max_docs=2)
        search_time = time.time() - start
        print(f"  ✅ 搜索完成: {search_time:.2f}秒, {len(documents)} 个文档")
        
        if documents:
            # 提取上下文
            context = qa.extract_context_from_documents(documents)
            print(f"  ✅ 上下文长度: {len(context)} 字符")
            
            # 生成答案（可能耗时）
            print("  ⏳ 生成答案...")
            start = time.time()
            answer, citations = qa.generate_answer(question, context, documents)
            answer_time = time.time() - start
            
            print(f"  ✅ 答案生成: {answer_time:.2f}秒")
            print(f"  ✅ 答案长度: {len(answer)} 字符")
            print(f"  ✅ 引用数量: {len(citations)} 个")
            
            # 显示答案预览
            preview = answer[:200] + "..." if len(answer) > 200 else answer
            print(f"  📝 答案预览: {preview}")
            
            return True
        else:
            print("  ⚠️ 未找到相关文档")
            return False
            
    except TimeoutException as e:
        print(f"  ❌ 测试超时: {e}")
        return False
    except Exception as e:
        print(f"  ❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        signal.alarm(0)  # 取消定时器

def test_simple_ollama():
    """测试简单Ollama调用"""
    print("\n🤖 测试简单Ollama调用...")
    
    from processor import OllamaClient
    
    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(30)
    
    try:
        start = time.time()
        ollama = OllamaClient(model="gemma4:e4b")
        init_time = time.time() - start
        print(f"  ✅ 初始化: {init_time:.2f}秒")
        
        # 简单聊天测试
        messages = [
            {"role": "system", "content": "请用中文简短回答。"},
            {"role": "user", "content": "人工智能是什么？"}
        ]
        
        print("  ⏳ 发送简单消息...")
        start = time.time()
        response = ollama.chat(messages, options={"think": False})
        chat_time = time.time() - start
        
        if response:
            print(f"  ✅ 响应时间: {chat_time:.2f}秒")
            print(f"  ✅ 响应长度: {len(response)} 字符")
            print(f"  📝 响应预览: {response[:100]}...")
            return True
        else:
            print("  ❌ 空响应")
            return False
            
    except TimeoutException as e:
        print(f"  ❌ 测试超时: {e}")
        return False
    except Exception as e:
        print(f"  ❌ 测试失败: {e}")
        return False
    finally:
        signal.alarm(0)

def main():
    print("=" * 60)
    print("🧪 Karpathy知识库优化测试")
    print("=" * 60)
    
    success_count = 0
    total_tests = 2
    
    # 测试1: 简单Ollama调用
    if test_simple_ollama():
        success_count += 1
    
    print("\n" + "-" * 60)
    
    # 测试2: 问答系统
    if test_qa_with_timeout():
        success_count += 1
    
    print("\n" + "=" * 60)
    print(f"测试结果: {success_count}/{total_tests} 通过")
    
    if success_count == total_tests:
        print("✅ 所有测试通过！优化似乎有效。")
    else:
        print("⚠️  部分测试失败，需要进一步优化。")
    
    print("=" * 60)

if __name__ == "__main__":
    main()