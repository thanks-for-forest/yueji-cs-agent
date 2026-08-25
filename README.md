# 悦己美妆智能客服 Agent（YUEJI CS Agent）

基于 **RAG + 工具调用 + 多 Agent 路由 + 情绪转人工** 的美妆电商智能客服系统，覆盖商品咨询、订单查询、退换货、护肤推荐四大场景。

> 📋 详细项目规划见 [`docs/项目规划_美妆电商客服Agent.md`](docs/项目规划_美妆电商客服Agent.md)

## ✨ 功能

| 场景 | 能力 | 技术 |
|------|------|------|
| 🛍️ 商品咨询 | 成分/功效/价格/用法问答，引用溯源，敏感人群提示 | RAG（Dense+BM25+RRF）+ 拒答协议 |
| 📦 订单查询 | 订单状态/商品/金额查询，多轮槽位追问 | Function Calling + 槽位状态机 + 双校验防越权 |
| 🔄 退换货 | 售后资格判定（规则引擎）、表单式多轮、生成工单 | 规则引擎 + 状态机 + 工单系统 |
| 💆 护肤推荐 | 肤质/肌肤问题/年龄标签匹配，Top3 + 搭配建议 | LLM 标签提取 + 标签打分 |
| 😡 情绪转人工 | 三级情绪检测，连续负面/愤怒自动转接并带摘要工单 | 情感词典 + 规则 + 会话级平滑 |

## 🏗️ 架构

```
Streamlit 前端 ⇄ FastAPI ⇄ 编排器(安全→情绪→路由→Agent) ⇄ DeepSeek API
                              │                    │
                          SQLite(会话/订单/工单)   RAG(Chroma索引 + BM25)
                              │                    │
                           记忆(窗口+摘要)      Ollama bge-m3 嵌入
```

**LangGraph StateGraph 编排（Supervisor-Worker）**：安全护栏 → 情绪检测 → 意图路由（Supervisor）→ 5 个 Worker Agent（商品咨询 / 订单查询 / 售后处理 / 护肤推荐 / 人工转接）→ 记忆回写；三级意图路由（规则→LLM）。

## 🚀 快速开始

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # 填入 DEEPSEEK_API_KEY

python -m scripts.gen_data       # 生成数据（产品/FAQ/政策）
python -m scripts.gen_orders     # 生成模拟订单
python -m scripts.ingest         # 知识库向量化（需 Ollama bge-m3）

python -m uvicorn src.api.main:app --port 8000 &   # 后端
streamlit run frontend/app.py                       # 前端 http://localhost:8501
```

自检：`python -m scripts.check_env`

## 🧪 评测

```bash
python -m pytest tests/ -q                  # 50 项单元测试（含 LangGraph/追踪测试）
python -m eval.evaluate                     # 100 条测试集双轨评测（走 LangGraph 路径）
python -m scripts.compare_retrieval         # 检索四策略对比 → docs/检索策略对比报告.md
python -m scripts.trace_report --html        # 自研可观测性报告 + HTML 看板
python -m scripts.stress_test --concurrency 50
```

**最终评测（100 条测试集，`eval/reports/20260824_201045_report.md`）**：

| 指标 | 结果 | 目标 |
|------|------|------|
| 问题解决率（LangGraph 路径） | **100%** (100/100) | ≥75% |
| 幻觉率 | **0%** | ≤5% |
| 转人工 P/R | **100% / 100%** | ≥85% / ≥90% |
| 情绪识别 | **100%** (30/30) | ≥80% |
| 检索 Recall@10 / MRR / NDCG@5 | **98.9% / 0.942 / 0.852**（dense_first 混合） | ≥85% / 0.7 / 0.75 |
| 中位 / P95 延迟 | **2.47s / 4.82s** | <3s / <8s |
| 流式 TTFT | **~2.0s** | <3s |
| 并发 50 | **100% 成功，无 5xx** | - |

## 📁 目录结构

```text
├── config/settings.py      # 集中配置
├── data/                   # 原始数据 / 数据库 / 索引
├── scripts/                # gen_data / gen_orders / ingest / check_env / stress_test
├── src/
│   ├── api/                # FastAPI
│   ├── agents/             # 编排器 + 5 个专项 Agent + 意图路由
│   ├── rag/                # 混合检索 + 向量库
│   ├── tools/              # 订单/售后/产品工具 + 注册表
│   ├── memory/  emotion/  session/  llm/  utils/
├── frontend/app.py         # Streamlit 界面
├── eval/                   # 测试集 + 评测脚本 + 报告
├── tests/                  # pytest 单测
└── docs/                   # 规划 / 部署手册 / 开发笔记
```

## 🛡️ 安全设计

- Prompt 注入检测（规则 + 关键词）、敏感内容拦截
- 订单查询强制「订单号 + 手机尾号」双校验（防越权）
- PII 脱敏（日志/工单手机号打码）
- 会话级限流（20 req/min）

## 📊 技术栈

Python 3.14 · **LangGraph(Supervisor-Worker)** · FastAPI · Streamlit · DeepSeek API · Ollama(bge-m3) · rank-bm25 · SQLite · **自研 JSONL 追踪器 + Langfuse(可选)** · pytest

## 📄 文档

- [项目规划（独一份·环境定制版）](docs/项目规划_美妆电商客服Agent.md)
- [部署手册](docs/部署手册.md)
- [开发笔记（决策记录/调优）](docs/开发笔记.md)
