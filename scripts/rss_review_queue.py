#!/usr/bin/env python3
"""Manual RSS review queue: sync feeds, then generate Chinese previews.

The queue is intentionally manual. It gives one tracked job for the review
workflow so operators can tell whether it is fetching feeds, translating
previews, finished, or failed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

KB_DIR = Path(__file__).resolve().parent.parent


class JobState:
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir.resolve()
        self.report_dir = self.base_dir / "reports"
        self.report_dir.mkdir(parents=True, exist_ok=True)
        self.latest_path = self.report_dir / "rss-review-latest.json"
        self.history_path = self.report_dir / "rss-review-history.jsonl"
        self.lock_path = self.report_dir / "rss-review.lock"
        self.lock_fd: int | None = None
        self.data: Dict[str, Any] = {}

    def acquire_lock(self) -> None:
        try:
            self.lock_fd = os.open(str(self.lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(self.lock_fd, str(os.getpid()).encode("utf-8"))
        except FileExistsError as exc:
            holder = ""
            try:
                holder = self.lock_path.read_text(encoding="utf-8")
            except Exception:
                pass
            raise RuntimeError(f"rss review queue already running or stale lock exists: {self.lock_path} pid={holder}") from exc

    def release_lock(self) -> None:
        if self.lock_fd is not None:
            os.close(self.lock_fd)
            self.lock_fd = None
        try:
            self.lock_path.unlink()
        except FileNotFoundError:
            pass

    def start(self, args: argparse.Namespace) -> None:
        now = datetime.now(timezone.utc).isoformat()
        job_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.data = {
            "job_id": job_id,
            "status": "running",
            "current_stage": "starting",
            "started_at": now,
            "finished_at": None,
            "config": {
                "rss_max_per_source": args.rss_max_per_source,
                "preview_batch_size": args.preview_batch_size,
                "preview_max_seconds": args.preview_max_seconds,
                "fill_backlog": args.fill_backlog,
                "force_preview": args.force_preview,
            },
            "stages": {
                "rss_sync": {"status": "pending"},
                "preview": {"status": "pending"},
            },
            "errors": [],
        }
        self.write()

    def update(self, **changes: Any) -> None:
        self.data.update(changes)
        self.write()

    def stage(self, name: str, **changes: Any) -> None:
        self.data.setdefault("stages", {}).setdefault(name, {}).update(changes)
        self.data["current_stage"] = name
        self.write()

    def add_error(self, stage: str, error: str) -> None:
        self.data.setdefault("errors", []).append({"stage": stage, "error": error})
        self.write()

    def finish(self, status: str) -> None:
        self.data["status"] = status
        self.data["current_stage"] = "finished"
        self.data["finished_at"] = datetime.now(timezone.utc).isoformat()
        self.write()
        with self.history_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(self.data, ensure_ascii=False) + "\n")

    def write(self) -> None:
        tmp = self.latest_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        tmp.replace(self.latest_path)


def article_ids(articles: List[Any]) -> set[str]:
    import hashlib

    ids = set()
    for article in articles or []:
        url = getattr(article, "url", "") or ""
        if url:
            ids.add(hashlib.sha256(url.encode("utf-8")).hexdigest()[:16])
    return ids


def candidate_queue(base_dir: Path, preferred_ids: set[str], fill_backlog: bool) -> List[Dict[str, Any]]:
    from translate_preview_queue import build_item, iter_candidates  # type: ignore

    rows = []
    for md_path, ctype in iter_candidates(base_dir, "rss"):
        try:
            content = md_path.read_text(encoding="utf-8", errors="ignore")
            item = build_item(base_dir, md_path, ctype, content)
            item["_content"] = content
            item["_preferred"] = item["id"] in preferred_ids
            rows.append(item)
        except Exception as exc:
            rows.append({"id": "", "path": str(md_path), "_load_error": str(exc), "_preferred": False})

    if fill_backlog:
        rows.sort(key=lambda i: (not i.get("_preferred"), i.get("path", "")))
        return rows
    return [i for i in rows if i.get("_preferred")]


def run(args: argparse.Namespace) -> int:
    base_dir = Path(args.base_dir).expanduser().resolve()
    sys.path.insert(0, str(base_dir / "scripts"))

    state = JobState(base_dir)
    state.acquire_lock()
    try:
        state.start(args)

        from rss_sync import RSSManager  # type: ignore
        from translator import CandidateTranslator  # type: ignore

        state.stage("rss_sync", status="running", started_at=datetime.now(timezone.utc).isoformat())
        mgr = RSSManager(base_dir)
        mgr.generate_preview = False
        rss_result = mgr.sync_all(max_per_source=args.rss_max_per_source)
        compact_rss = {k: v for k, v in rss_result.items() if k != "articles"}
        compact_rss["articles_count"] = len(rss_result.get("articles") or [])
        state.stage("rss_sync", status="ok", finished_at=datetime.now(timezone.utc).isoformat(), result=compact_rss)

        new_ids = article_ids(rss_result.get("articles") or [])
        translator = CandidateTranslator(base_dir)
        queue = candidate_queue(base_dir, new_ids, args.fill_backlog)
        state.stage(
            "preview",
            status="running",
            started_at=datetime.now(timezone.utc).isoformat(),
            queued=len(queue),
            translated=0,
            skipped_with_preview=0,
            failed=[],
            items=[],
        )

        started = time.monotonic()
        translated, skipped, failed, items = 0, 0, [], []
        for item in queue:
            if translated >= args.preview_batch_size:
                break
            if time.monotonic() - started > args.preview_max_seconds:
                break
            if item.get("_load_error"):
                failed.append({"path": item.get("path"), "error": item.get("_load_error")})
                continue
            content = item.pop("_content", "")
            item.pop("_preferred", None)
            try:
                existing = translator.load_translation(item["id"])
                source_hash = translator._hash_text(content)
                if existing and existing.get("source_hash") == source_hash and existing.get("preview") and not args.force_preview:
                    skipped += 1
                    continue
                result = translator.translate_preview_candidate(item, content, force=args.force_preview)
                translated += 1
                items.append({"id": item["id"], "title": item.get("title"), "translated_title": result.get("translated_title")})
            except Exception as exc:
                failed.append({"id": item.get("id"), "title": item.get("title"), "error": str(exc)})
            state.stage("preview", translated=translated, skipped_with_preview=skipped, failed=failed[-10:], items=items[-20:])

        preview_status = "ok" if not failed else "warn"
        state.stage(
            "preview",
            status=preview_status,
            finished_at=datetime.now(timezone.utc).isoformat(),
            queued=len(queue),
            translated=translated,
            skipped_with_preview=skipped,
            failed=failed,
            items=items,
        )

        status = "ok"
        if compact_rss.get("errors") or failed:
            status = "warn"
        state.finish(status)
        print(json.dumps(state.data, ensure_ascii=False, indent=2, default=str))
        return 0 if status == "ok" else 1
    except Exception as exc:
        state.add_error(state.data.get("current_stage", "unknown"), str(exc))
        state.finish("failed")
        print(json.dumps(state.data, ensure_ascii=False, indent=2, default=str))
        return 2
    finally:
        state.release_lock()


def status(args: argparse.Namespace) -> int:
    path = Path(args.base_dir).expanduser().resolve() / "reports" / "rss-review-latest.json"
    if not path.exists():
        print(json.dumps({"status": "missing", "path": str(path)}, ensure_ascii=False, indent=2))
        return 1
    print(path.read_text(encoding="utf-8"))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Manual RSS sync + Chinese preview queue")
    parser.add_argument("command", choices=["run", "status"], nargs="?", default="run")
    parser.add_argument("--base-dir", default=str(KB_DIR))
    parser.add_argument("--rss-max-per-source", type=int, default=5)
    parser.add_argument("--preview-batch-size", type=int, default=20)
    parser.add_argument("--preview-max-seconds", type=int, default=1200)
    parser.add_argument("--fill-backlog", action="store_true", help="After new RSS items, also fill older candidates missing previews")
    parser.add_argument("--force-preview", action="store_true")
    args = parser.parse_args()
    if args.command == "status":
        return status(args)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
