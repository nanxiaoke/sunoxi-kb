#!/usr/bin/env python3
"""Karpathy 知识库监控任务。

默认策略偏保守：
- 同步 RSS 到候选池，不直接入库。
- 扫描 raw/ 中普通待处理文件并导入。
- 只有在 monitor_config.json 中显式开启 auto_import_candidates 时，才会自动导入候选池内容。
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("kb_monitor")

DEFAULT_CONFIG: Dict[str, Any] = {
    "interval_seconds": 1800,
    "rss_sync": True,
    "rss_max_per_source": 5,
    "rss_generate_preview": False,
    "auto_import_raw": True,
    "raw_import_limit": 5,
    "auto_import_candidates": False,
    "candidate_import_limit": 3,
    "run_maintenance_after_candidates": True,
}


class KBMonitor:
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir.resolve()
        self.config_path = self.base_dir / "monitor_config.json"
        self.report_path = self.base_dir / "reports" / "monitor-latest.json"
        self.report_path.parent.mkdir(parents=True, exist_ok=True)
        self.config = self.load_config()

    def load_config(self) -> Dict[str, Any]:
        if not self.config_path.exists():
            self.config_path.write_text(json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2), encoding="utf-8")
            return dict(DEFAULT_CONFIG)
        try:
            data = json.loads(self.config_path.read_text(encoding="utf-8"))
            return {**DEFAULT_CONFIG, **data}
        except Exception as e:
            logger.warning("读取 monitor_config.json 失败，使用默认配置: %s", e)
            return dict(DEFAULT_CONFIG)

    def run_once(self) -> Dict[str, Any]:
        started = datetime.now(timezone.utc).isoformat()
        report: Dict[str, Any] = {"started_at": started, "steps": {}, "errors": []}

        if self.config.get("rss_sync"):
            try:
                from rss_sync import RSSManager  # type: ignore
                mgr = RSSManager(self.base_dir)
                mgr.generate_preview = bool(self.config.get("rss_generate_preview", False))
                result = mgr.sync_all(max_per_source=int(self.config.get("rss_max_per_source", 5)))
                # rss_sync may include full Article objects; keep monitor reports compact.
                compact_result = {
                    k: v for k, v in result.items()
                    if k not in {"articles", "items", "raw_articles"}
                }
                if "articles" in result:
                    compact_result["articles_count"] = len(result.get("articles") or [])
                report["steps"]["rss_sync"] = compact_result
                logger.info("RSS 同步完成: new=%s skipped=%s errors=%s", result.get("new"), result.get("skipped"), result.get("errors"))
            except Exception as e:
                logger.exception("RSS 同步失败")
                report["errors"].append({"step": "rss_sync", "error": str(e)})

        if self.config.get("auto_import_raw"):
            try:
                from auto_importer import AutoImporter  # type: ignore
                importer = AutoImporter(self.base_dir)
                result = importer.process_pending(limit=int(self.config.get("raw_import_limit", 5)))
                report["steps"]["auto_import_raw"] = result
                logger.info("raw 自动导入完成: processed=%s success=%s failed=%s", result.get("processed"), result.get("success"), result.get("failed"))
            except Exception as e:
                logger.exception("raw 自动导入失败")
                report["errors"].append({"step": "auto_import_raw", "error": str(e)})

        if self.config.get("auto_import_candidates"):
            try:
                from candidate_manager import CandidateManager  # type: ignore
                cm = CandidateManager(self.base_dir)
                items = cm.list_candidates()[: int(self.config.get("candidate_import_limit", 3))]
                imported = []
                for item in items:
                    imported.append(cm.import_candidate(
                        item["id"],
                        process=True,
                        run_maintenance=bool(self.config.get("run_maintenance_after_candidates", True)),
                    ))
                report["steps"]["auto_import_candidates"] = {"count": len(imported), "items": imported}
                logger.info("候选池自动导入完成: %s", len(imported))
            except Exception as e:
                logger.exception("候选池自动导入失败")
                report["errors"].append({"step": "auto_import_candidates", "error": str(e)})
        else:
            report["steps"]["auto_import_candidates"] = {"status": "disabled"}

        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        report["status"] = "ok" if not report["errors"] else "warn"
        self.report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        return report

    def watch(self, interval: int | None = None) -> None:
        interval = interval or int(self.config.get("interval_seconds", 1800))
        logger.info("知识库监控启动，间隔 %ss", interval)
        while True:
            self.config = self.load_config()
            self.run_once()
            time.sleep(interval)


def main() -> int:
    parser = argparse.ArgumentParser(description="Karpathy 知识库监控自动导入")
    parser.add_argument("command", nargs="?", choices=["run", "watch", "config"], default="run")
    parser.add_argument("--base-dir", default=str(Path.home() / "karpathy-kb"))
    parser.add_argument("--interval", type=int, help="watch 间隔秒数")
    args = parser.parse_args()

    monitor = KBMonitor(Path(args.base_dir))
    if args.command == "config":
        print(json.dumps(monitor.config, ensure_ascii=False, indent=2))
    elif args.command == "watch":
        monitor.watch(args.interval)
    else:
        print(json.dumps(monitor.run_once(), ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
