"""
Wikilink 图谱索引 — 从 vault 的 [[wikilinks]] 构建 文件→文件 映射
向量 + BM25 + 图谱 = 三路融合检索

用法:
  python graph_index.py            # 构建并缓存
  python graph_index.py --check    # 检查缓存是否最新
"""
import os
import re
import json
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from config import DOC_DIR

GRAPH_CACHE = os.path.join(os.path.dirname(__file__), "graph_cache.json")
WIKILINK_RE = re.compile(r'\[\[([^\]|#]+?)(?:[|#][^\]]+)?\]\]')


def _scan_files(root: str) -> list[str]:
    """递归扫描 vault 所有 .md 文件"""
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
    """从文件中提取所有 [[wikilink]] 目标"""
    targets = []
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        for match in WIKILINK_RE.finditer(content):
            target = match.group(1).strip()
            if target:
                targets.append(target)
    except Exception:
        pass
    return list(set(targets))  # 去重


def build_graph() -> dict:
    """
    构建图谱:
    {
      "outgoing": { "a.md": ["b.md", "c.md"], ... },     # a 引用了谁
      "backlinks": { "b.md": ["a.md"], ... },             # 谁引用了 b
      "title_index": { "笔记标题": "路径/文件名.md", ... }   # 标题→文件映射
    }
    """
    all_files = _scan_files(DOC_DIR)
    outgoing = {}
    title_index = {}

    for filepath in all_files:
        rel = os.path.relpath(filepath, DOC_DIR)
        # 标题 = 去掉扩展名的文件名
        title = os.path.splitext(os.path.basename(filepath))[0]
        title_index[title] = rel

        links = _extract_wikilinks(filepath)
        if links:
            outgoing[rel] = links
        else:
            outgoing[rel] = []

    # 构建反向索引
    backlinks = {}
    for source, targets in outgoing.items():
        for target_name in targets:
            # 解析 wikilink 目标 → 实际文件
            target_file = _resolve_link(target_name, title_index, source)
            if target_file:
                if target_file not in backlinks:
                    backlinks[target_file] = []
                if source not in backlinks[target_file]:
                    backlinks[target_file].append(source)

    # 共现词图谱（弥补 wikilinks 稀疏性）
    cooccurrence = _build_cooccurrence(all_files, title_index)

    graph = {
        "outgoing": outgoing,
        "backlinks": backlinks,
        "title_index": title_index,
        "file_count": len(all_files),
        "cooccurrence": cooccurrence,
    }
    return graph


def _build_cooccurrence(all_files: list[str], title_index: dict) -> dict:
    """提取文档中高频共现的技术词对，构建隐式边"""
    import jieba.analyse
    from collections import Counter

    pair_counter = Counter()
    doc_keywords = {}  # rel_path → {keywords}

    for fp in all_files:
        rel = os.path.relpath(fp, DOC_DIR)
        try:
            with open(fp, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
            # 只取技术关键词（英文+2字以上中文）
            kw = jieba.analyse.extract_tags(text, topK=8)
            kw_filtered = [k for k in kw if len(k) >= 2]
            doc_keywords[rel] = set(kw_filtered)
        except Exception:
            doc_keywords[rel] = set()

    # 统计共现对
    for rel, kws in doc_keywords.items():
        kws_list = list(kws)
        for i in range(len(kws_list)):
            for j in range(i + 1, len(kws_list)):
                pair = tuple(sorted([kws_list[i], kws_list[j]]))
                pair_counter[pair] += 1

    # 只保留高频共现对（≥2次）
    return {f"{a} <-> {b}": c for (a, b), c in pair_counter.items() if c >= 2}


def _resolve_link(target: str, title_index: dict, source_path: str) -> str | None:
    """解析 [[wikilink]] 目标 → vault 相对路径"""
    # 优先精确匹配标题
    if target in title_index:
        return title_index[target]

    # 模糊匹配
    target_lower = target.lower()
    for title, path in title_index.items():
        if title.lower() == target_lower:
            return path
    # 部分匹配（开头）
    matches = [(t, p) for t, p in title_index.items()
               if t.lower().startswith(target_lower)]
    if len(matches) == 1:
        return matches[0][1]

    # wikilink 可能就是文件名
    if target.endswith(".md"):
        return target

    return None


def load_graph() -> dict | None:
    """加载缓存图谱"""
    if os.path.exists(GRAPH_CACHE):
        with open(GRAPH_CACHE, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def save_graph(graph: dict):
    """缓存图谱"""
    with open(GRAPH_CACHE, "w", encoding="utf-8") as f:
        json.dump(graph, f, ensure_ascii=False, indent=2)


def expand_candidates(source_file: str, graph: dict, depth: int = 1) -> list[str]:
    """
    图谱扩展: 找到与 source_file 直接关联的文件
    - 它引用了谁 (outgoing)
    - 谁引用了它 (backlinks)
    """
    if not graph:
        return []
    linked = set()

    # 正向: 它引用了谁
    for target in graph.get("outgoing", {}).get(source_file, []):
        resolved = _resolve_link(target, graph.get("title_index", {}), source_file)
        if resolved:
            linked.add(resolved)

    # 反向: 谁引用了它
    for source in graph.get("backlinks", {}).get(source_file, []):
        linked.add(source)

    return list(linked)


# ═══ CLI ═══
if __name__ == "__main__":
    if "--check" in sys.argv:
        g = load_graph()
        if g:
            print(f"图谱缓存: {g.get('file_count', '?')} 个文件")
        else:
            print("未找到缓存，请先构建: python graph_index.py")
    else:
        print(f"扫描: {DOC_DIR}", flush=True)
        graph = build_graph()
        save_graph(graph)
        edges = sum(len(v) for v in graph["outgoing"].values())
        bl = sum(len(v) for v in graph["backlinks"].values())
        print(f"文件: {graph['file_count']} | 正向链接: {edges} | 反向链接: {bl}", flush=True)
        print(f"缓存: {GRAPH_CACHE}", flush=True)
