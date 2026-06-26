"""
记忆生命周期管理 — hot→warm→cold→deprecate 自动升降级。
cron 每日运行一次。
"""
import os
import sys
import datetime
import json
import re

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from ..config import VAULT_DIR


def _parse_frontmatter(content: str) -> dict | None:
    if not content.startswith("---"):
        return None
    end = content.find("---", 3)
    if end == -1:
        return None
    fm = {}
    for line in content[3:end].strip().split("\n"):
        if ":" in line:
            k, v = line.split(":", 1)
            v = v.strip().strip('"').strip("'")
            if v.startswith("[") and v.endswith("]"):
                v = [t.strip().strip('"').strip("'") for t in v[1:-1].split(",")]
            fm[k.strip()] = v
    return fm


def _update_frontmatter(content: str, new_tags: list[str]) -> str:
    """替换 tags 行"""
    tags_str = ", ".join(new_tags)
    return re.sub(
        r'(tags:\s*).*',
        f'\\1[{tags_str}]',
        content,
        count=1,
    )


def main():
    today = datetime.date.today()
    changes = []

    for root, dirs, files in os.walk(VAULT_DIR):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for f in files:
            if not f.endswith(".md"):
                continue
            fp = os.path.join(root, f)
            try:
                with open(fp, "r", encoding="utf-8") as fh:
                    content = fh.read()
            except Exception:
                continue

            fm = _parse_frontmatter(content)
            if not fm or "tags" not in fm or "date" not in fm:
                continue

            tags = fm["tags"] if isinstance(fm["tags"], list) else [fm["tags"]]
            try:
                file_date = datetime.date.fromisoformat(fm["date"])
            except ValueError:
                continue

            age = (today - file_date).days
            new_tags = list(tags)
            action = None

            # 降温
            if "hot-30d" in new_tags and age > 30:
                new_tags.remove("hot-30d")
                new_tags.append("warm-90d")
                action = "hot→warm"
            elif "warm-90d" in new_tags and age > 90:
                new_tags.remove("warm-90d")
                new_tags.append("cold-arch")
                action = "warm→cold"

            if action:
                new_content = _update_frontmatter(content, new_tags)
                with open(fp, "w", encoding="utf-8") as fh:
                    fh.write(new_content)
                rel = os.path.relpath(fp, VAULT_DIR)
                changes.append(f"{action}: {rel}")

    if changes:
        print(f"[Lifecycle] {today} — {len(changes)} 变更:")
        for c in changes:
            print(f"  {c}")
    else:
        print(f"[Lifecycle] {today} — 无变更")


if __name__ == "__main__":
    main()
