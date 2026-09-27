import json
import sys
from pathlib import Path

import pytest
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))
load_dotenv(Path(__file__).parent.parent / ".env")

from eval.hash_utils import compute_code_hash

RESULTS_PATH = Path(__file__).parent.parent / "eval" / "results.json"


@pytest.fixture(scope="session")
def eval_results():
    if not RESULTS_PATH.exists():
        pytest.skip(
            "找不到 eval/results.json。請先執行 bash scripts/run_eval.sh 產生評估結果。"
        )
    return json.loads(RESULTS_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="session", autouse=True)
def validate_eval_freshness(eval_results):
    stored_hash = eval_results.get("code_hash")
    if stored_hash is None:
        pytest.exit(
            "\n⚠️  results.json 沒有 code_hash（舊版格式）\n"
            "請重新執行：bash scripts/run_eval.sh\n",
            returncode=1,
        )
    if compute_code_hash() != stored_hash:
        pytest.exit(
            "\n⚠️  核心邏輯已更動，但 eval/results.json 尚未更新！\n"
            "請執行：bash scripts/run_eval.sh\n"
            "然後：git add eval/results.json && git commit\n",
            returncode=1,
        )
