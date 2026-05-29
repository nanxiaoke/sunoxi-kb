#!/usr/bin/env python3
"""
Karpathy知识库 — 知识图谱模块 v2
- 实体关系共现提取
- 邻居子图查询（BFS）
- D3.js / ECharts 可视化数据生成
- 缓存机制避免重复计算
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Tuple, Set, Optional
from collections import defaultdict

logger = logging.getLogger(__name__)


class KnowledgeGraph:
    """知识图谱：从文档实体中构建实体关系图，支持邻居查询"""

    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir)
        self.searcher = None
        self._graph_data = None
        self._adj: Dict[str, Set[str]] = {}  # 邻接表（缓存）

    def _ensure_searcher(self):
        if self.searcher is None:
            from search import WikiSearcher
            self.searcher = WikiSearcher(self.base_dir)
            self.searcher.build_index(rebuild=False)
        return self.searcher

    # ── 核心提取 ─────────────────────────────────────────
    def extract_graph(self, min_cooccur: int = 1) -> Dict:
        """
        构建全量实体关系图。
        返回 {"nodes": [...], "edges": [...], "stats": {...}}
        """
        s = self._ensure_searcher()

        # (1) 文档 → 实体集合
        doc_entities: Dict[str, Set[str]] = {}
        entity_docs: Dict[str, Set[str]] = defaultdict(set)
        entity_categories: Dict[str, Set[str]] = defaultdict(set)

        for doc_id, doc in s.doc_index.items():
            raw_ents = doc.get("entities", [])
            if not raw_ents:
                continue
            clean = set()
            for e in raw_ents:
                e = e.strip()
                if len(e) <= 1:
                    continue
                clean.add(e)
            if not clean:
                continue
            doc_entities[doc_id] = clean
            cat = doc.get("category", "")
            for e in clean:
                entity_docs[e].add(doc_id)
                if cat:
                    entity_categories[e].add(cat)

        # (2) 过滤无意义实体
        skip = {
            "http", "https", "iana", "example.com", "documentation",
            "defuddle", "http status code 200", "docx", "word format",
            "paragraph detection", "heading extraction", "karpathy kb",
        }

        # (3) 节点
        node_ids: Dict[str, str] = {}
        nodes = []
        for entity in sorted(entity_docs):
            el = entity.lower()
            if el in skip:
                continue
            freq = len(entity_docs[entity])
            cats = sorted(entity_categories.get(entity, set()))[:3]
            nid = f"ent_{el.replace(' ', '_').replace('(', '').replace(')', '')}"
            node_ids[entity] = nid

            # 取相关文档标题（最多5个）
            related = []
            for did in sorted(entity_docs[entity])[:5]:
                dinfo = s.doc_index.get(did, {})
                t = dinfo.get("title", "")
                if t:
                    related.append(t)

            nodes.append({
                "id": nid,
                "label": entity,
                "name": entity,
                "freq": freq,
                "categories": cats,
                "group": cats[0] if cats else "其他",
                "docs": len(entity_docs[entity]),
                "relatedDocs": related,
                "type": "entity",
            })

        # (4) 边（共现）
        edges = []
        edge_weight: Dict[Tuple[str, str], int] = defaultdict(int)
        for ents in doc_entities.values():
            sl = sorted(ents)
            for i in range(len(sl)):
                a = sl[i]
                if a.lower() in skip or a not in node_ids:
                    continue
                for j in range(i + 1, len(sl)):
                    b = sl[j]
                    if b.lower() in skip or b not in node_ids:
                        continue
                    key = (node_ids[a], node_ids[b])
                    edge_weight[key] += 1

        for (src, tgt), w in edge_weight.items():
            edges.append({"source": src, "target": tgt, "weight": w})

        # (5) 过滤孤立节点
        connected = set()
        for e in edges:
            connected.add(e["source"])
            connected.add(e["target"])
        nodes = [n for n in nodes if n["id"] in connected]

        # (6) 按度数排序
        degree = defaultdict(int)
        for e in edges:
            degree[e["source"]] += e["weight"]
            degree[e["target"]] += e["weight"]
        nodes.sort(key=lambda n: degree.get(n["id"], 0), reverse=True)
        edges.sort(key=lambda e: e["weight"], reverse=True)

        # 构建邻接表缓存
        self._adj = defaultdict(set)
        for e in edges:
            self._adj[e["source"]].add(e["target"])
            self._adj[e["target"]].add(e["source"])

        self._graph_data = {
            "nodes": nodes,
            "edges": edges,
            "stats": {
                "total_entities": len(entity_docs),
                "graph_nodes": len(nodes),
                "graph_edges": len(edges),
                "documents": len(doc_entities),
            }
        }
        return self._graph_data

    # ── 邻居查询（BFS 子图） ─────────────────────────────
    def get_entity_neighbors(self, entity: str, depth: int = 1,
                             max_nodes: int = 60) -> Dict:
        """
        以某个实体为中心，做 BFS 取子图。
        depth: 扩展层数（1=直接邻居）
        """
        if not self._graph_data:
            self.extract_graph()

        nodes = self._graph_data["nodes"]
        edges = self._graph_data["edges"]

        # 查找目标节点
        target_id = None
        for n in nodes:
            if n["label"].lower() == entity.lower() or n["name"].lower() == entity.lower():
                target_id = n["id"]
                break

        if target_id is None:
            return {"nodes": [], "edges": [], "center": None}

        # BFS
        visited = {target_id}
        frontier = {target_id}
        for _ in range(depth):
            nxt = set()
            for nid in frontier:
                if nid in self._adj:
                    for nb in self._adj[nid]:
                        if nb not in visited:
                            visited.add(nb)
                            nxt.add(nb)
            frontier = nxt
            if not frontier:
                break

        # 收集边
        sub_edges = []
        for e in edges:
            if e["source"] in visited and e["target"] in visited:
                sub_edges.append(e)

        sub_nodes = [n for n in nodes if n["id"] in visited]
        sub_nodes.sort(key=lambda n: n.get("freq", 0), reverse=True)

        return {
            "nodes": sub_nodes[:max_nodes],
            "edges": sub_edges[:max_nodes * 2],
            "center": target_id,
        }

    # ── 搜索实体 ─────────────────────────────────────────
    def search_entities(self, query: str, limit: int = 10) -> List[Dict]:
        """模糊搜索实体名称"""
        if not self._graph_data:
            self.extract_graph()
        q = query.lower()
        matches = []
        for n in self._graph_data["nodes"]:
            if q in n["label"].lower():
                matches.append(n)
        matches.sort(key=lambda n: n.get("freq", 0), reverse=True)
        return matches[:limit]

    # ── 导出 ────────────────────────────────────────────
    def export_json(self, filepath: str = None) -> str:
        data = self.extract_graph()
        s = json.dumps(data, ensure_ascii=False, indent=2)
        if filepath:
            Path(filepath).write_text(s, encoding="utf-8")
            logger.info("Graph exported to %s", filepath)
        return s

    def print_summary(self):
        data = self.extract_graph()
        stats = data["stats"]
        print(f"\n{'='*50}\n🕸️  知识图谱摘要\n{'='*50}")
        print(f"  实体总数: {stats['total_entities']}")
        print(f"  图中节点: {stats['graph_nodes']}")
        print(f"  图中边数: {stats['graph_edges']}")
        print(f"  关联文档: {stats['documents']}")
        print(f"\n  核心实体:")
        for n in data["nodes"][:10]:
            print(f"    {n['label']:<20} 频率={n['freq']}  分类={n['categories']}")
        print()


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)

    base = Path(__file__).resolve().parent.parent
    kg = KnowledgeGraph(base)
    kg.print_summary()

    # 导出
    output = base / "knowledge_graph.json"
    kg.export_json(str(output))
    print(f" ✅ 已导出到 {output}")
