#!/usr/bin/env python3
"""Karpathy 知识库 QA 质量验证套件。

目标：覆盖当前真实文档，验证检索、引用、答案可用性和关键词命中。
默认绕过 QA 缓存，避免新增内容后使用旧答案。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

KB_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KB_DIR / "scripts"))

from qa import KnowledgeBaseQA  # type: ignore

DEFAULT_CASES: List[Dict[str, Any]] = [
    {
        "id": "hotspot_site",
        "question": "AI热点网站是什么？它解决什么问题？",
        "expected_keywords": ["热点", "网站", "自媒体"],
        "expected_title_keywords": ["AI热点网站"],
    },
    {
        "id": "research_prompt",
        "question": "深度研究Prompt应该怎么用？",
        "expected_keywords": ["Prompt", "研究", "领域"],
        "expected_title_keywords": ["深度研究Prompt"],
    },
    {
        "id": "kimi_hermes",
        "question": "Kimi K2.6 和 Hermes 多 Agent 的六个技巧是什么？",
        "expected_keywords": ["Kimi", "Hermes", "Agent"],
        "expected_title_keywords": ["Kimi", "Hermes"],
    },
    {
        "id": "hermes_management",
        "question": "为什么说 Hermes 多 Agent 不是技术活而是管理活？",
        "expected_keywords": ["Hermes", "Agent", "管理"],
        "expected_title_keywords": ["Hermes", "管理活"],
    },
    {
        "id": "cc_switch",
        "question": "CC Switch 是什么？它如何解决模型切换问题？",
        "expected_keywords": ["CC Switch", "模型", "切换"],
        "expected_title_keywords": ["51K", "模型"],
    },
    {
        "id": "agent_os",
        "question": "Anthropic 的 Agent OS / Meta-Harness 思路是什么？",
        "expected_keywords": ["Anthropic", "Agent", "OS"],
        "expected_title_keywords": ["Anthropic", "Agent OS"],
    },
    {
        "id": "tcp_tuning",
        "question": "TCP 传输性能调优主要关注哪些机制？",
        "expected_keywords": ["TCP", "窗口", "重传"],
        "expected_title_keywords": ["TCP"],
    },
    {
        "id": "torchtpu",
        "question": "TorchTPU 是什么？它和 PyTorch/TPU 有什么关系？",
        "expected_keywords": ["TorchTPU", "PyTorch", "TPU"],
        "expected_title_keywords": ["TorchTPU"],
    },
]


def _contains_any(text: str, keywords: List[str]) -> bool:
    lower = (text or "").lower()
    return any(k.lower() in lower for k in keywords)


def evaluate_result(case: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
    answer = result.get("answer", "") or ""
    docs = result.get("documents", []) or []
    citations = result.get("citations", []) or []
    titles = "\n".join(d.get("title", "") for d in docs)

    checks = {
        "has_answer": len(answer.strip()) >= 80 and "抱歉" not in answer[:80],
        "has_documents": len(docs) > 0,
        "has_citations": bool(citations) or "[文档" in answer,
        "keyword_hit": _contains_any(answer, case.get("expected_keywords", [])),
        "title_hit": _contains_any(titles, case.get("expected_title_keywords", [])),
    }
    passed = all(checks.values())
    return {
        "id": case["id"],
        "question": case["question"],
        "passed": passed,
        "checks": checks,
        "latency": result.get("latency"),
        "answer_chars": len(answer),
        "documents": [{"title": d.get("title"), "score": d.get("score")} for d in docs],
        "citations": citations,
        "answer_preview": answer[:500],
    }


def run_suite(base_dir: Path, limit: int = 0, use_cache: bool = False) -> Dict[str, Any]:
    qa = KnowledgeBaseQA(base_dir)
    cases = DEFAULT_CASES[:limit] if limit and limit > 0 else DEFAULT_CASES
    results = []
    started = time.time()

    for i, case in enumerate(cases, 1):
        print(f"[{i}/{len(cases)}] {case['question']}", flush=True)
        result = qa.answer_question(case["question"], max_docs=4, use_cache=use_cache)
        evaluated = evaluate_result(case, result)
        results.append(evaluated)
        status = "✅" if evaluated["passed"] else "❌"
        print(f"  {status} {case['id']} latency={evaluated['latency']}s docs={len(evaluated['documents'])} chars={evaluated['answer_chars']}", flush=True)

    passed_count = sum(1 for r in results if r["passed"])
    report = {
        "status": "ok" if passed_count == len(results) else "warn",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "total": len(results),
        "passed": passed_count,
        "failed": len(results) - passed_count,
        "duration_seconds": round(time.time() - started, 2),
        "use_cache": use_cache,
        "results": results,
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Karpathy KB QA 质量验证")
    parser.add_argument("--base-dir", default=str(KB_DIR))
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--use-cache", action="store_true")
    parser.add_argument("--output", default=str(KB_DIR / "reports" / "qa-eval-latest.json"))
    args = parser.parse_args()

    report = run_suite(Path(args.base_dir).expanduser(), limit=args.limit, use_cache=args.use_cache)
    out = Path(args.output).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ["status", "total", "passed", "failed", "duration_seconds"]}, ensure_ascii=False, indent=2))
    print(f"Report: {out}")
    return 0 if report["failed"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
