#!/usr/bin/env python3
"""
Karpathy知识库维护流水线

把知识库的日常维护固化为一个可重复执行的功能：
1. 重建 wiki 交叉链接/分类索引
2. lint 检查坏链与孤立页
3. 重建搜索索引
4. 更新语义向量嵌入（可选）
5. 输出 JSON 维护报告

用法：
  python3 scripts/maintenance.py
  python3 scripts/maintenance.py --no-embeddings
  python3 scripts/maintenance.py --json
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


class KBMaintenance:
    def __init__(self, base_dir: Path, *, update_embeddings: bool = False, ollama_model: str = "gemma4:e4b", ollama_host: str = "http://127.0.0.1:11434"):
        self.base_dir = base_dir.resolve()
        self.scripts_dir = self.base_dir / "scripts"
        self.update_embeddings = update_embeddings
        self.ollama_model = ollama_model
        self.ollama_host = ollama_host.rstrip("/")
        self.started_at = datetime.now(timezone.utc)
        self.report: Dict[str, Any] = {
            "started_at": self.started_at.isoformat(),
            "base_dir": str(self.base_dir),
            "steps": [],
            "summary": {},
            "status": "running",
        }

    def _run_cmd(self, name: str, cmd: List[str], timeout: int = 300) -> Dict[str, Any]:
        t0 = time.time()
        step = {
            "name": name,
            "cmd": cmd,
            "status": "running",
            "duration_sec": None,
            "returncode": None,
            "stdout_tail": "",
            "stderr_tail": "",
        }
        self.report["steps"].append(step)
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(self.base_dir),
                text=True,
                capture_output=True,
                timeout=timeout,
            )
            step["returncode"] = proc.returncode
            step["status"] = "ok" if proc.returncode == 0 else "failed"
            step["stdout_tail"] = proc.stdout[-4000:]
            step["stderr_tail"] = proc.stderr[-4000:]
        except subprocess.TimeoutExpired as e:
            step["status"] = "timeout"
            step["returncode"] = None
            step["stdout_tail"] = (e.stdout or "")[-4000:] if isinstance(e.stdout, str) else ""
            step["stderr_tail"] = (e.stderr or "")[-4000:] if isinstance(e.stderr, str) else ""
        except Exception as e:
            step["status"] = "error"
            step["stderr_tail"] = str(e)
        finally:
            step["duration_sec"] = round(time.time() - t0, 2)
        return step

    def _lint_structured(self) -> Dict[str, Any]:
        sys.path.insert(0, str(self.scripts_dir))
        from linter import KBLinter  # type: ignore

        linter = KBLinter(self.base_dir)
        linter._collect_files()
        linter._scan_links()
        linter._analyze()
        orphans = []
        for rel_path, sources in linter.incoming.items():
            if "INDEX" in rel_path or "DOCUMENTS" in rel_path or rel_path.startswith("category_"):
                continue
            if len(sources) == 0:
                orphans.append(rel_path)
        return {
            "files": len(linter.files),
            "internal_links": len(linter.links),
            "broken_links": len(linter.broken_links),
            "orphans": len(orphans),
            "broken_link_items": linter.broken_links,
            "orphan_items": orphans,
        }

    def _doc_counts(self) -> Dict[str, Any]:
        wiki_dir = self.base_dir / "wiki"
        raw_dir = self.base_dir / "raw"
        wiki_files = list(wiki_dir.rglob("*.md")) if wiki_dir.exists() else []
        real_docs = [
            p for p in wiki_files
            if not p.name.startswith("category_") and p.name not in {"00_INDEX.md", "DOCUMENTS.md"}
        ]
        raw_files = [p for p in raw_dir.rglob("*") if p.is_file()] if raw_dir.exists() else []
        return {
            "wiki_files": len(wiki_files),
            "real_wiki_docs": len(real_docs),
            "raw_files": len(raw_files),
        }


    def _check_ollama_model(self) -> Dict[str, Any]:
        """Check local Ollama/Gemma4 availability without calling external providers."""
        payload = json.dumps({
            "model": self.ollama_model,
            "prompt": "只回复OK",
            "stream": False,
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{self.ollama_host}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        t0 = time.time()
        with urllib.request.urlopen(req, timeout=45) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return {
            "provider": "ollama",
            "model": self.ollama_model,
            "status": "ok" if data.get("done") else "warn",
            "response_preview": str(data.get("response", ""))[:80],
            "duration_sec": round(time.time() - t0, 2),
        }

    def _update_embeddings(self) -> Dict[str, Any]:
        sys.path.insert(0, str(self.scripts_dir))
        from search import WikiSearcher  # type: ignore
        from embeddings import EmbeddingEngine  # type: ignore

        searcher = WikiSearcher(self.base_dir)
        searcher.build_index(rebuild=False)
        embedder = EmbeddingEngine(self.base_dir)
        count = embedder.build_all(searcher)
        return {
            "embedded_documents": count,
            "dimension": getattr(embedder, "dimension", 0),
            "mapping_file": str(self.base_dir / "embeddings_map.json"),
            "vectors_file": str(self.base_dir / "embeddings.npy"),
        }

    def run(self) -> Dict[str, Any]:
        py = sys.executable or "python3"

        self.report["summary"].update(self._doc_counts())

        t0 = time.time()
        model_step = {"name": "local_ollama_model_check", "status": "running", "duration_sec": None}
        self.report["steps"].append(model_step)
        try:
            model_report = self._check_ollama_model()
            model_step["status"] = model_report.get("status", "ok")
            model_step["result"] = model_report
            self.report["summary"]["model"] = model_report
        except Exception as e:
            model_step["status"] = "failed"
            model_step["error"] = str(e)
            self.report["summary"]["model"] = {"provider": "ollama", "model": self.ollama_model, "status": "failed", "error": str(e)}
        finally:
            model_step["duration_sec"] = round(time.time() - t0, 2)

        self._run_cmd(
            "wiki_linker_rebuild",
            [py, str(self.scripts_dir / "wiki_linker.py"), "--rebuild", "--base-dir", str(self.base_dir)],
            timeout=300,
        )

        lint_step = self._run_cmd(
            "lint",
            [py, str(self.scripts_dir / "kb_cli.py"), "lint", "--base-dir", str(self.base_dir)],
            timeout=120,
        )
        try:
            lint_report = self._lint_structured()
        except Exception as e:
            lint_report = {"error": str(e)}
        self.report["summary"]["lint"] = lint_report

        self._run_cmd(
            "search_reindex",
            [py, str(self.scripts_dir / "kb_cli.py"), "reindex", "--base-dir", str(self.base_dir)],
            timeout=300,
        )

        assoc_step = self._run_cmd(
            "association_report",
            [py, str(self.scripts_dir / "association_report.py"), "--base-dir", str(self.base_dir)],
            timeout=120,
        )
        assoc_path = self.base_dir / "reports" / "knowledge-associations-latest.json"
        if assoc_path.exists():
            try:
                assoc_report = json.loads(assoc_path.read_text(encoding="utf-8"))
                self.report["summary"]["associations"] = assoc_report.get("summary", {})
            except Exception as e:
                self.report["summary"]["associations"] = {"error": str(e)}
        elif assoc_step.get("status") != "ok":
            self.report["summary"]["associations"] = {"error": assoc_step.get("stderr_tail") or assoc_step.get("stdout_tail") or "association report failed"}

        if self.update_embeddings:
            t0 = time.time()
            step = {"name": "embeddings_rebuild", "status": "running", "duration_sec": None}
            self.report["steps"].append(step)
            try:
                embed_report = self._update_embeddings()
                step["status"] = "ok"
                step["result"] = embed_report
                self.report["summary"]["embeddings"] = embed_report
            except Exception as e:
                step["status"] = "failed"
                step["error"] = str(e)
                self.report["summary"]["embeddings"] = {"error": str(e)}
            finally:
                step["duration_sec"] = round(time.time() - t0, 2)
        else:
            self.report["summary"]["embeddings"] = {"skipped": True}

        self.report["summary"].update(self._doc_counts())
        failed = [s for s in self.report["steps"] if s.get("status") not in {"ok"}]
        broken = self.report["summary"].get("lint", {}).get("broken_links", 0)
        self.report["status"] = "ok" if not failed and broken == 0 else "warn"
        self.report["finished_at"] = datetime.now(timezone.utc).isoformat()

        report_dir = self.base_dir / "reports"
        report_dir.mkdir(exist_ok=True)
        report_path = report_dir / "maintenance-latest.json"
        report_path.write_text(json.dumps(self.report, ensure_ascii=False, indent=2), encoding="utf-8")
        self.report["report_path"] = str(report_path)
        return self.report


def main() -> int:
    parser = argparse.ArgumentParser(description="Karpathy知识库维护流水线")
    parser.add_argument("--base-dir", default=str(Path(__file__).resolve().parent.parent), help="知识库目录")
    parser.add_argument("--embeddings", action="store_true", help="显式重建语义向量（默认关闭，避免拉取外部embedding模型）")
    parser.add_argument("--no-embeddings", action="store_true", help="兼容旧参数：跳过语义向量重建")
    parser.add_argument("--ollama-model", default="gemma4:e4b", help="本地Ollama模型，默认 gemma4:e4b")
    parser.add_argument("--json", action="store_true", help="只输出 JSON")
    args = parser.parse_args()

    maint = KBMaintenance(Path(args.base_dir), update_embeddings=bool(args.embeddings and not args.no_embeddings), ollama_model=args.ollama_model)
    report = maint.run()

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        summary = report.get("summary", {})
        lint = summary.get("lint", {})
        emb = summary.get("embeddings", {})
        print("\n🧹 知识库维护完成")
        print(f"状态: {report['status']}")
        print(f"真实文档: {summary.get('real_wiki_docs', 0)} / wiki文件: {summary.get('wiki_files', 0)} / raw文件: {summary.get('raw_files', 0)}")
        if lint:
            print(f"Lint: 坏链 {lint.get('broken_links', '?')}，孤立页 {lint.get('orphans', '?')}，内部链接 {lint.get('internal_links', '?')}")
        assoc = summary.get("associations", {})
        if assoc:
            print(f"关联: 孤立 {assoc.get('orphans', '?')}，弱关联 {assoc.get('weak_docs', '?')}，实体 {assoc.get('entities', '?')}")
        model = summary.get("model", {})
        if model:
            print(f"本地模型: {model.get('provider')} / {model.get('model')} / {model.get('status')}")
        if emb:
            if emb.get("skipped"):
                print("Embedding: 已跳过（默认关闭，避免外部模型下载）")
            elif emb.get("error"):
                print(f"Embedding: 失败 - {emb['error']}")
            else:
                print(f"Embedding: {emb.get('embedded_documents', 0)} 文档，{emb.get('dimension', 0)} 维")
        print(f"报告: {report.get('report_path')}")

    return 0 if report.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
