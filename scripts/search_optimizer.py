#!/usr/bin/env python3
"""
搜索系统优化器
第二阶段开发 - 任务3：搜索系统优化
"""

import sys
import time
import json
import argparse
from pathlib import Path
from typing import List, Dict, Any
import re
# import jieba  # 需要安装：pip install jieba (可选依赖)

# 添加当前目录到路径
sys.path.insert(0, str(Path(__file__).parent))

# 配置日志
import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class SearchOptimizer:
    """搜索系统优化器"""
    
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.search_index_file = base_dir / "search_index.json"
        self.optimized_index_file = base_dir / "search_index_optimized.json"
        
        # 加载现有索引
        self.index = self._load_index()
        
        logger.info(f"搜索优化器初始化完成 (基础目录: {base_dir})")
    
    def _load_index(self) -> Dict[str, Any]:
        """加载搜索索引"""
        if not self.search_index_file.exists():
            logger.warning("搜索索引文件不存在")
            return {"documents": [], "metadata": {}}
        
        try:
            with open(self.search_index_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"加载搜索索引失败: {e}")
            return {"documents": [], "metadata": {}}
    
    def analyze_current_performance(self) -> Dict[str, Any]:
        """分析当前搜索性能"""
        logger.info("分析当前搜索性能...")
        
        # 测试查询
        test_queries = [
            "人工智能",
            "机器学习",
            "RAG技术",
            "Ollama使用",
            "Python代码示例"
        ]
        
        results = {
            "total_documents": len(self.index.get("documents", [])),
            "test_queries": [],
            "recommendations": []
        }
        
        # 导入当前搜索器
        try:
            from search import WikiSearcher
            
            searcher = WikiSearcher(self.base_dir)
            
            for query in test_queries:
                start_time = time.time()
                search_results = searcher.search(query, search_type="fulltext", limit=5)
                elapsed_time = time.time() - start_time
                
                results["test_queries"].append({
                    "query": query,
                    "response_time": elapsed_time,
                    "results_count": len(search_results),
                    "has_results": len(search_results) > 0
                })
                
                logger.info(f"查询 '{query}': {len(search_results)} 结果, {elapsed_time:.3f}秒")
        
        except Exception as e:
            logger.error(f"性能分析失败: {e}")
            results["error"] = str(e)
        
        # 生成建议
        self._generate_recommendations(results)
        
        return results
    
    def _generate_recommendations(self, results: Dict[str, Any]):
        """生成优化建议"""
        recommendations = []
        
        # 检查文档数量
        if results["total_documents"] < 10:
            recommendations.append({
                "priority": "high",
                "area": "数据量",
                "suggestion": "增加wiki文档数量，目标至少20篇",
                "reason": f"当前只有 {results['total_documents']} 篇文档，搜索效果有限"
            })
        
        # 分析查询性能
        slow_queries = [q for q in results["test_queries"] if q["response_time"] > 0.5]
        if slow_queries:
            recommendations.append({
                "priority": "medium",
                "area": "性能",
                "suggestion": "优化分词算法和索引结构",
                "reason": f"{len(slow_queries)} 个查询响应时间超过0.5秒"
            })
        
        # 检查无结果查询
        no_result_queries = [q for q in results["test_queries"] if not q["has_results"]]
        if no_result_queries:
            recommendations.append({
                "priority": "high",
                "area": "召回率",
                "suggestion": "改进分词和索引策略，提高召回率",
                "reason": f"{len(no_result_queries)} 个查询没有返回结果"
            })
        
        # 检查索引结构
        if "doc_index" in self.index:
            doc_index_size = len(self.index["doc_index"])
            if doc_index_size < results["total_documents"]:
                recommendations.append({
                    "priority": "high",
                    "area": "索引完整性",
                    "suggestion": "重建搜索索引，确保所有文档都被索引",
                    "reason": f"索引中有 {doc_index_size} 个文档，但应该有 {results['total_documents']} 个"
                })
        
        results["recommendations"] = recommendations
    
    def optimize_tokenizer(self):
        """优化分词器"""
        logger.info("优化分词器...")
        
        # 当前分词策略分析
        current_strategy = """
        当前分词策略：
        1. 英文单词（2个字符以上）
        2. 连续中文字符（2个字符以上）
        3. 简单停用词过滤
        """
        
        logger.info(current_strategy)
        
        # 建议改进
        improvements = [
            "使用jieba中文分词库提高中文分词准确性",
            "添加同义词扩展",
            "支持词干提取（英文）",
            "添加专业术语识别",
            "改进停用词列表"
        ]
        
        logger.info("建议改进：")
        for i, improvement in enumerate(improvements, 1):
            logger.info(f"  {i}. {improvement}")
        
        return improvements
    
    def create_enhanced_tokenizer(self):
        """创建增强分词器"""
        logger.info("创建增强分词器...")
        
        enhanced_tokenizer_code = '''
class EnhancedTokenizer:
    \"\"\"增强分词器\"\"\"
    
    def __init__(self):
        # 中文停用词（扩展版）
        self.chinese_stop_words = set([
            \"的\", \"了\", \"在\", \"是\", \"我\", \"有\", \"和\", \"就\", \"不\", \"人\", \"都\", \"一\", \"一个\",
            \"也\", \"很\", \"到\", \"说\", \"要\", \"去\", \"你\", \"会\", \"着\", \"没有\", \"看\", \"好\", \"自己\",
            \"这\", \"那\", \"上\", \"下\", \"个\", \"年\", \"月\", \"日\", \"时\", \"分\", \"秒\", \"与\", \"或\", \"而\",
            \"且\", \"但\", \"虽然\", \"如果\", \"因为\", \"所以\", \"然后\", \"而且\", \"或者\", \"一些\", \"一种\",
            \"这个\", \"那个\", \"这些\", \"那些\", \"什么\", \"为什么\", \"怎么\", \"如何\", \"哪里\", \"谁\"
        ])
        
        # 英文停用词
        self.english_stop_words = set([
            \"a\", \"an\", \"the\", \"and\", \"or\", \"but\", \"in\", \"on\", \"at\", \"to\", \"for\", \"of\", \"with\",
            \"by\", \"about\", \"as\", \"into\", \"like\", \"through\", \"after\", \"over\", \"between\", \"out\",
            \"from\", \"up\", \"down\", \"under\", \"again\", \"further\", \"then\", \"once\", \"here\", \"there\",
            \"when\", \"where\", \"why\", \"how\", \"all\", \"any\", \"both\", \"each\", \"few\", \"more\", \"most\",
            \"other\", \"some\", \"such\", \"no\", \"nor\", \"not\", \"only\", \"own\", \"same\", \"so\", \"than\",
            \"too\", \"very\", \"can\", \"will\", \"just\", \"don\", \"should\", \"now\"
        ])
        
        # 同义词词典（简化版）
        self.synonyms = {
            \"ai\": [\"人工智能\", \"ai\", \"artificial intelligence\"],
            \"ml\": [\"机器学习\", \"ml\", \"machine learning\"],
            \"nlp\": [\"自然语言处理\", \"nlp\", \"natural language processing\"],
            \"rag\": [\"检索增强生成\", \"rag\", \"retrieval augmented generation\"],
            \"python\": [\"python\", \"py\"],
        }
        
        # 尝试导入jieba，如果不可用则使用简单分词
        try:
            import jieba
            self.use_jieba = True
            # 添加自定义词典
            for word in self.synonyms:
                for synonym in self.synonyms[word]:
                    jieba.add_word(synonym)
        except ImportError:
            self.use_jieba = False
            logger.warning(\"jieba未安装，使用简单分词器\")
    
    def tokenize(self, text: str) -> List[str]:
        \"\"\"增强分词\"\"\"
        if not text:
            return []
        
        tokens = []
        
        # 使用jieba进行中文分词（如果可用）
        if self.use_jieba:
            import jieba
            words = jieba.lcut(text)
        else:
            # 回退到简单分词
            words = re.findall(r'[a-zA-Z]{2,}|[\\u4e00-\\u9fff]{2,}|[^\\s\\w]', text)
        
        # 处理每个词
        for word in words:
            word_lower = word.lower().strip()
            
            # 过滤停用词
            if (word_lower in self.chinese_stop_words or 
                word_lower in self.english_stop_words or
                len(word_lower) <= 1):
                continue
            
            # 添加原始词
            tokens.append(word_lower)
            
            # 添加同义词扩展
            for base_word, synonym_list in self.synonyms.items():
                if word_lower in synonym_list:
                    for synonym in synonym_list:
                        if synonym != word_lower:
                            tokens.append(synonym)
        
        # 去重并返回
        return list(set(tokens))
    
    def extract_entities(self, text: str) -> List[str]:
        \"\"\"提取实体（简化版）\"\"\"
        entities = []
        
        # 技术术语模式
        tech_patterns = [
            r'[A-Z][a-z]+(?:\\s+[A-Z][a-z]+)*',  # 驼峰式或首字母大写
            r'[A-Z]{2,}',  # 大写缩写
            r'\\b[A-Z][a-z]+\\b',  # 单个大写单词
        ]
        
        for pattern in tech_patterns:
            matches = re.findall(pattern, text)
            entities.extend(matches)
        
        # 中文技术术语（简单匹配）
        chinese_tech_terms = ['人工智能', '机器学习', '深度学习', '神经网络', 
                             '自然语言处理', '计算机视觉', '大数据', '云计算']
        
        for term in chinese_tech_terms:
            if term in text:
                entities.append(term)
        
        return list(set(entities))
'''
        
        # 保存增强分词器代码
        output_file = self.base_dir / "scripts" / "enhanced_tokenizer.py"
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write('''#!/usr/bin/env python3
"""
增强分词器
搜索系统优化 - 分词改进
"""
import re
import logging
from typing import List, Set, Dict
''' + enhanced_tokenizer_code)
        
        logger.info(f"增强分词器代码已保存到: {output_file}")
        
        return str(output_file)
    
    def optimize_index_structure(self):
        """优化索引结构"""
        logger.info("优化索引结构...")
        
        current_structure = """
        当前索引结构：
        1. doc_index: 文档ID -> 文档信息
        2. title_index: 词 -> 文档ID集合
        3. summary_index: 词 -> 文档ID集合  
        4. entity_index: 实体 -> 文档ID集合
        5. fulltext_index: 词 -> 文档ID集合
        6. category_index: 分类 -> 文档ID集合
        """
        
        logger.info(current_structure)
        
        # 建议改进
        improvements = [
            "添加向量索引支持语义搜索",
            "添加时间索引支持按时间范围搜索",
            "添加作者索引（如果有作者信息）",
            "添加标签索引支持多标签搜索",
            "添加相关性评分缓存",
            "添加搜索历史记录"
        ]
        
        logger.info("建议索引结构改进：")
        for i, improvement in enumerate(improvements, 1):
            logger.info(f"  {i}. {improvement}")
        
        return improvements
    
    def create_optimization_plan(self) -> Dict[str, Any]:
        """创建优化计划"""
        logger.info("创建搜索系统优化计划...")
        
        # 分析当前性能
        performance = self.analyze_current_performance()
        
        # 获取优化建议
        tokenizer_improvements = self.optimize_tokenizer()
        index_improvements = self.optimize_index_structure()
        
        # 创建优化计划
        plan = {
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "current_state": {
                "total_documents": performance["total_documents"],
                "performance_metrics": performance["test_queries"]
            },
            "optimization_areas": [
                {
                    "area": "分词器",
                    "priority": "high",
                    "improvements": tokenizer_improvements,
                    "estimated_effort": "2-4小时"
                },
                {
                    "area": "索引结构",
                    "priority": "medium",
                    "improvements": index_improvements,
                    "estimated_effort": "4-8小时"
                },
                {
                    "area": "搜索算法",
                    "priority": "medium",
                    "improvements": [
                        "实现混合搜索（关键词+语义）",
                        "改进相关性评分算法",
                        "添加搜索结果排序选项"
                    ],
                    "estimated_effort": "3-6小时"
                },
                {
                    "area": "性能优化",
                    "priority": "low",
                    "improvements": [
                        "添加查询缓存",
                        "实现增量索引更新",
                        "优化内存使用"
                    ],
                    "estimated_effort": "2-4小时"
                }
            ],
            "recommendations": performance.get("recommendations", []),
            "implementation_priority": [
                "1. 安装jieba并实现增强分词器",
                "2. 重建搜索索引使用新分词器",
                "3. 测试搜索性能改进",
                "4. 根据测试结果优化索引结构",
                "5. 实现高级搜索功能"
            ]
        }
        
        # 保存优化计划
        plan_file = self.base_dir / "search_optimization_plan.json"
        with open(plan_file, 'w', encoding='utf-8') as f:
            json.dump(plan, f, ensure_ascii=False, indent=2)
        
        logger.info(f"优化计划已保存到: {plan_file}")
        
        return plan
    
    def generate_report(self, plan: Dict[str, Any]) -> str:
        """生成优化报告"""
        report_lines = [
            "=" * 60,
            "Karpathy知识库搜索系统优化报告",
            "=" * 60,
            f"生成时间: {plan['created_at']}",
            f"当前文档数量: {plan['current_state']['total_documents']}",
            "",
            "📊 当前性能指标:"
        ]
        
        for metric in plan["current_state"]["performance_metrics"]:
            result_status = "✅ 有结果" if metric["has_results"] else "❌ 无结果"
            report_lines.append(f"  查询 '{metric['query']}': {metric['results_count']} 结果, {metric['response_time']:.3f}秒 ({result_status})")
        
        report_lines.extend([
            "",
            "🎯 优化领域:"
        ])
        
        for area in plan["optimization_areas"]:
            report_lines.append(f"  {area['area']} ({area['priority'].upper()}优先级):")
            for i, improvement in enumerate(area["improvements"], 1):
                report_lines.append(f"    {i}. {improvement}")
            report_lines.append(f"    预计耗时: {area['estimated_effort']}")
            report_lines.append("")
        
        if plan.get("recommendations"):
            report_lines.extend([
                "💡 具体建议:"
            ])
            for rec in plan["recommendations"]:
                report_lines.append(f"  {rec['priority'].upper()}: {rec['suggestion']} ({rec['reason']})")
            report_lines.append("")
        
        report_lines.extend([
            "🚀 实施优先级:"
        ])
        for i, step in enumerate(plan["implementation_priority"], 1):
            report_lines.append(f"  {step}")
        
        report_lines.extend([
            "",
            "=" * 60,
            "下一步行动:"
        ])
        
        # 根据优先级建议下一步
        high_priority_areas = [a for a in plan["optimization_areas"] if a["priority"] == "high"]
        if high_priority_areas:
            report_lines.append(f"  1. 立即开始: {high_priority_areas[0]['area']}")
        
        report_lines.append("  2. 安装jieba: pip install jieba")
        report_lines.append("  3. 测试增强分词器")
        report_lines.append("  4. 重建搜索索引")
        
        return "\n".join(report_lines)

def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="Karpathy知识库搜索系统优化器")
    parser.add_argument("--base-dir", default=".", help="知识库基础目录")
    parser.add_argument("--analyze", action="store_true", help="分析当前性能")
    parser.add_argument("--create-plan", action="store_true", help="创建优化计划")
    parser.add_argument("--create-tokenizer", action="store_true", help="创建增强分词器")
    
    args = parser.parse_args()
    
    # 转换为Path对象
    base_dir = Path(args.base_dir).resolve()
    if not base_dir.exists():
        logger.error(f"基础目录不存在: {base_dir}")
        sys.exit(1)
    
    # 初始化优化器
    optimizer = SearchOptimizer(base_dir)
    
    if args.analyze:
        # 分析性能
        results = optimizer.analyze_current_performance()
        print(json.dumps(results, ensure_ascii=False, indent=2))
    
    elif args.create_tokenizer:
        # 创建增强分词器
        tokenizer_file = optimizer.create_enhanced_tokenizer()
        print(f"✅ 增强分词器已创建: {tokenizer_file}")
    
    elif args.create_plan or not (args.analyze or args.create_tokenizer):
        # 创建优化计划（默认行为）
        plan = optimizer.create_optimization_plan()
        report = optimizer.generate_report(plan)
        print(report)
        
        # 保存报告到文件
        report_file = base_dir / "search_optimization_report.txt"
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write(report)
        
        print(f"\n📄 详细报告已保存到: {report_file}")

if __name__ == "__main__":
    main()