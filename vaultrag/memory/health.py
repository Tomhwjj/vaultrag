"""
健康度监控 — 记录记忆系统运行指标到 #mem-meta 文件。
每周运行一次。
"""
import os
import sys
import datetime
import json

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from config import DOC_DIR as VAULT_DIR
from memory_load import load as load_all


def main():
    today = datetime.date.today().isoformat()
    memories = load_all(hot_only=False)

    stats = {
        "date": today,
        "total_files": len(memories),
        "by_type": {},
        "by_age": {},
    }

    for m in memories:
        for tag in m["tags"]:
            if tag.startswith("mem-"):
                stats["by_type"][tag] = stats["by_type"].get(tag, 0) + 1
            if tag in ("hot-30d", "warm-90d", "cold-arch", "mem-deprecated"):
                stats["by_age"][tag] = stats["by_age"].get(tag, 0) + 1

    # 写入 #mem-meta 文件
    meta_dir = os.path.join(VAULT_DIR, "记忆")
    os.makedirs(meta_dir, exist_ok=True)
    meta_file = os.path.join(meta_dir, "_health-report.md")

    content = f"""---
tags: [mem-meta]
date: {today}
---

# 记忆系统健康报告 — {today}

## 概览
- 总记忆数: {stats['total_files']}

## 类型分布
{json.dumps(stats['by_type'], ensure_ascii=False, indent=2)}

## 时效分布
{json.dumps(stats['by_age'], ensure_ascii=False, indent=2)}
"""

    with open(meta_file, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"[Health] {today} — {stats['total_files']} 条记忆 (hot:{stats['by_age'].get('hot-30d',0)} warm:{stats['by_age'].get('warm-90d',0)} cold:{stats['by_age'].get('cold-arch',0)})")

    # 告警检查
    alerts = []
    hot = stats['by_age'].get('hot-30d', 0)
    deprecated = stats['by_age'].get('mem-deprecated', 0)
    cold = stats['by_age'].get('cold-arch', 0)
    total = stats['total_files']

    if hot == 0 and total > 0:
        alerts.append("⚠️  热记忆=0，下次启动将空载，建议检查是否有待确认的 /digest 草稿")
    if total > 0 and deprecated / total > 0.3:
        alerts.append(f"⚠️  废弃记忆占比 {deprecated/total*100:.0f}%，超过 30% 建议人工清理")
    if cold > 50:
        alerts.append(f"⚠️  冷归档记忆 {cold} 条，未召回超过1年的建议标记为 deprecated")
    if total == 0:
        alerts.append("💡 记忆库为空，首次使用建议用 /digest 建立初始记忆")

    if alerts:
        print("\n[告警]")
        for a in alerts:
            print(f"  {a}")
    else:
        print("  ✅ 无异常")


if __name__ == "__main__":
    main()
