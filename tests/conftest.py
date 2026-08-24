"""测试夹具：确保数据/索引存在（不存在则现场生成）。"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import settings  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def ensure_data():
    """保证 products/faq/policies/orders/索引 就绪。"""
    settings.ensure_dirs()
    if not (settings.RAW_DATA_DIR / "products.json").exists():
        import scripts.gen_data  # noqa: F401

        scripts.gen_data.main()
    if not (settings.RAW_DATA_DIR / "policies.json").exists():
        import scripts.gen_data

        scripts.gen_data.main()
    if not (settings.PROCESSED_DATA_DIR / "chunks.json").exists():
        import subprocess

        subprocess.run([sys.executable, "-m", "scripts.ingest"], cwd=ROOT, check=True)
    # 订单库
    if not settings.DB_PATH.exists():
        subprocess.run([sys.executable, "-m", "scripts.gen_orders"], cwd=ROOT, check=True)
    yield
