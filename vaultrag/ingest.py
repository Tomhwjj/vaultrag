"""
全量入库 — 首次建库或换 Embedding 模型时使用。
扫描 vault 所有 .md/.txt/.pdf → 分块 → BGE 向量化 → ChromaDB
"""
import os
import sys
import datetime
import fnmatch

from .config import VAULT_DIR, DB_DIR, EMBEDDING_MODEL, CHUNK_SIZE, CHUNK_OVERLAP
from .chunker import chunk
from .pdf import read_file

import chromadb
from sentence_transformers import SentenceTransformer


def _load_kbignore() -> list[str]:
    """读取 .kbignore"""
    path = os.path.join(VAULT_DIR, ".kbignore")
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return [l.strip() for l in f if l.strip() and not l.strip().startswith("#")]


def _should_ignore(name: str, rules: list[str]) -> bool:
    for rule in rules:
        if fnmatch.fnmatch(name, rule):
            return True
        if rule.endswith("/") and name.startswith(rule):
            return True
    return False


def _walk_files(root: str, ignore_rules: list[str]) -> list[str]:
    """递归扫描，返回相对路径"""
    result = []
    for entry in os.listdir(root):
        full = os.path.join(root, entry)
        rel = os.path.relpath(full, VAULT_DIR)
        if entry.startswith(".") or _should_ignore(rel, ignore_rules):
            continue
        if os.path.isfile(full):
            ext = os.path.splitext(entry)[1].lower()
            if ext in (".txt", ".md", ".pdf"):
                result.append(rel)
        elif os.path.isdir(full):
            result.extend(_walk_files(full, ignore_rules))
    return result


def main():
    print(f"[1/3] 加载 Embedding: {EMBEDDING_MODEL}", flush=True)
    model = SentenceTransformer(EMBEDDING_MODEL)

    print(f"[2/3] 向量库: {DB_DIR}", flush=True)
    chroma = chromadb.PersistentClient(path=DB_DIR)
    name = f"vaultrag_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
    col = chroma.create_collection(name=name)

    ignore = _load_kbignore()
    files = _walk_files(VAULT_DIR, ignore)
    print(f"[3/3] 扫描: {VAULT_DIR} → {len(files)} 个文件", flush=True)

    if not files:
        print("[WARN] 未找到文档", flush=True)
        return

    total = 0
    for fname in files:
        fp = os.path.join(VAULT_DIR, fname)
        text = read_file(fp)
        if not text or not text.strip():
            print(f"  [SKIP] {fname}", flush=True)
            continue

        chunks = chunk(text)
        if not chunks:
            continue

        safe = fname.replace("\\", "/").replace("/", "_")
        ids = [f"{safe}_c{i}" for i in range(len(chunks))]
        metas = [{"source": fname, "chunk": i, "len": len(c)} for i, c in enumerate(chunks)]
        embeddings = model.encode(chunks, show_progress_bar=True).tolist()
        col.add(ids=ids, documents=chunks, metadatas=metas, embeddings=embeddings)

        avg = sum(len(c) for c in chunks) // len(chunks)
        print(f"  [OK] {fname} → {len(chunks)} 块 (avg {avg}字)", flush=True)
        total += len(chunks)

    # 清理旧集合
    for c in chroma.list_collections():
        if c.name.startswith("vaultrag_") and c.name != name:
            chroma.delete_collection(name=c.name)

    print(f"\n[DONE] {len(files)} 文件, {total} 块 → {name}", flush=True)


if __name__ == "__main__":
    main()
