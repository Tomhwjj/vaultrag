"""
记忆快照写入 — BGE 语义去重 + 模板化写入 + 增量入库。
Claude Code 执行 /digest 时调用。
"""
import os
import sys
import json
import datetime
import numpy as np

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from config import DOC_DIR as VAULT_DIR, EMBEDDING_MODEL
from memory_load import load as load_all

MEMORY_DIR = os.path.join(VAULT_DIR, "记忆")

# 懒加载 BGE 模型（首次调用 check_dedup 时初始化）
_embed_model = None

TEMPLATE = """---
tags: [{tags}]
date: {date}
summary: {summary}
---

# {title}

## 📌 结论
{conclusion}

## 🧭 决策
{decisions}

## 🔒 约束
{constraints}

## 🐛 问题
{issues}

## 📎 来源
- 对话日期: {date}
"""


def _get_embed_model():
    global _embed_model
    if _embed_model is None:
        from sentence_transformers import SentenceTransformer
        _embed_model = SentenceTransformer(EMBEDDING_MODEL)
    return _embed_model


def _cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def check_dedup(title: str, summary: str, tags: list[str]) -> dict | None:
    """
    BGE 语义去重检查。
    对比范围: 近 3 天已写入的 #hot-30d 快照
    阈值: 余弦相似度 > 0.9 → merge
    返回: None（无重复）或 {"file": "路径", "sim": 0.95}
    """
    today = datetime.date.today()
    cutoff = today - datetime.timedelta(days=3)
    existing = load_all(hot_only=False)

    # 筛选近 3 天
    recent = []
    for m in existing:
        try:
            d = datetime.date.fromisoformat(m["date"])
            if d >= cutoff:
                recent.append(m)
        except ValueError:
            continue

    if not recent:
        return None

    # BGE 编码
    model = _get_embed_model()
    query_vec = model.encode([summary + " " + title])
    doc_texts = [m["summary"] + " " + m["title"] for m in recent]
    doc_vecs = model.encode(doc_texts)

    # 余弦相似度
    best_idx = 0
    best_sim = 0.0
    for i, dv in enumerate(doc_vecs):
        sim = _cosine_sim(query_vec[0], dv)
        if sim > best_sim:
            best_sim = sim
            best_idx = i

    if best_sim > 0.9:
        return {"file": recent[best_idx]["file"], "sim": round(best_sim, 3)}

    # 冲突检测：主题重叠但语义不相似 → 潜在矛盾
    import jieba.analyse
    new_topics = set(jieba.analyse.extract_tags(summary + " " + title, topK=5))
    old_topics = set(jieba.analyse.extract_tags(
        recent[best_idx]["summary"] + " " + recent[best_idx]["title"], topK=5))
    overlap = new_topics & old_topics
    if best_sim > 0 and len(overlap) >= 3 and best_sim < 0.5:
        return {
            "conflict": True,
            "file": recent[best_idx]["file"],
            "sim": round(best_sim, 3),
            "overlap_topics": list(overlap),
        }

    return None


def write(title: str, summary: str, tags: list[str],
          conclusion: str = "", decisions: str = "",
          constraints: str = "", issues: str = "") -> str:
    os.makedirs(MEMORY_DIR, exist_ok=True)

    date = datetime.date.today().isoformat()
    slug = title.replace(" ", "-").replace("/", "-")[:50]
    main_tag = [t for t in tags if t.startswith("mem-")]
    tag_part = main_tag[0] if main_tag else tags[0]
    fname = f"{date}-{tag_part}-{slug}.md"
    fpath = os.path.join(MEMORY_DIR, fname)

    content = TEMPLATE.format(
        tags=", ".join(tags),
        date=date,
        summary=summary,
        title=title,
        conclusion=conclusion or "（待补充）",
        decisions=decisions or "（无）",
        constraints=constraints or "（无）",
        issues=issues or "（无）",
    )
    with open(fpath, "w", encoding="utf-8") as f:
        f.write(content)

    import subprocess
    kb_dir = os.path.dirname(os.path.abspath(__file__))
    subprocess.run([sys.executable, os.path.join(kb_dir, "incremental_ingest.py")],
                   capture_output=True)
    return fpath


def merge(existing_file: str, title: str, summary: str, decisions: str = "",
          constraints: str = "", issues: str = ""):
    fpath = os.path.join(VAULT_DIR, existing_file)
    if not os.path.exists(fpath):
        return write(title, summary, [], "", decisions, constraints, issues)

    with open(fpath, "r", encoding="utf-8") as f:
        old = f.read()

    date = datetime.date.today().isoformat()

    history_block = f"""

## 📜 历史版本

<details>
<summary>{date} 更新前</summary>

{old.split('##')[1] if '##' in old else old}

</details>
"""

    tag_match = old[old.find("tags:") + 5: old.find("\n", old.find("tags:"))] if "tags:" in old else "mem-decision, hot-30d"

    new_content = TEMPLATE.format(
        tags=tag_match.strip(),
        date=old.split("\n")[2] if len(old.split("\n")) > 2 else date,
        summary=summary,
        title=title,
        conclusion="（已更新）",
        decisions=decisions or "（无）",
        constraints=constraints or "（无）",
        issues=issues or "（无）",
    ) + history_block

    with open(fpath, "w", encoding="utf-8") as f:
        f.write(new_content)

    import subprocess
    kb_dir = os.path.dirname(os.path.abspath(__file__))
    subprocess.run([sys.executable, os.path.join(kb_dir, "incremental_ingest.py")],
                   capture_output=True)
    return fpath


def main():
    import argparse
    p = argparse.ArgumentParser(description="记忆快照写入 — BGE语义去重")
    p.add_argument("--check", action="store_true", help="去重检查")
    p.add_argument("--write", action="store_true", help="写入新快照")
    p.add_argument("--merge", type=str, help="合并到已有文件")
    p.add_argument("--title", type=str)
    p.add_argument("--summary", type=str)
    p.add_argument("--tags", type=str)
    p.add_argument("--conclusion", type=str, default="")
    p.add_argument("--decisions", type=str, default="")
    p.add_argument("--constraints", type=str, default="")
    p.add_argument("--issues", type=str, default="")
    args = p.parse_args()

    if args.check:
        result = check_dedup(args.title or "", args.summary or "",
                             (args.tags or "").split(","))
        print(json.dumps(result or {"action": "create"}, ensure_ascii=False))

    elif args.write:
        fp = write(args.title or "Untitled", args.summary or "",
                   (args.tags or "mem-decision,hot-30d").split(","),
                   args.conclusion, args.decisions, args.constraints, args.issues)
        print(f"Created: {fp}")

    elif args.merge:
        fp = merge(args.merge, args.title or "Untitled", args.summary or "",
                   args.decisions, args.constraints, args.issues)
        print(f"Merged: {fp}")


if __name__ == "__main__":
    main()
