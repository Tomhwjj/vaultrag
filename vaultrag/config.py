"""
统一配置 — 所有参数集中管理。

设置 vault 路径:
    export VAULTRAG_VAULT="/path/to/obsidian/vault"
    export VAULTRAG_MODELS="/path/to/models"          # 可选，默认 ./models
    export VAULTRAG_DB="/path/to/vectordb"            # 可选，默认 ./vectordb
"""
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ── vault 路径（数据源）──────────────────────
VAULT_DIR = os.environ.get("VAULTRAG_VAULT", os.path.join(BASE_DIR, "..", "vault"))

# ── 存储路径 ──────────────────────────────────
MODELS_DIR = os.environ.get("VAULTRAG_MODELS", os.path.join(BASE_DIR, "..", "models"))
DB_DIR     = os.environ.get("VAULTRAG_DB",     os.path.join(BASE_DIR, "..", "vectordb"))

# ── Embedding 模型 ────────────────────────────
EMBEDDING_MODEL   = "BAAI/bge-base-zh-v1.5"
QUERY_INSTRUCTION = "为这个句子生成表示以用于检索相关文章："

# ── Reranker 模型 ─────────────────────────────
RERANKER_MODEL    = "BAAI/bge-reranker-base"

# ── 分块策略 ──────────────────────────────────
CHUNK_SIZE    = 800
CHUNK_OVERLAP = 100
SEPARATORS    = ["\n\n", "\n", "。", ".", "；", ";", "，", ",", " ", ""]

# ── 检索参数 ──────────────────────────────────
TOP_K            = 5
RERANK_MULTIPLIER = 3
RRF_K            = 60

# ── 离线模式（模型已缓存时设为 1）─────────────
if os.environ.get("VAULTRAG_OFFLINE", ""):
    os.environ["HF_HUB_OFFLINE"] = "1"

# ── 模型缓存路径 ──────────────────────────────
os.environ["HF_HOME"] = os.path.abspath(MODELS_DIR)
