# VaultRAG — 三路检索融合 + Claude Code 长久记忆

**基于 RAG 和 Obsidian 知识库的 Claude Code 长久记忆实现框架。**

Obsidian vault 即知识库和记忆系统。零导入、零同步、零复制、全离线。

---

## 为什么

Claude Code 每次新会话都从零开始。VaultRAG 让它拥有跨会话的持久记忆——启动时自动加载你的历史决策、编码规范、踩坑记录，对话中随时蒸馏新知识写入 vault，下次会话自动延续。

## 核心能力

```
🔍 三路检索      向量(BGE) + BM25(jieba) + 图谱([[wikilinks]])
                 → RRF 融合 → Cross-Encoder 精排
                 关键词自动增强 (正则+TF-IDF+TextRank, LLM兜底)
                 时间衰减 (30天半衰期)

🧠 长久记忆      标签分级: #mem-decision / #mem-rule / #mem-issue / #mem-task
                 时效分层: #hot-30d (启动加载) / #warm-90d (被动召回) / #cold-arch (归档)
                 生命周期: hot → warm → cold → deprecated 自动升降级
                 BGE 语义去重 (0.9阈值) + 写入前冲突检测

⚡ 水位判断      tiktoken 精算 token 占用
                 FULL_LOAD (≤70%窗口) / RAG_MODE (>70%窗口) 自动切换

🏠 全离线        BGE 模型嵌入项目，零 API 费用，零云依赖
```

---

## 架构

```
┌────────────────────────────────────────────────┐
│ L1: CLAUDE.md 指令                              │
│ 启动水位 → 记忆加载 → /digest → /compact        │
│ Claude 自身推理，不调外部脚本                     │
├────────────────────────────────────────────────┤
│ L2: Python 脚本                                 │
│ waterline / memory_load / memory_digest /       │
│ query / incremental_ingest / lifecycle / health │
├────────────────────────────────────────────────┤
│ L3: 系统定时任务                                │
│ lifecycle(日) / health(周) / analytics(月)      │
│ Stop Hook 会话结束自动蒸馏草稿                   │
└────────────────────────────────────────────────┘
```

---

## 快速开始

```bash
pip install -e .
export VAULTRAG_VAULT="/path/to/obsidian/vault"
python -m vaultrag.ingest          # 首次建索引
python -m vaultrag.query "搜索"     # 检索
python -m vaultrag.memory.load --list   # 记忆概览
python -m vaultrag.incremental      # 增量入库
```

## 记忆工作流

```
会话启动:
  waterline.py → FULL_LOAD / RAG_MODE
  memory_load.py → 加载 #hot-30d 记忆全文

对话中:
  /digest → BGE去重 → 写入 vault → 增量入库
  /digest --inject → 蒸馏 + 注入上下文 (释放token)
  /forget → 标记 #mem-obsolete 永不召回

会话结束:
  Stop Hook → 自动蒸馏草稿
```

## 记忆快照格式

```markdown
---
tags: [mem-decision, hot-30d]
date: 2026-06-27
summary: 一句话结论
---

# 标题
## 📌 结论
## 🧭 决策
## 🔒 约束
## 🐛 问题
## 📎 来源
```

文件名: `{date}-{tag}-{slug}.md`，存放 vault `/记忆/`。

---

## 检索管线

```
query
  ├─ 关键词增强 (正则+TF-IDF+TextRank, ≤2词→LLM兜底)
  ├─ 三路并行:
  │   ├─ BGE Embedding → ChromaDB 向量
  │   ├─ jieba → BM25Okapi 关键词
  │   └─ [[wikilinks]] + 共现词 → 图谱扩展
  ├─ RRF 融合 (k=60, 权重自适应)
  ├─ Cross-Encoder Reranker 精排
  └─ 时间衰减 e^(-0.023×天数), 30天半衰期
```

---

## 标签体系

内容标签:

| 标签 | 用途 | 优先级 |
|------|------|:--:|
| #mem-decision | 技术决策、方案选型、架构约定 | 最高 |
| #mem-rule | 编码规范、约束、禁止项 | 高 |
| #mem-issue | 历史 Bug、坑点、排障方案 | 中 |
| #mem-task | 待办、当前进度 | 低 |

时效标签:

| 标签 | 含义 | 加载策略 |
|------|------|------|
| #hot-30d | 近30天 | 启动全文加载 |
| #warm-90d | 30-90天 | 被动RAG召回 |
| #cold-arch | >90天 | 永不主动加载 |
| #mem-deprecated | 已废弃 | 永不参与检索 |

---

## 12 条设计落地

| # | 条款 | 实现 |
|:--:|------|------|
| 1 | 标签体系 | frontmatter tags |
| 2 | 快照模板 | memory_digest.py |
| 3 | 上下文调度 | waterline.py + CLAUDE.md |
| 4 | 运行三阶段 | 启动→水位→动态切换 |
| 5 | /digest + /compact | BGE 0.9去重 + 在线压缩 |
| 6 | /digest --inject | 蒸馏+注入上下文 |
| 7 | 生命周期 | lifecycle.py + 定时任务 |
| 8 | RAG查询改写 | query.py 内置关键词增强 |
| 9 | 冲突处理 | 当前指令优先 + 显式标注 |
| 10 | 去重合并 | BGE 语义相似度 > 0.9 |
| 11 | 降级保护 | 三层 fallback |
| 12 | 健康监控 | health.py + 告警阈值 |

## DeepSeek 评估后的 11 项改进

| 优先级 | 数量 | 状态 |
|:--:|:--:|:--:|
| P0 (当天) | 4项 | ✅ 水印精度 + 健康告警 + /forget + 冷启动引导 |
| P1 (本周) | 5项 | ✅ 共现词图谱 + 冲突检测 + RRF权重 + 延迟加载 + 时间衰减 |
| P2 (长期) | 2项 | ⏳ 数值KV索引 + inject位置 |

## 自动优化闭环

```
query.py 每次检索 → 静默记日志
    ↓ 每月
query_analytics.py → 统计三路贡献度
    ↓ 样本 ≥100
自动更新 RRF_WEIGHTS → 下次检索生效
```

---

## 文件结构

```
vaultrag/
├── vaultrag/
│   ├── config.py              统一配置
│   ├── query.py                三路检索 + 关键词 + 日志 + 时间衰减
│   ├── ingest.py               全量入库
│   ├── incremental.py          增量入库 + 图谱重建
│   ├── graph.py                Wikilink + 共现词图谱
│   ├── chunker.py              递归语义分块
│   ├── pdf.py                  PDF 表格解析
│   ├── query_analytics.py      月度分析 + 自动调参
│   └── memory/
│       ├── load.py             启动记忆加载
│       ├── digest.py           BGE去重 + 冲突检测 + 写入
│       ├── forget.py           /forget 废弃标记
│       ├── waterline.py        tiktoken 水位判断
│       ├── lifecycle.py        标签升降级
│       ├── health.py           健康监控 + 告警
│       └── dream.py            Dream 触发
├── skills/vaultrag.md          Claude Code skill
├── examples/demo.py            演示
└── README.md
```

---

## 技术栈

| 层 | 组件 |
|------|------|
| Embedding | BAAI/bge-base-zh-v1.5 |
| Reranker | BAAI/bge-reranker-base |
| 向量库 | ChromaDB |
| 分词 | jieba + BM25Okapi |
| 图谱 | [[wikilinks]] + 共现词 |
| PDF | pdfplumber + PyMuPDF |
| 分块 | 递归语义 (段落→句子→字符) |
| 水位 | tiktoken cl100k_base / 中英混合估算 |

## 依赖

```
chromadb, sentence-transformers, jieba, rank-bm25
pdfplumber, PyMuPDF (可选)
```

## License

MIT
