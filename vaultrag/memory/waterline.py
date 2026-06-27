"""
水位检查 — tiktoken 精确计算，输出明确指令。
Claude 只管执行，不用猜 token。

用法:
  python waterline.py                          # 会话启动（对话=0）
  python waterline.py --conversation-chars 8000  # 会话中（估算对话量）
"""
import sys, os

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from memory_load import load as load_memories

WINDOW = 200_000          # Claude Opus
MEMORY_MAX = 0.30         # 记忆占 30%
CONVERSATION_KEEP = 0.50  # 预留 50% 给当前对话
THRESHOLD = 0.70          # 总占用超 70% 切模式


def count_tokens(text: str) -> int:
    """tiktoken 精确计数"""
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except ImportError:
        # 回退：中英混合分别估算（中文 ~1.8 token/字, 英文 ~0.25 token/字）
        import re
        cn = len(re.findall(r'[一-鿿　-〿＀-￯]', text))
        en_chars = len(re.findall(r'[a-zA-Z0-9]', text))
        other = len(text) - cn - en_chars
        return int(cn * 1.8 + en_chars * 0.25 + other * 0.5)


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--conversation-chars", type=int, default=0,
                   help="当前对话已用字符数（会话中检查时传入）")
    args = p.parse_args()

    # 记忆 token
    memories = load_memories(hot_only=True)
    mem_text = "\n".join(m["content"] for m in memories)
    mem_tokens = count_tokens(mem_text)

    # 对话 token（如果传了）
    conv_tokens = count_tokens("x" * args.conversation_chars) if args.conversation_chars else 0

    total = mem_tokens + conv_tokens
    budget = int(WINDOW * MEMORY_MAX)
    threshold = int(WINDOW * THRESHOLD)

    print(f"记忆: {len(memories)} 篇, {mem_tokens} token ({mem_tokens/WINDOW*100:.1f}%)")
    if conv_tokens:
        print(f"对话: ~{conv_tokens} token ({conv_tokens/WINDOW*100:.1f}%)")
    print(f"总占用: {total/WINDOW*100:.1f}%  (阈值: {THRESHOLD*100:.0f}%)")

    if total > threshold:
        print(f"\n[RAG_MODE] 超水位 → 卸快照, 用 query.py 按需检索")
    elif total > budget:
        print(f"\n[WARNING] 记忆近上限 → 可加载全文, 注意后续对话长度")
    else:
        print(f"\n[FULL_LOAD] 安全 → memory_load.py --full")


if __name__ == "__main__":
    main()
