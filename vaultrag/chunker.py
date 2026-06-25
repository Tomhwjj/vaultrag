"""
递归语义分块器 — 在段落/句子边界断开，保留语义完整性。

优先级: 段落 → 换行 → 句号 → 分号 → 逗号 → 硬切
"""
from .config import CHUNK_SIZE, CHUNK_OVERLAP, SEPARATORS


def chunk(text: str,
          chunk_size: int = CHUNK_SIZE,
          chunk_overlap: int = CHUNK_OVERLAP,
          separators: list[str] | None = None) -> list[str]:
    """递归语义分块"""
    if separators is None:
        separators = SEPARATORS
    if not text or not text.strip():
        return []
    if len(text) <= chunk_size:
        return [text]

    sep = ""
    for candidate in separators:
        if candidate in text:
            sep = candidate
            break

    if not sep:
        chunks = []
        start = 0
        while start < len(text):
            chunks.append(text[start:start + chunk_size])
            start += chunk_size - chunk_overlap
        return chunks

    splits = text.split(sep)
    splits = [s + sep for s in splits[:-1]] + [splits[-1:][0]]
    chunks = []
    current = ""

    for split in splits:
        if not split.strip():
            if current:
                current += split
            continue
        if len(current) + len(split) <= chunk_size:
            current += split
        else:
            if current.strip():
                if len(current) >= chunk_size // 2:
                    chunks.append(current)
                    current = split
                else:
                    current += split
            else:
                current = split
        while len(current) > chunk_size:
            next_seps = separators[separators.index(sep) + 1:] if sep in separators else [""]
            sub = chunk(current, chunk_size, chunk_overlap, next_seps)
            if len(sub) > 1:
                chunks.extend(sub[:-1])
                current = sub[-1]
            else:
                chunks.append(current[:chunk_size])
                current = current[chunk_size - chunk_overlap:]
                break

    if current.strip():
        chunks.append(current)
    return chunks
