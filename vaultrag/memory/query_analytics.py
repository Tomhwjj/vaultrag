"""
查询分析 — 从日志中统计三路检索的贡献度，指导 RRF 权重调参。

用法:
  python query_analytics.py                     # 全量统计
  python query_analytics.py --days 30           # 最近30天
  python query_analytics.py --top 3             # 只看 Top 3 结果
"""
import os, sys, json

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

LOG_FILE = os.path.join(os.path.dirname(__file__), ".query_log.jsonl")


def load_logs(days: int = None) -> list[dict]:
    if not os.path.exists(LOG_FILE):
        return []
    entries = []
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        for line in f:
            try:
                e = json.loads(line)
                entries.append(e)
            except:
                pass
    if days:
        import datetime
        cutoff = datetime.datetime.now() - datetime.timedelta(days=days)
        entries = [e for e in entries
                   if datetime.datetime.fromisoformat(e["ts"]) > cutoff]
    return entries


def main():
    import argparse
    p = argparse.ArgumentParser(description="三路检索贡献度分析")
    p.add_argument("--days", type=int, default=0, help="最近N天（0=全部）")
    p.add_argument("--top", type=int, default=5, help="统计 Top N 结果")
    args = p.parse_args()

    entries = load_logs(days=args.days if args.days > 0 else None)
    if not entries:
        print("暂无查询日志。跑几次 query.py 后再分析。")
        return

    # 统计每路贡献
    path_hits = {"vector": 0, "bm25": 0, "graph": 0}
    path_top1 = {"vector": 0, "bm25": 0, "graph": 0}
    path_combos = {}  # "vector+bm25" → count
    total_results = 0
    total_queries = len(entries)

    for e in entries:
        for r in e["results"][:args.top]:
            total_results += 1
            paths = r["paths"]
            for p in paths:
                if p in path_hits:
                    path_hits[p] += 1
            # Top-1 贡献
            if r["rank"] == 1:
                for p in paths:
                    if p in path_top1:
                        path_top1[p] += 1
            # 组合
            combo = "+".join(sorted(paths)) if paths else "none"
            path_combos[combo] = path_combos.get(combo, 0) + 1

    print(f"分析范围: {total_queries} 次查询, 最近{args.days or '全部'}天")
    print(f"统计 Top-{args.top} 结果, 共 {total_results} 条\n")

    print("=== 各路命中率 (Top-{}) ===".format(args.top))
    for name, count in sorted(path_hits.items(), key=lambda x: x[1], reverse=True):
        pct = count / total_results * 100
        bar = "█" * int(pct / 2)
        print(f"  {name:8s}: {pct:5.1f}% ({count}/{total_results}) {bar}")

    print("\n=== Top-1 来源 ===")
    for name, count in sorted(path_top1.items(), key=lambda x: x[1], reverse=True):
        pct = count / total_queries * 100 if total_queries else 0
        print(f"  {name:8s}: {count}/{total_queries} ({pct:.0f}% 的查询首条命中)")

    print("\n=== 路径组合 (Top-{}) ===".format(args.top))
    for combo, count in sorted(path_combos.items(), key=lambda x: x[1], reverse=True)[:10]:
        pct = count / total_results * 100
        print(f"  {combo:20s}: {pct:5.1f}% ({count})")

    # 权重建议
    print("\n=== RRF 权重建议 ===")
    total = sum(path_hits.values()) or 1
    suggested = {k: round(v / total * 3, 2) for k, v in path_hits.items()}
    print(f"  归一化权重: vector={suggested['vector']:.2f}, bm25={suggested['bm25']:.2f}, graph={suggested['graph']:.2f}")
    print(f"  解读: 数值越高，该路在最终结果中贡献越大，RRF 时应给予更高权重")
    print(f"  使用: rrf_fusion(vector, bm25, graph, weights=[{suggested['vector']:.1f}, {suggested['bm25']:.1f}, {suggested['graph']:.1f}])")
    print(f"\n  ⚠️  积累 100+ 次查询后再调参，小样本不具统计意义")

    # ── 输出报告到 vault ──
    report_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "Obsidian store", "记忆", "_query-analytics-report.md",
    )
    # 尝试从 config 拿 vault 路径
    try:
        from config import DOC_DIR as vault
        report_path = os.path.join(vault, "记忆", "_query-analytics-report.md")
    except:
        pass

    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(f"---\ntags: [mem-meta]\ndate: {__import__('datetime').date.today().isoformat()}\n---\n\n")
        f.write(f"# 查询分析报告 — {__import__('datetime').date.today().isoformat()}\n\n")
        f.write(f"- 查询次数: {total_queries}\n")
        f.write(f"- 分析范围: Top-{args.top}\n\n")
        f.write("## 各路命中率\n\n")
        for name, count in sorted(path_hits.items(), key=lambda x: x[1], reverse=True):
            pct = count / total_results * 100 if total_results else 0
            f.write(f"- {name}: {pct:.1f}% ({count}/{total_results})\n")
        f.write(f"\n## RRF 权重建议\n\n")
        f.write(f"- vector={suggested['vector']:.2f}, bm25={suggested['bm25']:.2f}, graph={suggested['graph']:.2f}\n")
        f.write(f"- 样本: {total_queries} 次\n")
        f.write(f"- {'✅ 样本充足，可应用' if total_queries >= 100 else '⚠️ 样本不足，建议积累100+次后再应用'}\n")
    print(f"\n📄 报告已写入: {report_path}")

    return suggested, total_queries


if __name__ == "__main__":
    suggested, n = main()
    # 自动应用（仅当样本充足）
    if n >= 100:
        config_path = os.path.join(os.path.dirname(__file__), "config.py")
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = f.read()
        # 添加权重配置（如果不存则）
        weight_line = f"\n# 自动生成 — RRF 权重 (基于 {n} 次查询分析)\nRRF_WEIGHTS = [{suggested['vector']:.1f}, {suggested['bm25']:.1f}, {suggested['graph']:.1f}]\n"
        if "RRF_WEIGHTS" not in cfg:
            with open(config_path, "a", encoding="utf-8") as f:
                f.write(weight_line)
            print(f"⚡ 已自动应用 RRF 权重到 config.py: RRF_WEIGHTS = [{suggested['vector']:.1f}, {suggested['bm25']:.1f}, {suggested['graph']:.1f}]")
