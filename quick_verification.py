#!/usr/bin/env python3
"""快速验证gemma4修复"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scripts.processor import DocumentProcessor
import logging

logging.basicConfig(level=logging.INFO)

def quick_test():
    """快速测试"""
    print("🔧 快速验证gemma4修复")
    print("="*60)
    
    processor = DocumentProcessor()
    
    # 简短测试文本
    test_text = "Artificial intelligence is technology that enables machines to think and learn like humans."
    
    print(f"测试文本: {test_text}")
    print()
    
    # 测试摘要
    print("📋 测试摘要功能...")
    summary = processor.summarize(test_text, max_length=50)
    if summary:
        print(f"✅ 摘要成功: {summary}")
    else:
        print("❌ 摘要失败")
    print()
    
    # 测试分类
    print("📋 测试分类功能...")
    category = processor.categorize(test_text)
    if category:
        print(f"✅ 分类成功: {category}")
    else:
        print("❌ 分类失败")
    
    print()
    print("="*60)
    print("验证完成")

if __name__ == "__main__":
    quick_test()