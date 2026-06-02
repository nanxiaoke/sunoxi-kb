#!/usr/bin/env python3
"""
Karpathy知识库 — RSS订阅同步系统
抓取RSS/Atom源 → 转换为Markdown → 导入知识库
"""

import os
import re
import json
import time
import hashlib
import logging
import html
from pathlib import Path
from typing import Dict, List, Optional, Set
from datetime import datetime, timezone
from dataclasses import dataclass, field, asdict
from urllib.parse import urlparse

try:
    from import_quality import clean_import_title, safe_import_stem
    from translation_policy import full_translate_enabled, load_translation_policy
except ImportError:
    from .import_quality import clean_import_title, safe_import_stem
    from .translation_policy import full_translate_enabled, load_translation_policy

logger = logging.getLogger(__name__)

# 项目路径。默认跟随当前源码仓库，避免部署到 Windows/Linux 后继续写入 home 下旧路径。
KB_DIR = Path(__file__).resolve().parent.parent


@dataclass
class FeedSource:
    """RSS订阅源配置（扩展schema）"""
    url: str
    name: str
    category: str = "articles"
    enabled: bool = True
    priority: str = "medium"
    tags: List[str] = field(default_factory=list)
    language: str = "en"
    interval_minutes: int = 360
    max_articles: int = 10
    last_checked: Optional[str] = None
    notes: str = ""


@dataclass
class Article:
    """RSS文章"""
    title: str
    url: str
    content: str
    summary: str = ""
    author: str = ""
    published: str = ""
    source: str = ""
    source_name: str = ""
    content_hash: str = ""
    
    def to_markdown(self) -> str:
        """转换为Markdown格式"""
        title = clean_import_title(self.title, fallback="RSS文章")
        lines = []
        lines.append(f"# {title}")
        lines.append("")
        
        meta = []
        if self.author:
            meta.append(f"作者: {self.author}")
        if self.published:
            meta.append(f"日期: {self.published}")
        if self.source_name:
            meta.append(f"来源: {self.source_name}")
        meta.append(f"链接: {self.url}")
        lines.append(" | ".join(meta))
        lines.append("")
        lines.append("---")
        lines.append("")
        
        # 正文
        content = self._clean_html(self.content)
        lines.append(content)
        
        return "\n".join(lines)
    
    @staticmethod
    def _clean_html(text: str) -> str:
        """清理HTML标签，保留Markdown可读格式"""
        # 移除script/style
        text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL)
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
        
        # 换行标签
        text = re.sub(r'</p>', '\n\n', text)
        text = re.sub(r'<br\s*/?>', '\n', text)
        text = re.sub(r'</(div|h[1-6]|li|tr|blockquote)>', '\n', text)
        
        # 链接
        text = re.sub(r'<a\s+[^>]*href="([^"]+)"[^>]*>(.*?)</a>', r'\2 (\1)', text)
        
        # 图片
        text = re.sub(r'<img[^>]*src="([^"]+)"[^>]*alt="([^"]*)"[^>]*/>', r'![\2](\1)', text)
        text = re.sub(r'<img[^>]*src="([^"]+)"[^>]*/>', r'![](\1)', text)
        
        # 粗体/斜体
        text = re.sub(r'<(strong|b)>(.*?)</\1>', r'**\2**', text)
        text = re.sub(r'<(em|i)>(.*?)</\1>', r'*\2*', text)
        
        # 列表
        text = re.sub(r'<li>(.*?)</li>', r'- \1', text)
        
        # 代码块
        text = re.sub(r'<pre><code>(.*?)</code></pre>', r'```\n\1\n```', text)
        text = re.sub(r'<code>(.*?)</code>', r'`\1`', text)
        
        # 标题
        for i in range(6, 0, -1):
            text = re.sub(f'<h{i}[^>]*>(.*?)</h{i}>', '#' * i + ' \\1', text)
        
        # 解码HTML实体
        text = html.unescape(text)
        
        # 移除剩余标签
        text = re.sub(r'<[^>]+>', '', text)
        
        # 折叠多余空行
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = re.sub(r' {2,}', ' ', text)
        
        return text.strip()


class RSSFetcher:
    """RSS/Atom源抓取器（无外部依赖，纯标准库实现）"""
    
    @staticmethod
    def fetch(url: str, timeout: int = 15) -> Optional[str]:
        """抓取RSS源内容"""
        import urllib.request
        import ssl
        
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "KarpathyKB-RSS/1.0",
                "Accept": "application/rss+xml, application/xml, text/xml, */*"
            }
        )
        
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                return raw
        except Exception as e:
            logger.warning(f"抓取失败 [{url}]: {e}")
            return None
    
    @staticmethod
    def parse_rss(xml: str) -> List[dict]:
        """解析RSS 2.0 XML（无外部依赖，简单xml.etree实现）"""
        import xml.etree.ElementTree as ET
        
        items = []
        try:
            root = ET.fromstring(xml)
        except ET.ParseError as e:
            logger.warning(f"XML解析错误: {e}")
            return items
        
        # 处理RSS 2.0
        channel = root.find("channel")
        if channel is not None:
            for item in channel.findall("item"):
                article = RSSFetcher._extract_rss_item(item, channel)
                if article:
                    items.append(article)
            return items
        
        # 处理Atom
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        entries = root.findall("atom:entry", ns) or root.findall("entry")
        for entry in entries:
            article = RSSFetcher._extract_atom_entry(entry, root, ns)
            if article:
                items.append(article)
        
        return items
    
    @staticmethod
    def _extract_rss_item(item, channel) -> Optional[dict]:
        def g(tag):
            el = item.find(tag)
            return el.text.strip() if el is not None and el.text else ""
        
        title = g("title")
        link = g("link")
        
        if not title or not link:
            return None
        
        # 内容（优先content:encoded）
        content = ""
        for tag in ["content:encoded", "description"]:
            el = item.find(tag)
            if el is not None and el.text:
                content = el.text.strip()
                break
        
        return {
            "title": title,
            "url": link,
            "content": content,
            "summary": g("description")[:500] if g("description") else "",
            "author": g("author") or "",
            "published": g("pubDate") or "",
        }
    
    @staticmethod
    def _extract_atom_entry(entry, root, ns) -> Optional[dict]:
        atom_ns = ns.get("atom", "")

        def find(tag):
            return entry.find(tag) or entry.find(f"{{{atom_ns}}}{tag}")

        def g(tag):
            el = find(tag)
            return el.text.strip() if el is not None and el.text else ""
        
        def get_href(tag):
            candidates = list(entry.findall(tag)) + list(entry.findall(f"{{{atom_ns}}}{tag}"))
            for el in candidates:
                rel = el.attrib.get("rel", "alternate")
                href = el.attrib.get("href", "")
                if href and rel == "alternate":
                    return href
            return candidates[0].attrib.get("href", "") if candidates else ""

        def author_name():
            author = find("author")
            if author is None:
                return ""
            name = author.find("name") or author.find(f"{{{atom_ns}}}name")
            if name is not None and name.text:
                return name.text.strip()
            return author.text.strip() if author.text else ""
        
        title = g("title")
        link = get_href("link") or g("link")
        
        if not title or not link:
            return None
        
        # 内容
        content = ""
        for tag in ["content", "summary"]:
            el = find(tag)
            if el is not None and el.text:
                content = el.text.strip()
                break
        
        return {
            "title": title,
            "url": link,
            "content": content,
            "summary": content[:500],
            "author": author_name(),
            "published": g("published") or g("updated") or "",
        }


class RSSManager:
    """RSS订阅管理器"""
    
    def __init__(self, kb_dir: Path = KB_DIR):
        self.kb_dir = Path(kb_dir)
        self.raw_dir = self.kb_dir / "raw" / "rss_candidates"
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.candidate_dir = self.raw_dir
        self.config_file = self.kb_dir / "rss_feeds.json"
        self.imported_file = self.kb_dir / "rss_imported.json"
        policy = load_translation_policy(self.kb_dir)
        policy_preview = full_translate_enabled(policy, "rss_candidate_preview")
        env_preview = os.environ.get("KB_RSS_GENERATE_PREVIEW")
        self.generate_preview = policy_preview if env_preview is None else env_preview.lower() not in {"0", "false", "no", "off"}
        
        self.config: Dict[str, FeedSource] = {}
        self.imported: Dict[str, Set[str]] = {}  # source_name -> set of content_hashes
        self._load_config()
        self._load_imported()
    
    def _load_config(self):
        """加载订阅配置"""
        if self.config_file.exists():
            try:
                raw = json.loads(self.config_file.read_text())
                self.config = {}
                for k, v in raw.items():
                    self.config[k] = FeedSource(**v)
                logger.info(f"已加载 {len(self.config)} 个RSS订阅源")
            except Exception as e:
                logger.warning(f"加载配置失败: {e}")
        
        # 默认示例源（已注释，需要用户启用）
        if not self.config:
            self._add_default_feeds()
    
    def _add_default_feeds(self):
        """添加默认示例源（用户需自行配置实际感兴趣的源）"""
        defaults = {}
        self.config_file.write_text(json.dumps(defaults, ensure_ascii=False, indent=2))
        logger.info("已创建默认配置（空），请编辑 rss_feeds.json 添加订阅源")
    
    def _load_imported(self):
        """加载已导入记录"""
        if self.imported_file.exists():
            try:
                raw = json.loads(self.imported_file.read_text())
                self.imported = {k: set(v) for k, v in raw.items()}
            except Exception:
                self.imported = {}
        else:
            self.imported = {}
    
    def _save_imported(self):
        """保存已导入记录"""
        raw = {k: list(v) for k, v in self.imported.items()}
        self.imported_file.write_text(json.dumps(raw, ensure_ascii=False, indent=2))
    
    # ========== 公开方法 ==========
    
    def add_feed(self, url: str, name: str = "", category: str = "articles",
                 interval: int = 360) -> bool:
        """添加订阅源"""
        if not name:
            name = urlparse(url).netloc or url
        
        key = name.lower().replace(" ", "_")
        self.config[key] = FeedSource(
            url=url, name=name, category=category,
            interval_minutes=interval
        )
        self._save_config()
        logger.info(f"已添加订阅源: {name} ({url})")
        return True
    
    def remove_feed(self, name_or_url: str) -> bool:
        """删除订阅源"""
        for key, feed in list(self.config.items()):
            if feed.name == name_or_url or feed.url == name_or_url or key == name_or_url:
                del self.config[key]
                self._save_config()
                logger.info(f"已删除订阅源: {feed.name}")
                return True
        return False
    
    def list_feeds(self) -> List[FeedSource]:
        """列出所有订阅源"""
        return list(self.config.values())
    
    def _save_config(self):
        """保存配置"""
        raw = {k: asdict(v) for k, v in self.config.items()}
        self.config_file.write_text(json.dumps(raw, ensure_ascii=False, indent=2))
    
    def sync_all(self, max_per_source: int = 5, auto_process: bool = True) -> Dict:
        """同步所有启用的订阅源
        auto_process: 同步后自动调用auto_importer处理新文章"""
        results = {"new": 0, "skipped": 0, "errors": 0, "articles": []}
        
        for key, feed in self.config.items():
            if not feed.enabled:
                continue
            
            try:
                source_result = self._sync_source(feed, max_per_source)
                results["new"] += source_result["new"]
                results["skipped"] += source_result["skipped"]
                results["errors"] += source_result["errors"]
                results["articles"].extend(source_result["articles"])
            except Exception as e:
                logger.error(f"同步失败 [{feed.name}]: {e}")
                results["errors"] += 1
        
        self._save_imported()
        
        return results
    
    def _sync_source(self, feed: FeedSource, max_articles: int) -> Dict:
        """同步单个订阅源"""
        result = {"new": 0, "skipped": 0, "errors": 0, "articles": []}
        
        logger.info(f"正在抓取: {feed.name} ({feed.url})")
        xml = RSSFetcher.fetch(feed.url)
        if not xml:
            result["errors"] = 1
            return result
        
        raw_items = RSSFetcher.parse_rss(xml)
        if not raw_items:
            logger.warning(f"未解析到文章: {feed.name}")
            result["errors"] = 1
            return result
        
        logger.info(f"  解析到 {len(raw_items)} 篇文章")
        
        # 已导入的hash
        imported_hashes = self.imported.get(feed.name, set())
        
        count = 0
        for item in raw_items:
            if count >= max_articles:
                break
            
            # 生成内容hash用于去重
            content_hash = hashlib.md5(
                (item["title"] + item["url"]).encode()
            ).hexdigest()[:12]
            
            if content_hash in imported_hashes:
                result["skipped"] += 1
                continue
            
            try:
                article = Article(
                    title=item["title"],
                    url=item["url"],
                    content=item.get("content", ""),
                    summary=item.get("summary", ""),
                    author=item.get("author", ""),
                    published=item.get("published", ""),
                    source=feed.url,
                    source_name=feed.name,
                    content_hash=content_hash
                )
                
                # 写入Markdown文件
                self._save_article(article, feed.category)
                
                # 记录已导入
                imported_hashes.add(content_hash)
                result["new"] += 1
                result["articles"].append(article)
                count += 1
                
            except Exception as e:
                logger.error(f"  保存失败 [{item.get('title', '?')}]: {e}")
                result["errors"] += 1
        
        self.imported[feed.name] = imported_hashes
        logger.info(f"  → {feed.name}: {result['new']} 新 / {result['skipped']} 跳过")
        
        return result
    
    def _auto_import(self):
        """自动导入新文章到知识库"""
        try:
            import subprocess
            scripts_dir = Path(__file__).parent
            result = subprocess.run(
                ["python3", str(scripts_dir / "auto_importer.py"), "import", "--category", "rss"],
                capture_output=True, text=True, timeout=120
            )
            if result.returncode == 0:
                for line in result.stdout.split(chr(92)+chr(110)):
                    if any(w in line for w in ["新文档", "完成", "成功"]):
                        logger.info(f"  auto_importer: {line.strip()}")
            else:
                logger.warning(f"  auto_importer 返回码: {result.returncode}")
        except Exception as e:
            logger.warning(f"  auto_importer 调用失败: {e}")

    def _save_article(self, article: Article, category: str):
        """保存文章到rss_candidates目录（候选池格式）"""
        article.title = clean_import_title(article.title, fallback="RSS文章")
        safe_title = safe_import_stem(article.title, fallback="rss_article", max_len=60)
        
        filename = f"rss_{safe_title}_{article.content_hash}.md"
        filepath = self.candidate_dir / filename
        meta_path = self.candidate_dir / f"{article.content_hash}_meta.json"
        
        md_content = article.to_markdown()
        filepath.write_text(md_content, encoding="utf-8")
        
        payload = {
            "status": "candidate",
            "source_name": article.source_name or "RSS",
            "url": article.url,
            "title": article.title,
            "author": article.author,
            "publish_time": article.published,
            "content_length": len(md_content),
            "candidate_path": str(filepath.relative_to(self.kb_dir)),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "discovery": {"provider": "rss", "feed": article.source or "", "feed_name": article.source_name},
        }
        meta_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        # 候选中文预览可能调用在线/本地 LLM，耗时和失败面都较大。
        # monitor 周期同步默认关闭，避免单篇翻译阻塞整轮 RSS 拉取；需要时再由候选池批处理补齐。
        if self.generate_preview:
            try:
                import sys
                sys.path.insert(0, str(self.kb_dir / "scripts"))
                from candidate_manager import CandidateManager  # type: ignore
                from translator import CandidateTranslator  # type: ignore
                cm = CandidateManager(self.kb_dir)
                meta_item = {
                    "id": cm._candidate_id(filepath, payload),
                    "title": article.title,
                    "source_name": article.source_name or "RSS",
                    "author": article.author,
                    "url": article.url,
                    "publish_time": article.published,
                    "candidate_type": "rss",
                }
                CandidateTranslator(self.kb_dir).translate_preview_candidate(meta_item, md_content, force=False)
                logger.info(f"  → 中文预览已生成: {meta_item['id']}")
            except Exception as e:
                logger.warning(f"  → 中文预览生成失败（保留英文候选）: {e}")
        
        logger.info(f"  → 候选池: {filename} ({len(md_content)} 字符)")
    
    def print_summary(self):
        """打印订阅源摘要"""
        feeds = self.list_feeds()
        total_imported = sum(len(h) for h in self.imported.values())
        
        print(f"\n{'='*50}")
        print(f"📡 RSS订阅管理")
        print(f"{'='*50}")
        print(f"  订阅源: {len(feeds)} 个")
        print(f"  已导入: {total_imported} 篇文章")
        print(f"  保存到: {self.raw_dir}")
        print()
        
        if feeds:
            print(f"  {'名称':<20} {'分类':<15} {'间隔':<8} {'状态':<6}")
            print(f"  {'-'*20} {'-'*15} {'-'*8} {'-'*6}")
            for feed in feeds:
                status = "🟢" if feed.enabled else "🔴"
                interval = f"{feed.interval_minutes}min"
                print(f"  {feed.name:<20} {feed.category:<15} {interval:<8} {status:<6}")
            print()
            print(f"  编辑配置: {self.config_file}")
        else:
            print(f"  ⚠️  暂无订阅源")
            print(f"  添加: kb_cli.py rss add <url> --name <名称> --category <分类>")
            print(f"  或编辑: {self.config_file}")


# ========== 命令行入口 ==========

def main():
    import argparse
    parser = argparse.ArgumentParser(description="RSS订阅同步工具")
    parser.add_argument("action", nargs="?", default="sync",
                        choices=["sync", "list", "add", "remove"])
    parser.add_argument("url", nargs="?", help="RSS URL")
    parser.add_argument("--name", help="订阅源名称")
    parser.add_argument("--category", default="articles", help="文章分类")
    parser.add_argument("--interval", type=int, default=360, help="同步间隔(分钟)")
    parser.add_argument("--max", type=int, default=5, help="每次最大文章数")
    
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    mgr = RSSManager()
    
    if args.action == "list":
        mgr.print_summary()
    
    elif args.action == "add":
        if not args.url:
            print("请提供RSS URL")
            return 1
        mgr.add_feed(args.url, args.name or "", args.category, args.interval)
        mgr.print_summary()
    
    elif args.action == "remove":
        if not args.url:
            print("请提供要删除的订阅源名称或URL")
            return 1
        if mgr.remove_feed(args.url):
            print(f"已删除: {args.url}")
        else:
            print(f"未找到: {args.url}")
    
    elif args.action == "sync":
        mgr.print_summary()
        result = mgr.sync_all(max_per_source=args.max)
        print(f"\n同步完成: {result['new']} 新文章, {result['skipped']} 跳过, {result['errors']} 错误")
    
    return 0


if __name__ == "__main__":
    exit(main())
