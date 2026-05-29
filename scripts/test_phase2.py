#!/usr/bin/env python3
"""Karpathy知识库第二阶段验证测试"""
import sys, logging
from pathlib import Path
sys.path.insert(0, str(Path.home() / "karpathy-kb" / "scripts"))
from qa import KnowledgeBaseQA

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

qa = KnowledgeBaseQA(Path.home() / "karpathy-kb")
sep = "=" * 60

questions = [
    "RAG技术的工作原理是什么？",
    "Ollama有什么功能？",
    "人工智能的核心技术有哪些？",
]

for q in questions:
    print(f"\n{sep}")
    print(f"❓ {q}")
    print(sep)
    result = qa.answer_question(q, max_docs=3)
    answer = result["answer"]
    # Limit to 600 chars for display
    if len(answer) > 600:
        print(answer[:600] + "...")
    else:
        print(answer)
    print(f"\n参考文档: {len(result['documents'])}")
    for d in result["documents"]:
        print(f"  - {d['title']} (score: {d['score']:.1f})")

print(f"\n{sep}")
print(f"✅ 第二阶段验证完成")
print(sep)
