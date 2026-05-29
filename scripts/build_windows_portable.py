#!/usr/bin/env python3
"""Build a Windows portable source package.

Deferred legacy helper for the future "formal distribution packaging
(Windows & Linux)" task.

The current deployment path is git-based:

    git clone <repo> karpathy-kb
    cd karpathy-kb
    ./packaging/windows/install_deps.sh
    ./packaging/windows/configure_key.sh --key "..."
    ./packaging/windows/start_webui.sh

Keep this builder out of the main workflow until the formal release package
task resumes.
"""

from __future__ import annotations

import argparse
import shutil
import zipfile
from pathlib import Path


KB_DIR = Path(__file__).resolve().parent.parent
DIST_DIR = KB_DIR / "dist"
PACKAGE_NAME = "karpathy-kb-windows-portable"

BASE_FILES = [
    "README.md",
    "requirements.txt",
    "llm_runtime.yaml",
    "translation_terms.json",
    "translation_config.json",
]

BASE_DIRS = [
    "scripts",
    "docs",
    "static",
    "config",
]

DATA_DIRS = [
    "wiki",
    "raw",
    "reports",
    "backups",
    "outputs",
    "logs",
]

EXCLUDE_NAMES = {
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".venv",
    "venv",
    "node_modules",
}

EXCLUDE_SUFFIXES = {
    ".pyc",
    ".pyo",
    ".log",
}


def ignore_func(_dir: str, names: list[str]) -> set[str]:
    ignored = set()
    for name in names:
        if name in EXCLUDE_NAMES or any(name.endswith(suffix) for suffix in EXCLUDE_SUFFIXES):
            ignored.add(name)
    return ignored


def copy_path(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    if src.is_dir():
        shutil.copytree(src, dst, ignore=ignore_func)
    else:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def build() -> Path:
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    package_root = DIST_DIR / PACKAGE_NAME
    if package_root.exists():
        shutil.rmtree(package_root)
    app_dir = package_root / "app"
    app_dir.mkdir(parents=True)

    for rel in BASE_FILES:
        copy_path(KB_DIR / rel, app_dir / rel)
    for rel in BASE_DIRS:
        copy_path(KB_DIR / rel, app_dir / rel)

    for data_dir in DATA_DIRS:
        target = app_dir / data_dir
        target.mkdir(parents=True, exist_ok=True)
        write_text(target / ".keep", "")

    for rel in ["install_deps.sh", "configure_key.sh", "start_webui.sh", "README-Windows.md"]:
        copy_path(KB_DIR / "packaging" / "windows" / rel, package_root / rel)

    write_text(
        package_root / "config" / "llm.env.example",
        "DEEPSEEK_API_KEY=your_key_here\n",
    )
    write_text(
        package_root / "config" / "llm.env",
        "",
    )

    zip_path = DIST_DIR / f"{PACKAGE_NAME}.zip"
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in package_root.rglob("*"):
            if path.is_file():
                zf.write(path, path.relative_to(DIST_DIR))
    return zip_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Windows portable package")
    parser.parse_args()
    zip_path = build()
    print(f"Built {zip_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
