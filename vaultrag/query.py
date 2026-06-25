"""
三路检索融合 — 向量语义 + BM25 关键词 + 图谱关系 → RRF → Reranker 精排
"""
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from .config import (
    DB_DIR, EMBEDDING_MODEL, QUERY_INSTRUCTION, RERANKER_MODEL,
    TOP_K, RERANK_MULTIPLIER, RRF_K, VAULT_DIR,
)
from .graph import load as load_graph, expand

import chromadb
from sentence_transformers import SentenceTransformer, CrossEncoder


# ═══ 初始化 ═══

def _init():
    """加载模型和索引，返回 (embed_model, reranker, collection, bm25_data, graph)"""
    print(f"Embedding: {EMBEDDING_MODEL} ...", end=" ", flush=True)
    embed = SentenceTransformer(EMBEDDING_MODEL)

    chroma = chromadb.PersistentClient(path=DB_DIR)
    cols = [c.name for c in chroma.list_collections() if c.name.startswith("vaultrag_")]
    if not cols:
        raise RuntimeError(f"向量库为空。先跑: python -m vaultrag.ingest")
    col = chroma.get_collection(name=sorted(cols)[-1])
    print(f"({col.count()}块)", end=" ", flush=True)

    print(f"Reranker: {RERANKER_MODEL} ...", end=" ", flush=True)
    reranker = CrossEncoder(RERANKER_MODEL)

    # BM25
    bm25_data = _build_bm25(col)

    # 图谱
    print(f"图谱 ...", end=" ", flush=True)
    graph = load_graph()
    print(f"({'✓' if graph else '未构建'})", flush=True)

    return embed, reranker, col, bm25_data, graph


def _build_bm25(collection):
    try:
        import jieba
        from rank_bm25 import BM25Okapi
    except ImportError:
        return None, None, None

    data = collection.get()
    if not data["ids"]:
        return None, None, None

    tokenized = [list(jieba.cut(d)) for d in data["documents"]]
    bm25 = BM25Okapi(tokenized)
    print(f"BM25({len(data['ids'])}篇) ...", end=" ", flush=True)
    return data["ids"], data["documents"], data["metadatas"], bm25


# ═══ RRF 融合 ═══

def rrf_fusion(*routes: list[dict], k: int = RRF_K) -> list[str]:
    """多路排名融合 — 量纲不同，只看排名"""
    scores: dict[str, float] = {}
    for route in routes:
        for rank, r in enumerate(route):
            doc_id = r["id"]
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
    return [d for d, _ in sorted(scores.items(), key=lambda x: x[1], reverse=True)]


# ═══ 检索 ═══

def retrieve(query: str, embed, reranker, collection, bm25_data, graph,
             top_k: int = TOP_K) -> list[dict]:
    """
    三路检索:
      路1: BGE 向量语义
      路2: jieba + BM25 关键词
      路3: [[wikilinks]] 图谱关系
    """
    fetch_k = min(top_k * RERANK_MULTIPLIER, collection.count())

    # 路1: 向量
    q_emb = embed.encode([QUERY_INSTRUCTION + query]).tolist()
    vec_raw = collection.query(query_embeddings=q_emb, n_results=fetch_k)
    vector_ranked = []
    if vec_raw["ids"] and vec_raw["ids"][0]:
        for i in range(len(vec_raw["ids"][0])):
            vector_ranked.append({
                "id": vec_raw["ids"][0][i],
                "document": vec_raw["documents"][0][i],
                "metadata": vec_raw["metadatas"][0][i],
                "distance": vec_raw["distances"][0][i],
            })

    # 路2: BM25
    bm25_ranked = []
    if bm25_data[0]:
        all_ids, all_docs, all_metas, bm25_model = bm25_data
        try:
            import jieba
            scores = bm25_model.get_scores(list(jieba.cut(query)))
            ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
            for idx, score in ranked[:fetch_k]:
                if score <= 0:
                    continue
                bm25_ranked.append({
                    "id": all_ids[idx],
                    "document": all_docs[idx],
                    "metadata": all_metas[idx],
                    "bm25_score": float(score),
                })
        except Exception:
            pass

    # 路3: 图谱
    graph_ranked = []
    if graph:
        top_sources = set()
        for r in (vector_ranked + bm25_ranked)[:top_k * 2]:
            src = r["metadata"].get("source", "")
            if src:
                top_sources.add(src)
        linked = set()
        for src in top_sources:
            linked.update(expand(src, graph))
        for lf in linked:
            try:
                chunks = collection.get(where={"source": lf}, limit=top_k)
                if chunks["ids"]:
                    for j in range(len(chunks["ids"])):
                        graph_ranked.append({
                            "id": chunks["ids"][j],
                            "document": chunks["documents"][j],
                            "metadata": chunks["metadatas"][j],
                            "graph_file": lf,
                        })
            except Exception:
                pass

    # RRF 融合
    merged = rrf_fusion(vector_ranked, bm25_ranked, graph_ranked)

    doc_map = {}
    for r in vector_ranked + bm25_ranked + graph_ranked:
        doc_map[r["id"]] = r

    candidates = [doc_map[d] for d in merged[:fetch_k] if d in doc_map]
    if not candidates:
        return []

    # Reranker 精排
    pairs = [[query, c["document"]] for c in candidates]
    for c, score in zip(candidates, reranker.predict(pairs, show_progress_bar=False)):
        c["rerank_score"] = float(score)

    candidates.sort(key=lambda x: x["rerank_score"], reverse=True)
    return candidates[:top_k]


# ═══ CLI ═══

def _source_tag(r: dict) -> str:
    tags = []
    if "distance" in r:
        tags.append("向量")
    if "bm25_score" in r:
        tags.append("BM25")
    if "graph_file" in r:
        tags.append("图谱")
    return "+".join(tags) if tags else "融合"


def search(query: str) -> list[dict]:
    """单次检索入口"""
    embed, reranker, col, bm25_data, graph = _init()
    return retrieve(query, embed, reranker, col, bm25_data, graph)


def main():
    embed, reranker, col, bm25_data, graph = _init()

    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
        results = retrieve(query, embed, reranker, col, bm25_data, graph)
        _print_results(query, results)
    else:
        print("输入问题 (quit 退出)\n", flush=True)
        while True:
            try:
                q = input("Query: ").strip()
                if not q:
                    continue
                if q.lower() in ("quit", "exit", "q"):
                    break
                results = retrieve(q, embed, reranker, col, bm25_data, graph)
                _print_results(q, results)
            except (EOFError, KeyboardInterrupt):
                break


def _print_results(query: str, results: list[dict]):
    print(f"\n{'='*60}")
    print(f"[Q] {query}\n")
    if not results:
        print("  (无结果)")
        return
    for i, r in enumerate(results):
        src = r["metadata"].get("source", "?")
        preview = r["document"][:250].replace("\n", " ") + ("..." if len(r["document"]) > 250 else "")
        print(f"  [{i+1}] [{src}]  精排:{r['rerank_score']:.4f} | {_source_tag(r)}")
        print(f"      {preview}\n")


if __name__ == "__main__":
    main()
