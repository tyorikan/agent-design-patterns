"""PROD-02: Idempotent Tool & Approval Gate パターン デモスクリプト。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from production_patterns.prod02_idempotent_approval_gate.agent import root_agent
from shared.demo_runner import run_demo


def main() -> None:
    """少額クレジット発行（自動承認）の動作確認デモ。"""
    run_demo(
        agent=root_agent,
        app_name="prod02_idempotent_approval_gate",
        queries=["注文番号 ORD-4021 に対して配送遅延のお詫びとして 45 USD のクレジットを発行してください。"],
    )


if __name__ == "__main__":
    main()
