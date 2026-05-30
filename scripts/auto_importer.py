#!/usr/bin/env python3
"""
自动文档导入管道
扫描raw/目录下的新文件，自动检测格式并触发处理

功能：
- 自动扫描raw/子目录中的新/未处理文件
- 支持多格式：md, txt, pdf, docx, py, 代码文件
- 进度跟踪，避免重复处理
- 处理报告输出
- 可配合cron定时扫描
"""

import os
import re
import sys
import json
import time
import hashlib
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Set
from datetime import datetime

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 添加项目路径
KB_BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KB_BASE_DIR / "scripts"))


class AutoImporter:
    """自动文档导入器"""

    # 支持的文件格式与处理器映射
    FORMAT_HANDLERS = {
        '.md': 'markdown',
        '.markdown': 'markdown',
        '.txt': 'text',
        '.text': 'text',
        '.pdf': 'pdf',
        '.docx': 'docx',
        '.py': 'code',
        '.js': 'code',
        '.ts': 'code',
        '.java': 'code',
        '.cpp': 'code',
        '.c': 'code',
        '.h': 'code',
        '.hpp': 'code',
        '.go': 'code',
        '.rs': 'code',
        '.rb': 'code',
        '.sh': 'code',
        '.yaml': 'text',
        '.yml': 'text',
        '.json': 'text',
        '.xml': 'text',
        '.html': 'text',
        '.csv': 'text',
    }

    # 已知Meta文件模式
    META_PATTERNS = ["_meta.json", ".DS_Store", "Thumbs.db"]

    # 需要跳过处理的上层索引/文档文件
    SKIP_FILES = {
        '00_INDEX.md', 'DOCUMENTS.md', 'category_教程.md',
        'category_文章.md', 'category_笔记.md',
    }

    # 候选池和翻译缓存目录不属于 raw 正文导入范围。
    # 候选应由 candidate_manager 审核/导入；candidate_translations 是 sidecar JSON 缓存。
    SKIP_DIRS = {
        "candidate_translations",
    }

    def __init__(self, base_dir: Path = None, include_candidates: bool = False):
        self.base_dir = base_dir or KB_BASE_DIR
        self.raw_dir = self.base_dir / "raw"
        self.wiki_dir = self.base_dir / "wiki"
        self.progress_file = self.base_dir / "batch_progress.json"
        self.include_candidates = include_candidates
        self.processed_cache: Set[str] = set()
        self._load_progress()

    def _load_progress(self):
        """加载已处理文件记录"""
        if self.progress_file.exists():
            try:
                data = json.loads(self.progress_file.read_text())
                # 从progress中恢复已处理列表
                processed = data.get("processed_files", [])
                if isinstance(processed, list):
                    self.processed_cache = set(processed)
                logger.info(f"加载进度: {len(self.processed_cache)} 个已处理文件记录")
            except Exception as e:
                logger.warning(f"加载进度文件失败: {e}")
                self.processed_cache = set()
        else:
            self.processed_cache = set()

    def _save_progress(self, new_files: List[str]):
        """保存处理进度"""
        self.processed_cache.update(new_files)
        progress = {
            "total_raw_files": len(self.processed_cache),
            "total_wiki_files": len(list(self.wiki_dir.rglob("*.md"))),
            "model": "gemma4:e4b",
            "processed_files": sorted(self.processed_cache),
            "last_updated": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        }
        self.progress_file.write_text(
            json.dumps(progress, ensure_ascii=False, indent=2)
        )
        logger.info(f"进度已保存: {len(self.processed_cache)} 个文件")

    def scan_raw(self) -> Dict[str, List[Path]]:
        """扫描raw/目录，按分类列出所有文件"""
        found = {"pending": [], "processed": [], "skipped": []}
        for root, dirs, files in os.walk(str(self.raw_dir)):
            root_path = Path(root)
            for fname in files:
                fpath = root_path / fname
                rel_parts = fpath.relative_to(self.raw_dir).parts
                if any(part in self.SKIP_DIRS for part in rel_parts):
                    found["skipped"].append(fpath)
                    continue
                if not self.include_candidates and any(part.endswith("_andidates") or part.endswith("_candidates") for part in rel_parts):
                    found["skipped"].append(fpath)
                    continue
                # 跳过元数据/系统文件
                if any(fname.endswith(p) for p in self.META_PATTERNS):
                    found["skipped"].append(fpath)
                    continue
                # 跳过索引文件
                if fname in self.SKIP_FILES:
                    found["skipped"].append(fpath)
                    continue
                # 跳过不支持格式
                ext = fpath.suffix.lower()
                if ext not in self.FORMAT_HANDLERS:
                    found["skipped"].append(fpath)
                    continue
                # 判断是否已处理
                if str(fpath) in self.processed_cache:
                    found["processed"].append(fpath)
                else:
                    found["pending"].append(fpath)
        return found

    def scan_summary(self) -> Dict:
        """生成扫描摘要"""
        found = self.scan_raw()
        # 按分类统计
        pending_by_category = {}
        for f in found["pending"]:
            rel = f.relative_to(self.raw_dir)
            cat = rel.parts[0] if len(rel.parts) > 1 else "other"
            pending_by_category.setdefault(cat, []).append(f)

        return {
            "total_raw": len(found["pending"]) + len(found["processed"]),
            "pending": len(found["pending"]),
            "processed": len(found["processed"]),
            "skipped": len(found["skipped"]),
            "pending_by_category": {
                cat: len(files) for cat, files in sorted(pending_by_category.items())
            },
            "pending_files": [str(f.relative_to(self.raw_dir)) for f in found["pending"]]
        }

    def get_batch_processor(self):
        """延迟加载batch_processor模块"""
        from batch_processor import BatchProcessor
        return BatchProcessor(self.base_dir)

    def process_file(self, filepath: Path) -> Tuple[bool, str]:
        """处理单个文件（通过 batch_processor 的 LLMService 业务流策略）"""
        try:
            # 构建file_info字典（兼容batch_processor.process_file的格式）
            rel = filepath.relative_to(self.raw_dir)
            category = rel.parts[0] if len(rel.parts) > 1 else "other"
            file_info = {
                "path": filepath,
                "name": filepath.name,
                "category": category,
                "size": filepath.stat().st_size,
            }

            # 使用batch_processor处理
            bp = self.get_batch_processor()
            result = bp.process_file(file_info)

            if result:
                return True, str(result)
            else:
                return False, getattr(bp, "last_error", None) or "AI处理失败（返回空）"

        except Exception as e:
            return False, f"异常: {e}"

    def process_pending(self, limit: int = 0, category: str = None,
                        dry_run: bool = False) -> Dict:
        """处理所有待处理文件"""
        found = self.scan_raw()
        pending = found["pending"]

        # 按分类过滤
        if category:
            pending = [f for f in pending
                       if f.parent.name == category or category in str(f)]
        # 数量限制
        if limit > 0:
            pending = pending[:limit]

        if not pending:
            return {"status": "no_pending", "processed": 0, "results": []}

        if dry_run:
            return {
                "status": "dry_run",
                "processed": 0,
                "would_process": len(pending),
                "files": [str(f.relative_to(self.raw_dir)) for f in pending]
            }

        results = []
        success_count = 0
        fail_count = 0

        for i, fpath in enumerate(pending, 1):
            rel_path = str(fpath.relative_to(self.raw_dir))
            logger.info(f"[{i}/{len(pending)}] 处理: {rel_path} "
                        f"({fpath.stat().st_size} bytes)")

            success, message = self.process_file(fpath)
            if success:
                success_count += 1
                logger.info(f"  ✅ 成功: {message}")
            else:
                fail_count += 1
                logger.warning(f"  ❌ 失败: {message}")

            results.append({
                "file": rel_path,
                "success": success,
                "message": message
            })

            # 仅成功时更新进度
            if success:
                self._save_progress([str(fpath)])
            time.sleep(2)  # 冷却，避免Ollama过载

        # 更新搜索索引（如果有新文件成功处理）
        if success_count > 0:
            try:
                from optimizer import IncrementalIndex
                inc = IncrementalIndex(self.base_dir)
                changed, _ = inc.get_changed_files()
                if changed:
                    logger.info(f"重建搜索索引（{len(changed)} 个文件变化）...")
                    from search import WikiSearcher
                    searcher = WikiSearcher(self.base_dir)
                    searcher.build_index(rebuild=True)
                    logger.info("搜索索引已更新")
            except Exception as e:
                logger.warning(f"索引更新失败: {e}")
        
        return {
            "status": "completed",
            "processed": len(pending),
            "success": success_count,
            "failed": fail_count,
            "results": results
        }


def display_summary(summary: Dict):
    """显示扫描摘要"""
    print(f"\n📊 文档导入管道 — 扫描结果")
    print(f"{'='*50}")
    print(f"  总文件: {summary['total_raw']}")
    print(f"  ✅ 已处理: {summary['processed']}")
    print(f"  ⏳ 待处理: {summary['pending']}")
    print(f"  ⏭️  跳过: {summary['skipped']}")
    if summary["pending_by_category"]:
        print(f"\n  待处理分类:")
        for cat, cnt in summary["pending_by_category"].items():
            print(f"    {cat}: {cnt} 文件")
    if summary["pending_files"]:
        print(f"\n  待处理列表:")
        for f in summary["pending_files"]:
            print(f"    - {f}")


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Karpathy知识库 — 自动文档导入管道"
    )
    parser.add_argument("action", nargs="?", default="scan",
                        choices=["scan", "import", "dry-run"],
                        help="操作：scan(扫描) / import(导入) / dry-run(预演)")
    parser.add_argument("--limit", type=int, default=0,
                        help="处理数量限制")
    parser.add_argument("--category", type=str,
                        help="分类过滤（如articles, notes）")
    parser.add_argument("--watch", action="store_true",
                        help="启动监控模式（持续扫描）")
    parser.add_argument("--include-candidates", action="store_true",
                        help="包含 *_candidates 候选目录（默认跳过，建议用 candidate_manager 导入候选）")
    parser.add_argument("--interval", type=int, default=300,
                        help="监控间隔秒数（默认300秒）")

    args = parser.parse_args()

    importer = AutoImporter(include_candidates=args.include_candidates)

    if args.watch:
        print(f"\n👀 监控模式启动 (间隔: {args.interval}s)")
        print(f"   按 Ctrl+C 停止")
        try:
            while True:
                summary = importer.scan_summary()
                if summary["pending"] > 0:
                    print(f"\n[{datetime.now()}] 发现 {summary['pending']} 个新文件，开始导入...")
                    result = importer.process_pending(
                        limit=args.limit or summary["pending"],
                        category=args.category,
                    )
                    print(f"  处理: {result['processed']}, "
                          f"成功: {result.get('success', 0)}, "
                          f"失败: {result.get('failed', 0)}")
                else:
                    print(f"[{datetime.now()}] 无新文件")
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\n👋 监控已停止")
        return

    if args.action == "scan":
        summary = importer.scan_summary()
        display_summary(summary)
        return

    if args.action == "dry-run":
        found = importer.scan_raw()
        pending = found["pending"]
        if args.category:
            pending = [f for f in pending
                       if f.parent.name == args.category]
        if args.limit > 0:
            pending = pending[:args.limit]

        print(f"\n🔍 预演模式 — 将处理 {len(pending)} 个文件")
        for f in pending:
            rel = f.relative_to(importer.raw_dir)
            handler = importer.FORMAT_HANDLERS.get(f.suffix.lower(), "text")
            print(f"  📄 {rel} ({handler}, {f.stat().st_size} bytes)")
        return

    if args.action == "import":
        result = importer.process_pending(
            limit=args.limit,
            category=args.category,
        )
        print(f"\n{'='*50}")
        print(f"📥 导入完成")
        print(f"  处理: {result['processed']}")
        print(f"  ✅ 成功: {result.get('success', 0)}")
        print(f"  ❌ 失败: {result.get('failed', 0)}")
        print(f"{'='*50}")
        return


if __name__ == "__main__":
    main()
