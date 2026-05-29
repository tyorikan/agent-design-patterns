"""ReAct Pattern デモ - Thought/Action/Observation ループの可視化。"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from agent import run_with_react_trace

DEMO_QUERY = (
    "Cloud Run と GKE のどちらを選ぶべきか、コストと運用の観点から比較分析してください。"
    "月間 100 万リクエスト、平均レスポンス 200ms を想定した場合のコスト試算も含めてください。"
)

if __name__ == "__main__":
    print("=" * 60)
    print("Lv.2 ReAct Pattern - Thought/Action/Observation 可視化")
    print("=" * 60)
    print("エージェントの内部思考プロセスをステップごとに表示します")
    print()
    asyncio.run(run_with_react_trace(DEMO_QUERY))
