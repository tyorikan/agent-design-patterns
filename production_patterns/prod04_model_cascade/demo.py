"""PROD-04: Model Cascade パターン デモスクリプト。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from production_patterns.prod04_model_cascade.agent import (
    evaluate_cascade_economics,
    rogan_gladen_estimate,
    root_agent,
)
from shared.demo_runner import run_demo


def main() -> None:
    theta_hat = rogan_gladen_estimate(
        observed_pass_rate=0.78,
        sensitivity_q1=0.92,
        specificity_q0=0.88,
    )
    econ = evaluate_cascade_economics(
        fast_cost_usd=0.0005,
        judge_cost_usd=0.0008,
        strong_cost_usd=0.0080,
        pre_gate_pass_rate=0.90,
        judge_observed_pass_rate=0.78,
        judge_q1=0.92,
        judge_q0=0.88,
        strong_solve_rate=0.96,
    )
    print(f"Rogan-Gladen 補正後の真の一次合格率: {theta_hat:.1%}")
    print(f"解決 1 件あたり実効コスト: ${econ.effective_cost_per_solved_task_usd:.5f}")
    run_demo(
        agent=root_agent,
        app_name="prod04_model_cascade",
        queries=["HTTP 429 レート制限エラーが発生した際の指数バックオフとジッターの実装手順を教えてください。"],
    )


if __name__ == "__main__":
    main()
