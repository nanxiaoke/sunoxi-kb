#!/usr/bin/env python3
"""
简单文档转换器
将raw文档转换为wiki格式，不依赖AI处理
第二阶段开发 - 任务1.1：快速文档转换
"""

import sys
import os
import re
import time
import argparse
from pathlib import Path
from typing import List, Dict, Any
import json

# 配置日志
import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class SimpleDocumentConverter:
    """简单文档转换器"""
    
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.raw_dir = base_dir / "raw"
        self.wiki_dir = base_dir / "wiki"
        
        # 确保wiki目录结构存在
        self._ensure_wiki_structure()
        
        logger.info(f"简单文档转换器初始化完成 (基础目录: {base_dir})")
    
    def _ensure_wiki_structure(self):
        """确保wiki目录结构存在"""
        subdirs = [
            "concepts",
            "people", 
            "projects",
            "technologies",
            "notes",
            "articles",
            "codes"
        ]
        
        for subdir in subdirs:
            (self.wiki_dir / subdir).mkdir(exist_ok=True, parents=True)
    
    def find_raw_documents(self) -> List[Dict[str, Any]]:
        """查找原始文档"""
        documents = []
        
        # 支持的扩展名
        extensions = {'.md', '.txt', '.py', '.json', '.yaml', '.yml'}
        
        for file_path in self.raw_dir.rglob("**/*"):
            if file_path.is_file() and file_path.suffix.lower() in extensions:
                # 获取相对路径
                rel_path = file_path.relative_to(self.raw_dir)
                
                # 读取文件内容
                try:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                except Exception as e:
                    logger.warning(f"读取文件失败 {file_path}: {e}")
                    continue
                
                # 跳过空文件
                if not content.strip():
                    continue
                
                documents.append({
                    "path": str(file_path),
                    "rel_path": str(rel_path),
                    "filename": file_path.name,
                    "content": content,
                    "size": len(content),
                    "extension": file_path.suffix.lower()
                })
        
        logger.info(f"找到 {len(documents)} 个原始文档")
        return documents
    
    def determine_category(self, doc_info: Dict[str, Any]) -> str:
        """确定文档分类"""
        filename = doc_info["filename"].lower()
        content = doc_info["content"].lower()
        extension = doc_info["extension"]
        
        # 基于扩展名和内容的分类判断
        if extension == '.py':
            return "codes"
        
        elif extension == '.md':
            # 检查内容特征
            if any(keyword in content for keyword in ['# ', '## ', '### ']):
                # 检查是否是技术相关
                tech_keywords = ['python', 'javascript', 'html', 'css', 'api', 'database', 'server']
                if any(keyword in content for keyword in tech_keywords):
                    return "technologies"
                else:
                    return "articles"
            else:
                return "notes"
        
        elif extension == '.txt':
            if len(content.splitlines()) > 5:
                return "notes"
            else:
                return "concepts"
        
        elif extension in {'.json', '.yaml', '.yml'}:
            return "config"
        
        else:
            return "documents"
    
    def extract_title(self, doc_info: Dict[str, Any]) -> str:
        """提取文档标题"""
        filename = doc_info["filename"]
        content = doc_info["content"]
        
        # 尝试从Markdown文件中提取标题
        if doc_info["extension"] == '.md':
            # 查找第一个一级标题
            match = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
            if match:
                return match.group(1).strip()
            
            # 查找第一个二级标题
            match = re.search(r'^##\s+(.+)$', content, re.MULTILINE)
            if match:
                return match.group(1).strip()
        
        # 使用文件名（去除扩展名和特殊字符）
        title = Path(filename).stem
        title = re.sub(r'[_-]', ' ', title)  # 替换下划线和连字符为空格
        title = re.sub(r'\s+', ' ', title).strip()  # 合并多个空格
        
        # 首字母大写
        if title:
            title = title[0].upper() + title[1:]
        
        return title or "未命名文档"
    
    def extract_summary(self, doc_info: Dict[str, Any]) -> str:
        """提取文档摘要"""
        content = doc_info["content"]
        
        # 对于Markdown文件，提取第一段非标题文本
        if doc_info["extension"] == '.md':
            lines = content.split('\n')
            summary_lines = []
            
            for line in lines:
                line = line.strip()
                if line and not line.startswith('#'):
                    summary_lines.append(line)
                    if len('\n'.join(summary_lines)) > 200:  # 限制长度
                        break
            
            if summary_lines:
                summary = ' '.join(summary_lines)
                if len(summary) > 300:
                    summary = summary[:300] + "..."
                return summary
        
        # 对于其他文件，使用前几行
        lines = [line.strip() for line in content.split('\n') if line.strip()]
        if lines:
            summary = ' '.join(lines[:3])
            if len(summary) > 200:
                summary = summary[:200] + "..."
            return summary
        
        return "（无摘要）"
    
    def extract_keypoints(self, doc_info: Dict[str, Any]) -> List[str]:
        """提取关键点"""
        content = doc_info["content"]
        keypoints = []
        
        # 对于Markdown文件，提取列表项
        if doc_info["extension"] == '.md':
            # 查找列表项
            list_items = re.findall(r'^\s*[-*+]\s+(.+)$', content, re.MULTILINE)
            keypoints.extend(list_items[:5])  # 最多5个
        
        # 对于任何文件，提取包含重要关键词的句子
        important_keywords = ['重要', '关键', '注意', '总结', '结论', '要点']
        lines = content.split('\n')
        
        for line in lines:
            line = line.strip()
            if any(keyword in line for keyword in important_keywords) and len(line) < 100:
                keypoints.append(line)
                if len(keypoints) >= 5:  # 最多5个
                    break
        
        return keypoints
    
    def generate_wiki_filename(self, title: str, category: str) -> str:
        """生成wiki文件名"""
        import hashlib
        
        # 清理标题
        clean_title = re.sub(r'[^\w\s-]', '', title)  # 移除特殊字符
        clean_title = re.sub(r'[-\s]+', '_', clean_title).strip('_')
        
        # 生成短哈希
        title_hash = hashlib.md5(title.encode('utf-8')).hexdigest()[:8]
        
        # 组合文件名
        filename = f"{clean_title[:50]}_{title_hash}.md"
        
        # 如果清理后的标题为空，使用哈希作为文件名
        if not clean_title:
            filename = f"document_{title_hash}.md"
        
        return filename
    
    def convert_to_wiki(self, doc_info: Dict[str, Any]) -> Dict[str, Any]:
        """将原始文档转换为wiki格式"""
        # 提取信息
        title = self.extract_title(doc_info)
        category = self.determine_category(doc_info)
        summary = self.extract_summary(doc_info)
        keypoints = self.extract_keypoints(doc_info)
        
        # 生成wiki文件名
        wiki_filename = self.generate_wiki_filename(title, category)
        wiki_path = self.wiki_dir / category / wiki_filename
        
        # 创建wiki内容
        wiki_content = self._create_wiki_content(
            title=title,
            category=category,
            summary=summary,
            keypoints=keypoints,
            original_content=doc_info["content"],
            source_file=doc_info["filename"]
        )
        
        # 保存wiki文件
        try:
            with open(wiki_path, 'w', encoding='utf-8') as f:
                f.write(wiki_content)
            
            logger.info(f"转换完成: {doc_info['filename']} → {category}/{wiki_filename}")
            
            return {
                "success": True,
                "title": title,
                "category": category,
                "wiki_path": str(wiki_path.relative_to(self.base_dir)),
                "summary_length": len(summary),
                "keypoints_count": len(keypoints)
            }
            
        except Exception as e:
            logger.error(f"保存wiki文件失败 {wiki_path}: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    def _create_wiki_content(self, title: str, category: str, summary: str, 
                           keypoints: List[str], original_content: str, 
                           source_file: str) -> str:
        """创建wiki内容"""
        lines = [
            f"# {title}",
            "",
            f"**分类**: {category}",
            f"**来源文件**: {source_file}",
            f"**转换时间**: {time.strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "## 摘要",
            summary,
            ""
        ]
        
        if keypoints:
            lines.extend([
                "## 关键点",
                ""
            ])
            for i, point in enumerate(keypoints, 1):
                lines.append(f"{i}. {point}")
            lines.append("")
        
        lines.extend([
            "## 原始内容",
            "```",
            original_content[:1000],  # 限制原始内容长度
            "```" if len(original_content) <= 1000 else "...（内容过长，已截断）",
            ""
        ])
        
        return '\n'.join(lines)
    
    def convert_batch(self, documents: List[Dict[str, Any]]) -> Dict[str, Any]:
        """批量转换文档"""
        logger.info(f"开始批量转换 {len(documents)} 个文档")
        
        results = {
            "total": len(documents),
            "converted": 0,
            "successful": 0,
            "failed": 0,
            "start_time": time.time(),
            "documents": []
        }
        
        for i, doc_info in enumerate(documents):
            logger.info(f"转换文档 [{i+1}/{len(documents)}]: {doc_info['filename']}")
            
            start_time = time.time()
            result = self.convert_to_wiki(doc_info)
            elapsed_time = time.time() - start_time
            
            results["converted"] += 1
            
            if result["success"]:
                results["successful"] += 1
                results["documents"].append({
                    "filename": doc_info["filename"],
                    "status": "success",
                    "title": result["title"],
                    "category": result["category"],
                    "elapsed_time": elapsed_time
                })
            else:
                results["failed"] += 1
                results["documents"].append({
                    "filename": doc_info["filename"],
                    "status": "failed",
                    "error": result.get("error", "未知错误"),
                    "elapsed_time": elapsed_time
                })
            
            # 每处理5个文档输出一次进度
            if results["converted"] % 5 == 0:
                logger.info(f"进度: {results['converted']}/{len(documents)}")
        
        # 计算总耗时
        results["elapsed_time"] = time.time() - results["start_time"]
        
        logger.info(f"批量转换完成: 成功 {results['successful']}, 失败 {results['failed']}")
        logger.info(f"总耗时: {results['elapsed_time']:.2f}秒")
        
        return results
    
    def generate_report(self, results: Dict[str, Any]) -> str:
        """生成转换报告"""
        report_lines = [
            "=" * 60,
            "Karpathy知识库简单文档转换报告",
            "=" * 60,
            f"转换时间: {time.strftime('%Y-%m-%d %H:%M:%S')}",
            f"总文档数: {results['total']}",
            f"已转换: {results['converted']}",
            f"成功: {results['successful']}",
            f"失败: {results['failed']}",
            f"总耗时: {results['elapsed_time']:.2f}秒",
            "",
            "文档转换详情:"
        ]
        
        for doc in results["documents"]:
            status_icon = "✅" if doc["status"] == "success" else "❌"
            title = doc.get("title", "无标题")
            category = doc.get("category", "未知分类")
            time_str = f" ({doc.get('elapsed_time', 0):.2f}秒)" if doc.get("elapsed_time") else ""
            
            if doc["status"] == "success":
                report_lines.append(f"  {status_icon} {doc['filename']}: {title} [{category}]{time_str}")
            else:
                report_lines.append(f"  {status_icon} {doc['filename']}: 失败 - {doc.get('error', '未知错误')}")
        
        report_lines.extend([
            "",
            "=" * 60,
            "建议下一步:"
        ])
        
        if results["failed"] > 0:
            report_lines.append("  🔧 检查失败文档，可能需要手动处理")
        
        if results["successful"] > 0:
            report_lines.append("  🔍 运行搜索测试验证新文档")
            report_lines.append("  📊 查看统计信息: python3 scripts/kb_cli.py stats")
            report_lines.append("  🔄 重建搜索索引: python3 scripts/kb_cli.py search --query test --rebuild")
        
        return "\n".join(report_lines)

def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="Karpathy知识库简单文档转换器")
    parser.add_argument("--base-dir", default=".", help="知识库基础目录")
    parser.add_argument("--test", action="store_true", help="测试模式（只处理前3个文档）")
    
    args = parser.parse_args()
    
    # 转换为Path对象
    base_dir = Path(args.base_dir).resolve()
    if not base_dir.exists():
        logger.error(f"基础目录不存在: {base_dir}")
        sys.exit(1)
    
    # 初始化转换器
    converter = SimpleDocumentConverter(base_dir)
    
    # 查找原始文档
    documents = converter.find_raw_documents()
    
    if not documents:
        logger.warning("未找到原始文档")
        sys.exit(0)
    
    # 测试模式：只处理前3个文档
    if args.test:
        logger.info("测试模式：只处理前3个文档")
        documents = documents[:3]
    
    # 批量转换文档
    results = converter.convert_batch(documents)
    
    # 生成并打印报告
    report = converter.generate_report(results)
    print(report)
    
    # 保存报告到文件
    report_file = base_dir / "simple_conversion_report.txt"
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write(report)
    
    print(f"\n📄 详细报告已保存到: {report_file}")

if __name__ == "__main__":
    main()