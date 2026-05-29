#!/usr/bin/env python3
"""
微信公众号订阅发现器

目标：根据 wechat_sources.json 管理的公众号订阅，发现/抓取文章进入候选池，不直接入库。

现实限制：微信公众号历史消息页 profile_ext 通常返回验证页；因此 discovery 第一版采用：
1) profile_ext 探测并记录状态；
2) 若提供 --url，则抓取指定 URL；
3) 若无 --url，则用样例 sample_url 做可用性验证，避免伪造“最近文章”发现结果；
4) 使用搜索发现候选文章；能抓取 mp.weixin.qq.com 正文则写入正文候选，不能抓取则写入外部链接候选。

用法：
  python3 scripts/wechat_discovery.py --source 数字生命卡兹克 --since 2026-04-01 --limit 10
  python3 scripts/wechat_discovery.py --source 数字生命卡兹克 --url 'https://mp.weixin.qq.com/s/...'
"""

from __future__ import annotations

import argparse
import html as html_lib
import hashlib
import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote, urljoin

import requests
from bs4 import BeautifulSoup

KB_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KB_DIR / "scripts"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

from wechat_fetcher import WeChatFetcher  # type: ignore


class WeChatDiscovery:
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir.resolve()
        self.sources_file = self.base_dir / "wechat_sources.json"
        self.candidate_dir = self.base_dir / "raw" / "wechat_candidates"
        self.fetcher = WeChatFetcher(str(self.base_dir))
        self.candidate_dir.mkdir(parents=True, exist_ok=True)

    def load_sources(self) -> Dict[str, Any]:
        if self.sources_file.exists():
            return json.loads(self.sources_file.read_text(encoding="utf-8"))
        return {}

    def save_sources(self, sources: Dict[str, Any]) -> None:
        self.sources_file.write_text(json.dumps(sources, ensure_ascii=False, indent=2), encoding="utf-8")

    def list_sources(self) -> List[Dict[str, Any]]:
        sources = self.load_sources()
        out = []
        for name, data in sources.items():
            item = dict(data)
            item.setdefault("name", name)
            out.append(item)
        return sorted(out, key=lambda x: x.get("priority", ""), reverse=True)

    def upsert_source(self, name: str, sample_url: str = "", tags: Optional[List[str]] = None, priority: str = "normal") -> Dict[str, Any]:
        sources = self.load_sources()
        existing = sources.get(name, {})
        biz = existing.get("biz")
        user_name = existing.get("user_name")
        if sample_url:
            try:
                ok, html, _ = self.fetcher.fetch_article_html(sample_url)
                if ok:
                    biz, user_name = self._extract_ids(html, sample_url)
            except Exception:
                pass
        sources[name] = {
            **existing,
            "enabled": existing.get("enabled", True),
            "name": name,
            "sample_url": sample_url or existing.get("sample_url", ""),
            "biz": biz,
            "user_name": user_name,
            "tags": tags if tags is not None else existing.get("tags", []),
            "priority": priority or existing.get("priority", "normal"),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self.save_sources(sources)
        return sources[name]

    def _extract_ids(self, html: str, url: str = "") -> tuple[Optional[str], Optional[str]]:
        params = self.fetcher.extract_wechat_params(url) if url else {}
        biz_match = re.search(r"var\s+biz\s*=\s*[\"']([^\"']+)", html) or re.search(r"__biz=([A-Za-z0-9_=\-]+)", html)
        user_match = re.search(r"var\s+user_name\s*=\s*[\"']([^\"']+)", html)
        biz = biz_match.group(1) if biz_match else params.get("__biz")
        user_name = user_match.group(1) if user_match else None
        return biz, user_name

    def _extract_publish_time(self, html: str, article: Dict[str, Any]) -> str:
        m = re.search(r"var\s+(?:oriCreateTime|ct)\s*=\s*[\"']?([^\"';]+)", html)
        if m:
            try:
                return datetime.fromtimestamp(int(str(m.group(1)).strip("'\" ")), tz=timezone.utc).isoformat()
            except Exception:
                pass
        return article.get("publish_time") or ""

    def test_profile_ext(self, biz: Optional[str]) -> Dict[str, Any]:
        if not biz:
            return {"ok": False, "reason": "missing_biz"}
        try:
            url = f"https://mp.weixin.qq.com/mp/profile_ext?action=home&__biz={biz}&scene=124#wechat_redirect"
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0 (Linux; Android 10) MicroMessenger/8.0.40"}, timeout=20)
            text = r.text or ""
            return {
                "ok": r.status_code == 200,
                "status_code": r.status_code,
                "length": len(text),
                "is_verify": "验证" in text[:500] or "captcha" in text.lower()[:1000],
                "has_msg_list": "msgList" in text or "app_msg_list" in text,
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def save_candidate(self, source_name: str, url: str) -> Dict[str, Any]:
        ok, html, meta = self.fetcher.fetch_article_html(url)
        if not ok:
            return {"ok": False, "url": url, "error": str(html)[:500]}
        article = self.fetcher.extract_article_data(html)
        biz, user_name = self._extract_ids(html, url)
        publish_time = self._extract_publish_time(html, article)
        content = article.get("content", "")
        url_hash = hashlib.md5(url.encode("utf-8")).hexdigest()[:12]
        safe_title = "".join(c for c in article.get("title", "wechat_article") if c.isalnum() or c in " -_")[:80] or "wechat_article"
        md_path = self.candidate_dir / f"{safe_title}_{url_hash}.md"
        meta_path = self.candidate_dir / f"{url_hash}_meta.json"
        md = f'''# {article.get('title', '微信公众号文章')}

> **候选来源**: {source_name}
> **作者**: {article.get('author') or '未知'}
> **公众号biz**: {biz or '未知'}
> **公众号user_name**: {user_name or '未知'}
> **发布时间**: {publish_time or '未知'}
> **原文链接**: {url}
> **抓取时间**: {datetime.now(timezone.utc).isoformat()}
> **状态**: candidate
> **建议分类**: AI/LLM/Agent/工程实践

---

{content}
'''
        md_path.write_text(md, encoding="utf-8")
        payload = {
            "status": "candidate",
            "source_name": source_name,
            "url": url,
            "title": article.get("title"),
            "author": article.get("author"),
            "account": article.get("account"),
            "biz": biz,
            "user_name": user_name,
            "publish_time": publish_time,
            "content_length": len(content),
            "candidate_path": str(md_path.relative_to(self.base_dir)),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "fetch": {"ok": True, "status_code": meta.get("status_code"), "content_length": meta.get("content_length"), "elapsed_time": meta.get("elapsed_time")},
        }
        meta_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"ok": True, "candidate": str(md_path.relative_to(self.base_dir)), "meta": str(meta_path.relative_to(self.base_dir)), **payload}


    def save_external_candidate(self, source_name: str, item: Dict[str, Any]) -> Dict[str, Any]:
        """保存无法直接抓正文的搜索结果为外部链接候选。"""
        url = item.get("url") or ""
        title = item.get("title") or "外部候选文章"
        url_hash = hashlib.md5(url.encode("utf-8")).hexdigest()[:12]
        safe_title = "".join(c for c in title if c.isalnum() or c in " -_")[:80] or "external_candidate"
        md_path = self.candidate_dir / f"{safe_title}_{url_hash}.md"
        meta_path = self.candidate_dir / f"{url_hash}_meta.json"
        md = f'''# {title}

> **候选来源**: {source_name}
> **候选类型**: external_link
> **发现来源**: {item.get('provider', 'search')}
> **发布时间**: {item.get('publish_time') or '未知'}
> **原文/来源链接**: {url}
> **抓取时间**: {datetime.now(timezone.utc).isoformat()}
> **状态**: candidate_external
> **说明**: 该候选来自搜索发现，暂未直接抓取到微信正文；请人工确认后再决定是否手动补正文或导入。

---

{item.get('snippet') or '（无摘要）'}
'''
        md_path.write_text(md, encoding="utf-8")
        payload = {
            "status": "candidate_external",
            "source_name": source_name,
            "url": url,
            "title": title,
            "author": item.get("source") or "",
            "publish_time": item.get("publish_time") or "",
            "content_length": len(item.get("snippet") or ""),
            "candidate_path": str(md_path.relative_to(self.base_dir)),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "discovery": item,
        }
        meta_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"ok": True, "external": True, "candidate": str(md_path.relative_to(self.base_dir)), "meta": str(meta_path.relative_to(self.base_dir)), **payload}

    def search_sogou_weixin(self, source_name: str, since: Optional[str] = None, limit: int = 10) -> List[Dict[str, Any]]:
        """通过搜狗微信搜索发现候选文章。返回搜索结果，不保证可直接解析为 mp.weixin 原文。"""
        url = "https://weixin.sogou.com/weixin?type=2&query=" + quote(source_name)
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
            "Referer": "https://weixin.sogou.com/",
        }
        r = requests.get(url, headers=headers, timeout=20)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        since_ts = None
        if since:
            try:
                since_ts = int(datetime.fromisoformat(since).replace(tzinfo=timezone.utc).timestamp())
            except Exception:
                since_ts = None
        items: List[Dict[str, Any]] = []
        for li in soup.select("li"):
            a = li.select_one(".txt-box h3 a") or li.select_one("h3 a")
            if not a:
                continue
            raw_href = html_lib.unescape(a.get("href") or "")
            if not raw_href:
                continue
            resolved = urljoin("https://weixin.sogou.com", raw_href)
            title = a.get_text(" ", strip=True)
            snippet_el = li.select_one(".txt-info")
            snippet = snippet_el.get_text(" ", strip=True) if snippet_el else ""
            source_el = li.select_one(".s-p .all-time-y2")
            source = source_el.get_text(" ", strip=True) if source_el else ""
            ts = None
            m = re.search(r"timeConvert\('?(\d+)'?\)", str(li))
            if m:
                try:
                    ts = int(m.group(1))
                except Exception:
                    ts = None
            if since_ts and ts and ts < since_ts:
                continue
            publish_time = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat() if ts else ""
            items.append({
                "provider": "sogou_weixin",
                "title": title,
                "url": resolved,
                "snippet": snippet,
                "source": source,
                "publish_time": publish_time,
                "timestamp": ts,
            })
            if len(items) >= max(limit, 1):
                break
        return items

    def _infer_source_from_url(self, url: str) -> Optional[str]:
        """根据文章 URL 提取 biz，匹配已订阅的公众号。"""
        try:
            ok, html, _ = self.fetcher.fetch_article_html(url)
            if not ok:
                return None
            params = self.fetcher.extract_wechat_params(url)
            biz_match = re.search(r"var\s+biz\s*=\s*[\"']([^\"']+)", html) or re.search(r"__biz=([A-Za-z0-9_=\-]+)", html)
            biz = biz_match.group(1) if biz_match else params.get("__biz")
            if not biz:
                return None
            sources = self.load_sources()
            for name, cfg in sources.items():
                if cfg.get("biz") == biz or cfg.get("user_name") and cfg["user_name"] in html:
                    return name
        except Exception:
            pass
        return None

    def discover(self, source: Optional[str] = None, since: Optional[str] = None, limit: int = 10, url: Optional[str] = None) -> Dict[str, Any]:
        sources = self.load_sources()

        # 如果没指定 source 但提供了 URL，自动匹配公众号
        if not source and url and sources:
            inferred = self._infer_source_from_url(url)
            if inferred:
                source = inferred
                logger.info(f"  自动匹配公众号: {inferred}")
            else:
                # URL 没有匹配到已订阅源，直接保存为未关联
                logger.info(f"  URL 未匹配到已订阅公众号，保存为未关联")
                candidates = []
                candidates.append(self.save_candidate("未关联公众号", url))
                results = [{
                    "source": "未关联公众号",
                    "biz": None,
                    "user_name": None,
                    "since": since, "limit": limit,
                    "strategy": "url_direct",
                    "note": "URL 未匹配到已订阅公众号，独立保存。",
                    "candidates": candidates,
                }]
                return {"ok": True, "total_sources": 1, "results": results}

        selected = {source: sources[source]} if source and source in sources else sources
        if source and source not in sources:
            # 有 source 名但找不到：如果是 URL 模式，尝试不关联源直接保存
            if url:
                selected = {}
            else:
                return {"ok": False, "error": f"source not found: {source}", "sources": list(sources.keys())}

        results = []
        source_updates = False

        # 如果是 URL 模式且没有匹配到任何源，直接单独保存
        if url and not selected:
            candidates = []
            candidates.append(self.save_candidate("未关联公众号", url))
            results.append({
                "source": "未关联公众号",
                "biz": None,
                "user_name": None,
                "since": since,
                "limit": limit,
                "strategy": "url_direct",
                "note": "URL 未匹配到已订阅公众号，独立保存。",
                "candidates": candidates,
            })
            return {"ok": True, "total_sources": 1, "results": results}

        for name, cfg in selected.items():
            if not cfg.get("enabled", True):
                continue
            biz = cfg.get("biz")
            profile = self.test_profile_ext(biz)
            cfg["profile_ext_status"] = profile
            cfg["last_checked"] = datetime.now(timezone.utc).isoformat()
            source_updates = True
            candidates = []
            discovered = []
            target_urls = []
            if url:
                target_urls.append(url)
            elif cfg.get("sample_url"):
                try:
                    discovered = self.search_sogou_weixin(name, since=since, limit=limit)
                except Exception as e:
                    discovered = [{"provider": "sogou_weixin", "error": str(e)}]
                if not discovered or (len(discovered) == 1 and discovered[0].get("error")):
                    target_urls.append(cfg["sample_url"])
            for u in target_urls[: max(limit, 1)]:
                candidates.append(self.save_candidate(name, u))
            for item in discovered:
                if item.get("error"):
                    continue
                candidates.append(self.save_external_candidate(name, item))
            results.append({
                "source": name,
                "biz": biz,
                "user_name": cfg.get("user_name"),
                "since": since,
                "limit": limit,
                "profile_ext_status": profile,
                "strategy": "url" if url else "search_discovery",
                "note": "profile_ext 返回验证页时，改用搜索发现候选；搜索结果可能是跳转/转载/索引页，需人工确认后导入。",
                "discovered": discovered,
                "candidates": candidates,
            })
        if source_updates:
            self.save_sources(sources)
        return {"ok": True, "total_sources": len(results), "results": results}


def main() -> int:
    p = argparse.ArgumentParser(description="微信公众号订阅发现器")
    p.add_argument("--base-dir", default=str(KB_DIR))
    p.add_argument("--source", help="公众号作者/订阅名")
    p.add_argument("--since", help="YYYY-MM-DD")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--url", help="指定文章 URL，抓取后进入候选池")
    p.add_argument("--list-sources", action="store_true")
    p.add_argument("--add-source", help="新增/更新公众号订阅名")
    p.add_argument("--sample-url", default="")
    p.add_argument("--tags", default="")
    p.add_argument("--priority", default="normal")
    args = p.parse_args()
    wd = WeChatDiscovery(Path(args.base_dir))
    if args.list_sources:
        print(json.dumps({"sources": wd.list_sources()}, ensure_ascii=False, indent=2))
    elif args.add_source:
        tags = [x.strip() for x in args.tags.split(",") if x.strip()]
        print(json.dumps(wd.upsert_source(args.add_source, args.sample_url, tags, args.priority), ensure_ascii=False, indent=2))
    else:
        print(json.dumps(wd.discover(source=args.source, since=args.since, limit=args.limit, url=args.url), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
