# VaultRAG

**Vault-native AI memory stack — RAG + persistent memory for Claude Code.**

Your Obsidian vault **is** the knowledge base AND the memory system. No import, no sync, no duplication.

Three-way retrieval (vector + BM25 + graph) for search. Tag-based memory snapshots for persistent AI context across sessions.

```
query ─┬─ BGE Embedding ──→ Vector Semantic ──┐
       │                                       │
       ├─ jieba ──────────→ BM25 Keyword ─────┤── RRF Fusion ──→ Cross-Encoder Rerank ──→ top_k
       │                                       │
       └─ [[wikilinks]] ───→ Graph Relations ─┘
```

## Why VaultRAG

Most RAG systems only do **one thing**: find documents that *look similar* to your query. That misses:

| Blind spot | What VaultRAG does |
|---|---|
| "茅台 2024 Q3 营收" vs "白酒行业分析" | **BM25** catches the exact numbers and names |
| A note about 茅台 references `[[白酒板块]]`, but the two don't share keywords | **Graph** pulls in connected notes via wikilinks |

Three retrieval paths, one unified rank. Each fills a gap the others leave.

## Architecture

```
Your Obsidian Vault  ──read──→  Chunker (recursive semantic)
       │                        │
       │                        ▼
       │              ChromaDB (vector index)
       │                        │
       ▼                        ▼
  [[wikilinks]]            Query Engine
       │                        │
       ▼                        ▼
  Graph Index ────→  Three-Way RRF ──→ Reranker ──→ Results
```

**Vault-native**: The vault directory *is* the document source. Write a note → incremental ingest → instantly searchable. No export step. No `.copy_to_kb()`.

## Quick Start

```bash
# 1. Install
pip install -e .

# 2. Set your vault path and build the index
export VAULTRAG_VAULT="/path/to/your/obsidian/vault"
python -m vaultrag.ingest

# 3. Search
python -m vaultrag.query "割肉还是调仓换股"
```

First run downloads ~1.5GB of models (cached in `./models/`).

## Daily Use

```bash
# Add notes to your vault, then:
python -m vaultrag.incremental     # seconds, not minutes

# Search anytime:
python -m vaultrag.query "白酒板块投资逻辑"
```

## Configuration

All via environment variables:

| Variable | Default | Description |
|---|---|---|
| `VAULTRAG_VAULT` | `./vault` | Path to Obsidian vault |
| `VAULTRAG_DB` | `./vectordb` | ChromaDB storage |
| `VAULTRAG_MODELS` | `./models` | BGE model cache |
| `VAULTRAG_OFFLINE` | (empty) | Set to `1` to skip HF checks |

Or edit `vaultrag/config.py` directly.

## .kbignore

Drop a `.kbignore` in your vault root to exclude files from indexing:

```
.obsidian/
Templates/
*.canvas
日记/
```

Same syntax as `.gitignore`.

## The Three Retrieval Paths

### 1. Vector (Semantic)
BGE Chinese embedding → HNSW similarity. Finds what "means the same thing".

### 2. BM25 (Keyword)
jieba tokenization → BM25Okapi scoring. Finds exact terms, stock codes, numbers.

### 3. Graph (Relationship)
Scans `[[wikilinks]]` in vault → builds outgoing + backlink graph. When a note ranks high in vector/BM25, its linked neighbors get pulled in too.

### RRF + Reranker
Reciprocal Rank Fusion merges the three ranked lists (rank matters, not raw scores). Then a Cross-Encoder reranker does the final sort.

## Stack

| Layer | Tech |
|---|---|
| Embedding | `BAAI/bge-base-zh-v1.5` |
| Reranker | `BAAI/bge-reranker-base` |
| Vector DB | ChromaDB (embedded) |
| Tokenizer | jieba |
| Graph | Regex `[[wikilinks]]` scanner |
| PDF | pdfplumber (tables) / PyMuPDF |
| Chunking | Recursive semantic (paragraph → sentence → character) |

## Requirements

- Python ≥ 3.10
- `chromadb`, `sentence-transformers`, `jieba`, `rank-bm25`
- Optional: `pdfplumber`, `PyMuPDF` (for PDF support)

## License

MIT — see [LICENSE](LICENSE).
