#!/usr/bin/env python3
"""
微信公众号文章获取方案研究
分析反爬机制，探索免费获取方案
"""

import sys
import re
import json
import requests
from urllib.parse import urlparse, parse_qs, quote
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class WeChatArticleAnalyzer:
    """微信公众号文章分析器"""
    
    # 微信客户端User-Agent列表
    USER_AGENTS = {
        "wechat_android": "Mozilla/5.0 (Linux; Android 10; SM-G960F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Mobile Safari/537.36 MicroMessenger/8.0.40.2340(0x28002837) WeChat/arm64 Weixin NetType/WIFI Language/zh_CN ABI/arm64",
        "wechat_ios": "Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.40(0x1800282f) NetType/WIFI Language/zh_CN",
        "pc_wechat": "Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/86.0.4240.198 Safari/537.36",
        "mobile_chrome": "Mozilla/5.0 (Linux; Android 10; SM-G960F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Mobile Safari/537.36"
    }
    
    def __init__(self):
        self.session = requests.Session()
        self.session.timeout = 30
    
    def fetch_with_user_agent(self, url, user_agent_key="wechat_android"):
        """使用不同User-Agent抓取页面"""
        headers = {
            "User-Agent": self.USER_AGENTS.get(user_agent_key, self.USER_AGENTS["wechat_android"]),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
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
        
        try:
            logger.info(f"使用 {user_agent_key} User-Agent 抓取: {url}")
            response = self.session.get(url, headers=headers, timeout=30)
            return response
        except Exception as e:
            logger.error(f"抓取失败: {e}")
            return None
    
    def analyze_page_structure(self, html_content):
        """分析页面结构，寻找文章内容"""
        findings = {
            "has_article_content": False,
            "data_in_scripts": False,
            "api_endpoints": [],
            "json_data": [],
            "content_selectors": []
        }
        
        # 检查是否有文章内容标签
        content_selectors = [
            r'<div[^>]*id="js_content"[^>]*>.*?</div>',
            r'<div[^>]*class="rich_media_content"[^>]*>.*?</div>',
            r'<article[^>]*>.*?</article>',
            r'<div[^>]*class="article-content"[^>]*>.*?</div>'
        ]
        
        for selector in content_selectors:
            matches = re.findall(selector, html_content, re.DOTALL | re.IGNORECASE)
            if matches:
                findings["content_selectors"].append(selector)
                findings["has_article_content"] = True
                logger.info(f"找到文章内容选择器: {selector}")
                # 提取前500字符预览
                for match in matches[:2]:
                    preview = match[:500].replace('\n', ' ').strip()
                    logger.info(f"内容预览: {preview}...")
        
        # 检查JavaScript中的变量数据
        script_patterns = [
            r'window\.msg\s*=\s*({[^}]+})',
            r'window\.article\s*=\s*({[^}]+})',
            r'window\.content\s*=\s*[\'"]([^\'"]+)[\'"]',
            r'var\s+msg\s*=\s*({[^}]+})',
            r'var\s+article\s*=\s*({[^}]+})',
            r'data\s*:\s*({[^}]+})',
            r'window\.__REDUX_STATE__\s*=\s*({[^;]+})',
            r'window\.initialData\s*=\s*({[^;]+})'
        ]
        
        for pattern in script_patterns:
            matches = re.findall(pattern, html_content, re.DOTALL)
            for match in matches:
                findings["data_in_scripts"] = True
                logger.info(f"找到JavaScript数据模式: {pattern[:50]}...")
                try:
                    # 尝试解析JSON
                    if isinstance(match, str):
                        data = json.loads(match)
                        findings["json_data"].append({
                            "pattern": pattern,
                            "data_type": type(data).__name__,
                            "keys": list(data.keys()) if isinstance(data, dict) else str(data)[:100]
                        })
                        logger.info(f"解析JSON成功，键: {list(data.keys()) if isinstance(data, dict) else '非字典'}")
                except json.JSONDecodeError:
                    # 可能不是完整JSON，或者是字符串
                    findings["json_data"].append({
                        "pattern": pattern,
                        "data_type": "string",
                        "preview": str(match)[:200]
                    })
                    logger.info(f"数据预览: {str(match)[:200]}...")
        
        # 查找API端点
        api_patterns = [
            r'https?://[^"\']+mp\.weixin\.qq\.com[^"\']+getappmsgext[^"\']*',
            r'https?://[^"\']+mp\.weixin\.qq\.com[^"\']+appmsg[^"\']*',
            r'https?://[^"\']+mp\.weixin\.qq\.com[^"\']+s\?[^"\']*',
            r'https?://[^"\']+mp\.weixin\.qq\.com[^"\']+cgi-bin[^"\']*'
        ]
        
        for pattern in api_patterns:
            matches = re.findall(pattern, html_content, re.IGNORECASE)
            for match in matches:
                if match not in findings["api_endpoints"]:
                    findings["api_endpoints"].append(match)
                    logger.info(f"找到API端点: {match}")
        
        # 查找可能的XHR请求URL模式
        xhr_patterns = [
            r'"url"\s*:\s*"([^"]+)"',
            r"'url'\s*:\s*'([^']+)'",
            r'fetch\(["\']([^"\']+)["\']\)',
            r'axios\.get\(["\']([^"\']+)["\']\)',
            r'\.ajax\([^)]*url\s*:\s*["\']([^"\']+)["\']'
        ]
        
        for pattern in xhr_patterns:
            matches = re.findall(pattern, html_content)
            for match in matches:
                if 'mp.weixin.qq.com' in match or 'weixin' in match:
                    if match not in findings["api_endpoints"]:
                        findings["api_endpoints"].append(match)
                        logger.info(f"找到XHR URL: {match}")
        
        return findings
    
    def extract_url_params(self, url):
        """提取URL参数，分析可能的验证参数"""
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        
        logger.info(f"URL参数分析: {url}")
        for key, values in params.items():
            logger.info(f"  {key}: {values}")
        
        # 微信文章URL常见参数
        common_params = ['__biz', 'mid', 'idx', 'sn', 'chksm', 'scene', 'ascene', 'subscene']
        found_params = [p for p in common_params if p in params]
        
        logger.info(f"发现微信参数: {found_params}")
        return params
    
    def test_common_api_patterns(self, base_url):
        """测试常见的微信公众号API模式"""
        api_tests = []
        
        # 常见的微信文章API模式
        patterns = [
            # 文章扩展信息API (需要cookie和referer)
            "https://mp.weixin.qq.com/mp/getappmsgext",
            # 文章列表API
            "https://mp.weixin.qq.com/mp/profile_ext",
            # 单篇文章API (可能需要不同参数格式)
            "https://mp.weixin.qq.com/s"
        ]
        
        # 从原始URL提取参数
        parsed = urlparse(base_url)
        params = parse_qs(parsed.query)
        
        for api_pattern in patterns:
            test_url = api_pattern
            if '?' in api_pattern:
                test_url += '&'
            else:
                test_url += '?'
            
            # 添加可能的参数
            test_params = {}
            for key in ['__biz', 'mid', 'idx', 'sn']:
                if key in params:
                    test_params[key] = params[key][0]
            
            if test_params:
                from urllib.parse import urlencode
                test_url += urlencode(test_params)
                
                logger.info(f"测试API: {test_url}")
                
                # 使用微信User-Agent测试
                headers = {
                    "User-Agent": self.USER_AGENTS["wechat_android"],
                    "Referer": base_url
                }
                
                try:
                    response = self.session.get(test_url, headers=headers, timeout=15)
                    api_tests.append({
                        "url": test_url,
                        "status": response.status_code,
                        "content_type": response.headers.get('Content-Type', ''),
                        "content_length": len(response.text),
                        "is_json": 'application/json' in response.headers.get('Content-Type', '')
                    })
                    
                    if response.status_code == 200:
                        logger.info(f"  ✅ 成功: {response.status_code}, 类型: {response.headers.get('Content-Type')}")
                        if 'application/json' in response.headers.get('Content-Type', ''):
                            try:
                                data = response.json()
                                logger.info(f"  JSON响应键: {list(data.keys()) if isinstance(data, dict) else '非字典'}")
                            except:
                                logger.info(f"  响应预览: {response.text[:200]}")
                    else:
                        logger.info(f"  ❌ 失败: {response.status_code}")
                        
                except Exception as e:
                    api_tests.append({
                        "url": test_url,
                        "error": str(e)
                    })
                    logger.error(f"  ❌ 异常: {e}")
        
        return api_tests
    
    def search_open_source_solutions(self):
        """调研开源解决方案"""
        solutions = [
            {
                "name": "wechat-article-spider",
                "description": "微信公众号文章爬虫，支持抓取文章内容、评论、阅读数等",
                "language": "Python",
                "url": "https://github.com/wnma3mz/wechat_article_spider",
                "method": "模拟请求 + 解析HTML",
                "limitation": "可能需要维护cookie池"
            },
            {
                "name": "WeChatSogou",
                "description": "基于搜狗微信搜索的微信公众号爬虫",
                "language": "Python",
                "url": "https://github.com/Chyroc/WeChatSogou",
                "method": "通过搜狗微信搜索接口",
                "limitation": "搜狗限制较多，不稳定"
            },
            {
                "name": "wechat-crawler",
                "description": "微信公众号历史文章爬虫",
                "language": "Python",
                "url": "https://github.com/wonderfulsuccess/weixin_crawler",
                "method": "解析微信公众号页面",
                "limitation": "需要公众号biz参数"
            },
            {
                "name": "wechat-spider",
                "description": "微信公众号爬虫，支持文章、阅读量、点赞量",
                "language": "Python",
                "url": "https://github.com/striver-ing/wechat-spider",
                "method": "模拟微信客户端请求",
                "limitation": "需要处理反爬"
            }
        ]
        
        logger.info("开源解决方案调研:")
        for sol in solutions:
            logger.info(f"  📦 {sol['name']}: {sol['description']}")
            logger.info(f"    方法: {sol['method']}, 限制: {sol['limitation']}")
        
        return solutions

def main():
    """主分析函数"""
    test_url = "https://mp.weixin.qq.com/s/Y_uRMYBmdLWUPnz_ac7jW"
    analyzer = WeChatArticleAnalyzer()
    
    logger.info("="*80)
    logger.info("微信公众号文章获取方案研究")
    logger.info(f"测试URL: {test_url}")
    logger.info("="*80)
    
    # 1. 分析URL参数
    logger.info("\n1. URL参数分析")
    analyzer.extract_url_params(test_url)
    
    # 2. 使用不同User-Agent测试
    logger.info("\n2. User-Agent测试")
    user_agent_results = {}
    
    for ua_key in ["wechat_android", "wechat_ios", "pc_wechat", "mobile_chrome"]:
        response = analyzer.fetch_with_user_agent(test_url, ua_key)
        if response:
            user_agent_results[ua_key] = {
                "status": response.status_code,
                "content_length": len(response.text),
                "headers": dict(response.headers)
            }
            logger.info(f"  {ua_key}: HTTP {response.status_code}, {len(response.text)}字符")
            
            # 分析页面结构
            if response.status_code == 200:
                findings = analyzer.analyze_page_structure(response.text)
                if findings["has_article_content"]:
                    logger.info(f"    ✅ 发现文章内容")
                if findings["data_in_scripts"]:
                    logger.info(f"    ✅ 发现脚本数据")
                if findings["api_endpoints"]:
                    logger.info(f"    ✅ 发现{len(findings['api_endpoints'])}个API端点")
    
    # 3. 测试常见API模式
    logger.info("\n3. API模式测试")
    api_results = analyzer.test_common_api_patterns(test_url)
    
    # 4. 开源方案调研
    logger.info("\n4. 开源解决方案调研")
    solutions = analyzer.search_open_source_solutions()
    
    # 5. 总结与建议
    logger.info("\n5. 免费获取方案总结")
    logger.info("="*80)
    
    # 基于分析结果的建议
    recommendations = []
    
    # 检查是否有直接可用的内容
    for ua_key, result in user_agent_results.items():
        if result["status"] == 200 and result["content_length"] > 10000:
            recommendations.append({
                "方案": f"直接使用{ua_key} User-Agent抓取",
                "可行性": "高",
                "复杂度": "低",
                "风险": "中（可能触发反爬）",
                "实施建议": "添加Referer和必要的请求头"
            })
    
    # 检查API端点
    if api_results:
        for api in api_results:
            if api.get("status") == 200 and api.get("is_json"):
                recommendations.append({
                    "方案": "调用微信内部API",
                    "可行性": "中",
                    "复杂度": "中",
                    "风险": "中（API可能变更）",
                    "实施建议": "模拟完整微信请求链，处理cookie"
                })
                break
    
    # 添加开源方案
    for sol in solutions[:2]:  # 推荐前两个
        recommendations.append({
            "方案": f"集成{sol['name']}开源方案",
            "可行性": "中到高",
            "复杂度": "中",
            "风险": "低（社区维护）",
            "实施建议": f"参考{sol['url']}，适配到当前项目"
        })
    
    # 备用方案
    recommendations.append({
        "方案": "手动导入 + 自动化处理",
        "可行性": "高",
        "复杂度": "低",
        "风险": "无",
        "实施建议": "微信中复制文章 → 保存到raw/ → processor.py自动处理"
    })
    
    # 输出推荐方案
    logger.info("\n推荐方案（按优先级排序）:")
    for i, rec in enumerate(recommendations, 1):
        logger.info(f"\n{i}. {rec['方案']}")
        logger.info(f"   可行性: {rec['可行性']}, 复杂度: {rec['复杂度']}, 风险: {rec['风险']}")
        logger.info(f"   实施建议: {rec['实施建议']}")
    
    # 具体实施步骤
    logger.info("\n具体实施步骤:")
    logger.info("1. 优先尝试: 优化User-Agent和请求头，直接抓取HTML")
    logger.info("2. 备用方案: 集成wechat-article-spider等开源项目")
    logger.info("3. 保底方案: 手动导入，利用现有processor.py自动化处理")
    logger.info("4. 长期方案: 维护cookie池，模拟完整微信客户端行为")
    
    logger.info("\n" + "="*80)
    logger.info("研究完成。建议从方案1开始尝试，逐步降级到方案3。")
    
    # 保存分析结果
    with open("/tmp/wechat_analysis_report.txt", "w", encoding="utf-8") as f:
        f.write("微信公众号文章获取方案研究报告\n")
        f.write("="*80 + "\n")
        f.write(f"测试URL: {test_url}\n")
        f.write(f"分析时间: {__import__('datetime').datetime.now()}\n\n")
        
        f.write("推荐方案:\n")
        for i, rec in enumerate(recommendations, 1):
            f.write(f"{i}. {rec['方案']}\n")
            f.write(f"   可行性: {rec['可行性']}, 复杂度: {rec['复杂度']}, 风险: {rec['风险']}\n")
            f.write(f"   实施建议: {rec['实施建议']}\n\n")
    
    logger.info(f"详细报告已保存到: /tmp/wechat_analysis_report.txt")
    return 0

if __name__ == "__main__":
    sys.exit(main())