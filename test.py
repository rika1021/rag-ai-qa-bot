import os
os.environ["ANONYMIZED_TELEMETRY"] = "False"
from app.core.vectorstore import get_collection

col = get_collection()  # 呼叫函式，取得 ChromaDB collection 物件

result = col.get(limit=1, include=['embeddings', 'documents'])

print('文字：', result['documents'][0][:50])
print('向量前10個數字：', result['embeddings'][0][:10])

