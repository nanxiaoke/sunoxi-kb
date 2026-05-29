#!/usr/bin/env python3
"""
知识库性能优化模块
包含：模型预热、响应缓存、增量索引、性能追踪等
"""

import os
import re
import json
import time
import hashlib
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any, Set
from datetime import datetime
from collections import OrderedDict

logger = logging.getLogger(__name__)

# 添加项目路径
KB_BASE_DIR = Path.home() / "karpathy-kb"
CACHE_FILE = KB_BASE_DIR / "qa_cache.json"
METRICS_FILE = KB_BASE_DIR / "performance_metrics.json"


class LRUCache:
    """简单的LRU缓存（字典+有序维护）"""
    
    def __init__(self, capacity: int = 50):
        self.cache = OrderedDict()
        self.capacity = capacity
    
    def get(self, key: str) -> Optional[str]:
        if key not in self.cache:
            return None
        # 移动到末尾（最近使用）
        self.cache.move_to_end(key)
        return self.cache[key]
    
    def put(self, key: str, value: str):
        if key in self.cache:
            self.cache.move_to_end(key)
        self.cache[key] = value
        if len(self.cache) > self.capacity:
            self.cache.popitem(last=False)  # 淘汰最久未用
    
    def save(self, filepath: Path):
        """持久化到文件"""
        try:
            data = dict(self.cache)
            filepath.write_text(
                json.dumps(data, ensure_ascii=False, indent=2)
            )
        except Exception as e:
            logger.warning(f"缓存持久化失败: {e}")
    
    def load(self, filepath: Path):
        """从文件加载"""
        try:
            if filepath.exists():
                data = json.loads(filepath.read_text())
                for k, v in data.items():
                    self.cache[k] = v
                logger.info(f"已加载缓存: {len(self.cache)} 条")
        except Exception as e:
            logger.warning(f"缓存加载失败: {e}")
    
    @property
    def size(self) -> int:
        return len(self.cache)


class ModelWarmup:
    """Ollama模型预热管理器"""
    
    def __init__(self, model: str = "gemma4:e4b"):
        self.model = model
        self.is_warmed = False
        self.warmup_time = 0.0
    
    def warmup(self, force: bool = False) -> bool:
        """预热模型（首次调用约17秒加载时间）"""
        if self.is_warmed and not force:
            logger.info("模型已预热，跳过")
            return True
        
        import subprocess
        logger.info(f"预热模型: {self.model}...")
        start = time.time()
        
        try:
            # 用一个简单的prompt预热，让ollama把模型加载到GPU
            result = subprocess.run(
                ['ollama', 'run', self.model, '--', 'Hello, respond with "ready"'],
                capture_output=True, text=True, timeout=120
            )
            elapsed = time.time() - start
            output = (result.stdout or result.stderr or "").strip()
            
            if output:
                self.is_warmed = True
                self.warmup_time = elapsed
                logger.info(f"模型预热完成: {elapsed:.1f}秒")
                return True
            else:
                logger.warning(f"预热无响应 ({elapsed:.1f}秒)")
                return False
                
        except subprocess.TimeoutExpired:
            logger.warning(f"预热超时 (120s)")
            return False
        except Exception as e:
            logger.warning(f"预热失败: {e}")
            return False
    
    def check_loaded(self) -> bool:
        """检查模型是否已加载到内存"""
        import subprocess
        try:
            result = subprocess.run(
                ['ollama', 'ps'], capture_output=True, text=True, timeout=10
            )
            return self.model in (result.stdout or "")
        except Exception:
            return False


class MetricsTracker:
    """性能指标追踪器"""
    
    def __init__(self, metrics_file: Path = METRICS_FILE):
        self.metrics_file = metrics_file
        self.data = self._load()
    
    def _load(self) -> Dict:
        if self.metrics_file.exists():
            try:
                return json.loads(self.metrics_file.read_text())
            except Exception:
                return {"qa": [], "search": [], "batch": []}
        return {"qa": [], "search": [], "batch": []}
    
    def _save(self):
        try:
            self.metrics_file.write_text(
                json.dumps(self.data, ensure_ascii=False, indent=2)
            )
        except Exception as e:
            logger.warning(f"指标保存失败: {e}")
    
    def record_qa(self, duration: float, success: bool, query_len: int = 0):
        """记录QA延迟"""
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "duration": round(duration, 2),
            "success": success,
            "query_len": query_len
        }
        self.data["qa"].append(entry)
        # 保留最近200条
        if len(self.data["qa"]) > 200:
            self.data["qa"] = self.data["qa"][-200:]
        self._save()
    
    def record_search(self, duration: float, num_results: int):
        """记录搜索延迟"""
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "duration": round(duration, 2),
            "results": num_results
        }
        self.data["search"].append(entry)
        if len(self.data["search"]) > 200:
            self.data["search"] = self.data["search"][-200:]
        self._save()
    
    def record_batch(self, duration: float, files_processed: int, success: int, failed: int):
        """记录批处理延迟"""
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "duration": round(duration, 2),
            "files": files_processed,
            "success": success,
            "failed": failed
        }
        self.data["batch"].append(entry)
        if len(self.data["batch"]) > 100:
            self.data["batch"] = self.data["batch"][-100:]
        self._save()
    
    def get_summary(self) -> Dict:
        """获取性能摘要"""
        summary = {}
        for category in ["qa", "search"]:
            entries = self.data.get(category, [])
            if entries:
                durations = [e["duration"] for e in entries]
                successes = [e["success"] for e in entries if "success" in e]
                summary[category] = {
                    "count": len(entries),
                    "avg_ms": round(sum(durations) / len(durations) * 1000),
                    "min_ms": round(min(durations) * 1000),
                    "max_ms": round(max(durations) * 1000),
                    "success_rate": round(sum(successes) / len(successes) * 100, 1) if successes else 0,
                    "recent_5_avg_ms": round(sum(durations[-5:]) / min(5, len(durations[-5:])) * 1000) if durations else 0
                }
            else:
                summary[category] = {"count": 0}
        
        summary["batch"] = {
            "count": len(self.data.get("batch", [])),
            "total_files": sum(e["files"] for e in self.data.get("batch", []))
        }
        
        return summary
    
    def print_dashboard(self):
        """打印性能仪表盘"""
        s = self.get_summary()
        print(f"\n📊 知识库性能仪表盘")
        print(f"{'='*50}")
        for category in ["qa", "search", "batch"]:
            info = s.get(category, {})
            if info.get("count", 0) > 0:
                print(f"\n  [{category.upper()}] {info['count']} 次请求")
                if "avg_ms" in info:
                    print(f"    延迟: {info['avg_ms']}ms (min: {info['min_ms']}, max: {info['max_ms']})")
                if "recent_5_avg_ms" in info:
                    print(f"    最近5次: {info['recent_5_avg_ms']}ms")
                if "success_rate" in info:
                    print(f"    成功率: {info['success_rate']}%")
            else:
                print(f"\n  [{category.upper()}] 无数据")
        print(f"\n{'='*50}")


class IncrementalIndex:
    """增量索引管理器
    
    只重新索引修改过的文件，避免每次全量重建
    """
    
    def __init__(self, base_dir: Path = KB_BASE_DIR):
        self.base_dir = base_dir
        self.wiki_dir = base_dir / "wiki"
        self.index_file = base_dir / "search_index.json"
        self.state_file = base_dir / "index_state.json"
    
    def get_file_hashes(self) -> Dict[str, str]:
        """计算所有wiki文件的哈希值"""
        hashes = {}
        for fpath in sorted(self.wiki_dir.rglob("*.md")):
            try:
                content = fpath.read_text()
                hashes[str(fpath.relative_to(self.wiki_dir))] = hashlib.md5(
                    content.encode()
                ).hexdigest()
            except Exception:
                pass
        return hashes
    
    def get_changed_files(self) -> Tuple[List[Path], List[str]]:
        """检测新增和修改的文件
        
        Returns:
            (new_or_changed: 需重新索引的文件列表, 
             removed: 已删除的旧文件路径列表)
        """
        current = self.get_file_hashes()
        old_state = {}
        
        if self.state_file.exists():
            try:
                old_state = json.loads(self.state_file.read_text())
            except Exception:
                pass
        
        # 检测变化
        changed = []
        for rel_path, c_hash in current.items():
            if rel_path not in old_state or old_state[rel_path] != c_hash:
                changed.append(self.wiki_dir / rel_path)
        
        removed = [k for k in old_state if k not in current]
        
        # 保存当前状态
        self.state_file.write_text(
            json.dumps(current, ensure_ascii=False, indent=2)
        )
        
        return changed, removed
    
    def needs_rebuild(self) -> bool:
        """判断是否需要全量重建"""
        changed, removed = self.get_changed_files()
        if not changed and not removed:
            return False
        # 如果超过20%的文件变化了，全量重建
        current_count = len(self.get_file_hashes())
        if current_count == 0:
            return True
        return len(changed) / current_count > 0.2
    
    def incremental_update(self) -> int:
        """增量更新索引，返回更新的文档数"""
        from search import WikiSearcher
        
        changed, removed = self.get_changed_files()
        if not changed and not removed:
            logger.info("没有变化的文件，跳过索引更新")
            return 0
        
        logger.info(f"检测到 {len(changed)} 个新增/修改, {len(removed)} 个删除")
        
        searcher = WikiSearcher(self.base_dir)
        searcher.build_index(rebuild=True)
        
        return len(changed)


class SystemHealth:
    """系统健康检查"""
    
    def __init__(self, base_dir: Path = KB_BASE_DIR):
        self.base_dir = base_dir
        self.wiki_dir = base_dir / "wiki"
    
    def check_all(self) -> Dict[str, Any]:
        """全面健康检查"""
        results = {
            "timestamp": datetime.utcnow().isoformat(),
            "status": "ok",
            "checks": {}
        }
        
        # 1. Ollama服务
        results["checks"]["ollama"] = self._check_ollama()
        
        # 2. 磁盘空间
        results["checks"]["disk"] = self._check_disk()
        
        # 3. 模型加载
        results["checks"]["model"] = self._check_model()
        
        # 4. 索引完整性
        results["checks"]["index"] = self._check_index()
        
        # 5. Wiki文件完整性
        results["checks"]["wiki"] = self._check_wiki()
        
        # 总体状态
        failures = [k for k, v in results["checks"].items()
                    if isinstance(v, dict) and v.get("status") == "fail"]
        if failures:
            results["status"] = "degraded"
            results["failures"] = failures
        
        return results
    
    def _check_ollama(self) -> Dict:
        """检查Ollama服务"""
        import subprocess
        try:
            result = subprocess.run(
                ['ollama', 'list'], capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                models = [l.split()[0] for l in result.stdout.strip().split('\n')[1:] if l.strip()]
                return {"status": "ok", "models": models}
            return {"status": "fail", "error": result.stderr.strip()}
        except FileNotFoundError:
            return {"status": "fail", "error": "ollama命令未找到"}
        except Exception as e:
            return {"status": "fail", "error": str(e)}
    
    def _check_model(self) -> Dict:
        """检查本地知识库模型是否可用。

        旧逻辑只看 `ollama ps`，模型未常驻内存就返回 warn；
        但 Ollama 可按需加载模型，这不代表模型不可用。这里改为：
        1) 记录当前已加载模型；
        2) 对 gemma4:e4b 做一次轻量本地 generate 探活；
        3) 只要本地生成成功就判定 ok。
        """
        import subprocess
        import json
        import urllib.request
        model = os.environ.get("KARPATHY_KB_MODEL", "gemma4:e4b")
        loaded_models = []
        try:
            ps = subprocess.run(['ollama', 'ps'], capture_output=True, text=True, timeout=10)
            output = ps.stdout or ""
            loaded_models = [l.split()[0] for l in output.strip().splitlines()[1:] if l.strip()]
        except Exception:
            loaded_models = []

        try:
            payload = json.dumps({
                "model": model,
                "prompt": "只回复OK",
                "stream": False,
            }).encode("utf-8")
            req = urllib.request.Request(
                "http://127.0.0.1:11434/api/generate",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            start = time.time()
            with urllib.request.urlopen(req, timeout=45) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return {
                "status": "ok" if data.get("done") else "warn",
                "model": model,
                "loaded_models": loaded_models,
                "response_preview": str(data.get("response", ""))[:80],
                "latency_sec": round(time.time() - start, 2),
                "note": "本地Ollama生成探活成功" if data.get("done") else "本地模型返回未完成",
            }
        except Exception as e:
            return {
                "status": "fail",
                "model": model,
                "loaded_models": loaded_models,
                "error": str(e),
            }

    def _check_disk(self) -> Dict:
        """检查磁盘空间"""
        try:
            st = os.statvfs(str(self.base_dir))
            free_gb = (st.f_bavail * st.f_frsize) / (1024**3)
            total_gb = (st.f_blocks * st.f_frsize) / (1024**3)
            used_pct = round((1 - st.f_bavail / st.f_blocks) * 100, 1) if st.f_blocks > 0 else 0
            return {
                "status": "ok" if free_gb > 1 else "warn",
                "total_gb": round(total_gb, 1),
                "free_gb": round(free_gb, 1),
                "used_pct": used_pct
            }
        except Exception as e:
            return {"status": "fail", "error": str(e)}
    
    def _check_index(self) -> Dict:
        """检查索引完整性"""
        if self.base_dir.joinpath("search_index.json").exists():
            try:
                data = json.loads(self.base_dir.joinpath("search_index.json").read_text())
                doc_count = len(data.get("documents", data.get("doc_index", {})))
                return {
                    "status": "ok",
                    "documents": doc_count,
                    "last_updated": data.get("last_updated", "unknown")
                }
            except Exception as e:
                return {"status": "fail", "error": str(e)}
        return {"status": "fail", "error": "索引文件不存在"}
    
    def _check_wiki(self) -> Dict:
        """检查Wiki文件完整性"""
        wiki_files = list(self.wiki_dir.rglob("*.md"))
        # 排除索引文件
        content_files = [f for f in wiki_files 
                        if f.name not in ("00_INDEX.md", "DOCUMENTS.md")]
        empty_files = [f for f in content_files if f.stat().st_size < 10]
        return {
            "status": "ok" if not empty_files else "warn",
            "total": len(wiki_files),
            "content_files": len(content_files),
            "empty_files": len(empty_files)
        }


def warmup_and_check():
    """一键预热+健康检查"""
    print("="*50)
    print("🔧 Karpathy知识库 健康检查与预热")
    print("="*50)
    
    # 健康检查
    health = SystemHealth()
    report = health.check_all()
    for name, check in report["checks"].items():
        icon = "✅" if check.get("status") == "ok" else "⚠️" if check.get("status") == "warn" else "❌"
        print(f"  {icon} {name}: {check.get('status', 'unknown')}")
        if "models" in check:
            print(f"    模型: {', '.join(check['models'])}")
        if "error" in check:
            print(f"    错误: {check['error']}")
        if "free_gb" in check:
            print(f"    磁盘: {check['free_gb']}GB 空闲 / {check['total_gb']}GB 总计")
        if "documents" in check:
            print(f"    索引: {check['documents']} 文档")
        if "loaded_models" in check:
            print(f"    已加载: {check['loaded_models']}")
    
    # 预热（如果模型未加载）
    print()
    warmup = ModelWarmup()
    if not warmup.check_loaded():
        print("⚡ 模型未加载，开始预热...")
        ok = warmup.warmup()
        print(f"  {'✅ 预热成功' if ok else '⚠️ 预热失败或跳过'}")
    else:
        print("✅ 模型已加载，跳过预热")
    
    # 性能摘要
    metrics = MetricsTracker()
    metrics.print_dashboard()
    
    return report["status"] == "ok"


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    ok = warmup_and_check()
    exit(0 if ok else 1)
