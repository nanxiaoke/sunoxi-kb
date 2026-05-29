#!/usr/bin/env python3
"""
模型自适应层
根据模型类型自动选择最佳配置、提示词和参数
"""

import re
import yaml
import logging
from typing import Dict, List, Optional, Any, Tuple
from pathlib import Path
import json

logger = logging.getLogger(__name__)

class ModelAdapter:
    """模型自适应适配器"""
    
    def __init__(self, config_path: Optional[Path] = None):
        """
        初始化模型适配器
        
        Args:
            config_path: 配置文件路径，默认为项目根目录下的models_config.yaml
        """
        if config_path is None:
            config_path = Path.home() / "karpathy-kb" / "models_config.yaml"
        
        self.config_path = config_path
        self.config = self._load_config()
        self.model_cache = {}  # 缓存检测结果
        
        logger.info(f"模型适配器初始化完成，配置文件: {config_path}")
    
    def _load_config(self) -> Dict[str, Any]:
        """加载配置文件"""
        try:
            if not self.config_path.exists():
                logger.warning(f"配置文件不存在: {self.config_path}，使用默认配置")
                return self._get_default_config()
            
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
            
            logger.debug(f"配置文件加载成功: {self.config_path}")
            return config
            
        except Exception as e:
            logger.error(f"加载配置文件失败: {e}，使用默认配置")
            return self._get_default_config()
    
    def _get_default_config(self) -> Dict[str, Any]:
        """获取默认配置"""
        return {
            "model_configs": {
                "default": {
                    "patterns": [".*"],
                    "system_prompts": ["You are a helpful assistant."],
                    "api_params": {
                        "ollama": {"temperature": 0.7, "num_predict": 800}
                    }
                }
            },
            "task_configs": {
                "summarization": {
                    "system_prompt_templates": [
                        "You are a helpful research assistant that summarizes documents."
                    ]
                }
            }
        }
    
    def detect_model_type(self, model_name: str) -> str:
        """
        检测模型类型
        
        Args:
            model_name: 模型名称，如 "gemma4:e4b"、"deepseek-chat"等
            
        Returns:
            检测到的模型类型，如 "gemma4"、"deepseek"等
        """
        # 检查缓存
        if model_name in self.model_cache:
            return self.model_cache[model_name]
        
        model_name_lower = model_name.lower()
        
        # 遍历配置中的所有模型类型
        model_configs = self.config.get("model_configs", {})
        
        for model_type, config in model_configs.items():
            patterns = config.get("patterns", [])
            for pattern in patterns:
                # 简单字符串匹配
                if pattern in model_name_lower:
                    self.model_cache[model_name] = model_type
                    logger.debug(f"检测到模型 '{model_name}' -> 类型 '{model_type}' (模式匹配: {pattern})")
                    return model_type
                
                # 正则表达式匹配
                try:
                    if re.search(pattern, model_name_lower):
                        self.model_cache[model_name] = model_type
                        logger.debug(f"检测到模型 '{model_name}' -> 类型 '{model_type}' (正则匹配: {pattern})")
                        return model_type
                except re.error:
                    # 不是有效的正则表达式，跳过
                    continue
        
        # 默认类型
        self.model_cache[model_name] = "default"
        logger.debug(f"检测到模型 '{model_name}' -> 类型 'default' (默认)")
        return "default"
    
    def get_model_config(self, model_name: str) -> Dict[str, Any]:
        """
        获取指定模型的完整配置
        
        Args:
            model_name: 模型名称
            
        Returns:
            模型配置字典
        """
        model_type = self.detect_model_type(model_name)
        model_configs = self.config.get("model_configs", {})
        
        config = model_configs.get(model_type, {})
        
        # 添加模型名称到配置
        config["detected_type"] = model_type
        config["original_name"] = model_name
        
        return config
    
    def get_system_prompts(self, model_name: str, task_type: Optional[str] = None) -> List[str]:
        """
        获取模型的最佳系统提示词列表
        
        Args:
            model_name: 模型名称
            task_type: 任务类型，如 "summarization"、"categorization"等
            
        Returns:
            系统提示词列表（优先级顺序）
        """
        model_config = self.get_model_config(model_name)
        
        # 首先获取任务特定的系统提示（如果提供）
        task_prompts = []
        if task_type:
            task_configs = self.config.get("task_configs", {})
            task_config = task_configs.get(task_type, {})
            task_prompts = task_config.get("system_prompt_templates", [])
        
        # 获取模型特定的系统提示
        model_prompts = model_config.get("system_prompts", [])
        
        # 合并列表：任务提示优先，然后是模型提示
        all_prompts = []
        if task_prompts:
            all_prompts.extend(task_prompts)
        
        if model_prompts:
            all_prompts.extend(model_prompts)
        
        # 如果没有找到任何提示，使用默认
        if not all_prompts:
            all_prompts = ["You are a helpful assistant."]
        
        logger.debug(f"为模型 '{model_name}' 任务 '{task_type}' 生成 {len(all_prompts)} 个系统提示")
        return all_prompts
    
    def get_api_params(self, model_name: str, api_type: str = "ollama") -> Dict[str, Any]:
        """
        获取模型的API参数
        
        Args:
            model_name: 模型名称
            api_type: API类型，"ollama"或"generic"
            
        Returns:
            API参数字典
        """
        model_config = self.get_model_config(model_name)
        api_params = model_config.get("api_params", {})
        
        # 获取指定API类型的参数
        params = api_params.get(api_type, {})
        
        # 如果没有找到特定API类型的参数，使用generic
        if not params and api_type != "generic":
            params = api_params.get("generic", {})
        
        # 确保有基本参数
        if not params:
            params = {"temperature": 0.7, "num_predict": 800}
        
        logger.debug(f"为模型 '{model_name}' API类型 '{api_type}' 生成参数: {params}")
        return params
    
    def format_user_prompt(self, task_type: str, **kwargs) -> str:
        """
        格式化用户提示词
        
        Args:
            task_type: 任务类型
            **kwargs: 任务特定的参数
            
        Returns:
            格式化的用户提示词
        """
        task_configs = self.config.get("task_configs", {})
        task_config = task_configs.get(task_type, {})
        
        templates = task_config.get("user_prompt_templates", [])
        
        if not templates:
            # 默认模板
            if task_type == "summarization":
                text = kwargs.get("text", "")
                max_length = kwargs.get("max_length", 300)
                return f"Please summarize the following text in under {max_length} words:\n\n{text}\n\nSummary:"
            elif task_type == "categorization":
                text = kwargs.get("text", "")
                categories = kwargs.get("categories", "technology, academic_paper, notes, code, article, news, tutorial, other")
                return f"Classify this document: {categories}\n\nDocument: {text}\n\nCategory:"
            else:
                text = kwargs.get("text", "")
                return text
        
        # 使用第一个模板
        template = templates[0]
        
        try:
            formatted = template.format(**kwargs)
            return formatted
        except KeyError as e:
            logger.warning(f"格式化提示词时缺少参数 {e}，使用原始模板")
            return template
    
    def get_task_config(self, task_type: str) -> Dict[str, Any]:
        """
        获取任务配置
        
        Args:
            task_type: 任务类型
            
        Returns:
            任务配置字典
        """
        task_configs = self.config.get("task_configs", {})
        return task_configs.get(task_type, {})
    
    def get_recommended_models(self, task_type: Optional[str] = None) -> List[str]:
        """
        获取推荐模型列表
        
        Args:
            task_type: 任务类型，如果为None则返回通用推荐
            
        Returns:
            推荐模型类型列表（优先级顺序）
        """
        if task_type:
            # 按任务推荐
            model_selection = self.config.get("model_selection", {})
            by_task = model_selection.get("by_task", {})
            return by_task.get(task_type, [])
        else:
            # 通用回退顺序
            model_selection = self.config.get("model_selection", {})
            return model_selection.get("fallback_order", [])
    
    def adapt_messages(self, model_name: str, task_type: str, 
                      original_messages: Optional[List[Dict[str, str]]] = None,
                      **task_kwargs) -> List[List[Dict[str, str]]]:
        """
        自适应调整消息格式，生成多种策略
        
        Args:
            model_name: 模型名称
            task_type: 任务类型
            original_messages: 原始消息列表
            **task_kwargs: 任务特定参数
            
        Returns:
            消息策略列表
        """
        strategies = []
        
        # 获取模型配置
        model_config = self.get_model_config(model_name)
        model_type = model_config.get("detected_type", "default")
        
        # 获取系统提示
        system_prompts = self.get_system_prompts(model_name, task_type)
        
        # 生成用户提示
        user_prompt = self.format_user_prompt(task_type, **task_kwargs)
        
        # 策略1: 最佳系统提示 + 用户提示
        if system_prompts:
            best_system_prompt = system_prompts[0]
            strategies.append([
                {"role": "system", "content": best_system_prompt},
                {"role": "user", "content": user_prompt}
            ])
        
        # 策略2: 备选系统提示（如果有多个）
        if len(system_prompts) > 1:
            for system_prompt in system_prompts[1:3]:  # 最多取前3个
                strategies.append([
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ])
        
        # 策略3: 无系统提示（某些模型可能不需要）
        strategies.append([
            {"role": "user", "content": user_prompt}
        ])
        
        # 策略4: 对于gemma4，添加专用禁用思考提示
        if model_type == "gemma4":
            gemma4_specific = [
                {"role": "system", "content": "Do not think. Just answer directly without showing your thinking process."},
                {"role": "user", "content": user_prompt}
            ]
            strategies.append(gemma4_specific)
        
        # 策略5: 如果提供了原始消息，也包含它
        if original_messages:
            strategies.append(original_messages)
        
        logger.debug(f"为模型 '{model_name}' 任务 '{task_type}' 生成 {len(strategies)} 种消息策略")
        return strategies
    
    def adapt_api_params(self, model_name: str, original_params: Optional[Dict[str, Any]] = None,
                        api_type: str = "ollama") -> Dict[str, Any]:
        """
        自适应调整API参数
        
        Args:
            model_name: 模型名称
            original_params: 原始API参数
            api_type: API类型
            
        Returns:
            调整后的API参数
        """
        # 获取模型推荐参数
        model_params = self.get_api_params(model_name, api_type)
        
        # 合并参数：模型参数为基础，原始参数覆盖
        final_params = model_params.copy()
        if original_params:
            final_params.update(original_params)
        
        # 特殊处理：对于gemma4，确保think参数被设置
        model_type = self.detect_model_type(model_name)
        if model_type == "gemma4" and "think" not in final_params:
            final_params["think"] = False
        
        logger.debug(f"为模型 '{model_name}' 调整API参数: {final_params}")
        return final_params
    
    def validate_response(self, model_name: str, response: Dict[str, Any]) -> Tuple[bool, str]:
        """
        验证模型响应
        
        Args:
            model_name: 模型名称
            response: 响应字典
            
        Returns:
            (是否有效, 错误信息)
        """
        model_config = self.get_model_config(model_name)
        behavior = model_config.get("behavior", {})
        
        # 检查content字段是否为空
        content = response.get("content", "")
        thinking = response.get("thinking", "")
        
        content_empty = not bool(content.strip())
        thinking_present = bool(thinking.strip())
        
        # 对于有content字段问题的模型
        if behavior.get("content_field_issues", False):
            if content_empty and thinking_present:
                return False, "Content field is empty but thinking is present (gemma4思考模式问题)"
        
        # 基本检查
        if content_empty:
            return False, "Content field is empty"
        
        return True, "Response is valid"
    
    def get_model_behavior_info(self, model_name: str) -> Dict[str, Any]:
        """
        获取模型行为信息
        
        Args:
            model_name: 模型名称
            
        Returns:
            行为信息字典
        """
        model_config = self.get_model_config(model_name)
        behavior = model_config.get("behavior", {})
        
        info = {
            "model_name": model_name,
            "detected_type": model_config.get("detected_type", "default"),
            "default_thinking_enabled": behavior.get("default_thinking_enabled", False),
            "content_field_issues": behavior.get("content_field_issues", False),
            "requires_explicit_disable": behavior.get("requires_explicit_disable", False),
            "recommended_system_prompts": self.get_system_prompts(model_name)[:3],
            "recommended_api_params": self.get_api_params(model_name),
        }
        
        return info
    
    def log_model_performance(self, model_name: str, task_type: str, 
                            success: bool, response_time: float,
                            response: Optional[Dict[str, Any]] = None):
        """
        记录模型性能数据
        
        Args:
            model_name: 模型名称
            task_type: 任务类型
            success: 是否成功
            response_time: 响应时间（秒）
            response: 响应数据（可选）
        """
        # 这里可以集成到监控系统
        metrics = {
            "timestamp": self._get_timestamp(),
            "model_name": model_name,
            "task_type": task_type,
            "success": success,
            "response_time": response_time,
            "detected_type": self.detect_model_type(model_name),
        }
        
        if response:
            content = response.get("content", "")
            thinking = response.get("thinking", "")
            metrics.update({
                "content_length": len(content),
                "thinking_present": bool(thinking),
                "content_empty": not bool(content.strip()),
            })
        
        # 记录到日志
        logger.info(f"模型性能: {json.dumps(metrics, ensure_ascii=False)}")
        
        # 这里可以添加将数据保存到文件或数据库的逻辑
        # self._save_performance_data(metrics)
    
    def _get_timestamp(self) -> str:
        """获取时间戳"""
        from datetime import datetime
        return datetime.now().isoformat()
    
    def update_config(self, model_name: str, field: str, value: Any):
        """
        更新配置（用于动态调优）
        
        Args:
            model_name: 模型名称
            field: 字段名，如 "system_prompts"、"api_params"
            value: 新值
        """
        model_type = self.detect_model_type(model_name)
        model_configs = self.config.get("model_configs", {})
        
        if model_type in model_configs:
            # 更新配置
            if isinstance(value, dict) and field in model_configs[model_type]:
                # 合并字典
                model_configs[model_type][field].update(value)
            else:
                model_configs[model_type][field] = value
            
            # 保存到文件
            try:
                with open(self.config_path, 'w', encoding='utf-8') as f:
                    yaml.dump(self.config, f, default_flow_style=False, allow_unicode=True)
                logger.info(f"配置已更新: {model_type}.{field}")
            except Exception as e:
                logger.error(f"保存配置失败: {e}")
        else:
            logger.warning(f"未找到模型类型配置: {model_type}")


# 工具函数
def get_model_adapter(config_path: Optional[Path] = None) -> ModelAdapter:
    """
    获取模型适配器实例（单例模式简化版）
    
    Args:
        config_path: 配置文件路径
        
    Returns:
        ModelAdapter实例
    """
    return ModelAdapter(config_path)


# 测试函数
def test_model_adapter():
    """测试模型适配器"""
    import sys
    
    logging.basicConfig(level=logging.INFO)
    
    adapter = ModelAdapter()
    
    # 测试模型检测
    test_models = [
        "gemma4:e4b",
        "gemma4:26b",
        "deepseek-chat",
        "deepseek-reasoner",
        "llama3:8b",
        "qwen2.5:7b",
        "chatglm3:6b",
        "unknown-model:1.0",
    ]
    
    print("🔍 测试模型检测:")
    for model in test_models:
        model_type = adapter.detect_model_type(model)
        print(f"  {model} -> {model_type}")
    
    print("\n🔍 测试配置获取:")
    for model in ["gemma4:e4b", "deepseek-chat", "unknown-model"]:
        config = adapter.get_model_config(model)
        print(f"  {model}: {config.get('detected_type', 'unknown')}")
    
    print("\n🔍 测试系统提示生成:")
    for model in ["gemma4:e4b", "deepseek-chat"]:
        prompts = adapter.get_system_prompts(model, "summarization")
        print(f"  {model} 摘要任务提示:")
        for i, prompt in enumerate(prompts[:2]):
            print(f"    {i+1}. {prompt[:60]}...")
    
    print("\n🔍 测试消息策略生成:")
    for model in ["gemma4:e4b", "deepseek-chat"]:
        strategies = adapter.adapt_messages(
            model_name=model,
            task_type="summarization",
            text="This is a test document about artificial intelligence.",
            max_length=100
        )
        print(f"  {model} 生成 {len(strategies)} 种策略")
    
    print("\n🔍 测试API参数适配:")
    for model in ["gemma4:e4b", "deepseek-chat"]:
        params = adapter.adapt_api_params(model, {"temperature": 0.5})
        print(f"  {model}: {params}")
    
    print("\n🔍 测试模型行为信息:")
    for model in ["gemma4:e4b", "deepseek-chat"]:
        info = adapter.get_model_behavior_info(model)
        print(f"  {model}:")
        print(f"    类型: {info['detected_type']}")
        print(f"    默认思考: {info['default_thinking_enabled']}")
        print(f"    content字段问题: {info['content_field_issues']}")
        print(f"    需要显式禁用: {info['requires_explicit_disable']}")


if __name__ == "__main__":
    test_model_adapter()