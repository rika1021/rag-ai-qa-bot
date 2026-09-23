FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 預先下載 embedding model，避免 container 啟動時才下載（約 100MB）
# fastembed 在第一次呼叫時才從網路下載 model，若不在 build 階段處理，
# 每次 container 冷啟動都要重新下載，CI 或受限網路環境中會直接失敗
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2')"

COPY . .
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
