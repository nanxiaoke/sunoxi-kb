#!/usr/bin/env python3
"""
微信公众号文章深度分析
检查页面内容结构，寻找实际文章数据
"""

import sys
import re
import json
import requests
from bs4 import BeautifulSoup
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class WeChatDeepAnalyzer:
    """微信公众号深度分析器"""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.timeout = 30
    
    def fetch_page(self, url):
        """抓取页面"""
        headers = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; SM-G960F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Mobile Safari/537.36 MicroMessenger/8.0.40.2340(0x28002837) WeChat/arm64 Weixin NetType/WIFI Language/zh_CN ABI/arm64",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": "https://mp.weixin.qq.com/",
            "Accept-Encoding": "gzip, deflate, br"
        }
        
        try:
            response = self.session.get(url, headers=headers, timeout=30)
            return response.text
        except Exception as e:
            logger.error(f"抓取失败: {e}")
            return None
    
    def analyze_with_bs4(self, html):
        """使用BeautifulSoup分析页面结构"""
        soup = BeautifulSoup(html, 'html.parser')
        
        findings = {
            "title": "",
            "author": "",
            "publish_time": "",
            "content_elements": [],
            "script_data": [],
            "meta_tags": [],
            "has_error": False
        }
        
        # 检查标题
        title_tag = soup.find('title')
        if title_tag:
            findings["title"] = title_tag.text.strip()
            logger.info(f"页面标题: {findings['title']}")
        
        # 检查是否有错误提示
        error_indicators = [
            '参数错误', 'error', '出错', '加载失败', '无法访问',
            'weui-msg__title', 'weui-msg__desc'
        ]
        
        for indicator in error_indicators:
            if indicator in html:
                findings["has_error"] = True
                logger.warning(f"发现错误指示: {indicator}")
        
        # 查找文章内容容器
        content_selectors = [
            {'id': 'js_content'},
            {'class': 'rich_media_content'},
            {'id': 'js_article_content'},
            {'class': 'article-content'},
            {'id': 'content'},
            {'class': 'content'}
        ]
        
        for selector in content_selectors:
            elements = soup.find_all('div', selector)
            for elem in elements:
                text = elem.text.strip()
                if text and len(text) > 100:  # 有实际内容
                    findings["content_elements"].append({
                        "selector": str(selector),
                        "text_length": len(text),
                        "preview": text[:200]
                    })
                    logger.info(f"找到内容元素 {selector}: {len(text)}字符")
        
        # 检查meta标签
        meta_tags = soup.find_all('meta')
        for meta in meta_tags:
            name = meta.get('name', '') or meta.get('property', '')
            content = meta.get('content', '')
            if name and content:
                findings["meta_tags"].append(f"{name}: {content}")
                if 'title' in name.lower() or 'og:title' in name:
                    logger.info(f"Meta标题: {content}")
                if 'description' in name.lower() or 'og:description' in name:
                    logger.info(f"Meta描述: {content[:100]}...")
        
        # 查找script标签中的数据
        scripts = soup.find_all('script')
        for i, script in enumerate(scripts):
            if script.string:
                script_text = script.string
                
                # 检查常见的数据变量
                data_patterns = [
                    r'window\.msg\s*=\s*(\{.*?\});',
                    r'window\.__REDUX_STATE__\s*=\s*(\{.*?\});',
                    r'window\.initialData\s*=\s*(\{.*?\});',
                    r'var\s+msg\s*=\s*(\{.*?\});',
                    r'var\s+article\s*=\s*(\{.*?\});',
                    r'data\s*:\s*(\{.*?\})',
                    r'"content"\s*:\s*"([^"]+)"',
                    r"'content'\s*:\s*'([^']+)'",
                    r'"title"\s*:\s*"([^"]+)"',
                    r"'title'\s*:\s*'([^']+)'"
                ]
                
                for pattern in data_patterns:
                    matches = re.findall(pattern, script_text, re.DOTALL)
                    for match in matches:
                        if len(match) > 10:  # 有实际内容
                            findings["script_data"].append({
                                "pattern": pattern[:50],
                                "match_preview": str(match)[:200]
                            })
                            logger.info(f"脚本数据[{i}]: {pattern[:50]}... -> {str(match)[:100]}...")
        
        # 检查页面文本内容
        all_text = soup.get_text()
        lines = [line.strip() for line in all_text.split('\n') if line.strip()]
        
        # 查找可能的文章段落
        article_lines = []
        for line in lines:
            if len(line) > 50 and not line.startswith('http') and not 'cookie' in line.lower():
                article_lines.append(line)
        
        if article_lines:
            logger.info(f"找到{len(article_lines)}个可能的内容段落")
            for i, line in enumerate(article_lines[:3]):
                logger.info(f"  段落{i+1}: {line[:100]}...")
        
        return findings
    
    def test_dynamic_loading(self, html, url):
        """测试动态加载机制"""
        # 查找可能的XHR请求或动态加载脚本
        dynamic_patterns = [
            r'fetch\(["\']([^"\']+)["\']\)',
            r'axios\.get\(["\']([^"\']+)["\']\)',
            r'\.ajax\([^)]*url\s*:\s*["\']([^"\']+)["\']',
            r'XMLHttpRequest\(\)[^;]+open\(["\']GET["\']\s*,\s*["\']([^"\']+)["\']',
            r'src\s*=\s*["\']([^"\']+\.js)["\']',
            r'data-url\s*=\s*["\']([^"\']+)["\']'
        ]
        
        endpoints = []
        for pattern in dynamic_patterns:
            matches = re.findall(pattern, html)
            for match in matches:
                if 'mp.weixin.qq.com' in match or match.startswith('/'):
                    endpoints.append(match)
        
        if endpoints:
            logger.info(f"发现{len(endpoints)}个可能的动态端点")
            for endpoint in endpoints[:5]:
                logger.info(f"  端点: {endpoint}")
        
        # 尝试构造完整URL并测试
        from urllib.parse import urljoin
        tested_endpoints = []
        
        for endpoint in endpoints[:3]:  # 测试前3个
            if endpoint.startswith('http'):
                full_url = endpoint
            else:
                full_url = urljoin(url, endpoint)
            
            logger.info(f"测试端点: {full_url}")
            try:
                response = self.session.get(full_url, timeout=15)
                tested_endpoints.append({
                    "url": full_url,
                    "status": response.status_code,
                    "content_type": response.headers.get('Content-Type', ''),
                    "is_json": 'application/json' in response.headers.get('Content-Type', ''),
                    "length": len(response.text)
                })
                
                if response.status_code == 200:
                    logger.info(f"  ✅ 成功: {response.status_code}, {len(response.text)}字符")
                    if 'application/json' in response.headers.get('Content-Type', ''):
                        try:
                            data = response.json()
                            logger.info(f"  JSON键: {list(data.keys()) if isinstance(data, dict) else '非字典'}")
                        except:
                            logger.info(f"  响应: {response.text[:200]}")
                else:
                    logger.info(f"  ❌ 失败: {response.status_code}")
            except Exception as e:
                logger.error(f"  测试异常: {e}")
        
        return tested_endpoints
    
    def extract_article_data(self, html):
        """尝试从页面提取文章数据"""
        # 方法1: 正则提取JSON数据
        json_patterns = [
            r'window\.msg\s*=\s*(\{.*?\});',
            r'window\.__REDUX_STATE__\s*=\s*(\{.*?\});',
            r'var\s+msg\s*=\s*(\{.*?\});'
        ]
        
        article_data = None
        
        for pattern in json_patterns:
            match = re.search(pattern, html, re.DOTALL)
            if match:
                json_str = match.group(1)
                try:
                    data = json.loads(json_str)
                    logger.info(f"成功解析JSON数据，键: {list(data.keys())}")
                    
                    # 检查是否有文章内容
                    if isinstance(data, dict):
                        # 常见的内容字段
                        content_fields = ['content', 'msg', 'article', 'text', 'html']
                        for field in content_fields:
                            if field in data:
                                content = data[field]
                                if content and len(str(content)) > 100:
                                    article_data = {
                                        "source": "json_data",
                                        "field": field,
                                        "content_length": len(str(content)),
                                        "preview": str(content)[:200]
                                    }
                                    logger.info(f"找到文章内容字段 '{field}': {len(str(content))}字符")
                                    break
                    
                    return article_data
                except json.JSONDecodeError as e:
                    logger.warning(f"JSON解析失败: {e}")
                    # 尝试修复JSON（可能有不匹配的引号等）
                    pass
        
        # 方法2: 查找内嵌的base64或加密数据
        encoded_patterns = [
            r'data-content\s*=\s*["\']([^"\']+)["\']',
            r'content\s*:\s*["\']([^"\']+)["\']',
            r'encrypt_content\s*:\s*["\']([^"\']+)["\']'
        ]
        
        for pattern in encoded_patterns:
            matches = re.findall(pattern, html)
            for match in matches:
                if len(match) > 50:
                    logger.info(f"找到编码数据: {pattern[:30]}..., 长度: {len(match)}")
                    # 可能需要进行base64解码或其他处理
        
        return article_data

def main():
    """主分析函数"""
    test_url = "https://mp.weixin.qq.com/s/Y_uRMYBmdLWUPnz_ac7jW"
    analyzer = WeChatDeepAnalyzer()
    
    logger.info("="*80)
    logger.info("微信公众号文章深度分析")
    logger.info(f"测试URL: {test_url}")
    logger.info("="*80)
    
    # 1. 抓取页面
    logger.info("\n1. 抓取页面")
    html = analyzer.fetch_page(test_url)
    if not html:
        logger.error("页面抓取失败")
        return 1
    
    logger.info(f"页面大小: {len(html)}字符")
    
    # 2. BeautifulSoup分析
    logger.info("\n2. 页面结构分析")
    findings = analyzer.analyze_with_bs4(html)
    
    if findings["has_error"]:
        logger.warning("⚠️ 页面可能包含错误提示")
    
    if findings["content_elements"]:
        logger.info(f"✅ 找到{len(findings['content_elements'])}个内容元素")
    else:
        logger.warning("❌ 未找到明显的内容元素")
    
    # 3. 尝试提取文章数据
    logger.info("\n3. 提取文章数据")
    article_data = analyzer.extract_article_data(html)
    
    if article_data:
        logger.info(f"✅ 成功提取文章数据")
        logger.info(f"   来源: {article_data['source']}")
        logger.info(f"   字段: {article_data['field']}")
        logger.info(f"   长度: {article_data['content_length']}字符")
        logger.info(f"   预览: {article_data['preview']}")
    else:
        logger.warning("❌ 未能提取文章数据")
    
    # 4. 测试动态加载
    logger.info("\n4. 动态加载测试")
    endpoints = analyzer.test_dynamic_loading(html, test_url)
    
    # 5. 分析总结
    logger.info("\n5. 分析总结")
    logger.info("="*80)
    
    conclusions = []
    
    if findings["has_error"]:
        conclusions.append("页面可能返回错误状态，需要验证URL有效性")
    
    if article_data:
        conclusions.append("页面包含结构化文章数据，可通过解析JavaScript提取")
    elif findings["content_elements"]:
        conclusions.append("页面包含HTML格式文章内容，可直接解析")
    else:
        conclusions.append("页面可能为空框架，内容需动态加载")
    
    if endpoints:
        conclusions.append(f"发现{len(endpoints)}个可能的API端点，需进一步测试")
    
    logger.info("\n结论:")
    for i, conclusion in enumerate(conclusions, 1):
        logger.info(f"  {i}. {conclusion}")
    
    # 6. 实施建议
    logger.info("\n6. 具体实施建议")
    
    if article_data:
        logger.info("✅ 方案A: 解析JavaScript中的JSON数据")
        logger.info("   步骤: 1. 正则提取window.msg等变量 2. JSON解析 3. 提取content字段")
        logger.info("   复杂度: 中, 稳定性: 中（依赖页面结构）")
    
    if findings["content_elements"]:
        logger.info("✅ 方案B: 直接解析HTML内容")
        logger.info("   步骤: 1. 使用BeautifulSoup 2. 查找#js_content等元素 3. 提取文本")
        logger.info("   复杂度: 低, 稳定性: 高")
    
    if endpoints:
        logger.info("✅ 方案C: 调用动态API")
        logger.info("   步骤: 1. 分析页面中的API端点 2. 模拟请求 3. 处理响应")
        logger.info("   复杂度: 高, 稳定性: 低（API可能变更）")
    
    if not article_data and not findings["content_elements"]:
        logger.info("✅ 方案D: 手动导入 + 自动处理（推荐）")
        logger.info("   步骤: 1. 微信中复制文章 2. 保存到raw/目录 3. 使用processor.py处理")
        logger.info("   复杂度: 低, 稳定性: 高, 无技术风险")
    
    logger.info("\n" + "="*80)
    logger.info("深度分析完成。建议根据实际情况选择合适的方案。")
    
    # 保存详细结果
    import datetime
    report = {
        "url": test_url,
        "analysis_time": str(datetime.datetime.now()),
        "html_length": len(html),
        "findings": findings,
        "article_data": article_data,
        "endpoints_tested": endpoints,
        "conclusions": conclusions
    }
    
    with open("/tmp/wechat_deep_analysis.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    
    logger.info(f"详细分析结果已保存到: /tmp/wechat_deep_analysis.json")
    return 0

if __name__ == "__main__":
    sys.exit(main())