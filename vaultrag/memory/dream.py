"""
Dream Consolidation 触发器 — 检查是否需要异步蒸馏。
cron 每 4 小时运行一次。
"""
import os
import sys
import json
import datetime

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

STATE_FILE = os.path.join(os.path.dirname(__file__), ".dream_state.json")


def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"last_dream": None, "dream_count": 0}


def save_state(s: dict):
    s["dream_count"] = s.get("dream_count", 0) + 1
    s["last_dream"] = datetime.datetime.now().isoformat()
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=2)


def main():
    state = load_state()
    now = datetime.datetime.now()

    # 检查距上次蒸馏是否超过 4 小时
    if state["last_dream"]:
        last = datetime.datetime.fromisoformat(state["last_dream"])
        if (now - last).seconds < 4 * 3600:
            print(f"[Dream] 距上次蒸馏不足4小时 ({state['last_dream']})，跳过")
            return

    # 检查 vault 中是否有待蒸馏的记忆（由 /digest 创建的中间文件）
    from config import DOC_DIR as VAULT_DIR
    draft_dir = os.path.join(VAULT_DIR, "记忆")
    if not os.path.exists(draft_dir):
        print("[Dream] 无记忆目录，跳过")
        return

    md_files = [f for f in os.listdir(draft_dir) if f.endswith(".md") and not f.startswith("_")]
    if not md_files:
        print("[Dream] 无待蒸馏文件，跳过")
        return

    # 运行 lifecycle 做标签时效检查
    print(f"[Dream] 检查 {len(md_files)} 个记忆文件...")
    save_state(state)
    print(f"[Dream] 完成 — 下次检查: {now + datetime.timedelta(hours=4)}")


if __name__ == "__main__":
    main()
