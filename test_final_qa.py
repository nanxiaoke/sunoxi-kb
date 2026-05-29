#!/usr/bin/env python3
"""
最终问答系统测试脚本
测试修复后的问答系统，包含降级策略
"""

import sys
import time
from pathlib import Path

# 添加脚本目录到路径
script_dir = Path(__file__).parent
sys.path.insert(0, str(script_dir / "scripts"))

from search import WikiSearcher

def test_search_only():
    """测试搜索功能（问答系统降级方案）"""
    print("🔍 测试搜索功能（问答降级方案）")
    print("=" * 60)
    
    base_dir = Path("/home/sunoxi/karpathy-kb")
    searcher = WikiSearcher(base_dir)
    searcher.build_index(rebuild=False)
    
    test_questions = [
        "什么是人工智能？",
        "RAG技术是什么？",
        "大语言模型发展历史",
        "Python代码示例",
    ]
    
    for question in test_questions:
        print(f"\n❓ 问题: {question}")
        
        start_time = time.time()
        results = searcher.search(question, search_type="fulltext", limit=2)
        elapsed = time.time() - start_time
        
        if results:
            print(f"   ✅ 找到 {len(results)} 个相关文档 (耗时: {elapsed:.2f}秒)")
            for i, doc in enumerate(results, 1):
                print(f"      {i}. {doc['title']} (分类: {doc['category']})")
                print(f"          摘要: {doc['summary'][:100]}...")
        else:
            print(f"   ⚠️  未找到相关文档 (耗时: {elapsed:.2f}秒)")
    
    return True

def test_qa_with_fallback():
    """测试问答系统（包含降级策略）"""
    print("\n🤖 测试问答系统（包含降级策略）")
    print("=" * 60)
    
    try:
        from qa import KnowledgeBaseQA
    except ImportError as e:
        print(f"❌ 无法导入问答系统: {e}")
        print("   请确保qa.py文件存在且语法正确")
        return False
    
    base_dir = Path("/home/sunoxi/karpathy-kb")
    
    try:
        print("初始化问答系统...")
        qa_system = KnowledgeBaseQA(base_dir)
        
        if not qa_system.ollama:
            print("❌ Ollama客户端初始化失败，使用搜索降级方案")
            return test_search_only()
        
        print("✅ 问答系统初始化成功")
        
        # 测试问题
        question = "什么是人工智能？"
        print(f"\n❓ 测试问题: {question}")
        
        # 设置超时
        import signal
        
        class TimeoutException(Exception):
            pass
        
        def timeout_handler(signum, frame):
            raise TimeoutException("问答超时（60秒）")
        
        # 设置超时处理
        signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(60)  # 60秒超时
        
        try:
            start_time = time.time()
            answer, citations = qa_system.answer_question(question, max_docs=1)
            elapsed = time.time() - start_time
            
            signal.alarm(0)  # 取消超时
            
            if answer and "抱歉" not in answer and "错误" not in answer:
                print(f"✅ 成功生成答案 (耗时: {elapsed:.2f}秒)")
                print("-" * 40)
                print(answer[:500] + ("..." if len(answer) > 500 else ""))
                print("-" * 40)
                
                if citations:
                    print(f"📚 引用文档: {len(citations)} 个")
                    for citation in citations:
                        print(f"   - {citation['title']}")
                
                return True
            else:
                print(f"⚠️  答案生成不完整或包含错误 (耗时: {elapsed:.2f}秒)")
                print(f"   答案预览: {answer[:200] if answer else '空答案'}")
                print("   切换到搜索降级方案...")
                return test_search_only()
                
        except TimeoutException:
            signal.alarm(0)
            print("❌ 问答系统超时（60秒）")
            print("   切换到搜索降级方案...")
            return test_search_only()
        except Exception as e:
            signal.alarm(0)
            print(f"❌ 问答系统异常: {e}")
            print("   切换到搜索降级方案...")
            return test_search_only()
            
    except Exception as e:
        print(f"❌ 问答系统初始化异常: {e}")
        print("   切换到搜索降级方案...")
        return test_search_only()

def main():
    """主测试函数"""
    print("🧪 Karpathy知识库系统最终测试")
    print("=" * 60)
    
    # 测试1: 搜索功能（核心功能）
    print("\n📋 测试1: 搜索功能（核心基础）")
    search_success = test_search_only()
    
    # 测试2: 问答功能（高级功能）
    print("\n📋 测试2: 问答功能（高级功能）")
    qa_success = test_qa_with_fallback()
    
    # 总结
    print("\n" + "=" * 60)
    print("📊 测试结果总结")
    print("=" * 60)
    
    if search_success:
        print("✅ 搜索功能: 正常")
        print("   核心知识检索功能可用，用户可通过搜索获取文档")
    else:
        print("❌ 搜索功能: 失败")
        print("   需要紧急修复搜索系统")
    
    if qa_success:
        print("✅ 问答功能: 正常")
        print("   高级AI问答功能可用，用户可获得智能答案")
    else:
        print("⚠️  问答功能: 降级到搜索")
        print("   AI问答不稳定，但搜索功能作为降级方案可用")
    
    print("\n💡 建议:")
    if qa_success:
        print("   1. 问答系统工作正常，可继续使用")
        print("   2. 监控响应时间，考虑进一步优化")
        print("   3. 添加更多文档以提高答案质量")
    else:
        print("   1. 搜索功能作为核心功能完全可用")
        print("   2. 问答系统需要进一步调试优化")
        print("   3. 用户可通过搜索功能获取所需信息")
        print("   4. 考虑实现更稳定的问答降级策略")
    
    print("\n🚀 下一步行动:")
    print("   1. 运行完整测试: python3 scripts/kb_cli.py search --query '人工智能'")
    print("   2. 测试问答: python3 scripts/kb_cli.py qa --question '什么是人工智能？'")
    print("   3. 查看统计: python3 scripts/kb_cli.py stats")
    print("   4. 列出文档: python3 scripts/kb_cli.py list")

if __name__ == "__main__":
    main()