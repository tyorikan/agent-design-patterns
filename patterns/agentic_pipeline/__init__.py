# noqa: D104
import logging
import sys
from pathlib import Path

# adk run で実行時、shared パッケージを解決するためプロジェクトルートを追加
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


# ---------------------------------------------------------------------------
# Logging Filter: Antigravity SDK のノイジーなログを抑制
# ---------------------------------------------------------------------------
# ADK CLI の log_to_tmp_folder() が root logger に FileHandler を設定する。
# Antigravity SDK (local_connection.py) が root logger に RAW WS MSG を
# 大量出力するため、ログの 90%+ がノイズになる。
# このフィルタで以下を抑制:
#   - RAW WS MSG (Antigravity WebSocket 生メッセージ)
#   - Policy approved tool (ツール承認ログ)
#   - harness stderr (プロセス stderr)
# ---------------------------------------------------------------------------
class _QuietAntigravityFilter(logging.Filter):
    """Antigravity SDK の冗長ログを抑制する。"""

    _NOISY_PATTERNS = (
        "RAW WS MSG:",
        "Policy '",
        "harness stderr:",
        "WebSocket closed",
    )

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return not any(pattern in msg for pattern in self._NOISY_PATTERNS)


# root logger に filter を適用（ADK の FileHandler にも効く）
logging.getLogger().addFilter(_QuietAntigravityFilter())
