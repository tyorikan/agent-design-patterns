"""Capstone デモ - エンタープライズリサーチエージェント。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from agent import root_agent
from shared.demo_runner import run_demo

if __name__ == "__main__":
    print("=" * 70)
    print("🏆 Capstone: Enterprise Research Agent")
    print("   全デザインパターン統合デモ")
    print("=" * 70)
    print()
    print("使用するパターン:")
    print("  🎯 Coordinator  - ユーザーリクエスト解釈・委譲")
    print("  🔄 Sequential   - データ収集 → 分析 → レポート")
    print("  ⚡ Parallel     - 3チームが同時並行でデータ収集")
    print("  🔁 Loop         - 品質85点まで自動改善（最大3回）")
    print("  ✅ Review/Critique - 厳格な品質チェック")
    print()
    print("分析対象: Salesforce")
    print("-" * 70)
    print()

    run_demo(
        agent=root_agent,
        app_name="enterprise_research_coordinator",
        queries=["Salesforce の企業技術戦略を分析して、投資判断レポートを作成してください"],
    )
