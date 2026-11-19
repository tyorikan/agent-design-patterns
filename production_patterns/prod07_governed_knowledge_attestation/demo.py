"""PROD-07: Governed Knowledge & Attested Computation パターン デモスクリプト。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from production_patterns.prod07_governed_knowledge_attestation.agent import (
    DEFAULT_BUNDLE_DIR,
    OkfBundle,
    app,
)
from shared.demo_runner import run_demo


def main() -> None:
    bundle = OkfBundle(DEFAULT_BUNDLE_DIR)
    print(f"OKF Bundle: {bundle.metadata.title} (v{bundle.metadata.okf_version})")
    print("─" * 72)
    for concept in bundle.iter_concepts():
        stale_label = "STALE" if concept.is_stale else "fresh"
        downgrade_note = " [最終変更後に未再検証]" if concept.verified_before_last_change else ""
        redirect_note = f" -> {concept.superseded_by}" if concept.superseded_by else ""
        print(
            f"  {concept.concept_id:<32} | {concept.trust_tier:<17} | "
            f"{concept.status:<10} | {stale_label}{downgrade_note}{redirect_note}"
        )
    print("─" * 72)

    run_demo(
        agent=app,
        app_name="prod07_governed_knowledge_attestation",
        queries=[
            "2026年度の認識売上 (Recognized Revenue) を承認済み計算で算出し、根拠と信頼ステータスを教えてください。",
            "2026年度の online セグメント粗利 (Gross Profit) を確認してください。定義の鮮度や信頼ティアに注意点があれば必ず教えてください。",
            "値引承認ルール (discount_approval) と旧マージン基準 (legacy_margin_policy) の現行扱いを教えてください。",
        ],
    )


if __name__ == "__main__":
    main()
