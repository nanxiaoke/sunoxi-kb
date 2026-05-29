#!/usr/bin/env python3
"""
简单测试优化效果
"""

import time
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

def main():
    print("🧪 简单优化测试")
    
    try:
        from processor import OllamaClient
        
        # 测试1: 初始化Ollama
        print("1. 初始化OllamaClient...")
        start = time.time()
        ollama = OllamaClient(model="gemma4:e4b")
        init_time = time.time() - start
        print(f"   ✅ 初始化时间: {init_time:.2f}秒")
        print(f"   ✅ 当前模型: {ollama.model}")
        
        # 测试2: 简单聊天
        print("2. 简单聊天测试...")
        messages = [
            {"role": "system", "content": "请用中文简短回答。"},
            {"role": "user", "content": "人工智能是什么？"}
        ]
        
        start = time.time()
        response = ollama.chat(messages, options={"think": False})
        chat_time = time.time() - start
        
        if response:
            print(f"   ✅ 响应时间: {chat_time:.2f}秒")
            print(f"   ✅ 响应长度: {len(response)} 字符")
            print(f"   📝 响应预览: {response[:100]}...")
        else:
            print("   ❌ 空响应")
        
        # 测试3: 搜索功能
        print("3. 测试搜索功能...")
        from search import WikiSearcher
        
        searcher = WikiSearcher(Path.home() / "karpathy-kb")
        searcher.build_index(rebuild=False)
        
        start = time.time()
        results = searcher.search("横纵分析法", search_type='fulltext', limit=3)
        search_time = time.time() - start
        
        print(f"   ✅ 搜索时间: {search_time:.2f}秒")
        print(f"   ✅ 找到结果: {len(results)} 个")
        
        if results:
            for i, r in enumerate(results, 1):
                print(f"   📄 结果{i}: {r.get('title', '无标题')} - 分数: {r.get('score', 0):.2f}")
        
        print("\n✅ 测试完成！")
        return True
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    main()