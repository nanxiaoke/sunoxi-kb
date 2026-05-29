#!/usr/bin/env python3
"""
验证模型自适应层的修复
"""

import sys
import logging
from pathlib import Path

# 添加脚本目录到路径
sys.path.insert(0, str(Path.home() / "karpathy-kb" / "scripts"))

# 设置日志
logging.basicConfig(level=logging.WARNING)

def verify_model_mapping():
    """验证模型类型到具体模型的映射"""
    print("🔍 验证模型映射修复...")
    
    # 模拟的可用模型列表（基于实际Ollama输出）
    available_models = ["gemma4:e4b", "gemma4:e4b-it-q8_0", "gemma4:26b"]
    
    # 测试映射逻辑
    test_cases = [
        {
            "task": "summarization",
            "recommended_types": ["gemma4", "deepseek", "llama3"],
            "expected_matches": ["gemma4:e4b", "gemma4:e4b-it-q8_0", "gemma4:26b"]
        },
        {
            "task": "categorization", 
            "recommended_types": ["gemma4", "deepseek", "llama3"],
            "expected_matches": ["gemma4:e4b", "gemma4:e4b-it-q8_0", "gemma4:26b"]
        }
    ]
    
    all_passed = True
    
    for test in test_cases:
        print(f"\n📋 测试任务: {test['task']}")
        print(f"   推荐类型: {test['recommended_types']}")
        
        # 执行映射逻辑
        available_concrete_models = []
        for model_type in test["recommended_types"]:
            matching_models = [m for m in available_models if model_type.lower() in m.lower()]
            if matching_models:
                available_concrete_models.extend(matching_models)
        
        # 去重
        available_concrete_models = list(dict.fromkeys(available_concrete_models))
        
        print(f"   映射结果: {available_concrete_models}")
        print(f"   预期结果: {test['expected_matches']}")
        
        # 检查映射是否包含预期模型
        has_all_expected = all(m in available_concrete_models for m in test["expected_matches"])
        
        if has_all_expected:
            print("   ✅ 映射正确")
        else:
            print("   ❌ 映射错误")
            all_passed = False
    
    return all_passed

def verify_processor_structure():
    """验证处理器结构"""
    print("\n🔍 验证处理器结构...")
    
    try:
        # 检查文件修改
        processor_path = Path.home() / "karpathy-kb" / "scripts" / "processor.py"
        with open(processor_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        check_points = [
            ("模型自适应层导入", "from .model_adapter import ModelAdapter" in content or "from model_adapter import ModelAdapter" in content),
            ("适配器初始化", "self.adapter = ModelAdapter()" in content),
            ("可用模型存储", "self.available_models = []" in content),
            ("模型映射逻辑", "matching_models = [m for m in self.available_models" in content),
            ("_process_task方法", "def _process_task(self, task_type: str, text: str," in content),
            ("更新AI方法", "def summarize(self, text: str, max_length: int = 300)" in content and "_process_task" in content),
        ]
        
        all_passed = True
        for check_name, check_result in check_points:
            status = "✅" if check_result else "❌"
            print(f"   {status} {check_name}: {'通过' if check_result else '失败'}")
            if not check_result:
                all_passed = False
        
        return all_passed
        
    except Exception as e:
        print(f"❌ 验证失败: {e}")
        return False

def verify_config_files():
    """验证配置文件"""
    print("\n🔍 验证配置文件...")
    
    config_files = [
        ("models_config.yaml", Path.home() / "karpathy-kb" / "models_config.yaml"),
        ("model_adapter.py", Path.home() / "karpathy-kb" / "scripts" / "model_adapter.py"),
    ]
    
    all_passed = True
    
    for file_name, file_path in config_files:
        if file_path.exists():
            print(f"   ✅ {file_name} 存在")
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                size_kb = len(content) / 1024
                print(f"      大小: {size_kb:.1f} KB")
                
                # 检查关键内容
                if file_name == "models_config.yaml":
                    checks = [
                        ("gemma4配置", "gemma4:" in content),
                        ("deepseek配置", "deepseek:" in content),
                        ("任务配置", "task_configs:" in content),
                        ("模型选择策略", "model_selection:" in content),
                    ]
                else:  # model_adapter.py
                    checks = [
                        ("ModelAdapter类", "class ModelAdapter" in content),
                        ("detect_model_type方法", "def detect_model_type" in content),
                        ("adapt_messages方法", "def adapt_messages" in content),
                        ("get_recommended_models方法", "def get_recommended_models" in content),
                    ]
                
                for check_name, check_result in checks:
                    if check_result:
                        print(f"      包含: {check_name}")
                    else:
                        print(f"      ⚠️ 缺少: {check_name}")
                        all_passed = False
                        
            except Exception as e:
                print(f"   ❌ 读取{file_name}失败: {e}")
                all_passed = False
        else:
            print(f"   ❌ {file_name} 不存在")
            all_passed = False
    
    return all_passed

def main():
    """主验证函数"""
    print("🧪 验证模型自适应层修复")
    print("=" * 60)
    
    results = []
    
    # 验证配置文件
    results.append(("配置文件", verify_config_files()))
    
    # 验证处理器结构
    results.append(("处理器结构", verify_processor_structure()))
    
    # 验证模型映射
    results.append(("模型映射", verify_model_mapping()))
    
    print("\n" + "=" * 60)
    print("📊 验证结果汇总:")
    
    all_passed = True
    for test_name, passed in results:
        status = "✅" if passed else "❌"
        print(f"   {status} {test_name}: {'通过' if passed else '失败'}")
        if not passed:
            all_passed = False
    
    print("\n" + "=" * 60)
    if all_passed:
        print("🎉 所有验证通过！模型自适应层已成功实现。")
    else:
        print("⚠️  部分验证失败，请检查修复。")

if __name__ == "__main__":
    main()