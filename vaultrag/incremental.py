"""
增量入库 — 只处理新增/修改/删除的文件，秒级完成。
日常记笔记后自动运行，无需全量重建。
"""
import os
import sys
import json
import hashlib
import datetime
import fnmatch

from .config import VAULT_DIR, DB_DIR, EMBEDDING_MODEL
from .chunker import chunk
from .pdf import read_file
from .graph import build as build_graph, save as save_graph

import chromadb
from sentence_transformers import SentenceTransformer

MANIFEST = os.path.join(VAULT_DIR, ".vaultrag_manifest.json")


def _file_hash(filepath: str) -> str:
    h = hashlib.md5()
    with open(filepath, "rb") as f:
        for block in iter(lambda: f.read(8192), b""):
            h.update(block)
    return h.hexdigest()


def _load_manifest() -> dict:
    if os.path.exists(MANIFEST):
        with open(MANIFEST, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_manifest(m: dict):
    with open(MANIFEST, "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=2)


def _load_kbignore() -> list[str]:
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


def _find_collection(chroma_client):
    cols = [c.name for c in chroma_client.list_collections()
            if c.name.startswith("vaultrag_")]
    if not cols:
        raise RuntimeError("向量库为空，请先运行 python -m vaultrag.ingest")
    return sorted(cols)[-1]


def main(dry_run: bool = False):
    tag = " (预览)" if dry_run else ""
    print(f"增量入库{tag}", flush=True)

    ignore = _load_kbignore()
    all_files = _walk_files(VAULT_DIR, ignore)
    manifest = _load_manifest()

    new = [(f, _file_hash(os.path.join(VAULT_DIR, f))) for f in all_files if f not in manifest]
    changed = [(f, _file_hash(os.path.join(VAULT_DIR, f))) for f in all_files
               if f in manifest and manifest[f].get("hash") != _file_hash(os.path.join(VAULT_DIR, f))]
    deleted = [f for f in manifest if f not in all_files]
    unchanged = len(all_files) - len(new) - len(changed)

    print(f"  新增:{len(new)}  修改:{len(changed)}  删除:{len(deleted)}  不变:{unchanged}", flush=True)
    for f, _ in new:
        print(f"    + {f}", flush=True)
    for f, _ in changed:
        print(f"    ~ {f}", flush=True)
    for f in deleted:
        print(f"    - {f}", flush=True)

    if not any([new, changed, deleted]):
        print("  无变化", flush=True)
        return

    if dry_run:
        return

    print(f"\n  加载 Embedding: {EMBEDDING_MODEL} ...", end=" ", flush=True)
    model = SentenceTransformer(EMBEDDING_MODEL)
    print("OK", flush=True)

    chroma = chromadb.PersistentClient(path=DB_DIR)
    col_name = _find_collection(chroma)
    col = chroma.get_collection(name=col_name)
    print(f"  向量库: {col_name} ({col.count()} 块)", flush=True)

    # 删除已移除的文件
    for f in deleted:
        safe = f.replace("\\", "/").replace("/", "_")
        old_ids = [f"{safe}_c{i}" for i in range(manifest[f].get("chunks", 0))]
        if old_ids:
            try:
                col.delete(ids=old_ids)
                print(f"  [-] {f}", flush=True)
            except Exception:
                pass

    # 处理新增/修改
    to_process = new + changed
    added = 0
    for fname, fhash in to_process:
        safe = fname.replace("\\", "/").replace("/", "_")
        # 先删旧块
        if fname in manifest:
            old_ids = [f"{safe}_c{i}" for i in range(manifest[fname].get("chunks", 0))]
            if old_ids:
                try:
                    col.delete(ids=old_ids)
                except Exception:
                    pass

        fp = os.path.join(VAULT_DIR, fname)
        text = read_file(fp)
        if not text or not text.strip():
            continue

        chunks = chunk(text)
        if not chunks:
            continue

        ids = [f"{safe}_c{i}" for i in range(len(chunks))]
        metas = [{"source": fname, "chunk": i, "len": len(c)} for i, c in enumerate(chunks)]
        embeddings = model.encode(chunks, show_progress_bar=False).tolist()
        col.add(ids=ids, documents=chunks, metadatas=metas, embeddings=embeddings)

        manifest[fname] = {"hash": fhash, "chunks": len(chunks),
                           "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        added += len(chunks)
        tag = "+" if fname in dict(new) else "~"
        print(f"  [{tag}] {fname} → {len(chunks)} 块", flush=True)

    for f in deleted:
        del manifest[f]
    _save_manifest(manifest)

    # 自动重建图谱
    print("  图谱 ...", end=" ", flush=True)
    g = build_graph()
    save_graph(g)
    print(f"({g['file_count']} 节点)", flush=True)

    print(f"\n[DONE] 新增 {added} 块 → 总计 {col.count()} 块", flush=True)


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    main(dry_run=dry)
