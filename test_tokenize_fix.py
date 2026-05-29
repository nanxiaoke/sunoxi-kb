#!/usr/bin/env python3
"""
测试分词修复
"""

import re

def tokenize_old(text: str):
    """旧的分词函数"""
    if not text:
        return []
    
    words = []
    for word in re.findall(r'[a-zA-Z]{2,}|[\u4e00-\u9fff]|[^\s\w]', text):
        word_lower = word.lower()
        if word_lower:
            words.append(word_lower)
    
    return words

def tokenize_new(text: str):
    """新的分词函数"""
    if not text:
        return []
    
    # 停用词（简化）
    stop_words = set(["的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都"])
    
    words = []
    for word in re.findall(r'[a-zA-Z]{2,}|[\u4e00-\u9fff]{2,}|[^\s\w]', text):
        word_lower = word.lower()
        # 过滤停用词和单个字符（除了英文单词）
        if word_lower and word_lower not in stop_words:
            # 过滤掉单个字符的中文（除非是英文单词）
            if len(word) == 1 and '\u4e00' <= word <= '\u9fff':
                continue
            words.append(word_lower)
    
    return words

# 测试用例
test_cases = [
    "横纵分析法",
    "横纵分析法是什么？",
    "人工智能简介",
    "AI和机器学习",
    "自然语言处理(NLP)是什么？",
    "这篇文档介绍了横纵分析法",
    "ChatGPT和DeepSeek都是AI模型",
]

print("🔧 分词函数测试")
print("="*60)

for test in test_cases:
    old = tokenize_old(test)
    new = tokenize_new(test)
    print(f"\n输入: {test}")
    print(f"旧分词: {old}")
    print(f"新分词: {new}")

print("\n" + "="*60)
print("✅ 测试完成")