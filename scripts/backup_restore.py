#!/usr/bin/env python3
"""Karpathy 知识库备份/恢复工具。

备份范围默认包含：wiki、raw、reports、配置与索引状态文件。
恢复默认只解包到指定目录；如要覆盖当前知识库，需显式使用 restore --apply。
"""

from __future__ import annotations

import argparse
import json
import shutil
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List

DEFAULT_INCLUDE_DIRS = ["wiki", "raw", "reports", "guides", "static"]
DEFAULT_INCLUDE_FILES = [
    "README.md",
    "PROGRESS.md",
    "models_config.yaml",
    "rss_feeds.json",
    "rss_imported.json",
    "wechat_sources.json",
    "candidate_state.json",
    "batch_progress.json",
    "search_index.json",
    "wiki_index.json",
    "knowledge_graph.json",
    "embeddings.npy",
    "embeddings_map.json",
    "qa_cache.json",
]
DEFAULT_EXCLUDES = {"logs", "__pycache__", ".trash"}


class KBBackup:
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir.resolve()
        self.backup_dir = self.base_dir / "backups"
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    def _iter_paths(self) -> Iterable[Path]:
        for rel in DEFAULT_INCLUDE_DIRS:
            p = self.base_dir / rel
            if p.exists():
                yield p
        for rel in DEFAULT_INCLUDE_FILES:
            p = self.base_dir / rel
            if p.exists():
                yield p

    def _filter(self, tarinfo: tarfile.TarInfo) -> tarfile.TarInfo | None:
        parts = Path(tarinfo.name).parts
        if any(part in DEFAULT_EXCLUDES for part in parts):
            return None
        return tarinfo

    def create(self, output: Path | None = None) -> dict:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        output = output or (self.backup_dir / f"karpathy-kb-backup-{ts}.tar.gz")
        output = output.expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)

        included: List[str] = []
        manifest = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "base_dir": str(self.base_dir),
            "format": "tar.gz",
            "included": included,
        }

        with tarfile.open(output, "w:gz") as tar:
            for path in self._iter_paths():
                arcname = path.relative_to(self.base_dir)
                tar.add(path, arcname=str(arcname), filter=self._filter)
                included.append(str(arcname))

            manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
            info = tarfile.TarInfo("BACKUP_MANIFEST.json")
            info.size = len(manifest_bytes)
            info.mtime = datetime.now(timezone.utc).timestamp()
            import io
            tar.addfile(info, io.BytesIO(manifest_bytes))

        return {
            "status": "ok",
            "backup": str(output),
            "size_bytes": output.stat().st_size,
            "included_count": len(included),
            "included": included,
        }

    def inspect(self, archive: Path) -> dict:
        archive = archive.expanduser().resolve()
        with tarfile.open(archive, "r:gz") as tar:
            names = tar.getnames()
            manifest = None
            try:
                f = tar.extractfile("BACKUP_MANIFEST.json")
                if f:
                    manifest = json.loads(f.read().decode("utf-8"))
            except Exception:
                manifest = None
        return {"archive": str(archive), "files": len(names), "manifest": manifest, "sample": names[:50]}

    def restore(self, archive: Path, target: Path, apply: bool = False) -> dict:
        archive = archive.expanduser().resolve()
        target = target.expanduser().resolve()
        if apply and target == self.base_dir:
            # Make a safety copy before overwriting current KB.
            safety = self.create(self.backup_dir / f"pre-restore-safety-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.tar.gz")
        else:
            safety = None

        if target.exists() and not apply:
            raise SystemExit(f"Target exists: {target}. Use --apply to extract into an existing directory.")
        target.mkdir(parents=True, exist_ok=True)

        with tarfile.open(archive, "r:gz") as tar:
            def safe_members():
                for member in tar.getmembers():
                    dest = (target / member.name).resolve()
                    if not str(dest).startswith(str(target)):
                        raise SystemExit(f"Unsafe archive path: {member.name}")
                    if member.name == "BACKUP_MANIFEST.json":
                        continue
                    yield member
            tar.extractall(target, members=safe_members())

        return {"status": "ok", "restored_to": str(target), "safety_backup": safety}


def main() -> int:
    parser = argparse.ArgumentParser(description="Karpathy 知识库备份/恢复")
    parser.add_argument("command", choices=["create", "inspect", "restore"])
    parser.add_argument("archive", nargs="?", help="inspect/restore 使用的 .tar.gz 备份")
    parser.add_argument("--base-dir", default=str(Path.home() / "karpathy-kb"))
    parser.add_argument("--output", help="create 输出路径")
    parser.add_argument("--target", help="restore 目标目录；默认当前用户 home 下的 karpathy-kb-restored")
    parser.add_argument("--apply", action="store_true", help="允许恢复到已存在目录/当前知识库")
    args = parser.parse_args()

    tool = KBBackup(Path(args.base_dir))
    if args.command == "create":
        result = tool.create(Path(args.output) if args.output else None)
    elif args.command == "inspect":
        if not args.archive:
            raise SystemExit("archive required")
        result = tool.inspect(Path(args.archive))
    else:
        if not args.archive:
            raise SystemExit("archive required")
        target = Path(args.target) if args.target else (Path.home() / "karpathy-kb-restored")
        result = tool.restore(Path(args.archive), target, apply=args.apply)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
