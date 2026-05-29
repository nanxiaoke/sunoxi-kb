#!/usr/bin/env python3
"""
环境检查与配置脚本
"""
import os
import sys
import subprocess
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

def check_ollama():
    """检查Ollama服务状态"""
    print("🔍 检查Ollama服务...")
    try:
        result = subprocess.run(['curl', '-s', 'http://localhost:11434/api/tags'], 
                              capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            try:
                data = json.loads(result.stdout)
                if 'models' in data:
                    print("✅ Ollama服务正常")
                    print(f"   可用模型: {', '.join([m['name'] for m in data['models']])}")
                    return True
                else:
                    print("❌ Ollama返回数据格式异常")
                    return False
            except json.JSONDecodeError:
                print(f"❌ Ollama返回非JSON数据: {result.stdout[:100]}")
                return False
        else:
            print(f"❌ Ollama服务异常 (curl返回: {result.returncode})")
            print(f"   错误输出: {result.stderr}")
            return False
    except subprocess.TimeoutExpired:
        print("❌ Ollama服务连接超时 (10秒)")
        return False
    except Exception as e:
        print(f"❌ Ollama检查失败: {e}")
        return False

def check_directory_structure():
    """检查目录结构"""
    print("\n📁 检查目录结构...")
    base = BASE_DIR
    required_dirs = ['raw', 'wiki', 'outputs', 'scripts', 'config', 'logs', 'tests']
    
    all_ok = True
    for dir_name in required_dirs:
        dir_path = base / dir_name
        if dir_path.exists() and dir_path.is_dir():
            # 计算子目录数量
            subdirs = list(dir_path.iterdir())
            dir_count = len([d for d in subdirs if d.is_dir()])
            file_count = len([f for f in subdirs if f.is_file()])
            print(f"✅ {dir_name}/: 存在 ({dir_count}个子目录, {file_count}个文件)")
        else:
            print(f"❌ {dir_name}/: 目录缺失")
            all_ok = False
    
    # 检查raw子目录
    raw_subdirs = ['articles', 'papers', 'notes', 'codes', 'webpages']
    for subdir in raw_subdirs:
        subdir_path = base / 'raw' / subdir
        if subdir_path.exists():
            print(f"   raw/{subdir}/: 存在")
        else:
            print(f"   raw/{subdir}/: 缺失")
    
    # 检查wiki子目录  
    wiki_subdirs = ['concepts', 'people', 'projects', 'technologies', 'notes']
    for subdir in wiki_subdirs:
        subdir_path = base / 'wiki' / subdir
        if subdir_path.exists():
            print(f"   wiki/{subdir}/: 存在")
        else:
            print(f"   wiki/{subdir}/: 缺失")
    
    return all_ok

def check_python_dependencies():
    """检查Python依赖"""
    print("\n🐍 检查Python依赖...")
    dependencies = ['requests', 'markdown', 'beautifulsoup4']
    
    all_ok = True
    for dep in dependencies:
        try:
            __import__(dep)
            print(f"✅ {dep}: 已安装")
        except ImportError:
            print(f"❌ {dep}: 未安装")
            all_ok = False
    
    if not all_ok:
        print("\n💡 安装缺失依赖:")
        print(f"   pip install {' '.join(dependencies)}")
    
    return all_ok

def check_test_documents():
    """检查测试文档"""
    print("\n📄 检查测试文档...")
    base = BASE_DIR
    raw_path = base / 'raw'
    
    # 统计各目录文档数量
    total_files = 0
    for root, dirs, files in os.walk(raw_path):
        for file in files:
            if not file.startswith('.'):
                total_files += 1
    
    if total_files > 0:
        print(f"✅ raw/目录中有 {total_files} 个文档")
        
        # 列出各类型文档
        for subdir in ['articles', 'papers', 'notes', 'codes', 'webpages']:
            subdir_path = raw_path / subdir
            if subdir_path.exists():
                files = [f for f in os.listdir(subdir_path) if not f.startswith('.')]
                if files:
                    print(f"   {subdir}/: {len(files)} 个文件")
    else:
        print("⚠️  raw/目录中暂无文档")
        print("💡 建议添加测试文档:")
        print("   1. 复制现有文档到 raw/articles/ 或 raw/notes/")
        print("   2. 运行 scripts/create_test_docs.py 创建示例文档")
    
    return total_files > 0

def main():
    print("🔧 Karpathy知识库环境检查")
    print("=" * 60)
    
    ollama_ok = check_ollama()
    dirs_ok = check_directory_structure()
    python_ok = check_python_dependencies()
    docs_exist = check_test_documents()
    
    print("\n" + "=" * 60)
    print("📊 检查结果汇总:")
    print(f"  Ollama服务: {'✅ 正常' if ollama_ok else '❌ 异常'}")
    print(f"  目录结构: {'✅ 完整' if dirs_ok else '❌ 不完整'}")
    print(f"  Python依赖: {'✅ 已安装' if python_ok else '❌ 缺失'}")
    print(f"  测试文档: {'✅ 存在' if docs_exist else '⚠️  暂无'}")
    
    if ollama_ok and dirs_ok:
        print("\n🎉 基础环境检查通过，可以开始开发！")
        
        # 下一步建议
        print("\n🚀 下一步建议:")
        print("  1. 运行 python3 scripts/create_test_docs.py 创建测试文档")
        print("  2. 运行 python3 scripts/processor.py --test 测试处理流程")
        print("  3. 查看 README.md 了解项目结构")
        
        return 0
    else:
        print("\n⚠️  环境检查未通过，请先解决问题:")
        if not ollama_ok:
            print("  - 确保Ollama服务已启动: ollama serve &")
            print("  - 检查模型是否下载: ollama list")
        if not dirs_ok:
            print(f"  - 运行 mkdir -p {BASE_DIR}/{{raw,wiki,outputs,scripts,config,logs,tests}}")
        if not python_ok:
            print("  - 安装Python依赖: pip install requests markdown beautifulsoup4")
        
        return 1

if __name__ == '__main__':
    sys.exit(main())
