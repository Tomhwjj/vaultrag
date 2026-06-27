"""
启动记忆加载器 — Claude Code 每次会话开始时调用。
扫描 vault 中 #hot-30d + #mem-rule + #mem-decision 文件，按优先级排序。
"""
import os
import sys
import json

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from config import DOC_DIR as VAULT_DIR


def _parse_frontmatter(content: str) -> dict | None:
    """提取 YAML frontmatter"""
    if not content.startswith("---"):
        return None
    end = content.find("---", 3)
    if end == -1:
        return None
    fm = {}
    for line in content[3:end].strip().split("\n"):
        line = line.strip()
        if ":" in line:
            k, v = line.split(":", 1)
            v = v.strip().strip('"').strip("'")
            # tags 列表: [tag1, tag2]
            if v.startswith("[") and v.endswith("]"):
                v = [t.strip().strip('"').strip("'") for t in v[1:-1].split(",")]
            fm[k.strip()] = v
    return fm


def _priority(tags: list[str]) -> int:
    """排序优先级: mem-rule(0) > mem-decision(1) > mem-issue(2) > mem-task(3)"""
    if "mem-rule" in tags:
        return 0
    if "mem-decision" in tags:
        return 1
    if "mem-issue" in tags:
        return 2
    if "mem-task" in tags:
        return 3
    return 4


def load(hot_only: bool = True) -> list[dict]:
    """
    扫描 vault，返回需加载的记忆列表。
    hot_only=True: 只返回 #hot-30d 快照
    hot_only=False: 返回所有记忆文件（用于 /digest 去重检查）
    """
    memories = []

    for root, dirs, files in os.walk(VAULT_DIR):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for f in files:
            if not f.endswith(".md"):
                continue
            fp = os.path.join(root, f)
            rel = os.path.relpath(fp, VAULT_DIR)
            try:
                with open(fp, "r", encoding="utf-8", errors="replace") as fh:
                    content = fh.read()
            except Exception:
                continue

            fm = _parse_frontmatter(content)
            if not fm or "tags" not in fm:
                continue

            tags = fm["tags"] if isinstance(fm["tags"], list) else [fm["tags"]]
            date = fm.get("date", "unknown")
            summary = fm.get("summary", "")

            if hot_only and "hot-30d" not in tags:
                continue

            memories.append({
                "file": rel,
                "title": os.path.splitext(f)[0],
                "tags": tags,
                "date": date,
                "summary": summary,
                "priority": _priority(tags),
                "chars": len(content),
                "content": content,
            })

    memories.sort(key=lambda m: (m["priority"], m["date"]), reverse=False)
    return memories


def load_for_context(max_chars: int = 45000) -> str:
    """
    Claude Code 启动时调用: 返回组装好的记忆文本。
    max_chars: 记忆文本最大字符数（默认 45K 字符 ≈ 60K token 的 30%）
    """
    memories = load(hot_only=True)
    parts = []
    total = 0

    for m in memories:
        text = f"## [{m['title']}]\n{m['content']}\n"
        if total + len(text) > max_chars:
            # 超限时只加 summary
            text = f"## [{m['title']}] (摘要) {m['summary']}\n"
            if total + len(text) > max_chars:
                continue
        parts.append(text)
        total += len(text)

    header = "## 🧠 长期记忆（来自 Obsidian vault）\n\n"
    return header + "\n".join(parts) if parts else ""


def list_memories() -> str:
    """列出记忆概览（标题+摘要），用于快速展示"""
    memories = load(hot_only=True)
    lines = []
    for m in memories:
        lines.append(f"- [{m['date']}] [{','.join(m['tags'])}] {m['title']}: {m['summary']}")
    return "\n".join(lines) if lines else "(无记忆快照)"


def main():
    import argparse
    p = argparse.ArgumentParser(description="记忆加载器")
    p.add_argument("--list", action="store_true", help="列出记忆概览")
    p.add_argument("--full", action="store_true", help="输出完整上下文文本")
    p.add_argument("--json", action="store_true", help="JSON 格式输出")
    args = p.parse_args()

    if args.json:
        memories = load(hot_only=True)
        out = [{"file": m["file"], "tags": m["tags"], "date": m["date"],
                "summary": m["summary"], "chars": m["chars"]} for m in memories]
        print(json.dumps(out, ensure_ascii=False, indent=2))
    elif args.list:
        print(list_memories())
    elif args.full:
        print(load_for_context())
    else:
        # 默认输出：概览
        print(list_memories())


if __name__ == "__main__":
    main()
