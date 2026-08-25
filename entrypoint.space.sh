#!/bin/bash
# HF Spaces 入口：拉起 Ollama → 初始化数据 → FastAPI(:8000) → Streamlit(:8501) → Caddy(:7860)
set -e

echo "== [1/5] 启动 Ollama =="
ollama serve &
OLLAMA_PID=$!
for i in $(seq 1 30); do
  curl -s http://127.0.0.1:11434/api/tags >/dev/null 2>&1 && break
  sleep 1
done
echo "== [2/5] 拉取嵌入模型 bge-m3（首次较慢）=="
ollama pull bge-m3

echo "== [3/5] 初始化数据（缺则生成）=="
cd /app
[ -f data/raw/products.json ] || python -m scripts.gen_data
[ -f data/db/yueji.db ] || python -m scripts.gen_orders
[ -f data/processed/chunks.json ] || python -m scripts.ingest

echo "== [4/5] 启动 FastAPI（内部 :8000）与 Streamlit（内部 :8501）=="
python -m uvicorn src.api.main:app --host 0.0.0.0 --port 8000 &
API_PID=$!
streamlit run frontend/app.py --server.address 0.0.0.0 --server.port 8501 \
  --server.headless true --browser.gatherUsageStats false &
WEB_PID=$!

echo "== [5/5] 启动 Caddy 同源代理（对外 :7860）=="
caddy run --config /Caddyfile.space --adapter caddyfile &
CADDY_PID=$!

trap "kill $OLLAMA_PID $API_PID $WEB_PID $CADDY_PID 2>/dev/null" EXIT
wait
