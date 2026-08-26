"""测试夹具：确保数据/索引存在（不存在则现场生成）+ 离线 LLM mock。"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import settings  # noqa: E402


def _ollama_alive() -> bool:
    """探测本地 Ollama 是否可用（短超时）。"""
    try:
        import httpx

        r = httpx.get(f"{settings.OLLAMA_BASE_URL}/api/tags", timeout=2)
        return r.status_code == 200
    except Exception:  # noqa: BLE001
        return False


@pytest.fixture(scope="session", autouse=True)
def ensure_data():
    """保证 products/faq/policies/orders/索引 就绪（Ollama 不可用时跳过向量索引生成）。"""
    settings.ensure_dirs()
    if not (settings.RAW_DATA_DIR / "products.json").exists():
        import scripts.gen_data  # noqa: F401

        scripts.gen_data.main()
    if not (settings.PROCESSED_DATA_DIR / "chunks.json").exists():
        if _ollama_alive():
            import subprocess

            subprocess.run([sys.executable, "-m", "scripts.ingest"], cwd=ROOT, check=True)
        else:
            print("[conftest] Ollama 不可用，跳过索引生成（离线模式，检索类集成测试将被跳过）")
    # 订单库
    if not settings.DB_PATH.exists():
        subprocess.run([sys.executable, "-m", "scripts.gen_orders"], cwd=ROOT, check=True)
    yield


@pytest.fixture(autouse=True)
def mock_llm(request):
    """非 integration 测试注入 FakeLLM，保证离线可跑（CI 无 DeepSeek/Ollama）。"""
    if request.node.get_closest_marker("integration"):
        yield  # 集成测试使用真实 LLM
        return
    import src.llm.client as lc
    from tests.fake_llm import FakeLLM

    lc._llm = FakeLLM()
    yield
    lc._llm = None
