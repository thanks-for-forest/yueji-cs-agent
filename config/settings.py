"""集中配置：从 .env 加载，所有模块从这里读参数。"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# ---------- LLM（主：DeepSeek；备：Ollama） ----------
DEEPSEEK_API_KEY: str = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL: str = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL: str = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
OLLAMA_CHAT_MODEL: str = os.getenv("OLLAMA_CHAT_MODEL", "qwen2.5:1.5b")  # DeepSeek 失败时兜底

# ---------- Embedding / Rerank ----------
EMBED_PROVIDER: str = os.getenv("EMBED_PROVIDER", "ollama")  # ollama | deepseek(n/a) | api
EMBED_MODEL: str = os.getenv("EMBED_MODEL", "bge-m3")
EMBED_DIM: int = int(os.getenv("EMBED_DIM", "1024"))

RERANK_ENABLED: bool = os.getenv("RERANK_ENABLED", "false").lower() == "true"
RERANK_MODEL: str = os.getenv("RERANK_MODEL", "qwen2.5:1.5b")  # LLM 重排（无本地 reranker 时）

# ---------- 检索参数 ----------
RETRIEVE_DENSE_TOP_K: int = int(os.getenv("RETRIEVE_DENSE_TOP_K", "20"))
RETRIEVE_BM25_TOP_K: int = int(os.getenv("RETRIEVE_BM25_TOP_K", "20"))
RETRIEVE_FUSION_TOP_K: int = int(os.getenv("RETRIEVE_FUSION_TOP_K", "15"))
RETRIEVE_RERANK_TOP_K: int = int(os.getenv("RETRIEVE_RERANK_TOP_K", "5"))
RETRIEVE_RRF_K: int = int(os.getenv("RETRIEVE_RRF_K", "60"))
# RRF 融合分阈值：最大约 2/61≈0.033（两个列表都排第一）。0.02≈"至少在单一列表排进前19"，
# 用于区分"有一定依据"与"无可信答案"。低于阈值的查询走澄清/拒答流程。
RETRIEVE_MIN_SCORE: float = float(os.getenv("RETRIEVE_MIN_SCORE", "0.02"))

# ---------- Agent / 对话 ----------
MAX_TOOL_ITERS: int = int(os.getenv("MAX_TOOL_ITERS", "3"))
MEMORY_WINDOW: int = int(os.getenv("MEMORY_WINDOW", "10"))  # 短期窗口轮数
SUMMARY_THRESHOLD: int = int(os.getenv("SUMMARY_THRESHOLD", "20"))  # 超过该轮数启用摘要
MAX_SESSION_TURNS: int = int(os.getenv("MAX_SESSION_TURNS", "200"))
TEMPERATURE: float = float(os.getenv("TEMPERATURE", "0.3"))
MAX_TOKENS: int = int(os.getenv("MAX_TOKENS", "1024"))

# ---------- 情绪 ----------
EMOTION_NEGATIVE_WORDS = [
    "差评", "垃圾", "骗", "骗子", "投诉", "曝光", "315", "失望", "气死",
    "退钱", "退款！", "再也不买", "拉黑", "垃圾产品", "欺诈", "坑人", "离谱",
    "恶心", "太过分", "投诉到底", "媒体", "律师", "起诉", "维权",
    # 常见不满表达
    "太慢", "很慢", "好慢", "烦", "烦躁", "生气", "不满", "假货", "刺痛",
    "过敏", "不好用", "没用", "没效果", "质量差", "真差", "很差", "太坑",
    "糟心", "无语", "等太久", "着急", "气人",
]
EMOTION_STRONG_PUNCT = ["！！", "？？", "!!!", "？？？", "！！！"]
EMOTION_TRANSFER_KW = ["投诉", "315", "曝光", "律师", "媒体", "起诉", "维权", "人工"]

# ---------- 服务 ----------
API_HOST: str = os.getenv("API_HOST", "0.0.0.0")
API_PORT: int = int(os.getenv("API_PORT", "8000"))
WEB_PORT: int = int(os.getenv("WEB_PORT", "8501"))
RATE_LIMIT_PER_MIN: int = int(os.getenv("RATE_LIMIT_PER_MIN", "20"))

# ---------- 路径 ----------
DATA_DIR = BASE_DIR / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
PROCESSED_DATA_DIR = DATA_DIR / "processed"
DB_DIR = DATA_DIR / "db"
DB_PATH = DB_DIR / "yueji.db"
VECTOR_INDEX_PATH = PROCESSED_DATA_DIR / "vector_index.npz"
CHUNKS_META_PATH = PROCESSED_DATA_DIR / "chunks_meta.json"
EVAL_DIR = BASE_DIR / "eval"
REPORTS_DIR = EVAL_DIR / "reports"

BRAND_NAME = "悦己 YUEJI"
AGENT_NAME = "小悦"


def ensure_dirs() -> None:
    for d in (DATA_DIR, RAW_DATA_DIR, PROCESSED_DATA_DIR, DB_DIR, EVAL_DIR, REPORTS_DIR):
        d.mkdir(parents=True, exist_ok=True)
