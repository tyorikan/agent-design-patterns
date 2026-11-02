"""PROD-06: Context Compaction & Budget Guard パターン デモスクリプト。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from production_patterns.prod06_context_compaction_budget.agent import (
    calculate_cache_break_even_calls,
    estimate_cumulative_input_tokens,
    root_agent,
)
from shared.demo_runner import run_demo


def main() -> None:
    inline_20_turns = estimate_cumulative_input_tokens(
        turns=20,
        system_tokens=2_000,
        turn_tokens=500,
        inline_tool_tokens=8_000,
    )
    offloaded_20_turns = estimate_cumulative_input_tokens(
        turns=20,
        system_tokens=2_000,
        turn_tokens=500,
        inline_tool_tokens=200,
    )
    k_min = calculate_cache_break_even_calls(
        input_price_per_1m=0.75,
        cached_price_per_1m=0.075,
        storage_price_per_1m_hour=1.00,
        ttl_hours=1.0,
    )
    print(f"20 ターン累積入力トークン (インライン時): {inline_20_turns:,} tokens")
    print(f"20 ターン累積入力トークン (Artifact 退避時): {offloaded_20_turns:,} tokens")
    print(f"明示的キャッシュ 1 時間保持時の損益分岐呼び出し回数: K >= {k_min}")

    run_demo(
        agent=root_agent,
        app_name="prod06_context_compaction_budget",
        queries=["checkout-api の直近ログを取得し、エラー原因を特定してください。"],
    )


if __name__ == "__main__":
    main()
