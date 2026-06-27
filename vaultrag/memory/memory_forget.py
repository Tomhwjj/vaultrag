"""
/forget — 主动标记记忆为废弃。
用法: python memory_forget.py --file "记忆/xxx.md"
"""
import os, sys, re

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from config import DOC_DIR as VAULT_DIR


def forget(rel_path: str) -> str:
    fpath = os.path.join(VAULT_DIR, rel_path)
    if not os.path.exists(fpath):
        return f"文件不存在: {fpath}"

    with open(fpath, "r", encoding="utf-8") as f:
        content = f.read()

    # tags 里加 mem-obsolete，去 hot/warm/cold
    content = re.sub(r'hot-30d|warm-90d|cold-arch', '', content)
    content = re.sub(
        r'(tags:\s*\[)', r'\1mem-obsolete, ',
        content, count=1
    )
    # 清理多余逗号
    content = re.sub(r',\s*,', ',', content)
    content = re.sub(r'\[,\s*', '[', content)

    with open(fpath, "w", encoding="utf-8") as f:
        f.write(content)

    # 增量入库
    import subprocess
    kb_dir = os.path.dirname(os.path.abspath(__file__))
    subprocess.run([sys.executable, os.path.join(kb_dir, "incremental_ingest.py")],
                   capture_output=True)
    return f"已标记为废弃: {rel_path}"


def main():
    import argparse
    p = argparse.ArgumentParser(description="/forget 废弃记忆")
    p.add_argument("--file", required=True, help="vault 相对路径")
    args = p.parse_args()
    print(forget(args.file))


if __name__ == "__main__":
    main()
