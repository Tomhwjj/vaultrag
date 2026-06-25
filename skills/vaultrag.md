---
name: vaultrag
description: VaultRAG — 三路检索融合的本地 RAG 引擎。当用户说"搜一下 XX"、"知识库里有关于 XX 的吗"、"检索 XX"时触发。
---

# VaultRAG Skill

## 用法

搜索 vault:

```bash
python -m vaultrag.query "<query>"
```

新增笔记后增量入库:

```bash
python -m vaultrag.incremental
```

首次或重建:

```bash
python -m vaultrag.ingest
```

## 前置

确保设置 vault 路径:

```bash
export VAULTRAG_VAULT="D:\Agent\Obsidian store"
```
