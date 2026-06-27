---
name: vaultrag
description: VaultRAG — 三路检索融合 + Claude Code 长久记忆。搜索知识库、写记忆快照、蒸馏对话。
---

# VaultRAG — 三路检索融合 + 长久记忆

## 检索

```bash
# 推荐日常使用 --fast (50ms 极速, RRF融合)
python -m vaultrag.query "<query>" --fast

# 最高精度 (CrossEncoder精排, ~6s)
python -m vaultrag.query "<query>"
```

查询加速依赖常驻服务 `kb_server`，启动后模型常驻内存 + 评分缓存：
```bash
python kb_server.ps1 start          # 启动服务 (首次 ~20s 加载)
python kb_server.ps1 status         # 查看状态
python kb_server.ps1 stop           # 停止服务
```
query.py 自动检测 server，在线走 HTTP 毫秒查询，离线回退本地加载。

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
