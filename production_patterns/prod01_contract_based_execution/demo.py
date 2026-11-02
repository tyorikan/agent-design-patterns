"""PROD-01: Contract-Based Execution パターン デモスクリプト。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from production_patterns.prod01_contract_based_execution.agent import root_agent
from shared.demo_runner import run_demo


def main() -> None:
    """許容上限（40 レプリカ）を超過する要求チケットを入力し、制約内に収束させるデモ。"""
    sample_ticket = json.dumps(
        {
            "ticket_id": "CHG-202601",
            "service_name": "checkout-api",
            "requested_replicas": 60,
            "environment": "prod",
        },
        ensure_ascii=False,
    )
    run_demo(
        agent=root_agent,
        app_name="prod01_contract_based_execution",
        queries=[sample_ticket],
    )


if __name__ == "__main__":
    main()
