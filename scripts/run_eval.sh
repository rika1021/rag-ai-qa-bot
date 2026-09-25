#!/bin/bash
# 在 Docker container 裡執行 eval，並把結果複製回本地
# 使用方式：bash scripts/run_eval.sh

set -e

echo "安裝 eval 依賴..."
docker compose exec api pip install -q -r requirements-eval.txt

echo "執行 eval..."
docker compose exec api python eval/run_eval.py

echo "複製 results.json 回本地..."
docker compose cp api:/app/eval/results.json eval/results.json

echo ""
echo "完成！記得 git add eval/results.json 並 commit。"
