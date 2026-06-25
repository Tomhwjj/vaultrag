"""
VaultRAG 演示 — 三路检索对比
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ["VAULTRAG_VAULT"] = os.environ.get("VAULTRAG_VAULT",
    os.path.join(os.path.dirname(__file__), "..", "vault"))

from vaultrag.query import _init, retrieve, TOP_K

embed, reranker, col, bm25_data, graph = _init()

queries = [
    "割肉还是调仓换股",
    "炒股需要经历哪些痛苦",
    "如何控制回撤",
]

for q in queries:
    results = retrieve(q, embed, reranker, col, bm25_data, graph)
    print(f"\n{'='*60}")
    print(f"[Q] {q}")
    print(f"{'='*60}")
    for i, r in enumerate(results):
        src = r["metadata"].get("source", "?")
        tags = []
        if "distance" in r:
            tags.append("向量")
        if "bm25_score" in r:
            tags.append("BM25")
        if "graph_file" in r:
            tags.append("图谱")
        print(f"  [{i+1}] [{src}]  {r['rerank_score']:.4f} | {'+'.join(tags)}")
        preview = r["document"][:120].replace("\n", " ")
        print(f"      \"{preview}...\"")
    print()
