#!/usr/bin/env python3
"""
微信公众号文章抓取器
模拟微信客户端，专门处理微信公众号文章抓取
集成到Karpathy知识库项目中
"""

import os
import sys
import re
import json
import time
import hashlib
import logging
import argparse
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional, Tuple, Any
from urllib.parse import urlparse, parse_qs, urljoin
import requests
from bs4 import BeautifulSoup

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOG_DIR = PROJECT_ROOT / "logs"
DEFAULT_LOG_DIR.mkdir(parents=True, exist_ok=True)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(DEFAULT_LOG_DIR / "wechat_fetcher.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class WeChatFetcher:
    """微信公众号文章抓取器"""
    
    # 微信客户端User-Agent配置
    USER_AGENTS = {
        "android": "Mozilla/5.0 (Linux; Android 10; SM-G960F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Mobile Safari/537.36 MicroMessenger/8.0.40.2340(0x28002837) WeChat/arm64 Weixin NetType/WIFI Language/zh_CN ABI/arm64",
        "ios": "Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.40(0x1800282f) NetType/WIFI Language/zh_CN",
        "pc": "Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/86.0.4240.198 Safari/537.36",
        "mobile_chrome": "Mozilla/5.0 (Linux; Android 10; SM-G960F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Mobile Safari/537.36"
    }
    
    # 微信公众号文章常见的参数名
    WECHAT_PARAMS = ['__biz', 'mid', 'idx', 'sn', 'chksm', 'scene', 'ascene', 'subscene']
    
    def __init__(self, base_dir: str = None, user_agent: str = "android"):
        """初始化抓取器"""
        self.base_dir = Path(base_dir) if base_dir else PROJECT_ROOT
        self.raw_wechat_dir = self.base_dir / "raw" / "wechat_articles"
        self.logs_dir = self.base_dir / "logs"
        
        # 创建必要的目录
        self.raw_wechat_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        
        # 请求会话配置
        self.session = requests.Session()
        self.session.timeout = 60
        
        # 设置User-Agent
        self.user_agent = self.USER_AGENTS.get(user_agent, self.USER_AGENTS["android"])
        
        # 基础请求头
        self.base_headers = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Cache-Control": "max-age=0"
        }
        
        logger.info(f"微信公众号抓取器初始化完成，使用User-Agent: {user_agent}")
    
    def log(self, message: str, level: str = "INFO"):
        """记录日志"""
        log_method = getattr(logger, level.lower(), logger.info)
        log_method(message)
    
    def get_url_hash(self, url: str) -> str:
        """生成URL的哈希值，用于文件名"""
        return hashlib.md5(url.encode()).hexdigest()[:12]
    
    def extract_wechat_params(self, url: str) -> Dict[str, str]:
        """提取微信公众号URL参数"""
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        
        wechat_params = {}
        for param in self.WECHAT_PARAMS:
            if param in params and params[param]:
                wechat_params[param] = params[param][0]
        
        if wechat_params:
            logger.info(f"提取微信公众号参数: {wechat_params}")
        
        return wechat_params
    
    def build_wechat_headers(self, url: str) -> Dict[str, str]:
        """构建微信公众号专用请求头"""
        headers = self.base_headers.copy()
        
        # 添加Referer（重要）
        headers["Referer"] = "https://mp.weixin.qq.com/"
        
        # 如果是微信公众号文章URL，添加特定头部
        if 'mp.weixin.qq.com' in url:
            headers["Origin"] = "https://mp.weixin.qq.com"
            headers["Sec-Fetch-Site"] = "same-origin"
            
            # 添加微信公众号特定头部
            headers["X-Requested-With"] = "XMLHttpRequest"
            headers["X-DevTools-Emulate-Network-Conditions-Client-Id"] = "true"
        
        return headers
    
    def fetch_article_html(self, url: str) -> Tuple[bool, str, Dict]:
        """抓取微信公众号文章HTML"""
        try:
            logger.info(f"开始抓取微信公众号文章: {url}")
            
            # 构建请求头
            headers = self.build_wechat_headers(url)
            
            # 发送请求
            start_time = time.time()
            response = self.session.get(url, headers=headers, timeout=30)
            elapsed = time.time() - start_time
            
            if response.status_code == 200:
                html_content = response.text
                content_length = len(html_content)
                
                logger.info(f"抓取成功: HTTP 200, {content_length}字符, 耗时{elapsed:.2f}秒")
                
                # 检查是否有错误提示（仅用于日志）
                if self._has_error_page(html_content):
                    logger.debug("页面可能包含错误提示")
                
                # 检查是否有文章内容（仅用于日志）
                has_content = self._has_article_content(html_content)
                if not has_content:
                    logger.debug("页面未检测到明显文章内容")
                
                return True, html_content, {
                    "status_code": response.status_code,
                    "content_length": content_length,
                    "elapsed_time": elapsed,
                    "headers": dict(response.headers)
                }
            else:
                logger.warning(f"抓取失败: HTTP {response.status_code}")
                return False, "", {
                    "status_code": response.status_code,
                    "error": f"HTTP {response.status_code}"
                }
                
        except requests.exceptions.Timeout:
            logger.error(f"请求超时 (30秒)")
            return False, "", {"error": "请求超时"}
        except requests.exceptions.ConnectionError:
            logger.error(f"连接错误")
            return False, "", {"error": "连接错误"}
        except Exception as e:
            logger.error(f"抓取异常: {e}")
            return False, "", {"error": f"异常: {str(e)}"}
    
    def _has_error_page(self, html: str) -> bool:
        """检查是否是错误页面"""
        # 只检测明显的中文错误提示，避免误报
        error_indicators = [
            '参数错误',
            'weui-msg__title',
            'weui-msg__desc',
            '出错',
            '加载失败',
            '无法访问',
            '该内容已被发布者删除',
            '此内容因违规无法查看'
        ]
        
        for indicator in error_indicators:
            if indicator in html:
                return True
        
        return False
    
    def _has_article_content(self, html: str) -> bool:
        """检查页面是否有文章内容"""
        content_selectors = [
            r'<div[^>]*id="js_content"[^>]*>',
            r'<div[^>]*class="rich_media_content"[^>]*>',
            r'<article[^>]*>',
            r'<div[^>]*class="article-content"[^>]*>'
        ]
        
        for selector in content_selectors:
            if re.search(selector, html, re.IGNORECASE):
                return True
        
        # 检查是否有明显的文章文本
        soup = BeautifulSoup(html, 'html.parser')
        text = soup.get_text()
        
        # 如果有较长的连续文本，可能是文章内容
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        long_lines = [line for line in lines if len(line) > 100]
        
        return len(long_lines) > 0
    
    def extract_article_data(self, html: str) -> Dict[str, Any]:
        """从HTML提取文章数据"""
        soup = BeautifulSoup(html, 'html.parser')
        
        article_data = {
            "title": "",
            "author": "",
            "publish_time": "",
            "content": "",
            "extracted": False,
            "extraction_method": ""
        }
        
        # 方法1: 查找#js_content元素（微信公众号标准结构）
        js_content = soup.find('div', {'id': 'js_content'})
        if js_content:
            article_data["content"] = js_content.get_text().strip()
            article_data["extracted"] = True
            article_data["extraction_method"] = "js_content"
            logger.info("使用#js_content提取文章内容")
        
        # 方法2: 查找rich_media_content元素
        if not article_data["extracted"]:
            rich_content = soup.find('div', {'class': 'rich_media_content'})
            if rich_content:
                article_data["content"] = rich_content.get_text().strip()
                article_data["extracted"] = True
                article_data["extraction_method"] = "rich_media_content"
                logger.info("使用.rich_media_content提取文章内容")
        
        # 方法3: 查找article元素
        if not article_data["extracted"]:
            article_elem = soup.find('article')
            if article_elem:
                article_data["content"] = article_elem.get_text().strip()
                article_data["extracted"] = True
                article_data["extraction_method"] = "article"
                logger.info("使用<article>提取文章内容")
        
        # 方法4: 尝试从JavaScript中提取数据
        if not article_data["extracted"]:
            json_data = self._extract_json_from_scripts(html)
            if json_data and "content" in json_data:
                article_data["content"] = json_data["content"]
                article_data["extracted"] = True
                article_data["extraction_method"] = "json_script"
                logger.info("从JavaScript中提取文章内容")
        
        # 提取标题 - 微信公众号常用位置
        title_selectors = [
            {'property': 'og:title'},  # Open Graph标签
            {'name': 'title'},  # meta标签
            {'id': 'activity-name'},  # 活动名称
            {'class': 'rich_media_title'},  # 富媒体标题
            {'class': 'article-title'},  # 文章标题
            'title'  # 默认title标签
        ]
        
        for selector in title_selectors:
            if isinstance(selector, dict):
                # meta标签选择器
                meta_elem = soup.find('meta', selector)
                if meta_elem and meta_elem.get('content'):
                    article_data["title"] = meta_elem['content'].strip()
                    break
            else:
                # 常规标签选择器
                elem = soup.find(selector)
                if elem and elem.text.strip():
                    article_data["title"] = elem.text.strip()
                    break
        
        # 清理标题（移除公众号名称后缀）
        if article_data["title"]:
            # 移除常见的" - 公众号名"格式
            clean_title = article_data["title"]
            if ' - ' in clean_title:
                clean_title = clean_title.split(' - ')[0].strip()
            # 移除常见后缀
            for suffix in [' | 微信公众平台', ' - 微信公众平台', ' - 微信公众号']:
                if clean_title.endswith(suffix):
                    clean_title = clean_title[:-len(suffix)].strip()
            article_data["title"] = clean_title
        
        # 提取作者 - 微信公众号常用位置
        author_selectors = [
            {'property': 'og:article:author'},  # Open Graph作者标签
            {'name': 'author'},  # meta作者标签
            {'class': 'rich_media_meta_text'},  # 富媒体作者文本
            {'id': 'js_name'},  # 公众号名称
            {'class': 'profile_nickname'},  # 昵称
            {'class': 'author'},  # 作者类
            'strong'  # 有时作者在strong标签中
        ]
        
        for selector in author_selectors:
            if isinstance(selector, dict):
                # meta标签选择器
                meta_elem = soup.find('meta', selector)
                if meta_elem and meta_elem.get('content'):
                    article_data["author"] = meta_elem['content'].strip()
                    break
                # div或其他元素选择器
                elem = soup.find('div', selector)
                if elem and elem.text.strip():
                    article_data["author"] = elem.text.strip()
                    break
            else:
                elem = soup.find(selector)
                if elem and elem.text.strip():
                    article_data["author"] = elem.text.strip()
                    break
        
        # 清理作者信息
        if article_data["author"]:
            # 移除常见的"原创"前缀
            author_text = article_data["author"]
            if author_text.startswith('原创'):
                author_text = author_text[2:].strip()
            
            # 移除多余的空格、换行和重复内容
            lines = [line.strip() for line in author_text.split('\n') if line.strip()]
            unique_lines = []
            seen = set()
            for line in lines:
                if line not in seen:
                    seen.add(line)
                    unique_lines.append(line)
            
            # 如果有重复内容，取第一个非空行
            if unique_lines:
                # 如果所有行都相同，只取第一个
                if len(set(unique_lines)) == 1:
                    article_data["author"] = unique_lines[0]
                else:
                    # 尝试找到看起来像作者名的行（非通用文本）
                    for line in unique_lines:
                        if len(line) > 2 and '原创' not in line and '作者' not in line:
                            article_data["author"] = line
                            break
                    else:
                        article_data["author"] = unique_lines[0]
            else:
                article_data["author"] = ""
        
        # 提取发布时间 - 微信公众号常用位置
        time_selectors = [
            {'property': 'article:published_time'},  # Open Graph发布时间
            {'property': 'og:article:published_time'},  # Open Graph发布时间
            {'name': 'publish_date'},  # meta发布日期
            {'class': 'rich_media_meta_text'},  # 富媒体时间文本
            {'class': 'post-date'},  # 发布日期
            {'class': 'publish-time'},  # 发布时间
            {'id': 'publish_time'},  # 发布时间ID
            'time'  # time标签
        ]
        
        for selector in time_selectors:
            if isinstance(selector, dict):
                # meta标签选择器
                meta_elem = soup.find('meta', selector)
                if meta_elem and meta_elem.get('content'):
                    article_data["publish_time"] = meta_elem['content'].strip()
                    break
                # div或其他元素选择器
                elem = soup.find('div', selector)
                if elem and elem.text.strip():
                    article_data["publish_time"] = elem.text.strip()
                    break
            else:
                elem = soup.find(selector)
                if elem and elem.text.strip():
                    article_data["publish_time"] = elem.text.strip()
                    break
        
        # 尝试从JavaScript数据中提取时间
        if not article_data["publish_time"]:
            json_data = self._extract_json_from_scripts(html)
            if json_data and isinstance(json_data, dict):
                time_fields = ['publish_time', 'create_time', 'timestamp', 'date']
                for field in time_fields:
                    if field in json_data:
                        article_data["publish_time"] = str(json_data[field])
                        break
        
        if article_data["extracted"]:
            logger.info(f"文章提取成功: 方法={article_data['extraction_method']}, 内容长度={len(article_data['content'])}字符")
            if article_data["title"]:
                logger.info(f"标题: {article_data['title']}")
            if article_data["author"]:
                logger.info(f"作者: {article_data['author']}")
        else:
            logger.warning("未能提取文章内容")
        
        return article_data
    
    def _extract_json_from_scripts(self, html: str) -> Optional[Dict]:
        """从JavaScript脚本中提取JSON数据"""
        # 查找常见的JSON数据模式
        json_patterns = [
            r'window\.msg\s*=\s*(\{.*?\});',
            r'window\.__REDUX_STATE__\s*=\s*(\{.*?\});',
            r'var\s+msg\s*=\s*(\{.*?\});',
            r'data\s*:\s*(\{.*?\})'
        ]
        
        for pattern in json_patterns:
            match = re.search(pattern, html, re.DOTALL)
            if match:
                json_str = match.group(1)
                try:
                    data = json.loads(json_str)
                    logger.info(f"从脚本提取JSON数据，键: {list(data.keys()) if isinstance(data, dict) else '非字典'}")
                    
                    # 尝试提取内容字段
                    if isinstance(data, dict):
                        content_fields = ['content', 'msg', 'article', 'text', 'html']
                        for field in content_fields:
                            if field in data:
                                return {"content": str(data[field])}
                except json.JSONDecodeError:
                    # 尝试修复常见的JSON问题
                    pass
        
        return None
    
    def save_article(self, url: str, html: str, article_data: Dict[str, Any], metadata: Dict) -> Optional[Path]:
        """保存抓取的文章"""
        try:
            # 生成文件名
            url_hash = self.get_url_hash(url)
            
            # 使用标题或URL作为文件名
            if article_data.get("title"):
                title_slug = "".join(c for c in article_data["title"] if c.isalnum() or c in " -_")[:50]
                filename = f"{title_slug}_{url_hash}.md"
            else:
                filename = f"wechat_article_{url_hash}.md"
            
            filepath = self.raw_wechat_dir / filename
            
            # 构建Markdown内容
            markdown_content = f"""# {article_data.get('title', '微信公众号文章')}

> **来源**: {url}
> **抓取时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
> **作者**: {article_data.get('author', '未知')}
> **发布时间**: {article_data.get('publish_time', '未知')}
> **提取方法**: {article_data.get('extraction_method', '未知')}
> **内容长度**: {len(article_data.get('content', ''))} 字符
> **文件哈希**: {url_hash}

---

{article_data.get('content', '（未能提取文章内容）')}

---

## 元数据
- **原始URL**: {url}
- **抓取时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
- **HTTP状态码**: {metadata.get('status_code', 'N/A')}
- **响应大小**: {metadata.get('content_length', 0)} 字符
- **抓取耗时**: {metadata.get('elapsed_time', 0):.2f} 秒
- **内容提取**: {'成功' if article_data.get('extracted') else '失败'}
- **提取方法**: {article_data.get('extraction_method', 'N/A')}
"""
            
            # 保存文件
            filepath.write_text(markdown_content, encoding='utf-8')
            logger.info(f"保存成功: {filepath}")
            
            # 同时保存JSON格式的完整数据
            json_path = self.raw_wechat_dir / f"{url_hash}_meta.json"
            json_data = {
                "url": url,
                "title": article_data.get("title"),
                "author": article_data.get("author"),
                "publish_time": article_data.get("publish_time"),
                "content_length": len(article_data.get("content", "")),
                "extraction_method": article_data.get("extraction_method"),
                "extracted": article_data.get("extracted"),
                "metadata": metadata,
                "hash": url_hash,
                "saved_at": datetime.now().isoformat(),
                "filepath": str(filepath)
            }
            json_path.write_text(json.dumps(json_data, ensure_ascii=False, indent=2), encoding='utf-8')
            
            return filepath
            
        except Exception as e:
            logger.error(f"保存文章失败: {e}")
            return None
    
    def process_article(self, url: str) -> Tuple[bool, Optional[Path]]:
        """处理单个微信公众号文章"""
        logger.info(f"处理文章: {url}")
        
        # 1. 抓取HTML
        success, html, metadata = self.fetch_article_html(url)
        if not success:
            logger.error(f"抓取失败: {url}")
            return False, None
        
        # 2. 提取文章数据
        article_data = self.extract_article_data(html)
        
        # 3. 检查是否成功提取内容
        if not article_data.get("extracted", False):
            logger.warning(f"❌ 未提取到文章内容，可能URL无效或页面结构异常: {url}")
            # 检查页面是否有明显错误提示
            if self._has_error_page(html):
                logger.warning(f"页面包含错误提示，可能是无效URL: {url}")
            return False, None
        
        # 4. 保存文章
        saved_file = self.save_article(url, html, article_data, metadata)
        
        if saved_file:
            logger.info(f"✅ 处理完成: {url} -> {saved_file}")
            return True, saved_file
        else:
            logger.error(f"❌ 保存失败: {url}")
            return False, None

def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="微信公众号文章抓取器")
    parser.add_argument("--url", help="微信公众号文章URL")
    parser.add_argument("--file", help="包含URL列表的文件（每行一个URL）")
    parser.add_argument("--ua", choices=["android", "ios", "pc", "mobile_chrome"], 
                       default="android", help="User-Agent类型（默认: android）")
    parser.add_argument("--test", action="store_true", help="测试模式")
    
    args = parser.parse_args()
    
    # 初始化抓取器
    fetcher = WeChatFetcher(user_agent=args.ua)
    logger.info("微信公众号抓取器启动")
    
    if args.test:
        # 测试模式
        logger.info("运行测试模式...")
        
        # 使用示例URL测试
        test_urls = [
            "https://mp.weixin.qq.com/s/Y_uRMYBmdLWUPnz_ac7jW",
            # 可以添加更多测试URL
        ]
        
        success_count = 0
        for test_url in test_urls:
            logger.info(f"测试URL: {test_url}")
            success, saved_file = fetcher.process_article(test_url)
            if success:
                success_count += 1
                logger.info(f"✅ 测试成功: {test_url}")
            else:
                logger.error(f"❌ 测试失败: {test_url}")
        
        logger.info(f"测试完成: {success_count}/{len(test_urls)} 成功")
        return 0 if success_count > 0 else 1
    
    elif args.url:
        # 处理单个URL
        success, saved_file = fetcher.process_article(args.url)
        return 0 if success else 1
    
    elif args.file:
        # 处理URL文件
        try:
            with open(args.file, "r", encoding="utf-8") as f:
                urls = [line.strip() for line in f if line.strip() and not line.startswith("#")]
            
            logger.info(f"从文件读取 {len(urls)} 个URL: {args.file}")
            
            success_count = 0
            for i, url in enumerate(urls):
                logger.info(f"处理进度: {i+1}/{len(urls)}")
                
                success, saved_file = fetcher.process_article(url)
                if success:
                    success_count += 1
                
                # 延迟，避免过快请求
                if i < len(urls) - 1:
                    time.sleep(2)
            
            logger.info(f"处理完成: {success_count}/{len(urls)} 成功")
            return 0 if success_count > 0 else 1
            
        except Exception as e:
            logger.error(f"读取URL文件失败: {e}")
            return 1
    
    else:
        parser.print_help()
        return 1

if __name__ == "__main__":
    sys.exit(main())
