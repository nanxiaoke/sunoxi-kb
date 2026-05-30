#!/usr/bin/env python3
"""
网页内容收集器 v3 — 重构版
- 并发多源抓取（谁先成功用谁）
- URL 格式校验 + 黑名单过滤
- 进度回调支持
- 更好的错误分类和提示
- 支持自定义 User-Agent / Referer
"""

import os
import sys
import json
import hashlib
import logging
import re
import time
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Dict, Optional, Tuple, Callable
from urllib.parse import quote, urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    from import_quality import clean_import_title, safe_import_stem
except ImportError:
    from .import_quality import clean_import_title, safe_import_stem

logger = logging.getLogger(__name__)

# ── URL 黑名单（内部地址、危险地址） ──────────────────────────
BLOCKED_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1", "169.254.0.0/16"}
BLOCKED_SCHEMES = {"file", "ftp", "gopher", "javascript", "data"}

_URL_PATTERN = re.compile(
    r"^https?://[^\s/$.?#].[^\s]*$", re.IGNORECASE
)


class FetchError(Exception):
    """抓取错误（携带分类标签）"""
    def __init__(self, message: str, kind: str = "unknown"):
        super().__init__(message)
        self.kind = kind  # timeout | blocked | bad_url | http_error | service_down | empty | unknown


class WebCollector:
    """网页内容收集器 v3 — 并发多源 + 降级"""

    # ── 抓取服务配置 ──────────────────────────────────────
    SERVICES = [
        {
            "name": "jina",
            "url_template": "https://r.jina.ai/{encoded_url}",
            "headers": {
                "Accept": "text/markdown,text/plain;q=0.9",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            },
            "timeout": 30,
        },
        {
            "name": "markdown",
            "url_template": "https://markdown.new/{encoded_url}",
            "headers": {
                "Accept": "text/markdown,text/plain;q=0.9",
            },
            "timeout": 25,
        },
        {
            "name": "defuddle",
            "url_template": "https://defuddle.md/{encoded_url}",
            "headers": {
                "Accept": "text/markdown,text/plain;q=0.9",
            },
            "timeout": 25,
        },
    ]

    def __init__(self, base_dir: str = None, extra_headers: Dict[str, str] = None):
        self.base_dir = Path(base_dir) if base_dir else Path(__file__).resolve().parent.parent
        self.raw_dir = self.base_dir / "raw" / "webpages"
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.extra_headers = extra_headers or {}

    # ── URL 校验 ─────────────────────────────────────────
    @staticmethod
    def validate_url(url: str) -> Tuple[bool, str]:
        """校验 URL 合法性，返回 (ok, reason)"""
        if not url or not isinstance(url, str):
            return False, "URL 为空"

        url = url.strip()
        if not _URL_PATTERN.match(url):
            return False, "URL 格式不合法（仅支持 http/https）"

        try:
            parsed = urlparse(url)
        except Exception:
            return False, "URL 解析失败"

        if parsed.scheme.lower() not in ("http", "https"):
            return False, f"不支持的协议: {parsed.scheme}"

        hostname = (parsed.hostname or "").lower()
        if not hostname:
            return False, "无法解析主机名"

        if hostname in BLOCKED_HOSTS:
            return False, f"禁止访问内部地址: {hostname}"

        if hostname.startswith("127.") or hostname.startswith("10.") or \
           hostname.startswith("192.168.") or hostname.startswith("172."):
            return False, f"禁止访问私有地址: {hostname}"

        return True, ""

    # ── 编码 ────────────────────────────────────────────
    @staticmethod
    def _encode_url(url: str) -> str:
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        return quote(url, safe="")

    @staticmethod
    def _url_hash(url: str) -> str:
        return hashlib.md5(url.encode()).hexdigest()[:12]

    # ── 抓取 ────────────────────────────────────────────
    def _fetch_one(self, svc: Dict, url: str) -> Tuple[str, Dict]:
        """
        使用单个服务抓取。
        返回 (content, metadata)，失败则抛出 FetchError。
        """
        import requests
        encoded = self._encode_url(url)
        target = svc["url_template"].format(encoded_url=encoded)
        headers = {**svc.get("headers", {}), **self.extra_headers}
        timeout = svc.get("timeout", 30)

        try:
            resp = requests.get(target, headers=headers, timeout=timeout)
        except requests.exceptions.Timeout:
            raise FetchError("请求超时", kind="timeout")
        except requests.exceptions.ConnectionError:
            raise FetchError("连接错误", kind="service_down")
        except Exception as e:
            raise FetchError(str(e), kind="unknown")

        if resp.status_code != 200:
            raise FetchError(f"HTTP {resp.status_code}", kind="http_error")

        body = (resp.text or "").strip()
        if not body:
            raise FetchError("返回空内容", kind="empty")

        if len(body) < 80 and "#" not in body and "[" not in body:
            raise FetchError(f"返回内容过短 ({len(body)} 字符)", kind="empty")

        return body, {
            "service": svc["name"],
            "status_code": resp.status_code,
            "content_length": len(body),
        }

    def fetch(self, url: str, callback: Callable[[str, str], None] = None) -> Tuple[bool, str, Dict]:
        """
        并发多源抓取，返回 (ok, content, metadata)。
        callback(event, detail) 可选，用于上报进度: "started" / "trying" / "ok" / "failed"
        """
        # 1. 校验
        valid, reason = self.validate_url(url)
        if not valid:
            if callback:
                callback("failed", f"URL 不合法: {reason}")
            return False, f"URL 不合法: {reason}", {"error_kind": "bad_url"}

        if callback:
            callback("started", url)

        # 2. 微信公众号特殊处理（同步，因为 wechat_fetcher 是本地调用）
        if "mp.weixin.qq.com" in url:
            if callback:
                callback("trying", "wechat_fetcher")
            try:
                sys.path.insert(0, str(Path(__file__).parent))
                from wechat_fetcher import WeChatFetcher
                fetcher = WeChatFetcher(base_dir=str(self.base_dir))
                ok, html, _ = fetcher.fetch_article_html(url)
                if ok:
                    article = fetcher.extract_article_data(html)
                    content = article.get("content", "")
                    if content:
                        meta = {
                            "title": article.get("title", ""),
                            "author": article.get("author", ""),
                            "method_used": "wechat_fetcher",
                        }
                        if meta["title"] and not content.strip().startswith("#"):
                            content = f"# {meta['title']}\n\n{content}"
                        if callback:
                            callback("ok", "wechat_fetcher")
                        return True, content, meta
            except Exception:
                pass  # 回退到通用服务

        # 3. 并发多源
        errors: List[Tuple[str, str]] = []
        with ThreadPoolExecutor(max_workers=len(self.SERVICES)) as pool:
            futures = {
                pool.submit(self._fetch_one, svc, url): svc["name"]
                for svc in self.SERVICES
            }
            for fut in as_completed(futures):
                svc_name = futures[fut]
                if callback:
                    callback("trying", svc_name)
                try:
                    content, meta = fut.result()
                    meta["method_used"] = svc_name
                    if callback:
                        callback("ok", svc_name)
                    return True, content, meta
                except FetchError as e:
                    errors.append((svc_name, str(e)))
                except Exception as e:
                    errors.append((svc_name, str(e)))

        # 全部失败
        err_msg = "所有抓取服务均失败:\n" + "\n".join(f"  {n}: {m}" for n, m in errors)
        if callback:
            callback("failed", err_msg)
        return False, err_msg, {"errors": errors}

    # ── 保存 ────────────────────────────────────────────
    def _extract_title(self, content: str, url: str) -> str:
        meta_title = re.search(r'(?m)^title:\s*["\']?(.+?)["\']?\s*$', content[:2000])
        if meta_title:
            title = clean_import_title(meta_title.group(1), fallback="")
            if title and len(title) < 200:
                return title
        for line in content.split("\n")[:30]:
            line = line.strip()
            if line.startswith("# "):
                title = clean_import_title(line[2:], fallback="")
                if title and len(title) < 200:
                    return title
        parsed = urlparse(url)
        domain = (parsed.hostname or "").replace("www.", "")
        path_parts = [p for p in parsed.path.strip("/").split("/") if p]
        if path_parts:
            last = path_parts[-1].replace("-", " ").replace("_", " ")[:50]
            return clean_import_title(f"{domain} — {last}" if domain else f"网页_{self._url_hash(url)}")
        return domain or f"网页_{self._url_hash(url)}"

    def save(self, url: str, content: str, metadata: Dict) -> Optional[Path]:
        """保存抓取结果为 Markdown 文件"""
        title = clean_import_title(self._extract_title(content, url), fallback=f"网页_{self._url_hash(url)}")
        uh = self._url_hash(url)
        safe = safe_import_stem(title, fallback="webpage", max_len=50)
        filename = f"{safe}_{uh}.md"
        filepath = self.raw_dir / filename

        method = metadata.get("method_used", "unknown")
        now_iso = datetime.now(timezone.utc).isoformat()

        md = (
            f"# {title}\n\n"
            f"> **来源**: {url}\n"
            f"> **抓取时间**: {now_iso}\n"
            f"> **抓取方法**: {method}\n"
            f"> **内容长度**: {len(content)} 字符\n\n"
            f"---\n\n{content}\n\n"
            f"---\n\n"
            f"## 元数据\n\n"
            f"- URL: {url}\n"
            f"- 时间: {now_iso}\n"
            f"- 方法: {method}\n"
            f"- 长度: {len(content)} 字符\n"
        )
        filepath.write_text(md, encoding="utf-8")

        # 元数据 JSON
        meta_path = self.raw_dir / f"{uh}_meta.json"
        meta_path.write_text(json.dumps({
            "url": url, "title": title, "filename": filename,
            "method_used": method, "content_length": len(content),
            "hash": uh, "saved_at": now_iso, "filepath": str(filepath),
        }, ensure_ascii=False, indent=2), encoding="utf-8")

        logger.info("Saved: %s (%d chars)", filename, len(content))
        return filepath

    def process_url(self, url: str, callback: Callable[[str, str], None] = None) -> bool:
        """抓取 + 保存一站式"""
        ok, content, metadata = self.fetch(url, callback)
        if not ok:
            return False
        return self.save(url, content, metadata) is not None

    def process_urls(self, urls: List[str], delay: float = 1.0,
                     callback: Callable[[str, str], None] = None) -> Dict[str, bool]:
        """批量处理 URL"""
        results = {}
        for i, url in enumerate(urls):
            logger.info("[%d/%d] %s", i + 1, len(urls), url[:80])
            results[url] = self.process_url(url, callback)
            if i < len(urls) - 1:
                time.sleep(delay)
        return results

    def process_url_file(self, filepath: str, **kwargs) -> Dict[str, bool]:
        p = Path(filepath)
        if not p.exists():
            logger.error("File not found: %s", filepath)
            return {}
        urls = [l.strip() for l in p.read_text(encoding="utf-8").splitlines()
                if l.strip() and not l.strip().startswith("#")]
        return self.process_urls(urls, **kwargs)


# ── CLI ────────────────────────────────────────────────
def main():
    import argparse

    parser = argparse.ArgumentParser(description="网页内容收集器 v3")
    parser.add_argument("--url", help="单个 URL")
    parser.add_argument("--file", help="URL 列表文件（每行一个）")
    parser.add_argument("--delay", type=float, default=1.0, help="批量间隔秒数")
    parser.add_argument("--test", action="store_true", help="测试模式")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    wc = WebCollector()

    if args.test:
        test_urls = ["https://www.example.com", "https://www.python.org"]
        for u in test_urls:
            ok = wc.process_url(u, callback=lambda ev, dt: print(f"  [{ev}] {dt}"))
            print(f"  {'✅' if ok else '❌'} {u}")
        return 0

    if args.url:
        ok = wc.process_url(args.url, callback=lambda ev, dt: print(f"  [{ev}] {dt}"))
        return 0 if ok else 1

    if args.file:
        results = wc.process_url_file(args.file, delay=args.delay)
        ok_count = sum(1 for v in results.values() if v)
        print(f"\n完成: {ok_count}/{len(results)}")
        return 0 if ok_count else 1

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
