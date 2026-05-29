#!/usr/bin/env python3
"""
Karpathy Knowledge Base Linter
用于扫描知识库，检查坏链（Broken Links）、孤立页面（Orphan Pages）和交叉引用。
"""

import os
import re
from pathlib import Path
from typing import Dict, List, Set, Tuple
import urllib.parse
import json

class KBLinter:
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir.resolve()
        self.wiki_dir = self.base_dir / "wiki"
        self.raw_dir = self.base_dir / "raw"
        
        # stats
        self.files: Set[Path] = set()
        self.links: List[Dict] = []
        self.broken_links: List[Dict] = []
        
        # map from relative path string to Path
        self.rel_paths: Dict[str, Path] = {}
        
        # track incoming links
        self.incoming: Dict[str, Set[str]] = {}

    def run(self):
        print(f"🔍 开始扫描知识库: {self.wiki_dir}")
        self._collect_files()
        self._scan_links()
        self._analyze()
        self._print_report()
        
    def _collect_files(self):
        for root, _, files in os.walk(self.wiki_dir):
            for f in files:
                if f.endswith('.md'):
                    path = Path(root) / f
                    self.files.add(path)
                    rel_path = path.relative_to(self.wiki_dir).as_posix()
                    self.rel_paths[rel_path] = path
                    self.incoming[rel_path] = set()
        print(f"📄 找到 {len(self.files)} 个 Markdown 文件")

    def _scan_links(self):
        md_link_pattern = re.compile(r'\[([^\]]+)\]\(([^)]+)\)')
        wiki_link_pattern = re.compile(r'\[\[(.*?)\]\]')
        
        for file_path in self.files:
            rel_src = file_path.relative_to(self.wiki_dir).as_posix()
            try:
                content = file_path.read_text(encoding='utf-8')
            except Exception as e:
                print(f"⚠️ 无法读取 {rel_src}: {e}")
                continue
                
            lines = content.split('\n')
            for i, line in enumerate(lines):
                # 1. 提取 Markdown 链接 [text](url)
                for match in md_link_pattern.finditer(line):
                    text, url = match.groups()
                    self._record_link(rel_src, url, text, i+1, "markdown")
                    
                # 2. 提取 Wikilink [[url|text]] 或 [[url]]
                for match in wiki_link_pattern.finditer(line):
                    inner = match.group(1)
                    if '|' in inner:
                        url, text = inner.split('|', 1)
                    else:
                        url, text = inner, inner
                    self._record_link(rel_src, url, text, i+1, "wikilink")

    def _record_link(self, src: str, url: str, text: str, line_num: int, link_type: str):
        # 清理 url (去掉锚点等)
        target = url.strip()
        anchor = None
        if '#' in target:
            target, anchor = target.split('#', 1)
            
        target = urllib.parse.unquote(target)
        
        # 忽略外部链接、纯锚点、mailto 等
        if not target or target.startswith(('http://', 'https://', 'mailto:', 'ftp://')):
            return
            
        link_data = {
            'src': src,
            'target_raw': target,
            'anchor': anchor,
            'text': text,
            'line': line_num,
            'type': link_type
        }
        self.links.append(link_data)

    def _analyze(self):
        for link in self.links:
            src = link['src']
            target = link['target_raw']
            
            # 尝试解析目标路径。
            # Obsidian wikilink 在本项目中统一使用 wiki 根目录相对路径：
            #   [[technologies/foo.md|Foo]]
            # Markdown 相对链接仍按当前文件所在目录解析。
            target_candidates = []

            # 1) wiki 根目录相对路径（优先，匹配 wiki_linker 生成格式）
            target_candidates.append((self.wiki_dir / target.lstrip('/')).resolve())

            # 2) 当前文件目录相对路径（兼容普通 Markdown 链接）
            src_path = self.wiki_dir / src
            target_candidates.append((src_path.parent / target).resolve())

            # 3) Obsidian 常见省略 .md 后缀的写法
            if not target.endswith('.md'):
                target_candidates.append((self.wiki_dir / f"{target.lstrip('/')}.md").resolve())
                target_candidates.append((src_path.parent / f"{target}.md").resolve())

            target_path = next((p for p in target_candidates if p.exists()), target_candidates[0])
            
            # 检查是否越界或不存在
            is_broken = False
            target_rel = None
            
            if not str(target_path).startswith(str(self.wiki_dir)):
                is_broken = True
            elif not target_path.exists():
                is_broken = True
            else:
                if target_path.is_file():
                    target_rel = target_path.relative_to(self.wiki_dir).as_posix()
                    self.incoming[target_rel].add(src)
                else:
                    # 指向目录，暂时不算错，或者视需要也算错
                    pass
                    
            if is_broken:
                self.broken_links.append(link)

    def _print_report(self):
        print("\n" + "="*50)
        print("📊 扫描报告")
        print("="*50)
        print(f"总链接数 (内部): {len(self.links)}")
        print(f"坏链数: {len(self.broken_links)}")
        
        # 统计孤立页面
        orphans = []
        for rel_path, sources in self.incoming.items():
            # 排除索引文件被视为孤立
            if 'INDEX' in rel_path or 'DOCUMENTS' in rel_path or rel_path.startswith('category_'):
                continue
            if len(sources) == 0:
                orphans.append(rel_path)
                
        print(f"孤立页面数: {len(orphans)}")
        
        if self.broken_links:
            print("\n❌ 坏链列表:")
            for b in self.broken_links:
                print(f"  - [{b['src']}:{b['line']}] 目标: '{b['target_raw']}' (文本: {b['text']})")
                
        if orphans:
            print("\n👻 孤立页面 (没有被其他页面链接):")
            for o in orphans:
                print(f"  - {o}")
                
        print("\n✅ 扫描完成。")

if __name__ == "__main__":
    base_dir = Path(os.environ.get("KB_DIR", Path.home() / "karpathy-kb"))
    linter = KBLinter(base_dir)
    linter.run()
