#!/usr/bin/env python3
"""Generate Chinese review previews for candidate-pool items in small batches.

This is intentionally separate from RSS syncing: feed fetches should stay fast,
while translation can run as a retryable background queue.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

KB_DIR = Path(__file__).resolve().parent.parent


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def candidate_id(md_path: Path, meta: Dict[str, Any]) -> str:
    if meta.get("url"):
        return hashlib.sha256(str(meta["url"]).encode("utf-8")).hexdigest()[:16]
    return file_hash(md_path)


def meta_for(base_dir: Path, md_path: Path) -> Dict[str, Any]:
    suffix = md_path.name.rsplit("_", 1)[-1].replace(".md", "") if "_" in md_path.name else ""
    candidates = []
    if suffix:
        candidates.append(md_path.with_name(f"{suffix}_meta.json"))
    candidates.extend(md_path.parent.glob("*_meta.json"))
    for path in candidates:
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        try:
            rel = str(md_path.relative_to(base_dir))
        except ValueError:
            rel = str(md_path)
        if data.get("candidate_path") == rel or data.get("title") in md_path.stem:
            return data
    return {}


def iter_candidates(base_dir: Path, candidate_type: str) -> Iterable[tuple[Path, str]]:
    raw_dir = base_dir / "raw"
    dirs = []
    if candidate_type in {"rss", "all"}:
        dirs.append((raw_dir / "rss_candidates", "rss"))
    if candidate_type in {"wechat", "all"}:
        dirs.append((raw_dir / "wechat_candidates", "wechat"))
    if candidate_type in {"other", "all"}:
        dirs.append((raw_dir / "webpage_candidates", "other"))

    for directory, ctype in dirs:
        if not directory.exists():
            continue
        yield from ((path, ctype) for path in sorted(directory.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True))


def build_item(base_dir: Path, md_path: Path, ctype: str, content: str) -> Dict[str, Any]:
    meta = meta_for(base_dir, md_path)
    title = meta.get("title") or next((line[2:].strip() for line in content.splitlines()[:20] if line.startswith("# ")), md_path.stem)
    cid = candidate_id(md_path, meta)
    return {
        "id": cid,
        "title": title,
        "source_name": meta.get("source_name") or "",
        "author": meta.get("author") or "",
        "url": meta.get("url") or "",
        "publish_time": meta.get("publish_time") or "",
        "path": str(md_path.relative_to(base_dir)),
        "candidate_type": ctype,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Chinese preview translations for candidates")
    parser.add_argument("--base-dir", default=str(KB_DIR))
    parser.add_argument("--type", default="rss", choices=["rss", "wechat", "other", "all"])
    parser.add_argument("--batch-size", type=int, default=20)
    parser.add_argument("--max-seconds", type=int, default=1200)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    base_dir = Path(args.base_dir).expanduser().resolve()

    import sys
    sys.path.insert(0, str(base_dir / "scripts"))
    from translator import CandidateTranslator  # type: ignore

    translator = CandidateTranslator(base_dir)
    started = time.monotonic()
    translated, skipped, failed = [], 0, []

    for md_path, ctype in iter_candidates(base_dir, args.type):
        if len(translated) >= args.batch_size:
            break
        if time.monotonic() - started > args.max_seconds:
            break
        try:
            content = md_path.read_text(encoding="utf-8", errors="ignore")
            item = build_item(base_dir, md_path, ctype, content)
            existing = translator.load_translation(item["id"])
            source_hash = translator._hash_text(content)
            if existing and existing.get("source_hash") == source_hash and existing.get("preview") and not args.force:
                skipped += 1
                continue
            result = translator.translate_preview_candidate(item, content, force=args.force)
            translated.append({"id": item["id"], "title": item["title"], "translated_title": result.get("translated_title")})
        except Exception as exc:
            failed.append({"path": str(md_path.relative_to(base_dir)), "error": str(exc)})

    print(json.dumps({
        "translated": len(translated),
        "skipped_with_preview": skipped,
        "failed": failed,
        "items": translated,
    }, ensure_ascii=False, indent=2))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
