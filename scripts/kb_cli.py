#!/usr/bin/env python3
"""
Karpathy知识库命令行接口 v2.0
交互式搜索、问答、文档管理 — 彩色输出 + 自动补全
"""

import os
import re
import sys
import json
import time
import argparse
from pathlib import Path
from typing import Optional, List, Dict, Any

# 颜色代码
class C:
    RESET = '\033[0m'
    BOLD = '\033[1m'
    DIM = '\033[2m'
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    MAGENTA = '\033[95m'
    CYAN = '\033[96m'
    GRAY = '\033[90m'
    HEADER = '\033[95m'
    
    @classmethod
    def cyan(cls, s): return f"{cls.CYAN}{s}{cls.RESET}"
    @classmethod
    def gray(cls, s): return f"{cls.GRAY}{s}{cls.RESET}"
    @classmethod
    def ok(cls, s): return f"{cls.GREEN}{s}{cls.RESET}"
    @classmethod
    def info(cls, s): return f"{cls.CYAN}{s}{cls.RESET}"
    @classmethod
    def warn(cls, s): return f"{cls.YELLOW}{s}{cls.RESET}"
    @classmethod
    def err(cls, s): return f"{cls.RED}{s}{cls.RESET}"
    @classmethod
    def dim(cls, s): return f"{cls.DIM}{s}{cls.RESET}"
    @classmethod
    def bold(cls, s): return f"{cls.BOLD}{s}{cls.RESET}"
    @classmethod
    def score(cls, s): return f"{cls.MAGENTA}{s}{cls.RESET}"
    @classmethod
    def label(cls, s): return f"{cls.BLUE}{s}{cls.RESET}"

sys.path.insert(0, str(Path(__file__).parent))

try:
    from search import WikiSearcher
    from qa import KnowledgeBaseQA
except ImportError as e:
    print(f" {C.err('✖')} 导入模块失败: {e}")
    sys.exit(1)

# 可用的交互命令
COMMANDS = {
    "search": {"alias": "s", "help": "搜索知识库", "usage": "search <关键词>"},
    "qa": {"alias": "q", "help": "提问", "usage": "qa <问题>"},
    "stats": {"alias": "st", "help": "显示统计", "usage": "stats"},
    "list": {"alias": "l", "help": "列出文档", "usage": "list [分类]"},
    "entities": {"alias": "e", "help": "列出实体", "usage": "entities [min_freq]"},
    "categories": {"alias": "c", "help": "列出分类", "usage": "categories"},
    "graph": {"alias": "g", "help": "知识图谱摘要", "usage": "graph [实体名]"},
    "rss": {"alias": "r", "help": "RSS订阅管理", "usage": "rss list|sync|add <url>"},
    "reindex": {"alias": "ri", "help": "重建索引", "usage": "reindex"},
    "lint": {"alias": "l", "help": "扫描知识库坏链", "usage": "lint"},
    "warmup": {"alias": "wu", "help": "预热模型", "usage": "warmup"},
    "health": {"alias": "h", "help": "健康检查", "usage": "health"},
    "backup": {"alias": "bk", "help": "创建/查看/恢复备份", "usage": "backup create|inspect <archive>|restore <archive> [target]"},
    "monitor": {"alias": "mon", "help": "监控任务：RSS同步 + 自动导入", "usage": "monitor run|config"},
    "rss-review": {"alias": "rr", "help": "手动RSS同步+中文预览队列", "usage": "rss-review run|status"},
    "help": {"alias": "?", "help": "帮助", "usage": "help [命令]"},
    "exit": {"alias": "quit", "help": "退出", "usage": "exit"},
}


class InteractiveCLI:
    """交互式命令行（支持自动补全和彩色输出）"""
    
    def __init__(self, kb):
        self.kb = kb
        self.history: List[str] = []
        self.completions = list(COMMANDS.keys()) + [v["alias"] for v in COMMANDS.values()]

    def complete(self, text: str, state: int) -> Optional[str]:
        """Tab补全回调"""
        if state == 0:
            if not text:
                self.matches = self.completions[:]
            else:
                self.matches = [c for c in self.completions if c.startswith(text)]
        try:
            return self.matches[state]
        except IndexError:
            return None

    def resolve_cmd(self, raw: str) -> tuple:
        """解析用户输入为 (命令, 参数)"""
        parts = raw.strip().split(maxsplit=1)
        if not parts:
            return ("", "")
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""
        
        # 别名映射
        alias_map = {}
        for name, info in COMMANDS.items():
            alias_map[info["alias"]] = name
        return (alias_map.get(cmd, cmd), arg)

    def run(self):
        """启动交互式shell"""
        self._setup_completion()
        self._show_welcome()
        
        while True:
            try:
                raw = input(f"\n{C.bold(C.cyan('kb'))} {C.dim('➜')} ").strip()
                if not raw:
                    continue
                
                self.history.append(raw)
                cmd, arg = self.resolve_cmd(raw)
                
                if cmd in ("exit", "quit"):
                    print(f" {C.ok('✓')} 再见！")
                    break
                elif cmd == "help":
                    self._show_help(arg)
                elif cmd == "search":
                    if arg:
                        self.kb.command_search(arg)
                    else:
                        print(f" {C.warn('⚠')} 用法: search <关键词>")
                elif cmd == "qa":
                    if arg:
                        self.kb.command_qa(arg)
                    else:
                        print(f" {C.warn('⚠')} 用法: qa <问题>")
                elif cmd == "stats":
                    self.kb.command_stats()
                elif cmd == "list":
                    self.kb.command_list(arg)
                elif cmd == "entities":
                    freq = int(arg) if arg.isdigit() else 1
                    self.kb.command_entities(freq)
                elif cmd == "categories":
                    self.kb.command_categories()
                elif cmd == "graph":
                    self.kb.command_graph(arg)
                elif cmd == "rss":
                    self.kb.command_rss(arg)
                elif cmd == "reindex":
                    self.kb.command_reindex()
                elif cmd == "lint":
                    self.kb.command_lint()
                elif cmd == "warmup":
                    self.kb.command_warmup()
                elif cmd == "health":
                    self.kb.command_health()
                elif cmd == "backup":
                    self.kb.command_backup(arg)
                elif cmd == "monitor":
                    self.kb.command_monitor(arg)
                elif cmd == "rss-review":
                    self.kb.command_rss_review(arg)
                else:
                    print(f" {C.err('✖')} 未知命令: '{cmd}'  输入 {C.info('help')} 查看帮助")
            
            except KeyboardInterrupt:
                print(f"\n {C.dim('提示: 输入 exit 退出')}")
            except EOFError:
                print(f"\n {C.ok('✓')} 再见！")
                break
            except Exception as e:
                print(f" {C.err('✖')} 错误: {e}")

    def _setup_completion(self):
        """设置readline补全"""
        try:
            import readline
            readline.set_completer(self.complete)
            readline.set_completer_delims(' \t\n;')
            if 'libedit' in readline.__doc__:
                readline.parse_and_bind("bind ^I rl_complete")
            else:
                readline.parse_and_bind("tab: complete")
        except ImportError:
            pass  # 无readline（Windows）则跳过
    
    def _show_welcome(self):
        welcome = f"""
{C.bold(C.cyan('╔══════════════════════════════════╗'))}
{C.bold(C.cyan('║'))}    📚 Karpathy 知识库 v2.0       {C.bold(C.cyan('║'))}
{C.bold(C.cyan('║'))}    {C.dim('交互式命令行 · 自动补全 · 彩色输出')}   {C.bold(C.cyan('║'))}
{C.bold(C.cyan('╚══════════════════════════════════╝'))}

{C.dim('输入 help 查看可用命令  |  Tab键自动补全  |  Ctrl+C 取消输入')}
"""
        print(welcome)
    
    def _show_help(self, topic: str = ""):
        if topic:
            info = COMMANDS.get(topic)
            if info:
                print(f"\n {C.bold(topic)}")
                if info["alias"]:
                    print(f"   别名: {C.info(info['alias'])}")
                print(f"   说明: {info['help']}")
                print(f"   用法: {C.dim(info['usage'])}")
            else:
                print(f" {C.warn('⚠')} 未知命令: '{topic}'")
            return
        
        print(f"\n{C.bold('可用命令:')}")
        for name, info in COMMANDS.items():
            alias = f" ({info['alias']})" if info["alias"] else ""
            print(f"  {C.cyan(name):<12}{C.dim(alias+info['help']):<40}")
        print(f"\n{C.dim('提示: 使用 Tab 键自动补全命令')}")


class KnowledgeBaseCLI:
    """知识库命令行接口"""
    
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.searcher = None
        self.qa_system = None
        self.wiki_dir = base_dir / "wiki"
        self.raw_dir = base_dir / "raw"
    
    def _ensure_search(self):
        if self.searcher is None:
            self.searcher = WikiSearcher(self.base_dir)
            self.searcher.build_index(rebuild=False)
        return self.searcher
    
    def _ensure_qa(self):
        if self.qa_system is None:
            self.qa_system = KnowledgeBaseQA(self.base_dir)
        return self.qa_system
    
    # ========== 搜索 ==========
    
    def command_search(self, query: str):
        s = self._ensure_search()
        results = s.search(query, limit=20)
        
        if not results:
            print(f" {C.warn('⚠')} 未找到 '{query}' 的相关结果")
            return
        
        print(f"\n{C.bold(f'🔍 {query}')} — {C.ok(str(len(results)))} 条结果\n")
        for i, doc in enumerate(results, 1):
            title = doc.get("title", "无标题")
            score = doc.get("score", 0)
            cat = doc.get("category", "")
            summary = (doc.get("summary", "") or "")[:120]
            entities = doc.get("entities", [])
            
            print(f" {C.cyan(f'{i:>2}')} {C.bold(title)} {C.score(f'[{score:.1f}]')}")
            if cat:
                print(f"     {C.dim('分类:')} {C.label(cat)}")
            if summary:
                print(f"     {C.dim(summary)}")
            if entities:
                tags = " ".join(f"{C.gray(f'#{e}')}" for e in entities[:4])
                print(f"     {tags}")
    
    # ========== 问答 ==========
    
    def command_qa(self, question: str):
        print(f"\n{C.bold('💡 ')}{question}")
        print(f" {C.dim('正在分析知识库...')}")
        
        t0 = time.time()
        result = self._ensure_qa().answer_question(question)
        elapsed = time.time() - t0
        
        answer = result.get("answer", "")
        docs = result.get("documents", [])
        cached = result.get("cache_hit", False)
        
        elapsed_str = f"{elapsed:.1f}s" if elapsed > 1 else f"{int(elapsed*1000)}ms"
        
        print(f"\n{C.bold('答案')} {C.dim(f'({elapsed_str})')}", end="")
        if cached:
            print(f" {C.gray('[缓存]')}", end="")
        print()
        print(f"{'-'*40}")
        print(answer)
        
        if docs:
            print(f"\n{C.dim('参考文档:')}")
            for i, doc in enumerate(docs, 1):
                title = doc.get("title", "未知")
                score = doc.get("score", 0)
                print(f"  {i}. {C.bold(title)} {C.score(f'[{score:.1f}]')}")
    
    # ========== 统计 ==========
    
    def command_stats(self):
        s = self._ensure_search()
        try:
            s.print_stats()
        except Exception:
            # 手動統計
            print(f"\n{C.bold('📊 知识库统计')}")
            print(f"  {C.dim('文档:')}     {C.ok(len(s.doc_index))}")
            print(f"  {C.dim('索引词:')}   {len(s.fulltext_index)}")
            print(f"  {C.dim('实体:')}     {len(s.entity_index)}")
            print(f"  {C.dim('分类:')}     {len(s.category_index)}")
    
    # ========== RSS ==========
    
    def command_rss(self, args: str = ""):
        try:
            from rss_sync import RSSManager
            mgr = RSSManager(self.base_dir)
            
            parts = args.strip().split(maxsplit=2) if args else ["sync"]
            cmd = parts[0] if parts else "sync"
            
            if cmd == "list":
                mgr.print_summary()
            elif cmd == "sync":
                mgr.print_summary()
                result = mgr.sync_all(max_per_source=5)
                print(f"\n{'='*50}")
                icon = C.ok('✓') if result['errors'] == 0 else C.warn('⚠')
                print(f" {icon} 同步完成: {result['new']} 新文章, {result['skipped']} 跳过, {result['errors']} 错误")
            elif cmd == "add":
                url = parts[1] if len(parts) > 1 else ""
                name = parts[2] if len(parts) > 2 else ""
                if not url:
                    print(f" {C.err('✖')} 用法: rss add <url> [名称]")
                    return
                mgr.add_feed(url, name)
                mgr.print_summary()
            elif cmd == "remove":
                target = parts[1] if len(parts) > 1 else ""
                if not target:
                    print(f" {C.err('✖')} 用法: rss remove <名称或URL>")
                    return
                if mgr.remove_feed(target):
                    print(f" {C.ok('✓')} 已删除: {target}")
                else:
                    print(f" {C.err('✖')} 未找到: {target}")
            else:
                print(f" {C.err('✖')} 未知RSS命令: {cmd}  可选: list, sync, add, remove")
        except ImportError as e:
            print(f" {C.err('✖')} rss_sync 模块未找到: {e}")
    
    # ========== 知识图谱 ==========
    
    def command_graph(self, entity: str = ""):
        try:
            from knowledge_graph import KnowledgeGraph
            kg = KnowledgeGraph(self.base_dir)
            if entity:
                sub = kg.get_entity_neighbors(entity)
                print(f"\n{C.bold(f'🕸️ {entity}')} — {len(sub['nodes'])} 个关联实体, {len(sub['edges'])} 条关系")
                for n in sub['nodes']:
                    if n['label'].lower() != entity.lower():
                        print(f"  {C.label(n['label']):<24} ({n['docs']}篇)")
            else:
                kg.print_summary()
        except ImportError:
            s = self._ensure_search()
            entities = s.get_all_entities(min_freq=1)
            print(f"\n{C.bold('🔤 实体')} — {len(entities)} 个")
            for e, f in entities[:20]:
                print(f"  {C.label(e):<24} {f}篇")
    
    # ========== 列表 ==========
    
    def command_list(self, category: str = ""):
        s = self._ensure_search()
        if category:
            docs = s.search_by_category(category)
            if not docs:
                print(f" {C.warn('⚠')} 分类 '{category}' 下无文档")
                return
            label = f"📂 {category}"
        else:
            docs = list(s.doc_index.values())
            label = "📄 全部文档"
        
        print(f"\n{C.bold(label)} — {C.ok(str(len(docs)))} 篇\n")
        for i, doc in enumerate(docs[:30], 1):
            title = doc.get("title", "无标题")
            cat = doc.get("category", "")
            print(f"  {C.cyan(f'{i:>2}')} {C.bold(title)} {C.dim(cat)}")
        
        if len(docs) > 30:
            print(f"  {C.dim(f'... 还有 {len(docs)-30} 篇')}")
    
    # ========== 实体 ==========
    
    def command_entities(self, min_freq: int = 1):
        s = self._ensure_search()
        entities = s.get_all_entities(min_freq=min_freq)
        if not entities:
            print(f" {C.warn('⚠')} 无实体数据")
            return
        
        print(f"\n{C.bold(f'🔤 实体 (≥{min_freq}篇)')} — {C.ok(str(len(entities)))} 个\n")
        for entity, freq in entities[:40]:
            freq_str = C.dim(f"({freq}篇)") if freq <= 2 else C.ok(f"({freq}篇)")
            print(f"  {C.label(entity):<24} {freq_str}")
        if len(entities) > 40:
            print(f"  {C.dim(f'... 还有 {len(entities)-40} 个')}")
    
    # ========== 分类 ==========
    
    def command_categories(self):
        s = self._ensure_search()
        categories = s.get_all_categories()
        print(f"\n{C.bold(f'📂 分类 ({len(categories)})')}\n")
        for cat in sorted(categories):
            count = len(s.category_index.get(cat, []))
            bar = "█" * count + "░" * max(0, 10 - count)
            print(f"  {C.label(cat):<20} {C.ok(str(count)):>3}篇  {C.dim(bar)}")
    
    # ========== 重建索引 ==========
    
    def command_reindex(self):
        print(f" {C.warn('⚠')} 正在重建搜索索引...")
        s = self._ensure_search()
        s.build_index(rebuild=True)
        print(f" {C.ok('✓')} 索引重建完成: {len(s.doc_index)} 文档")
    
    # ========== 模型预热 ==========
    
    def command_warmup(self):
        try:
            from optimizer import ModelWarmup
            w = ModelWarmup()
            if w.check_loaded():
                print(f" {C.ok('✓')} 模型已加载")
            else:
                print(f" {C.dim('⟳ 正在预热模型...')}")
                ok = w.warmup()
                if ok:
                    print(f" {C.ok('✓')} 模型预热完成 ({w.warmup_time:.1f}s)")
                else:
                    print(f" {C.err('✖')} 预热失败")
        except ImportError:
            print(f" {C.err('✖')} optimizer 模块未找到")
    
    # ========== 健康检查 ==========
    
    def command_health(self):
        try:
            from optimizer import SystemHealth
            health = SystemHealth()
            report = health.check_all()
            
            print(f"\n{C.bold('🏥 系统健康检查')}")
            for name, check in report["checks"].items():
                status = check.get("status", "unknown")
                icon = C.ok("✓") if status == "ok" else C.warn("⚠") if status == "warn" else C.err("✖")
                print(f"  {icon} {name:<10} {C.dim(status)}", end="")
                if "models" in check:
                    print(f"  {', '.join(check['models'])}", end="")
                elif "free_gb" in check:
                    print(f"  {check['free_gb']}GB / {check['total_gb']}GB", end="")
                elif "documents" in check:
                    print(f"  {check['documents']} 文档", end="")
                print()
        except ImportError:
            s = self._ensure_search()
            print(f"\n{C.bold('🏥 基础健康检查')}")
            print(f"  {C.ok('✓')} 索引: {len(s.doc_index)} 文档")
            print(f"  {C.ok('✓')} 实体: {len(s.entity_index)} 个")
    
    # ========== 运行入口 ==========
    
    def command_lint(self):
        """扫描知识库检查坏链和孤立页面"""
        print(f"🔍 正在扫描知识库...")
        try:
            import sys
            sys.path.append(str(self.base_dir / "scripts"))
            from linter import KBLinter
            linter = KBLinter(self.base_dir)
            linter.run()
        except ImportError:
            print(Color.err("❌ 找不到 linter 模块，请确保 scripts/linter.py 存在。"))
        except Exception as e:
            print(Color.err(f"❌ 扫描过程中发生错误: {e}"))

    def command_backup(self, args: str = ""):
        """备份/恢复知识库"""
        try:
            from backup_restore import KBBackup
            tool = KBBackup(self.base_dir)
            parts = args.strip().split(maxsplit=2) if args else ["create"]
            action = parts[0]
            if action == "create":
                result = tool.create()
            elif action == "inspect":
                if len(parts) < 2:
                    print(f" {C.err('✖')} 用法: backup inspect <archive>")
                    return
                result = tool.inspect(Path(parts[1]).expanduser())
            elif action == "restore":
                if len(parts) < 2:
                    print(f" {C.err('✖')} 用法: backup restore <archive> [target]")
                    return
                target = Path(parts[2]).expanduser() if len(parts) > 2 else Path.home() / "karpathy-kb-restored"
                result = tool.restore(Path(parts[1]).expanduser(), target, apply=False)
            else:
                print(f" {C.err('✖')} 未知备份命令: {action}")
                return
            print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        except Exception as e:
            print(f" {C.err('✖')} 备份命令失败: {e}")

    def command_monitor(self, args: str = ""):
        """运行监控任务"""
        try:
            from monitor import KBMonitor
            mon = KBMonitor(self.base_dir)
            action = (args.strip().split(maxsplit=1)[0] if args else "run")
            if action == "config":
                result = mon.config
            elif action == "run":
                result = mon.run_once()
            else:
                print(f" {C.err('✖')} 未知监控命令: {action}  可选: run, config")
                return
            print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        except Exception as e:
            print(f" {C.err('✖')} 监控命令失败: {e}")

    def command_rss_review(self, args: str = ""):
        """手动运行 RSS 同步 + 中文预览队列。"""
        try:
            from rss_review_queue import run as run_queue, status as queue_status
            parts = args.strip().split() if args else ["status"]
            action = parts[0]
            if action == "status":
                ns = argparse.Namespace(base_dir=str(self.base_dir))
                queue_status(ns)
            elif action == "run":
                batch_size = 20
                max_per_source = 5
                fill_backlog = False
                for part in parts[1:]:
                    if part.startswith("--batch-size="):
                        batch_size = int(part.split("=", 1)[1])
                    elif part.startswith("--rss-max="):
                        max_per_source = int(part.split("=", 1)[1])
                    elif part == "--fill-backlog":
                        fill_backlog = True
                ns = argparse.Namespace(
                    base_dir=str(self.base_dir),
                    rss_max_per_source=max_per_source,
                    preview_batch_size=batch_size,
                    preview_max_seconds=1200,
                    fill_backlog=fill_backlog,
                    force_preview=False,
                )
                run_queue(ns)
            else:
                print(f" {C.err('✖')} 未知 rss-review 命令: {action}  可选: run, status")
        except Exception as e:
            print(f" {C.err('✖')} rss-review 命令失败: {e}")

    def run_interactive(self):
        """启动交互式模式"""
        cli = InteractiveCLI(self)
        cli.run()
    
    def run_single(self, cmd: str, arg: str = ""):
        """单次命令模式"""
        if cmd == "rss":
            self.command_rss(arg)
        elif cmd == "graph":
            self.command_graph(arg)
        elif cmd == "search":
            self.command_search(arg)
        elif cmd == "qa":
            self.command_qa(arg)
        elif cmd == "stats":
            self.command_stats()
        elif cmd == "list":
            self.command_list(arg)
        elif cmd == "entities":
            freq = int(arg) if arg.isdigit() else 1
            self.command_entities(freq)
        elif cmd == "categories":
            self.command_categories()
        elif cmd == "reindex":
            self.command_reindex()
        elif cmd == "lint":
            self.command_lint()
        elif cmd == "warmup":
            self.command_warmup()
        elif cmd == "health":
            self.command_health()
        elif cmd == "backup":
            self.command_backup(arg)
        elif cmd == "monitor":
            self.command_monitor(arg)
        elif cmd == "rss-review":
            self.command_rss_review(arg)
        elif cmd == "help":
            print("可用命令: search, qa, stats, list, entities, categories, reindex, warmup, health, lint, backup, monitor, rss-review")
        else:
            print(f" {C.err('✖')} 未知命令: {cmd}")
            return 1
        return 0


def main():
    parser = argparse.ArgumentParser(
        description="Karpathy 知识库命令行工具 v2.0",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  kb_cli.py                       交互式模式
  kb_cli.py search 人工智能       搜索
  kb_cli.py qa "什么是RAG？"       问答
  kb_cli.py stats                 统计信息
  kb_cli.py list                  文档列表
  kb_cli.py entities              实体列表
  kb_cli.py lint                  坏链和孤立页面扫描
  kb_cli.py health                健康检查
  kb_cli.py backup create         创建备份
  kb_cli.py monitor run           执行一次监控同步/导入
  kb_cli.py rss-review run        手动执行RSS同步+中文预览队列
  kb_cli.py rss-review status     查看RSS审查队列状态
  kb_cli.py reindex               重建索引
        """
    )
    parser.add_argument("command", nargs="?", help="命令: search/qa/stats/list/entities/categories/reindex/warmup/health/lint/rss/graph/backup/monitor/rss-review")
    parser.add_argument("args", nargs="*", help="命令参数")
    parser.add_argument("--base-dir", default=str(Path.home() / "karpathy-kb"), help="项目目录")
    parser.add_argument("--no-color", action="store_true", help="禁用彩色输出")
    
    args = parser.parse_args()
    
    if args.no_color:
        # 将颜色类置空
        for attr in dir(C):
            if not attr.startswith("_"):
                setattr(C, attr, lambda s, _a=attr: s if _a in ("RESET",) else lambda s: s)
    
    base_dir = Path(args.base_dir).expanduser()
    if not base_dir.exists():
        print(f" {C.err('✖')} 目录不存在: {base_dir}")
        return 1
    
    kb = KnowledgeBaseCLI(base_dir)
    
    if args.command:
        arg_str = " ".join(args.args)
        return kb.run_single(args.command, arg_str)
    else:
        kb.run_interactive()
        return 0


if __name__ == "__main__":
    sys.exit(main())
