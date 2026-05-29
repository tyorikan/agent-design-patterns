"""Iterative Refinement Pattern デモ - 技術ドキュメント自己改善。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from agent import root_agent
from shared.demo_runner import run_demo

if __name__ == "__main__":
    print("=" * 60)
    print("Lv.7 Iterative Refinement - 自己スコアで品質改善")
    print("=" * 60)
    print("スコア 85/100 に達するまで自己改善を繰り返します（最大5回）")
    print()
    run_demo(root_agent, "doc_refinement_loop", ["doc_topic: Pub/Sub を使ったイベント駆動アーキテクチャ"])
