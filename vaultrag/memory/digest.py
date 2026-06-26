"""
记忆快照写入 — 去重检查 + 模板化写入 + 增量入库。
Claude Code 执行 /digest 时调用。
"""
import os
import sys
import json
import datetime
import hashlib

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from ..config import VAULT_DIR
from .load import load as load_all


MEMORY_DIR = os.path.join(VAULT_DIR, "记忆")
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


def _cosine_sim(text1: str, text2: str) -> float:
    """简易语义相似度（基于词袋，无需加载 BGE 模型）"""
    import re
    words1 = set(re.findall(r'[一-鿿]+|[a-zA-Z]+', text1.lower()))
    words2 = set(re.findall(r'[一-鿿]+|[a-zA-Z]+', text2.lower()))
    if not words1 or not words2:
        return 0.0
    intersection = words1 & words2
    return len(intersection) / ((len(words1) * len(words2)) ** 0.5)


def check_dedup(title: str, summary: str, tags: list[str]) -> dict | None:
    """
    检查是否与已有 #hot-30d 快照重复。
    返回: None（无重复）或 {"file": "路径", "sim": 0.92}（建议合并）
    """
    existing = load_all(hot_only=False)
    best = None
    best_sim = 0.0

    for m in existing:
        sim = _cosine_sim(summary + title, m["summary"] + m["title"])
        if sim > best_sim:
            best_sim = sim
            best = m

    if best_sim > 0.85 and best:
        return {"file": best["file"], "sim": round(best_sim, 3)}
    return None


def write(title: str, summary: str, tags: list[str],
          conclusion: str = "", decisions: str = "",
          constraints: str = "", issues: str = "") -> str:
    """
    写入记忆快照。返回文件路径。
    """
    os.makedirs(MEMORY_DIR, exist_ok=True)

    # 文件名: YYYY-MM-DD-{tag}-{slug}.md
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

    # 增量入库
    from ..incremental import main as incremental_main
    import subprocess
    subprocess.run([sys.executable, "-m", "vaultrag.incremental"],
                   cwd=os.path.dirname(os.path.dirname(__file__)),
                   capture_output=True)

    return fpath


def merge(existing_file: str, title: str, summary: str, decisions: str = "",
          constraints: str = "", issues: str = ""):
    """合并到已有快照：新内容替换正文，旧结论移入历史区域"""
    fpath = os.path.join(VAULT_DIR, existing_file)
    if not os.path.exists(fpath):
        return write(title, summary, [], "", decisions, constraints, issues)

    with open(fpath, "r", encoding="utf-8") as f:
        old = f.read()

    date = datetime.date.today().isoformat()

    # 追加历史版本
    history_block = f"""

## 📜 历史版本

<details>
<summary>{date} 更新前</summary>

{old.split('##')[1] if '##' in old else old}

</details>
"""

    # 重建正文
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
    subprocess.run([sys.executable, "-m", "vaultrag.incremental"],
                   cwd=os.path.dirname(os.path.dirname(__file__)),
                   capture_output=True)

    return fpath


def main():
    import argparse
    p = argparse.ArgumentParser(description="记忆快照写入")
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
