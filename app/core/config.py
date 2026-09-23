from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    anthropic_api_key: str

    base_dir: Path = Path(__file__).parent.parent.parent
    data_dir: Path = base_dir / "data" / "documents"
    chroma_dir: Path = base_dir / "chroma_db"

    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    claude_model: str = "claude-haiku-4-5-20251001"

    chunk_size: int = 500
    chunk_overlap: int = 50
    retrieval_top_k: int = 5
    similarity_threshold: float = 0.30

    class Config:
        env_file = ".env"


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
settings.chroma_dir.mkdir(parents=True, exist_ok=True)
