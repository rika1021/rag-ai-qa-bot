from pathlib import Path
from dotenv import load_dotenv

# 在所有 test 跑之前先載入 .env，確保 ANTHROPIC_API_KEY 可用
load_dotenv(Path(__file__).parent.parent / ".env")
