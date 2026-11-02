"""Review & Critique Pattern デモ - ブログ記事品質チェック。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from patterns.p06_review_critique.agent import root_agent
from shared.demo_runner import run_demo

if __name__ == "__main__":
    print("=" * 60)
    print("Lv.6 Review & Critique - ブログ記事 Generator/Critic")
    print("=" * 60)
    print("Generator と Critic が品質 80 点以上になるまでループします（最大4回）")
    print()
    run_demo(
        root_agent,
        "blog_review_loop",
        ["Spanner のスケーラビリティについて技術ブログを書いてください"],
    )
