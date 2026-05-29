#!/usr/bin/env python3
"""
统一大模型提供者抽象层
支持本地 Ollama（带流式防超时和思考过程剥离）以及外部 OpenAI 兼容 API（DeepSeek, Qwen 等）
"""

import os
import re
import json
import logging
import requests
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)

class LLMProvider:
    """LLM 提供者基类"""
    def __init__(self, model_name: str, **kwargs):
        self.model_name = model_name
        self.kwargs = kwargs
        
    def generate(self, prompt: str, system_prompt: str = "", **kwargs) -> str:
        """生成单轮回复"""
        raise NotImplementedError
        
    def chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        """多轮对话"""
        raise NotImplementedError

class OllamaProvider(LLMProvider):
    """Ollama API 客户端（强制流式以解决超时，剥离思考过程）"""
    def __init__(self, model_name: str, base_url: str = "http://localhost:11434", **kwargs):
        super().__init__(model_name, **kwargs)
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        
    def _strip_thinking(self, text: str) -> str:
        """移除思考过程 <think>...</think>"""
        return re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()
        
    def chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        url = f"{self.base_url}/api/chat"
        payload = {
            "model": self.model_name,
            "messages": messages,
            "stream": True  # 强制流式以避免 22s HTTP 超时
        }
        
        if "options" in kwargs:
            options = dict(kwargs["options"] or {})
            # Ollama 的 think 参数是顶层字段，不属于 options；放错位置会导致 Gemma 仍然长时间思考。
            if "think" in options:
                payload["think"] = bool(options.pop("think"))
            if options:
                payload["options"] = options
        if "think" in kwargs:
            payload["think"] = bool(kwargs["think"])
            
        full_response = ""
        # 熔断与自愈机制：简单的重试逻辑
        max_retries = 2
        for attempt in range(max_retries):
            try:
                if attempt > 0:
                    logger.info(f"Ollama 重试第 {attempt} 次...")
                    __import__('time').sleep(2 ** attempt)  # 退避
                    
                logger.debug(f"Ollama(Stream): 发送请求至 {url}, 模型={self.model_name}")
                with self.session.post(url, json=payload, stream=True, timeout=120) as response:
                    response.raise_for_status()
                    for line in response.iter_lines():
                        if line:
                            chunk = json.loads(line)
                            if "message" in chunk and "content" in chunk["message"]:
                                full_response += chunk["message"]["content"]
                                
                stripped_response = self._strip_thinking(full_response)
                # 检查是否剥离后内容为空
                if not stripped_response and full_response:
                    logger.warning("Ollama: 剥离 <think> 后内容为空，返回原始响应的部分内容以备后用。")
                    return full_response.strip()
                    
                return stripped_response
                
            except requests.exceptions.RequestException as e:
                logger.error(f"OllamaProvider 请求异常 (attempt {attempt+1}/{max_retries}): {e}")
                if attempt == max_retries - 1:
                    raise

    def generate(self, prompt: str, system_prompt: str = "", **kwargs) -> str:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        return self.chat(messages, **kwargs)

class OpenAIProvider(LLMProvider):
    """OpenAI 兼容 API 客户端 (支持 DeepSeek, Qwen, etc.)"""
    def __init__(self, model_name: str, base_url: str, api_key: str, **kwargs):
        super().__init__(model_name, **kwargs)
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        })
        
    def _strip_thinking(self, text: str) -> str:
        """移除思考过程 <think>...</think> (兼容 DeepSeek Reasoner)"""
        return re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()
        
    def chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model_name,
            "messages": messages,
            "stream": False # 外部 API 一般较稳定，暂不用流式
        }
        
        # 传递额外的参数（提取options中的温度等参数）
        if "options" in kwargs:
            for k, v in kwargs["options"].items():
                if k in ["temperature", "top_p", "max_tokens", "presence_penalty", "frequency_penalty"]:
                    payload[k] = v
        
        try:
            logger.debug(f"OpenAI API: 发送请求至 {url}, 模型={self.model_name}")
            response = self.session.post(url, json=payload, timeout=60)
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            return self._strip_thinking(content)
        except Exception as e:
            logger.error(f"OpenAIProvider chat 异常: {e}")
            if hasattr(e, 'response') and getattr(e, 'response') is not None:
                logger.error(f"Response data: {e.response.text}")
            raise

    def generate(self, prompt: str, system_prompt: str = "", **kwargs) -> str:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        return self.chat(messages, **kwargs)

class ProviderFactory:
    """根据环境变量配置创建对应的 LLM Provider"""
    @staticmethod
    def create(default_model: str = "gemma4:e4b") -> LLMProvider:
        provider_type = os.environ.get("KB_LLM_PROVIDER", "ollama").lower()
        model_name = os.environ.get("KB_LLM_MODEL", default_model)
        
        if provider_type == "openai":
            base_url = os.environ.get("KB_LLM_BASE_URL", "https://api.deepseek.com/v1")
            api_key = os.environ.get("KB_LLM_API_KEY", "")
            logger.info(f"初始化 OpenAI Provider: model={model_name}, base_url={base_url}")
            return OpenAIProvider(model_name=model_name, base_url=base_url, api_key=api_key)
        else:
            base_url = os.environ.get("KB_LLM_BASE_URL", "http://localhost:11434")
            logger.info(f"初始化 Ollama Provider: model={model_name}, base_url={base_url}")
            return OllamaProvider(model_name=model_name, base_url=base_url)

if __name__ == "__main__":
    # 测试脚本
    logging.basicConfig(level=logging.INFO)
    provider = ProviderFactory.create()
    res = provider.generate("你好，请简短回答什么是机器学习？", system_prompt="你是一个AI助手。")
    print(f"Response:\n{res}")
