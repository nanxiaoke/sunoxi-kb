#!/usr/bin/env python3
"""测试processor.py与gemma4的集成"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scripts.processor import DocumentProcessor
import logging

# 配置日志
logging.basicConfig(level=logging.INFO)

def test_processor():
    """测试处理器"""
    print("🔧 测试DocumentProcessor与gemma4的集成")
    print("="*60)
    
    processor = DocumentProcessor()
    
    # 测试文本
    test_text = """Artificial intelligence (AI) refers to the simulation of human intelligence in machines that are programmed to think and learn like humans. 
    The term may also be applied to any machine that exhibits traits associated with a human mind such as learning and problem-solving.
    
    Key areas of AI research include machine learning, natural language processing, computer vision, and robotics. 
    AI is being used in a wide variety of fields including healthcare, finance, transportation, and entertainment."""
    
    print(f"测试文本长度: {len(test_text)} 字符")
    print()
    
    # 测试1: 摘要
    print("📋 测试1: 摘要功能")
    print("-" * 40)
    summary = processor.summarize(test_text, max_length=100)
    if summary:
        print(f"✅ 摘要成功: {summary}")
    else:
        print("❌ 摘要失败")
    print()
    
    # 测试2: 关键点提取
    print("📋 测试2: 关键点提取")
    print("-" * 40)
    keypoints = processor.extract_keypoints(test_text, num_points=3)
    if keypoints:
        print(f"✅ 关键点提取成功:")
        print(keypoints)
    else:
        print("❌ 关键点提取失败")
    print()
    
    # 测试3: 分类
    print("📋 测试3: 分类功能")
    print("-" * 40)
    category = processor.categorize(test_text)
    if category:
        print(f"✅ 分类成功: {category}")
    else:
        print("❌ 分类失败")
    print()
    
    # 测试4: 实体提取
    print("📋 测试4: 实体提取")
    print("-" * 40)
    entities = processor.extract_entities(test_text)
    if entities:
        print(f"✅ 实体提取成功:")
        print(entities)
    else:
        print("❌ 实体提取失败")
    
    print()
    print("="*60)
    print("测试完成")

if __name__ == "__main__":
    test_processor()