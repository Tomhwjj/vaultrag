"""
Wikilink 图谱 — 扫描 vault 的 [[wikilinks]]，构建文件关系图。
供给 query.py 做图谱增强检索。
"""
import os
import re
import json
from .config import VAULT_DIR

WIKILINK_RE = re.compile(r'\[\[([^\]|#]+?)(?:[|#][^\]]+)?\]\]')
CACHE_PATH = os.path.join(os.path.dirname(__file__), "..", "graph_cache.json")


def _scan_files(root: str) -> list[str]:
    """递归扫描所有 .md 文件"""
    files = []
    for entry in os.listdir(root):
        full = os.path.join(root, entry)
        if entry.startswith("."):
            continue
        if os.path.isfile(full) and entry.endswith(".md"):
            files.append(full)
        elif os.path.isdir(full):
            files.extend(_scan_files(full))
    return files


def _extract_wikilinks(filepath: str) -> list[str]:
    """提取文件中所有 [[wikilink]]"""
    targets = []
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            for match in WIKILINK_RE.finditer(f.read()):
                t = match.group(1).strip()
                if t:
                    targets.append(t)
    except Exception:
        pass
    return list(set(targets))


def _resolve_link(target: str, title_index: dict) -> str | None:
    """[[wikilink]] → vault 相对路径"""
    if target in title_index:
        return title_index[target]
    target_lower = target.lower()
    for title, path in title_index.items():
        if title.lower() == target_lower:
            return path
    matches = [(t, p) for t, p in title_index.items()
               if t.lower().startswith(target_lower)]
    if len(matches) == 1:
        return matches[0][1]
    if target.endswith(".md"):
        return target
    return None


def build() -> dict:
    """构建图谱: {outgoing, backlinks, title_index, file_count}"""
    all_files = _scan_files(VAULT_DIR)
    outgoing = {}
    title_index = {}

    for fp in all_files:
        rel = os.path.relpath(fp, VAULT_DIR)
        title = os.path.splitext(os.path.basename(fp))[0]
        title_index[title] = rel
        links = _extract_wikilinks(fp)
        outgoing[rel] = links or []

    backlinks = {}
    for source, targets in outgoing.items():
        for t in targets:
            tf = _resolve_link(t, title_index)
            if tf:
                backlinks.setdefault(tf, []).append(source)

    return {
        "outgoing": outgoing,
        "backlinks": backlinks,
        "title_index": title_index,
        "file_count": len(all_files),
    }


def load() -> dict | None:
    """加载缓存图谱"""
    if os.path.exists(CACHE_PATH):
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def save(graph: dict):
    """缓存图谱"""
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(graph, f, ensure_ascii=False, indent=2)


def expand(source_file: str, graph: dict) -> list[str]:
    """图谱扩展: 找到与 source_file 直接关联的文件"""
    if not graph:
        return []
    linked = set()
    ti = graph.get("title_index", {})
    # 正向: 它引用了谁
    for t in graph.get("outgoing", {}).get(source_file, []):
        r = _resolve_link(t, ti)
        if r:
            linked.add(r)
    # 反向: 谁引用了它
    for src in graph.get("backlinks", {}).get(source_file, []):
        linked.add(src)
    return list(linked)
