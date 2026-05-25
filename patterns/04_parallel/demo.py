"""Parallel Pattern デモ - マルチソース AI ニュース集約。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from agent import root_agent
from shared.demo_runner import run_demo

if __name__ == "__main__":
    print("=" * 60)
    print("Lv.4 Parallel Pattern - マルチソースニュース集約")
    print("=" * 60)
    print("4つのリサーチエージェントが【同時並行】で実行されます:")
    print("  ⚡ Google AI Researcher")
    print("  ⚡ OpenAI Researcher")
    print("  ⚡ Regulation Researcher")
    print("  ⚡ Industry Researcher")
    print("  → Synthesizer が統合レポートを作成")
    print()

    run_demo(
        agent=root_agent,
        app_name="news_aggregator",
        queries=["AI 技術の最新トレンドについて調査してください"],
    )
