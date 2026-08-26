# Dify 知识库能力对照与补强清单

> 目标：**保留自研 RAG 主链路**，以 Dify 知识库能力为基准逐项对照，把缺失能力补进自研管理后台。
> 依据：Dify 官方文档《指定分段设置》([cloud](https://docs.dify.ai/zh/cloud/use-dify/knowledge/create-knowledge/chunking-and-cleaning-text) / [self-host](https://docs.dify.ai/en/self-host/use-dify/knowledge/create-knowledge/chunking-and-cleaning-text))、[向量数据库配置](https://enterprise-docs.dify.ai/zh/3.8.x/deploy/advanced-configuration/vector-database)、[Dify 源码 VectorType](https://github.com/langgenius/dify/blob/59dc7c88/api/core/rag/datasource/vdb/vector_type.py)。
> 更新：2026-08-26（本轮补强后）

## 结论摘要

- Dify 是 RAG 应用平台，其知识库管理界面只管理**它自己索引的数据**，无法读写本项目自研的 `data/processed/vector_index.npz`（numpy 文件）体系。
- 本项目采用「自研 RAG 主链路 + 借鉴 Dify 能力清单补强」路线：本轮按清单补齐 8 项能力（批量上传/多格式/分块策略可视化/索引健康/导出/多模式命中测试/检索统计/批量删除/重新分块）。
- 未采纳项（OCR、父子分段、数据源同步、多知识库）记录理由与后续可选实现，见文末。

## 逐项对照表

| # | Dify 能力 | 自研现状（补强前） | 本轮补强 | 状态 |
|---|---|---|---|---|
| 1 | 多格式文档导入（txt/md/pdf/docx/html/xlsx/csv/pptx/OCR/音频） | md/markdown/txt/docx/pdf | +csv、+xlsx（openpyxl）、+html（lxml）；ppt/OCR/音频未做（轻量自研取舍） | ✅ 部分 |
| 2 | 分段设置可视化（chunk size / overlap / 分隔符 / 父子分段 / Q&A 模式） | 固定 400/60（代码常量） | +管理后台「分块策略」面板（100–1000 / 0–200 滑杆）；上传与重新分块共用；后端 `_resolve_chunk_params` 收敛非法值 | ✅ |
| 3 | 检索测试（命中测试：TopK 可调、分数展示） | 有（TopK + 余弦分数） | +模式对照：dense_first（主链路）/ rrf / dense（纯向量）/ bm25（纯关键词）；三路分数（dense/bm25/fusion）同屏展示；阈值说明（余弦 0.55 / RRF 0.02） | ✅ |
| 4 | 检索日志 / 命中率统计 | 无 | +`kb_query_log` 表：每次命中测试落库（query/mode/top_k/hit_count/top_score），后台「检索历史统计」展示平均命中率、高频测试问题、最近记录 | ✅ |
| 5 | 文档管理（状态/筛选/批量操作/删除） | 状态筛选 + 批量审核/回滚 + 单个删除 | +批量删除（`/api/kb/docs/batch-delete`）、历史区批量清理 | ✅ |
| 6 | 知识库统计（文档数/块数/分布） | 有（统计面板） | +索引健康检查（npz/chunks.json/meta.json 三方一致、基础库 vs KB 组成、最后重建时间）+ 一键强制重建 | ✅ |
| 7 | 数据导出 | 无 | +`/api/kb/export`：json（结构化全量）与 md（人类可读）两种格式，后台一键下载 | ✅ |
| 8 | 分类管理 | 自由文本分类 | +预置分类（KB_CATEGORIES 可配）+ 后台下拉选择 + `/api/kb/categories` 并集接口 | ✅ |
| 9 | 分块编辑后重切 | 单块编辑（重向量化） | +「按当前策略重新分块」：存 raw_text，按新 chunk_size/overlap 重切 + 全量重向量化，已入库自动重建索引 | ✅ |
| 10 | 向量库后端可选（Qdrant/Milvus/pgvector/…） | numpy 文件向量库（bge-m3 1024 维） | 保持自研（面试亮点、零外部依赖）；如需可平滑替换 VectorStore 实现 | ⏸ 保持 |
| 11 | Rerank 模型 | LLM 重排（RERANK_ENABLED 可开） | 保持（已文档化 ADR） | ⏸ 保持 |
| 12 | 数据源同步（Notion/网站/定时） | 无 | 未纳入本轮；后续可做「watch 目录定时入库」脚本 | 🔲 候选 |
| 13 | 父子分段（Parent-Child） | 无 | 未纳入本轮；后续可在 chunk_text 之上加 parent/child 两级索引 | 🔲 候选 |
| 14 | OCR / 图片 / 音频解析 | 无 | 未纳入本轮（本地无 OCR 引擎）；可接 PaddleOCR 或云 OCR | 🔲 候选 |
| 15 | 多知识库 / 成员权限 | 单库 + 管理员令牌 + 操作人审计 | 单库满足当前规模；多库需改 chunk meta 加 kb_id 字段 | 🔲 候选 |
| 16 | 上传后自动向量化 vs 手动审核 | 审核后生效（安全） | 保持（审计留痕是自研亮点） | ⏸ 保持 |

## 本轮改动文件

| 文件 | 改动 |
|---|---|
| `config/settings.py` | +KB_CHUNK_SIZE / KB_CHUNK_OVERLAP / KB_PRESET_CATEGORIES |
| `src/kb/parser.py` | +csv / xlsx / html 解析 |
| `src/rag/retriever.py` | hybrid_search/retrieve_context 支持 mode 覆盖；+bm25_search / +dense_search |
| `src/kb/service.py` | +raw_text 列与 kb_query_log 表；批量上传（一次 embed 全部块）；重新分块；导出 json/md；索引健康；强制重建；检索统计；批量删除；分类清单；命中测试模式化 |
| `src/api/main.py` | +/api/kb/upload-batch、/export、/index-status、/rebuild、/query-stats、/categories、/docs/batch-delete、/docs/{id}/rechunk；upload 增加 chunk_size/overlap；query-test 增加 mode（**修复**：category/chunk_size 等 form 字段此前因未用 Form() 声明而未被 FastAPI 接收的既有 bug） |
| `frontend/admin_app.py` | +索引健康卡片（含强制重建/导出）、分块策略面板、多文件批量上传+分类下拉、多模式命中测试+阈值说明、检索历史统计、分块显示全部开关、按策略重新分块、历史区批量删除 |
| `tests/test_kb.py` | +csv/xlsx/html 解析、分块策略参数、重分块+索引健康、命中测试模式+导出（service 级） |
| `tests/test_kb_admin.py` | +新端点集成测试（见下文） |

## 验证

- pytest：**69 通过**（原 64 + 新增 5 service 级 + 集成）
- 100 条评测回归：见 `eval/reports/` 最新报告
- 冒烟实测：批量上传（md/csv/html）→ 分块策略 180/25 生效 → 分类落库 → 4 种检索模式对照 → 索引健康全绿 → 导出 json/md → 重新分块 → 批量删除，全部通过

## 待办候选（后续轮次，按价值排序）

1. **watch 目录定时入库**（Dify 数据源同步的轻量版）：`scripts/kb_watch.py` 监控指定目录，新文件自动解析入库为待审核。
2. **父子分段**：chunk_text 输出 child 块 + 保留 parent 摘要块，检索命中 child 回 parent 上下文。
3. ~~**检索评测内置**~~ ✅ 已落地（2026-08-26）：`scripts/gen_retrieval_pairs.py` 自动派生 267 条检索对，管理后台「检索评估报表」一键跑四模式 recall@3/recall@5/延迟对比。
4. **PPTX 解析**：python-pptx 逐页取文本。
