#!/usr/bin/env python3
"""Wrapper: 全量 backfill 37 篇缺译文文档。

特性：
- 去重（同级目录副本只翻译一次）
- 进度持久化到 JSON（中断可重试）
- 每次只翻译一篇，每篇独立写入
- 日志记录每篇的 token 消耗、耗时
"""

import argparse
import json
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

KB_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KB_DIR / "scripts"))

from translation_backfill import (
    audit_backfill,
    split_frontmatter,
    write_frontmatter,
    source_text_for,
    translate_source,
    upsert_translation_section,
)

PROGRESS_FILE = KB_DIR / "data" / "backfill_progress.json"

DEFAULT_PROVIDER = "deepseek_pro"
DEFAULT_CHUNK_CHARS = 3500  # from llm_runtime.yaml


def load_progress() -> dict:
    if PROGRESS_FILE.exists():
        return json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
    return {
        "started_at": None,
        "completed_at": None,
        "total": 37,
        "done": [],
        "failed": [],
        "skipped_duplicates": [],
        "per_item": {},
    }


def save_progress(p: dict):
    PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
    PROGRESS_FILE.write_text(
        json.dumps(p, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def dedup_items(items: list) -> list:
    """去重：相同 hash_id（文件名中 8 位 hash）视为同一篇文章的不同归档位置，只取第一条。"""
    seen = set()
    deduped = []
    for item in items:
        # hash_id 在文件名倒数第二个 _ 后、.md 前
        stem = Path(item["path"]).stem  # e.g. "ABC中文_a2c11069"
        parts = stem.rsplit("_", 1)
        hash_id = parts[-1] if len(parts) > 1 and len(parts[-1]) == 8 else stem
        if hash_id not in seen:
            seen.add(hash_id)
            deduped.append(item)
        else:
            deduped.append({**item, "_duplicate_of": hash_id})
    return deduped


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Resume-safe translation backfill wrapper.")
    parser.add_argument("--provider", default=DEFAULT_PROVIDER, help="LLM provider ID")
    parser.add_argument("--chunk-chars", type=int, default=DEFAULT_CHUNK_CHARS, help="source chars per translation chunk")
    parser.add_argument("--limit", type=int, default=0, help="max pending non-duplicate items to translate this run")
    parser.add_argument("--min-chars", type=int, default=0, help="only translate items with source_chars >= this value")
    parser.add_argument("--max-chars", type=int, default=0, help="only translate items with source_chars <= this value")
    parser.add_argument("--status-only", action="store_true", help="print current audit/progress and exit")
    return parser.parse_args()


def item_matches_size(item: dict, args: argparse.Namespace) -> bool:
    source_chars = int(item.get("source_chars") or 0)
    if args.min_chars and source_chars < args.min_chars:
        return False
    if args.max_chars and source_chars > args.max_chars:
        return False
    return True


def run(args: argparse.Namespace):
    progress = load_progress()
    if progress["started_at"] is None:
        progress["started_at"] = datetime.now(timezone.utc).isoformat()
        save_progress(progress)

    # 获取所有缺译文文章（无 limit 限制）
    base_dir = KB_DIR
    audit = audit_backfill(base_dir, limit=9999)
    raw_items = audit["items"]
    print(f"审计: 扫描 {audit['stats']['scanned']}, 缺译文 {len(raw_items)}")

    items = dedup_items(raw_items)
    done_paths = {Path(p).stem for p in progress["done"]}
    failed_stems = {Path(p).stem for p in progress["failed"]}

    # 识别重复项
    for item in items:
        if "_duplicate_of" in item:
            if item["path"] not in progress["done"] and item["path"] not in progress["skipped_duplicates"]:
                progress["skipped_duplicates"].append(item["path"])
                print(f"  ⏭️ [重复/副归档] {item['title']} → {item['path']}")

    current_missing = len([i for i in items if "_duplicate_of" not in i])
    progress["current_missing"] = current_missing
    if not progress.get("total"):
        progress["total"] = current_missing
    save_progress(progress)

    completed = len(progress["done"])
    print(f"\n当前缺译文: {current_missing} 篇 (累计已完 {completed}, 失败 {len(failed_stems)})")

    pending = []
    for item in items:
        if "_duplicate_of" in item:
            continue  # 跳过重复归档

        rel = item["path"]
        stem = Path(rel).stem
        if stem in done_paths or rel in progress["done"]:
            print(f"  ✅ [已完] {rel}")
            continue
        if not item_matches_size(item, args):
            print(f"  ↪️ [本轮跳过/尺寸过滤] {rel} ({item['source_chars']}ch)")
            continue
        pending.append(item)

    if args.limit > 0:
        pending = pending[: args.limit]

    print(
        f"本轮计划: {len(pending)} 篇"
        f" (provider={args.provider}, chunk_chars={args.chunk_chars}, "
        f"min_chars={args.min_chars or '-'}, max_chars={args.max_chars or '-'}, limit={args.limit or '-'})"
    )
    if args.status_only:
        return

    for idx, item in enumerate(pending, start=1):
        rel = item["path"]
        stem = Path(rel).stem
        if stem in failed_stems or rel in progress["failed"]:
            print(f"  🔄 [重试] {rel}")

        print(f"\n{'='*60}")
        print(f"[{idx}/{len(pending)}] 翻译: {item['title']}")
        print(f"  路径: {rel}")
        print(f"  字符: {item['source_chars']}ch  目标: {item['missing_targets'][0]}")

        # 开始翻译单篇
        wiki_dir = base_dir / "wiki"
        path = (wiki_dir / rel).resolve()
        text = path.read_text(encoding="utf-8", errors="ignore")
        meta, body = split_frontmatter(text)
        source_text = source_text_for(meta, body, base_dir)

        try:
            start_ts = time.time()
            translated, chunk_meta = translate_source(
                source_text,
                title=item["title"],
                target_language=item["missing_targets"][0],
                provider_name=args.provider,
                chunk_chars=args.chunk_chars,
            )
            elapsed = time.time() - start_ts

            new_body = upsert_translation_section(body, item["missing_targets"][0], translated)

            first_chunk = chunk_meta[0] if chunk_meta else {}
            meta["llm_full_translation"] = {
                "flow": "full_translation",
                "provider": first_chunk.get("provider", args.provider),
                "model": first_chunk.get("model", ""),
                "status": first_chunk.get("status", "ok"),
                "source_language": item["source_language"],
                "target_language": item["missing_targets"][0],
                "chunk_count": len(chunk_meta),
                "chunks": chunk_meta,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "source": "translation_backfill",
            }

            path.write_text(write_frontmatter(meta, new_body), encoding="utf-8")

            record = {
                "path": rel,
                "title": item["title"],
                "source_chars": item["source_chars"],
                "chunk_count": len(chunk_meta),
                "elapsed_sec": round(elapsed, 1),
                "provider": args.provider,
            }
            progress["failed"] = [
                p for p in progress["failed"] if Path(p).stem != Path(rel).stem and p != rel
            ]
            progress["done"].append(rel)
            progress["per_item"][rel] = record
            print(f"  ✅ 完成 ({len(chunk_meta)} chunks, {elapsed:.1f}s)")
            save_progress(progress)

        except Exception as e:
            tb = traceback.format_exc()
            fail_record = {
                "path": rel,
                "title": item["title"],
                "error": str(e),
                "traceback": tb,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            if rel not in progress["failed"]:
                progress["failed"].append(rel)
            progress["per_item"][rel] = fail_record
            print(f"  ❌ 失败: {e}")
            save_progress(progress)

    if current_missing == 0:
        progress["completed_at"] = datetime.now(timezone.utc).isoformat()
    save_progress(progress)

    print(f"\n{'='*60}")
    print(f"全部完成!")
    print(f"  成功: {len(progress['done'])}")
    print(f"  失败: {len(progress['failed'])}")
    print(f"  重复(跳过): {len(progress['skipped_duplicates'])}")


if __name__ == "__main__":
    run(parse_args())
