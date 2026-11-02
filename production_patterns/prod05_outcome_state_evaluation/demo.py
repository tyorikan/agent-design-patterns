"""PROD-05: Outcome State Evaluation パターン デモスクリプト。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from production_patterns.prod05_outcome_state_evaluation.agent import (
    evaluate_pass_hat_k_gate,
)


def main() -> None:
    sample_runs = {
        "address_change_unshipped": [True, True, True, True, True],
        "refund_policy_boundary": [True, True, True, True, False],  # 5回中4回成功 (80%)
    }
    decision = evaluate_pass_hat_k_gate(
        sample_runs,
        k=3,
        default_min_pass_hat_k=0.80,
        critical_case_ids={"refund_policy_boundary"},
    )
    print(f"Gate Passed: {decision.passed}")
    for m in decision.case_metrics:
        print(
            f"  {m.eval_id}: pass_rate={m.pass_rate:.2f}, "
            f"Pass@3={m.pass_at_k:.3f}, pass^3={m.pass_hat_k:.3f}"
        )
    for reason in decision.blocking_reasons:
        print(f"  BLOCKED: {reason}")


if __name__ == "__main__":
    main()
