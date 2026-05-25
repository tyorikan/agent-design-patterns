"""Hierarchical Pattern デモ - 競合分析レポート。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from agent import root_agent
from shared.demo_runner import run_demo

if __name__ == "__main__":
    print("=" * 60)
    print("Lv.9 Hierarchical - 競合分析レポート（3層アーキテクチャ）")
    print("=" * 60)
    print("Root → Research/Analysis Coordinators → Worker Agents の3層構造")
    print()
    run_demo(root_agent, "competitive_analysis_root", [
        "analysis_target: Microsoft Azure の競合分析をしてください"
    ])
