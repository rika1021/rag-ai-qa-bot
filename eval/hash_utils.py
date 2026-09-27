import hashlib
from pathlib import Path

EVAL_RELEVANT_FILES = [
    "app/core/rag/retrieval.py",
    "app/core/rag/generator.py",
    "app/core/rag/ingestion.py",
    "app/core/vectorstore.py",
    "app/core/config.py",
    "requirements.txt",
    "eval/test_data.json",
]


def compute_code_hash() -> str:
    h = hashlib.sha256()
    root = Path(__file__).parent.parent
    for path in sorted(EVAL_RELEVANT_FILES):
        h.update((root / path).read_bytes())
    return h.hexdigest()
