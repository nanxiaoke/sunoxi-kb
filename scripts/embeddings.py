#!/usr/bin/env python3
"""
Karpathy知识库 — 语义搜索模块
基于 sentence-transformers 的向量嵌入和相似度搜索
"""

import json
import logging
import os
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

# 默认模型（80MB，中英文均可，CPU/GPU均可）
DEFAULT_MODEL = "all-MiniLM-L6-v2"

# 中文优化模型（更大，中文更好）  
CHINESE_MODEL = "shibing624/text2vec-base-chinese"

# 存储文件
EMBEDDINGS_FILE = "embeddings.npy"
MAPPING_FILE = "embeddings_map.json"


class EmbeddingEngine:
    """向量嵌入引擎"""
    
    def __init__(self, base_dir: Path, model_name: str = DEFAULT_MODEL):
        self.base_dir = base_dir
        self.model_name = model_name
        self.model: Optional[SentenceTransformer] = None
        self._loaded = False
        
        # 嵌入存储
        self.vectors: Optional[np.ndarray] = None  # (N, dim)
        self.doc_ids: List[str] = []  # 对应索引位置的doc_id
        self.doc_map: Dict[str, int] = {}  # doc_id -> index
        self.dimension: int = 0
        
        self._load()
    
    def _get_model(self) -> SentenceTransformer:
        """获取或初始化模型"""
        if self.model is None:
            logger.info(f"加载嵌入模型: {self.model_name}")
            t0 = time.time()
            local_only = os.environ.get("KB_EMBEDDINGS_LOCAL_ONLY", "1") != "0"
            self.model = SentenceTransformer(self.model_name, device="cuda", local_files_only=local_only)
            logger.info(f"模型加载完成 ({time.time()-t0:.1f}s)")
        return self.model
    
    def _embeddings_path(self) -> Path:
        return self.base_dir / EMBEDDINGS_FILE
    
    def _mapping_path(self) -> Path:
        return self.base_dir / MAPPING_FILE
    
    # ========== 公开方法 ==========
    
    def encode(self, texts: List[str]) -> np.ndarray:
        """编码文本为向量"""
        model = self._get_model()
        return model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    
    def build_all(self, searcher) -> int:
        """为索引中所有文档生成嵌入"""
        doc_ids = list(searcher.doc_index.keys())
        if not doc_ids:
            logger.warning("索引为空，无文档可嵌入")
            return 0
        
        texts = []
        valid_ids = []
        for did in doc_ids:
            doc = searcher.doc_index[did]
            # 拼接摘要+标题+关键点作为嵌入文本
            parts = []
            if doc.get("title"):
                parts.append(doc["title"])
            if doc.get("summary"):
                parts.append(doc["summary"][:500])
            if doc.get("keypoints"):
                parts.append(" ".join(doc["keypoints"][:3]))
            if doc.get("content"):
                parts.append(doc["content"][:300])
            
            text = "\n".join(parts)
            if len(text) < 10:
                continue
            texts.append(text)
            valid_ids.append(did)
        
        if not texts:
            return 0
        
        logger.info(f"生成 {len(texts)} 条向量嵌入...")
        t0 = time.time()
        vectors = self.encode(texts)
        logger.info(f"嵌入完成 ({time.time()-t0:.1f}s, {vectors.shape[1]}维)")
        
        self.vectors = vectors
        self.doc_ids = valid_ids
        self.doc_map = {did: i for i, did in enumerate(valid_ids)}
        self.dimension = vectors.shape[1]
        
        self._save()
        return len(vectors)
    
    def incremental_update(self, searcher) -> int:
        """增量更新：只嵌入新文档"""
        doc_ids = list(searcher.doc_index.keys())
        existing = set(self.doc_ids)
        new_ids = [d for d in doc_ids if d not in existing]
        
        if not new_ids:
            logger.info("无新文档需要嵌入")
            return 0
        
        texts = []
        valid_new = []
        for did in new_ids:
            doc = searcher.doc_index[did]
            parts = []
            if doc.get("title"):
                parts.append(doc["title"])
            if doc.get("summary"):
                parts.append(doc["summary"][:500])
            if doc.get("keypoints"):
                parts.append(" ".join(doc["keypoints"][:3]))
            text = "\n".join(parts)
            if len(text) < 10:
                continue
            texts.append(text)
            valid_new.append(did)
        
        if not texts:
            return 0
        
        new_vectors = self.encode(texts)
        
        # 追加到现有嵌入
        if self.vectors is None or len(self.vectors) == 0:
            self.vectors = new_vectors
        else:
            self.vectors = np.vstack([self.vectors, new_vectors])
        
        self.doc_ids.extend(valid_new)
        self.doc_map.update({did: i for i, did in enumerate(valid_new)})
        self.dimension = self.vectors.shape[1]
        
        self._save()
        logger.info(f"增量更新: {len(valid_new)} 条")
        return len(valid_new)
    
    def search(self, query: str, top_k: int = 10) -> List[Tuple[str, float]]:
        """语义搜索：返回 (doc_id, score) 列表"""
        if self.vectors is None or len(self.vectors) == 0:
            logger.warning("嵌入数据为空，请先 build_all")
            return []
        
        q_vec = self.encode([query])[0]
        # 余弦相似度（已归一化，直接点积）
        scores = np.dot(self.vectors, q_vec)
        
        # Top-K 索引
        if top_k >= len(scores):
            top_indices = np.argsort(-scores)
        else:
            top_indices = np.argpartition(-scores, top_k)[:top_k]
            top_indices = top_indices[np.argsort(-scores[top_indices])]
        
        results = []
        for idx in top_indices:
            doc_id = self.doc_ids[idx]
            score = float(scores[idx])
            results.append((doc_id, score))
        
        return results
    
    def hybrid_search(self, searcher, query: str, top_k: int = 10,
                      semantic_weight: float = 0.4) -> List[Dict]:
        """
        混合搜索：关键词 + 语义
        
        Args:
            searcher: WikiSearcher 实例
            query: 搜索关键词
            top_k: 返回条数
            semantic_weight: 语义搜索权重 (0=纯关键词, 1=纯语义)
        """
        # 1. 关键词搜索
        kw_results = searcher.search(query, limit=top_k * 2)
        kw_scores = {}
        for doc in kw_results:
            kw_scores[doc["id"]] = doc.get("score", 0)
        
        # 2. 语义搜索
        vec_results = self.search(query, top_k=top_k * 2)
        vec_scores = {doc_id: score for doc_id, score in vec_results}
        
        # 3. 融合
        all_ids = set(list(kw_scores.keys()) + list(vec_scores.keys()))
        fused = []
        
        for doc_id in all_ids:
            kw = kw_scores.get(doc_id, 0)
            vec = vec_scores.get(doc_id, 0)
            
            # 归一化关键词得分 [0, 1]
            max_kw = max(kw_scores.values()) if kw_scores else 1
            kw_norm = kw / max_kw if max_kw > 0 else 0
            
            # 融合得分
            combined = kw_norm * (1 - semantic_weight) + vec * semantic_weight
            
            # 获取文档信息
            doc = searcher.doc_index.get(doc_id, {})
            doc = dict(doc)  # 复制
            doc["score"] = round(combined * 10, 2)
            doc["kw_score"] = round(kw_norm * 10, 2)
            doc["vec_score"] = round(vec, 3)
            fused.append(doc)
        
        # 按融合得分排序
        fused.sort(key=lambda x: x["score"], reverse=True)
        return fused[:top_k]
    
    def _save(self):
        """保存嵌入数据到磁盘"""
        if self.vectors is not None and self.doc_ids:
            np.save(str(self._embeddings_path()), self.vectors)
            mapping = {
                "doc_ids": self.doc_ids,
                "model": self.model_name,
                "dimension": self.dimension,
                "count": len(self.doc_ids)
            }
            self._mapping_path().write_text(
                json.dumps(mapping, ensure_ascii=False, indent=2)
            )
            logger.info(f"保存 {len(self.doc_ids)} 条嵌入到 {EMBEDDINGS_FILE}")
    
    def _load(self) -> bool:
        """从磁盘加载嵌入数据"""
        emb_path = self._embeddings_path()
        map_path = self._mapping_path()
        
        if not emb_path.exists() or not map_path.exists():
            return False
        
        try:
            self.vectors = np.load(str(emb_path))
            mapping = json.loads(map_path.read_text())
            self.doc_ids = mapping["doc_ids"]
            self.doc_map = {did: i for i, did in enumerate(self.doc_ids)}
            self.dimension = mapping.get("dimension", self.vectors.shape[1])
            self.model_name = mapping.get("model", self.model_name)
            logger.info(f"加载 {len(self.doc_ids)} 条嵌入 ({self.vectors.shape[1]}维)")
            return True
        except Exception as e:
            logger.warning(f"加载嵌入失败: {e}")
            return False
    
    def get_stats(self) -> Dict:
        """获取嵌入统计"""
        return {
            "count": len(self.doc_ids) if self.doc_ids else 0,
            "dimension": self.dimension,
            "model": self.model_name,
            "device": "cuda" if self.model and hasattr(self.model, 'device') else "cpu"
        }


# ========== 快捷调用 ==========

def main():
    import argparse
    from search import WikiSearcher
    
    parser = argparse.ArgumentParser(description="语义搜索引擎")
    parser.add_argument("action", nargs="?", default="status",
                        choices=["build", "status", "search", "hybrid"])
    parser.add_argument("query", nargs="?", help="搜索关键词")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="嵌入模型")
    parser.add_argument("--topk", type=int, default=5, help="返回条数")
    
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s - %(levelname)s - %(message)s')
    
    base_dir = Path.home() / "karpathy-kb"
    ee = EmbeddingEngine(base_dir, args.model)
    searcher = WikiSearcher(base_dir)
    searcher.build_index(rebuild=False)
    
    if args.action == "build":
        n = ee.build_all(searcher)
        print(f"✅ 嵌入完成: {n} 条向量")
    
    elif args.action == "status":
        stats = ee.get_stats()
        print(f"\n📊 语义搜索引擎")
        print(f"  模型: {stats['model']}")
        print(f"  向量: {stats['count']} 条")
        print(f"  维度: {stats['dimension']}")
        print(f"  设备: {stats['device']}")
    
    elif args.action == "search" and args.query:
        results = ee.search(args.query, top_k=args.topk)
        print(f"\n🔍 语义搜索: {args.query}")
        for doc_id, score in results:
            doc = searcher.doc_index.get(doc_id, {})
            title = doc.get("title", "无标题")
            print(f"  [{score:.3f}] {title}")
    
    elif args.action == "hybrid" and args.query:
        results = ee.hybrid_search(searcher, args.query, top_k=args.topk)
        print(f"\n🔀 混合搜索: {args.query}")
        for doc in results:
            title = doc.get("title", "无标题")
            score = doc.get("score", 0)
            kw = doc.get("kw_score", 0)
            vec = doc.get("vec_score", 0)
            print(f"  [{score:.1f}] {title}  (关键词:{kw:.1f} 语义:{vec:.3f})")


if __name__ == "__main__":
    main()
