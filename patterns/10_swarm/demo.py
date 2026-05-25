"""Swarm Pattern デモ - 製品設計コンセンサス。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from agent import root_agent
from shared.demo_runner import run_demo

if __name__ == "__main__":
    print("=" * 60)
    print("Lv.10 Swarm - 専門家コンセンサス（全員が対等に議論）")
    print("=" * 60)
    print("市場・技術・財務の3専門家が議論してコンセンサスを形成します")
    print()
    run_demo(root_agent, "product_design_swarm", [
        "design_proposal: AI を活用したコード自動レビューツールの製品設計について議論してください"
    ])
