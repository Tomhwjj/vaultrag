---
name: vaultrag
description: VaultRAG — 三路检索融合 + Claude Code 长久记忆。搜索知识库、写记忆快照、蒸馏对话。
---

# VaultRAG — 三路检索融合 + 长久记忆

## 检索

```bash
python -m vaultrag.query "<query>"
```

## 记忆

```bash
# 查看当前记忆
python -m vaultrag.memory.load --list

# 加载上下文
python -m vaultrag.memory.load --full

# 蒸馏对话为记忆
python -m vaultrag.memory.digest --write --title "..." --summary "..." --conclusion "..." --decisions "..."
```

## 索引

```bash
python -m vaultrag.ingest          # 全量（首次）
python -m vaultrag.incremental      # 增量（日常）
```

## 维护

```bash
python -m vaultrag.memory.lifecycle  # 标签升降级
python -m vaultrag.memory.health     # 健康报告
```

## 前置

```bash
export VAULTRAG_VAULT="D:\Agent\Obsidian store"
```
