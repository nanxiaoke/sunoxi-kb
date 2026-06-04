#!/usr/bin/env python3
"""Wrapper: 全量 backfill 37 篇缺译文文档。

特性：
- 去重（同级目录副本只翻译一次）
- 进度持久化到 JSON（中断可重试）
- 每次只翻译一篇，每篇独立写入
- 日志记录每篇的 token 消耗、耗时
"""

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
    run_backfill,
    split_frontmatter,
    write_frontmatter,
    source_text_for,
    translate_source,
    upsert_translation_section,
)

PROGRESS_FILE = KB_DIR / "data" / "backfill_progress.json"

PROVIDER = "deepseek_pro"


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


def run():
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

    total = len([i for i in items if "_duplicate_of" not in i])
    progress["total"] = total
    save_progress(progress)

    policy = audit_backfill(base_dir, limit=10)  # just to get policy config
    chunk_chars = 3500  # from llm_runtime.yaml

    completed = len(progress["done"])
    print(f"\n需要翻译: {total} 篇 (已完 {completed}, 失败 {len(failed_stems)})")

    for idx, item in enumerate(items):
        if "_duplicate_of" in item:
            continue  # 跳过重复归档

        rel = item["path"]
        stem = Path(rel).stem
        if stem in done_paths or rel in progress["done"]:
            print(f"  ✅ [已完] {rel}")
            continue
        if stem in failed_stems or rel in progress["failed"]:
            print(f"  🔄 [重试] {rel}")

        print(f"\n{'='*60}")
        print(f"[{idx+1}/{total}] 翻译: {item['title']}")
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
                provider_name=PROVIDER,
                chunk_chars=chunk_chars,
            )
            elapsed = time.time() - start_ts

            new_body = upsert_translation_section(body, item["missing_targets"][0], translated)

            first_chunk = chunk_meta[0] if chunk_meta else {}
            meta["llm_full_translation"] = {
                "flow": "full_translation",
                "provider": first_chunk.get("provider", PROVIDER),
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
                "provider": PROVIDER,
            }
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
            progress["failed"].append(rel)
            progress["per_item"][rel] = fail_record
            print(f"  ❌ 失败: {e}")
            save_progress(progress)

    progress["completed_at"] = datetime.now(timezone.utc).isoformat()
    save_progress(progress)

    print(f"\n{'='*60}")
    print(f"全部完成!")
    print(f"  成功: {len(progress['done'])}")
    print(f"  失败: {len(progress['failed'])}")
    print(f"  重复(跳过): {len(progress['skipped_duplicates'])}")


if __name__ == "__main__":
    run()
