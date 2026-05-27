# noqa: D104
import sys
from pathlib import Path

# adk run で実行時、shared パッケージを解決するためプロジェクトルートを追加
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
