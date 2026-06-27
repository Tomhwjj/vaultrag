"""
知识库查询脚本 (v4)
- BGE 中文 Embedding（精度 +20%）
- BM25 + 向量 混合检索 + RRF 融合（补上关键词盲区）
- 图谱扩展: [[wikilinks]] 反向链接补上关系盲区
- Cross-Encoder Reranker 精排（精度 +30-50%）
- 三路召回 → RRF 融合 → 精排
"""
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from config import (
    DB_DIR,
    EMBEDDING_MODEL, QUERY_INSTRUCTION,
    RERANKER_MODEL,
    TOP_K, RERANK_MULTIPLIER, RRF_K,
)
try:
    from config import RRF_WEIGHTS
except ImportError:
    RRF_WEIGHTS = None
import chromadb
from sentence_transformers import SentenceTransformer, CrossEncoder


# ═══════════════════════════════════════════════
# 关键词提取（Route A 混合本地 + Route B LLM 兜底）
# ═══════════════════════════════════════════════

def _extract_keywords(text: str, llm_fallback: callable = None) -> list[str]:
    """
    三路本地关键词提取 + LLM 兜底:
      Route A1: 正则自动词典（技术栈/项目名）
      Route A2: jieba TF-IDF（中文技术词 + 未知词发现）
      Route A3: jieba TextRank（语义概念）
      兜底: 合并后 ≤2 且含中文 → LLM 最后一搏
    """
    import re, jieba.analyse

    keywords = []

    # ── A1: 正则自动词典（从 vault #mem-rule 快照中抽取）──
    # 先从 memory_load 拿已有规则快照的 summary 建词典
    try:
        from memory_load import load as load_memories
        rules = load_memories(hot_only=False)
        rule_text = " ".join([m.get("summary", "") for m in rules
                             if "mem-rule" in m.get("tags", [])])
    except Exception:
        rule_text = ""

    # 基础技术词典（硬编码保底）
    base_terms = [
        'ChromaDB', 'Milvus', 'BGE', 'MiniLM', 'BM25', 'jieba',
        'pdfplumber', 'PyMuPDF', 'Obsidian', 'RAG', 'RRF', 'Reranker',
        'Cross-Encoder', 'sentence-transformers', 'HuggingFace', 'Playwright',
        'Claude Code', 'vaultrag', 'knowledge-base', 'investment-advisor',
    ]
    # 从规则快照中提取项目名/工具名（自动扩展词典）
    auto_terms = re.findall(r'[A-Z][a-zA-Z0-9.\-]+[a-zA-Z0-9]', rule_text)
    all_terms = set(base_terms + auto_terms)

    for term in all_terms:
        if term.lower() in text.lower():
            keywords.append(term)

    # ── A2: jieba TF-IDF ──
    try:
        tfidf_kw = jieba.analyse.extract_tags(text, topK=6)
        keywords.extend([k for k in tfidf_kw if len(k) >= 2])
    except Exception:
        pass

    # ── A3: jieba TextRank ──
    try:
        tr_kw = jieba.analyse.textrank(text, topK=6)
        keywords.extend([k for k in tr_kw if len(k) >= 2])
    except Exception:
        pass

    # ── 去重合并 ──
    seen = set()
    merged = []
    for k in keywords:
        if k.lower() not in seen:
            seen.add(k.lower())
            merged.append(k)

    # ── 兜底: ≤2 且含中文 → LLM ──
    has_chinese = bool(re.search(r'[一-鿿]', text))
    if len(merged) <= 2 and has_chinese and llm_fallback:
        fallback_kw = llm_fallback(text)
        if fallback_kw:
            merged.extend(fallback_kw)

    return merged


# ═══════════════════════════════════════════════
# BM25 索引
# ═══════════════════════════════════════════════

def _build_bm25(collection):
    """从 ChromaDB 的所有文档构建 BM25 索引"""
    try:
        import jieba
    except ImportError:
        print("[WARN] jieba 未安装，BM25 关键词检索将跳过")
        print("       安装: pip install jieba")
        return None, None, None

    try:
        from rank_bm25 import BM25Okapi
    except ImportError:
        print("[WARN] rank_bm25 未安装，BM25 关键词检索将跳过")
        print("       安装: pip install rank-bm25")
        return None, None, None

    # 取出所有文档
    all_data = collection.get()
    if not all_data["ids"]:
        return None, None, None

    docs = all_data["documents"]
    ids = all_data["ids"]
    metas = all_data["metadatas"]

    # jieba 分词
    tokenized = [list(jieba.cut(doc)) for doc in docs]
    bm25 = BM25Okapi(tokenized)

    return bm25, docs, ids, metas


# ═══════════════════════════════════════════════
# 初始化
# ═══════════════════════════════════════════════

def _find_latest_collection(chroma_client) -> str:
    """找到最新的 knowledge_ 集合"""
    cols = [c.name for c in chroma_client.list_collections()
            if c.name.startswith("knowledge_")]
    if not cols:
        raise RuntimeError("向量库为空，请先运行 ingest.py")
    return sorted(cols)[-1]


print(f"加载 Embedding: {EMBEDDING_MODEL} ...", end=" ", flush=True)
embed_model = SentenceTransformer(EMBEDDING_MODEL)

chroma = chromadb.PersistentClient(path=DB_DIR)
try:
    collection_name = _find_latest_collection(chroma)
    collection = chroma.get_collection(name=collection_name)
except RuntimeError:
    print(f"\n[ERROR] 向量库为空。请先导入文档:")
    print(f"  python ingest.py")
    sys.exit(1)

print(f"({collection_name})", end=" ", flush=True)

print(f"Reranker: {RERANKER_MODEL} ...", end=" ", flush=True)
reranker = CrossEncoder(RERANKER_MODEL)

# 构建 BM25 索引
print(f"BM25 ...", end=" ", flush=True)
_bm25_result = _build_bm25(collection)
if _bm25_result[0] is not None:
    bm25, all_ids, all_docs, all_metas = _bm25_result
    id_to_idx = {doc_id: idx for idx, doc_id in enumerate(all_ids)}
    print(f"({len(all_ids)} 篇文档)", end=" ", flush=True)
    has_bm25 = True
else:
    has_bm25 = False

# 加载图谱
print(f"图谱 ...", end=" ", flush=True)
from graph_index import load_graph, expand_candidates
graph = load_graph()
if graph:
    print(f"({graph.get('file_count', '?')} 节点)", end=" ", flush=True)
    has_graph = True
else:
    print("(未构建)", end=" ", flush=True)
    has_graph = False

print("就绪\n")


# ═══════════════════════════════════════════════
# RRF 融合
# ═══════════════════════════════════════════════

def rrf_fusion(*routes: list[dict], k: int = RRF_K, weights: list[float] = None) -> list[str]:
    """
    Reciprocal Rank Fusion: 多路检索排名融合。
    weights 调节各路权重，如 [1.0, 1.5, 0.7] = 向量1.0, BM251.5, 图谱0.7
    """
    scores: dict[str, float] = {}
    if weights is None:
        weights = [1.0] * len(routes)

    for route, w in zip(routes, weights):
        for rank, r in enumerate(route):
            doc_id = r["id"]
            scores[doc_id] = scores.get(doc_id, 0.0) + w * 1.0 / (k + rank + 1)
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)

    sorted_ids = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return [doc_id for doc_id, _ in sorted_ids]


# ═══════════════════════════════════════════════
# 三阶段检索
# ═══════════════════════════════════════════════

LOG_FILE = os.path.join(os.path.dirname(__file__), ".query_log.jsonl")


def _log_query(query: str, results: list[dict], sources: list[str]):
    """无感日志：记录每次查询的每条结果来自哪路、最终排名"""
    import json, datetime
    entry = {
        "ts": datetime.datetime.now().isoformat(),
        "query": query[:200],
        "results": [],
    }
    for i, r in enumerate(results):
        paths = []
        if "distance" in r:
            paths.append("vector")
        if "bm25_score" in r:
            paths.append("bm25")
        if "graph_file" in r:
            paths.append("graph")
        entry["results"].append({
            "rank": i + 1,
            "score": round(r.get("rerank_score", 0), 4),
            "paths": paths,
            "source": r.get("metadata", {}).get("source", "")[:100],
        })
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def retrieve(query: str, top_k: int = TOP_K) -> list[dict]:
    """
    三路检索 + 关键词增强:
      阶段0: 关键词提取 (正则+TF-IDF+TextRank, ≤2词时LLM兜底)
      阶段1: 向量 + BM25 双路召回
      阶段2: RRF 融合排序
      阶段3: Cross-Encoder Reranker 精排
    """
    fetch_k = min(top_k * RERANK_MULTIPLIER, collection.count())

    # ── 阶段0: 关键词增强 ──
    kw = _extract_keywords(query)
    if kw:
        query = query + " " + " ".join(kw)

    # ── 路1: 向量检索 ──
    query_with_prefix = QUERY_INSTRUCTION + query
    q_emb = embed_model.encode([query_with_prefix]).tolist()
    vec_results = collection.query(query_embeddings=q_emb, n_results=fetch_k)

    vector_ranked = []
    if vec_results["ids"] and vec_results["ids"][0]:
        for i in range(len(vec_results["ids"][0])):
            vector_ranked.append({
                "id":       vec_results["ids"][0][i],
                "document": vec_results["documents"][0][i],
                "metadata": vec_results["metadatas"][0][i],
                "distance": vec_results["distances"][0][i],
            })

    # ── 路2: BM25 关键词检索 ──
    bm25_ranked = []
    if has_bm25:
        try:
            import jieba
            tokenized_q = list(jieba.cut(query))
            bm25_scores = bm25.get_scores(tokenized_q)
            # 取 top fetch_k
            indexed = list(enumerate(bm25_scores))
            indexed.sort(key=lambda x: x[1], reverse=True)
            for idx, score in indexed[:fetch_k]:
                if score <= 0:
                    continue
                bm25_ranked.append({
                    "id":       all_ids[idx],
                    "document": all_docs[idx],
                    "metadata": all_metas[idx],
                    "bm25_score": float(score),
                })
        except Exception:
            pass

    # ── 路3: 图谱扩展 ──
    graph_ranked = []
    if has_graph:
        # 取向量+BM25 的 top 候选项的源文件，找它们链接的笔记
        top_sources = set()
        for r in (vector_ranked + bm25_ranked)[:top_k * 2]:
            src = r["metadata"].get("source", "")
            if src:
                top_sources.add(src)

        graph_linked = set()
        for src in top_sources:
            linked = expand_candidates(src, graph)
            graph_linked.update(linked)

        # 在 ChromaDB 中查找图谱扩展的文档块
        if graph_linked:
            for linked_file in graph_linked:
                try:
                    linked_chunks = collection.get(
                        where={"source": linked_file},
                        limit=top_k,
                    )
                    if linked_chunks["ids"]:
                        for j in range(len(linked_chunks["ids"])):
                            graph_ranked.append({
                                "id":       linked_chunks["ids"][j],
                                "document": linked_chunks["documents"][j],
                                "metadata": linked_chunks["metadatas"][j],
                                "graph_file": linked_file,
                            })
                except Exception:
                    pass

    # ── RRF 三路融合 ──
    merged_ids = rrf_fusion(vector_ranked, bm25_ranked, graph_ranked,
                            weights=RRF_WEIGHTS)

    # 建立 doc_id → 详情 的映射
    doc_map = {}
    for r in vector_ranked:
        doc_map[r["id"]] = r
    for r in bm25_ranked:
        if r["id"] not in doc_map:
            doc_map[r["id"]] = r
    for r in graph_ranked:
        if r["id"] not in doc_map:
            doc_map[r["id"]] = r

    # 取融合后的 top candidates
    candidates = [doc_map[doc_id] for doc_id in merged_ids[:fetch_k] if doc_id in doc_map]

    if not candidates:
        return []

    # ── Cross-Encoder 精排 ──
    pairs = [[query, c["document"]] for c in candidates]
    rerank_scores = reranker.predict(pairs, show_progress_bar=False)

    for c, score in zip(candidates, rerank_scores):
        c["rerank_score"] = float(score)

        # 时间衰减（半衰期 30 天）
        import math, datetime
        mem_date = c.get("metadata", {}).get("date", "")
        if not mem_date:
            try:
                src = c.get("metadata", {}).get("source", "")
                if src:
                    match = __import__('re').search(r'(\d{4}-\d{2}-\d{2})', src)
                    if match:
                        mem_date = match.group(1)
            except:
                pass
        if mem_date:
            try:
                d = datetime.date.fromisoformat(mem_date)
                age = (datetime.date.today() - d).days
                decay = math.exp(-0.023 * age)  # λ = ln(2)/30
                c["rerank_score"] = float(score) * decay
            except ValueError:
                pass

    candidates.sort(key=lambda x: x["rerank_score"], reverse=True)
    result = candidates[:top_k]

    # 无感日志：记录每条最终结果的来源路径
    _log_query(query, result, [])

    return result


# ═══════════════════════════════════════════════
# 交互 / 单次查询
# ═══════════════════════════════════════════════

def format_results(query: str, results: list[dict]):
    """格式化输出检索结果"""
    print(f"\n{'='*60}")
    print(f"[Q] {query}\n")

    if not results:
        print("  (没有找到相关内容)")
        return

    for i, r in enumerate(results):
        source = r["metadata"].get("source", "?")
        vec_score = 1 / (1 + r.get("distance", 1.0))
        rerank = r["rerank_score"]

        # 显示每条结果来自哪条检索路
        sources = []
        if "distance" in r:
            sources.append("向量")
        if "bm25_score" in r:
            sources.append(f"BM25:{r['bm25_score']:.1f}")
        if "graph_file" in r:
            sources.append(f"图谱:{r['graph_file']}")
        source_tag = "+".join(sources) if sources else "融合"

        preview = r["document"][:250].replace("\n", " ") + ("..." if len(r["document"]) > 250 else "")

        print(f"  [{i+1}] [{source}]  精排: {rerank:.4f} | {source_tag}")
        print(f"      {preview}")
        print()


if len(sys.argv) > 1:
    query = " ".join(sys.argv[1:])
    results = retrieve(query)
    format_results(query, results)
else:
    print("输入问题，或 'quit' 退出\n")
    while True:
        try:
            q = input("Query: ").strip()
            if not q:
                continue
            if q.lower() in ("quit", "exit", "q"):
                print("Bye!")
                break
            results = retrieve(q)
            format_results(q, results)
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            break
