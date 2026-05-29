#!/usr/bin/env python3
"""
Karpathy知识库系统诊断和优化脚本
分析性能问题并提供优化建议
"""

import time
import sys
import json
import yaml
import logging
from pathlib import Path
from typing import Dict, Any, List

sys.path.insert(0, str(Path(__file__).parent))

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class SystemDiagnoser:
    """系统诊断器"""
    
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.config_path = base_dir / "models_config.yaml"
        self.issues = []
        self.optimizations = []
    
    def load_config(self) -> Dict[str, Any]:
        """加载配置文件"""
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)
        except Exception as e:
            logger.error(f"加载配置文件失败: {e}")
            return {}
    
    def check_ollama_service(self):
        """检查Ollama服务状态"""
        print("🔧 检查Ollama服务状态...")
        
        try:
            import requests
            response = requests.get("http://localhost:11434/api/tags", timeout=10)
            
            if response.status_code == 200:
                models = response.json().get("models", [])
                model_names = [m["name"] for m in models]
                print(f"  ✅ Ollama服务正常，{len(model_names)} 个可用模型:")
                for model in model_names:
                    print(f"    - {model}")
                
                # 检查gemma4模型
                gemma4_models = [m for m in model_names if "gemma4" in m]
                if gemma4_models:
                    print(f"  ✅ Gemma4模型可用: {', '.join(gemma4_models)}")
                else:
                    print("  ⚠️ 没有可用的Gemma4模型")
                    self.issues.append("Ollama中没有Gemma4模型")
                    
            else:
                print(f"  ❌ Ollama服务错误: HTTP {response.status_code}")
                self.issues.append(f"Ollama服务返回错误: HTTP {response.status_code}")
                
        except Exception as e:
            print(f"  ❌ 无法连接到Ollama服务: {e}")
            self.issues.append(f"无法连接到Ollama服务: {e}")
    
    def analyze_model_config(self):
        """分析模型配置文件"""
        print("\n📋 分析模型配置...")
        config = self.load_config()
        
        if not config:
            print("  ❌ 无法加载配置文件")
            self.issues.append("无法加载models_config.yaml")
            return
        
        # 检查gemma4配置
        model_configs = config.get("model_configs", {})
        gemma4_config = model_configs.get("gemma4")
        
        if gemma4_config:
            print("  ✅ 找到Gemma4配置")
            
            # 检查behavior设置
            behavior = gemma4_config.get("behavior", {})
            default_thinking = behavior.get("default_thinking_enabled")
            content_issues = behavior.get("content_field_issues")
            
            if default_thinking:
                print(f"  ⚠️ Gemma4默认启用思考模式: {default_thinking}")
                self.issues.append("Gemma4默认启用思考模式，可能导致content字段为空")
            
            if content_issues:
                print(f"  ⚠️ Gemma4有content字段问题: {content_issues}")
                self.issues.append("Gemma4有content字段问题，需要禁用思考模式")
            
            # 检查系统提示词
            system_prompts = gemma4_config.get("system_prompts", [])
            print(f"  ✅ 系统提示词数量: {len(system_prompts)}")
            
            # 检查API参数
            api_params = gemma4_config.get("api_params", {})
            ollama_params = api_params.get("ollama", {})
            
            if "think" in ollama_params:
                think_value = ollama_params.get("think")
                print(f"  ✅ Ollama think参数: {think_value}")
                if think_value is not False:
                    print(f"  ⚠️ think参数应为False，当前为: {think_value}")
                    self.optimizations.append("将Ollama think参数设置为False")
            else:
                print("  ⚠️ Ollama参数中没有think设置")
                self.optimizations.append("在Gemma4配置中添加think: false参数")
                
        else:
            print("  ❌ 没有找到Gemma4配置")
            self.issues.append("models_config.yaml中没有Gemma4配置")
    
    def check_processor_config(self):
        """检查processor.py中的配置"""
        print("\n🔍 检查processor.py配置...")
        
        processor_path = self.base_dir / "scripts" / "processor.py"
        if not processor_path.exists():
            print("  ❌ processor.py不存在")
            self.issues.append("processor.py不存在")
            return
        
        try:
            with open(processor_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 检查默认模型设置
            if "model: str = \"gemma4:e4b\"" in content:
                print("  ✅ 默认模型设置为gemma4:e4b")
            else:
                print("  ⚠️ 默认模型设置可能需要检查")
            
            # 检查超时设置
            if "session.timeout = 180" in content:
                print("  ✅ 会话超时设置为180秒")
            else:
                print("  ⚠️ 会话超时设置可能需要调整")
            
            # 检查是否使用了model_adapter
            if "self.adapter = ModelAdapter()" in content:
                print("  ✅ 使用了ModelAdapter")
            else:
                print("  ⚠️ 可能没有使用ModelAdapter")
                
        except Exception as e:
            print(f"  ❌ 读取processor.py失败: {e}")
    
    def check_qa_config(self):
        """检查qa.py中的配置"""
        print("\n❓ 检查qa.py配置...")
        
        qa_path = self.base_dir / "scripts" / "qa.py"
        if not qa_path.exists():
            print("  ❌ qa.py不存在")
            self.issues.append("qa.py不存在")
            return
        
        try:
            with open(qa_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 检查系统提示词长度
            import re
            system_prompt_match = re.search(r'system_prompt = """.*?"""', content, re.DOTALL)
            if system_prompt_match:
                system_prompt = system_prompt_match.group(0)
                prompt_length = len(system_prompt)
                print(f"  ✅ 系统提示词长度: {prompt_length} 字符")
                
                if prompt_length > 500:
                    print(f"  ⚠️ 系统提示词过长，可能影响Gemma4响应")
                    self.optimizations.append("缩短系统提示词，避免Gemma4提前终止")
            
            # 检查是否处理了thinking模式
            if "think" in content.lower():
                print("  ✅ 代码中考虑了think参数")
            else:
                print("  ⚠️ 代码中没有显式处理think参数")
                
        except Exception as e:
            print(f"  ❌ 读取qa.py失败: {e}")
    
    def test_simple_chat(self):
        """测试简单聊天性能"""
        print("\n🤖 测试简单Ollama聊天...")
        
        try:
            from processor import OllamaClient
            
            # 初始化客户端
            start = time.time()
            ollama = OllamaClient()
            init_time = time.time() - start
            print(f"  ✅ Ollama客户端初始化: {init_time:.2f}秒")
            
            # 测试简单消息
            messages = [
                {"role": "system", "content": "请用中文简短回答，不要思考。"},
                {"role": "user", "content": "你是谁？"}
            ]
            
            print("  ⏳ 发送测试消息...")
            start = time.time()
            
            try:
                response = ollama.chat(messages, options={"think": False}, max_retries=1)
                response_time = time.time() - start
                
                if response:
                    print(f"  ✅ 聊天响应时间: {response_time:.2f}秒")
                    print(f"  ✅ 响应长度: {len(response)} 字符")
                    print(f"  ✅ 响应预览: {response[:100]}...")
                    
                    if response_time > 30:
                        print(f"  ⚠️ 响应时间较长 ({response_time:.2f}秒)")
                        self.issues.append(f"Ollama响应时间较长: {response_time:.2f}秒")
                else:
                    print("  ❌ 收到空响应")
                    self.issues.append("Ollama返回空响应")
                    
            except Exception as e:
                print(f"  ❌ 聊天测试失败: {e}")
                self.issues.append(f"Ollama聊天失败: {e}")
                
        except Exception as e:
            print(f"  ❌ 初始化OllamaClient失败: {e}")
            self.issues.append(f"无法初始化OllamaClient: {e}")
    
    def generate_report(self):
        """生成诊断报告"""
        print("\n" + "="*60)
        print("📊 诊断报告")
        print("="*60)
        
        if self.issues:
            print(f"🔴 发现 {len(self.issues)} 个问题:")
            for i, issue in enumerate(self.issues, 1):
                print(f"  {i}. {issue}")
        else:
            print("✅ 未发现重大问题")
        
        if self.optimizations:
            print(f"\n🟡 建议 {len(self.optimizations)} 个优化:")
            for i, opt in enumerate(self.optimizations, 1):
                print(f"  {i}. {opt}")
        else:
            print("\n✅ 暂无优化建议")
        
        print("\n" + "="*60)
        print("🚀 优化行动计划")
        print("="*60)
        
        action_plan = []
        
        # 根据问题生成行动项
        if "Gemma4默认启用思考模式" in " ".join(self.issues):
            action_plan.append("1. 确保Gemma4配置中think: false")
            action_plan.append("2. 在Ollama调用中显式设置think=false")
            action_plan.append("3. 使用简短系统提示词避免提前终止")
        
        if any("响应时间" in issue for issue in self.issues):
            action_plan.append("4. 考虑使用更轻量模型如gemma4:e4b (8B)")
            action_plan.append("5. 减少上下文token长度")
            action_plan.append("6. 实现模型预热机制")
        
        if any("空响应" in issue for issue in self.issues):
            action_plan.append("7. 检查系统提示词是否过长")
            action_plan.append("8. 确保禁用thinking模式")
            action_plan.append("9. 添加空响应重试逻辑")
        
        if not action_plan:
            action_plan.append("1. 运行完整系统测试")
            action_plan.append("2. 优化答案输出格式")
            action_plan.append("3. 准备OpenClaw集成")
        
        for action in action_plan:
            print(f"  {action}")
        
        print("\n" + "="*60)

def main():
    """主函数"""
    base_dir = Path.home() / "karpathy-kb"
    
    if not base_dir.exists():
        print(f"❌ 错误: 目录不存在: {base_dir}")
        return 1
    
    print("🧪 Karpathy知识库系统诊断")
    print("="*60)
    
    diagnoser = SystemDiagnoser(base_dir)
    
    try:
        # 执行诊断
        diagnoser.check_ollama_service()
        diagnoser.analyze_model_config()
        diagnoser.check_processor_config()
        diagnoser.check_qa_config()
        diagnoser.test_simple_chat()
        
        # 生成报告
        diagnoser.generate_report()
        
    except KeyboardInterrupt:
        print("\n诊断被用户中断")
    except Exception as e:
        print(f"\n诊断过程中出现错误: {e}")
        import traceback
        traceback.print_exc()
    
    return 0

if __name__ == "__main__":
    sys.exit(main())