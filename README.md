# VaultRAG — 三路检索融合 + Claude Code 长久记忆（基于RAG和obsidian知识库，而构建的claude code长久记忆实现框架）

**Vault-native AI memory stack.** Obsidian vault 即知识库和记忆系统 —— 零导入、零同步、零复制。

- 🔍 **三路检索**: 向量(BGE) + BM25(jieba) + 图谱([[wikilinks]]) → RRF 融合 → Cross-Encoder 精排
- 🧠 **长久记忆**: 标签分级 (#mem-decision/#mem-rule/#mem-issue/#mem-task × hot/warm/cold) → 跨会话上下文延续
- 🏠 **全离线**: BGE 模型嵌入项目，零 API 费用，零云依赖
- 📓 **Vault-native**: 直接读写 Obsidian vault，写笔记即入库

## 架构总览

```
┌──────────────────────────────────────────────┐
│  Layer 1: CLAUDE.md 指令                     │
│  启动加载 / 水位判断 / 检索改写 / /digest     │
│  靠 Claude 自身推理执行                       │
├──────────────────────────────────────────────┤
│  Layer 2: Python 脚本                        │
│  memory_load / memory_digest / lifecycle /   │
│  query / incremental_ingest / graph_index    │
│  Claude 通过 Bash 调用，复用现有 RAG 管线      │
├──────────────────────────────────────────────┤
│  Layer 3: 后台定时任务                        │
│  生命周期升降级 / 健康监控 / Dream 触发        │
│  独立于 Claude Code，系统计划任务              │
└──────────────────────────────────────────────┘
```

---

## 快速开始

```bash
# 安装
pip install -e .

# 设置 vault 路径
export VAULTRAG_VAULT="/path/to/obsidian/vault"

# 首次建索引
python -m vaultrag.ingest

# 搜索
python -m vaultrag.query "搜索内容"

# 记忆加载
python -m vaultrag.memory.load --list
python -m vaultrag.memory.load --full

# 蒸馏对话为记忆
python -m vaultrag.memory.digest --write --title "..." --summary "..." --conclusion "..."
```

---

## 记忆标签体系

一级标签（内容类型）：

| 标签 | 用途 | 优先级 |
|------|------|:--:|
| #mem-decision | 技术决策、方案选型、架构约定 | 最高 |
| #mem-rule | 编码规范、约束、禁止项 | 高 |
| #mem-issue | 历史 Bug、坑点、排障方案 | 中 |
| #mem-task | 待办、当前进度 | 低 |

二级标签（时效分级）：

| 标签 | 含义 | 加载策略 |
|------|------|------|
| #hot-30d | 近 30 天热记忆 | 启动时全文加载 |
| #warm-90d | 中期记录 | 匹配主题时召回 |
| #cold-arch | 归档历史 | 仅被动 RAG 检索 |

---

## 记忆快照模板

```markdown
---
tags: [mem-decision, hot-30d]
date: 2026-06-26
summary: 一句话结论
---

# 标题

## 📌 结论
<一句话总结>

## 🧭 决策
- 选择 A 而非 B，原因: ...

## 🔒 约束
- 必须遵守 / 禁止 ...

## 🐛 问题
- 现象 → 根因 → 解决

## 📎 来源
- 对话日期: 2026-06-26
```

文件名: `{YYYY-MM-DD}-{tag}-{slug}.md`，存放 vault `/记忆/` 目录。

---

## 上下文调度（核心引擎）

```
总上下文 = A + B + C

A = 实时对话（50-60%）
B = 结构化记忆快照（匹配主题的全文）
C = RAG 召回 Top-N 片段（替代大量快照文本）
```

水位判断：

```
总占用 ≤ 窗口 70% → 全文加载模式：#hot 快照插入 Prompt
总占用 > 窗口 70% → RAG 模式：向量检索 Top 6-8 片段
```

Token 预算（Opus 200K）：

```
System: ~5% │ 记忆快照: ≤30% │ 当前对话: 50-55% │ 缓冲: 10-15%
≈60K token / 45,000 中文字符 / 22 篇标准快照
```

Prompt 排布顺序（优先级固定）：

```
[System: 全局铁律]
[记忆快照 / RAG 片段: 约束与参考]
[当前对话 + 用户指令: 优先级最高]
```

记忆优先级：**新指令 > 本轮对话 > 近期历史 > 久远归档**

---

## 记忆生命周期

```
升温: cold-arch 被 RAG 召回 ≥3 次/月 → warm-90d
降温: hot-30d 超 30 天 → warm-90d → 超 90 天 → cold-arch
废弃: cold-arch 超 1 年且 0 召回 → #mem-deprecated
```

---

## 文件清单

```
vaultrag/
├── vaultrag/
│   ├── query.py              三路检索（向量+BM25+图谱 → RRF → Reranker）
│   ├── ingest.py              全量入库（首次/换模型）
│   ├── incremental.py         增量入库（日常，秒级）
│   ├── graph.py               Wikilink 图谱构建
│   ├── chunker.py             递归语义分块
│   ├── pdf.py                 PDF 表格解析
│   ├── config.py              统一配置
│   └── memory/
│       ├── load.py            启动记忆加载
│       ├── digest.py          去重检查 + 模板写入
│       ├── lifecycle.py       标签升降级
│       ├── dream.py           Dream Consolidation 触发
│       └── health.py          健康度监控
├── skills/vaultrag.md         Claude Code skill
├── examples/demo.py           演示脚本
└── README.md
```

---

## 冲突处理

RAG 片段与当前指令冲突时，当前指令优先，回复显式标注：

```
⚠️ 与历史记忆冲突: {简述冲突内容}，已按当前指令执行。
```

---

## 降级保护

| 异常 | 策略 |
|------|------|
| vault/向量库不可达 | 丢弃 B+C，仅保留 A |
| RAG 返回 0 条 | 不注入记忆片段 |
| Token 超限 | 从旧到新硬截断，保留 System + 最后 3 轮 |

---

## 技术栈

| 层 | 组件 |
|------|------|
| Embedding | `BAAI/bge-base-zh-v1.5` |
| Reranker | `BAAI/bge-reranker-base` |
| 向量库 | ChromaDB (嵌入式) |
| 分词 | jieba + BM25Okapi |
| 图谱 | `[[wikilinks]]` 正则扫描 |
| PDF | pdfplumber + PyMuPDF |
| 分块 | 递归语义分块 (段落→句子→字符) |

## 依赖

```
chromadb, sentence-transformers, jieba, rank-bm25
pdfplumber, PyMuPDF (可选, PDF 支持)
```

## License

MIT
