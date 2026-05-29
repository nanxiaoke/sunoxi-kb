#!/usr/bin/env python3
"""
测试微信公众号文章抓取 - 验证反扒技能增强效果
测试URL: https://mp.weixin.qq.com/s/Y_uRMYBmdLWUPnz_ac7jW
"""

import sys
import requests
import time
from urllib.parse import quote
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 多源抓取服务配置（从web_collector.py复制）
SERVICES = {
    "jina": {
        "url": "https://r.jina.ai/{url}",
        "desc": "Jina AI Reader - 最稳定，通用性强",
        "headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/markdown,text/plain;q=0.9",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"
        }
    },
    "markdown": {
        "url": "https://markdown.new/{url}",
        "desc": "Cloudflare Markdown - Cloudflare保护网站专用",
        "headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/markdown,text/plain;q=0.9"
        }
    },
    "defuddle": {
        "url": "https://defuddle.md/{url}",
        "desc": "Defuddle - 备用方案",
        "headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/markdown,text/plain;q=0.9"
        }
    }
}

def encode_url_for_service(url: str) -> str:
    """对URL进行编码，适合在服务URL中使用"""
    # 确保URL有协议
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    # 对URL进行编码
    return quote(url, safe='')

def fetch_with_service(url: str, method: str = "jina"):
    """使用指定服务获取网页内容"""
    if method not in SERVICES:
        return False, f"未知服务: {method}", ""
    
    service_config = SERVICES[method]
    encoded_url = encode_url_for_service(url)
    service_url = service_config["url"].format(url=encoded_url)
    
    try:
        logger.info(f"使用 {method} 服务抓取: {url}")
        
        response = requests.get(
            service_url,
            headers=service_config["headers"],
            timeout=30
        )
        
        if response.status_code == 200:
            content = response.text.strip()
            if content:
                # 尝试解析为Markdown，检查是否有内容
                if len(content) > 100 or '#' in content or '[' in content:
                    logger.info(f"{method} 抓取成功: {len(content)}字符")
                    return True, content, method
                else:
                    logger.warning(f"{method} 返回内容过短或无Markdown格式: {len(content)}字符")
                    return False, "返回内容无效", method
            else:
                logger.warning(f"{method} 返回空内容")
                return False, "返回空内容", method
        else:
            logger.warning(f"{method} 请求失败: HTTP {response.status_code}")
            return False, f"HTTP {response.status_code}", method
            
    except requests.exceptions.Timeout:
        logger.error(f"{method} 请求超时 (30秒)")
        return False, "请求超时", method
    except requests.exceptions.ConnectionError:
        logger.error(f"{method} 连接错误")
        return False, "连接错误", method
    except Exception as e:
        logger.error(f"{method} 异常: {e}")
        return False, f"异常: {str(e)}", method

def fetch_with_fallback(url: str):
    """按优先级尝试所有服务"""
    errors = []
    
    for method in ["jina", "markdown", "defuddle"]:
        success, content, method_used = fetch_with_service(url, method)
        
        if success and content:
            logger.info(f"✅ 成功使用 {method} 抓取: {url}")
            return True, content, method_used
        else:
            error_msg = f"{method}: {content if not success else '无内容'}"
            errors.append(error_msg)
            logger.warning(f"❌ {method} 失败: {error_msg}")
        
        # 服务间延迟
        if method != "defuddle":
            time.sleep(1)
    
    # 所有方法都失败
    error_msg = "所有服务都失败:\n" + "\n".join(errors)
    logger.error(f"所有抓取服务都失败: {url}")
    return False, error_msg, ""

def main():
    """主测试函数"""
    test_url = "https://mp.weixin.qq.com/s/Y_uRMYBmdLWUPnz_ac7jW"
    logger.info(f"开始测试微信公众号文章抓取: {test_url}")
    logger.info(f"测试时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 首先尝试直接requests（预期会失败）
    logger.info("1. 尝试直接requests抓取（预期失败）...")
    try:
        direct_response = requests.get(test_url, timeout=10, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        logger.info(f"直接抓取状态码: {direct_response.status_code}")
        if direct_response.status_code == 200:
            logger.info(f"直接抓取成功，内容长度: {len(direct_response.text)}")
        else:
            logger.info(f"直接抓取失败，状态码: {direct_response.status_code}")
    except Exception as e:
        logger.info(f"直接抓取异常: {e}")
    
    # 使用多源抓取策略
    logger.info("2. 使用多源抓取策略（jina → markdown → defuddle）...")
    
    success, content, method_used = fetch_with_fallback(test_url)
    
    if success:
        logger.info(f"✅ 反扒技能测试成功！")
        logger.info(f"   使用服务: {method_used}")
        logger.info(f"   内容长度: {len(content)}字符")
        logger.info(f"   内容预览（前500字符）:")
        print("\n" + "="*80)
        print(content[:500] + "..." if len(content) > 500 else content)
        print("="*80)
        
        # 保存测试结果
        with open("/tmp/wechat_test_result.txt", "w", encoding="utf-8") as f:
            f.write(f"URL: {test_url}\n")
            f.write(f"成功: 是\n")
            f.write(f"使用服务: {method_used}\n")
            f.write(f"内容长度: {len(content)}字符\n")
            f.write(f"抓取时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("\n" + "="*80 + "\n")
            f.write(content[:2000] + "\n")
        
        logger.info(f"测试结果已保存到: /tmp/wechat_test_result.txt")
        return 0
    else:
        logger.error(f"❌ 反扒技能测试失败")
        logger.error(f"   错误信息: {content}")
        return 1

if __name__ == "__main__":
    sys.exit(main())