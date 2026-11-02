"""CLI-02: Evaluation Gate パターン実装（FinOps コスト急増トリアージエージェント）。"""

from __future__ import annotations

import os
from typing import Any

from google.adk.agents import Agent
from google.adk.apps import App
from google.genai import types

os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "global")
os.environ.setdefault("GOOGLE_GENAI_USE_ENTERPRISE", "True")
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "True")

DEFAULT_MODEL = os.environ.get("DEFAULT_MODEL", "gemini-3.8-flash")

_ANOMALY_SNAPSHOTS: dict[str, dict[str, Any]] = {
    "bigquery": {
        "daily_baseline_usd": 120.0,
        "daily_actual_usd": 540.0,
        "spike_ratio": 4.5,
        "root_cause": "パーティションフィルタなしのフルスキャン集計クエリが 15 分周期バッチに追加された",
        "recommended_action": "パーティション列フィルタの必須化（require_partition_filter=true）と BI キャッシュ有効化",
        "typical_reduction_percent": 75.0,
    },
    "llm_inference": {
        "daily_baseline_usd": 80.0,
        "daily_actual_usd": 310.0,
        "spike_ratio": 3.88,
        "root_cause": "全ターンで 50KB のツール出力生データを履歴に再送しており、かつ全リクエストで thinking_level=HIGH が固定されていた",
        "recommended_action": "巨大なツール出力のアーティファクト退避と、定型分類への軽量モデル（gemini-3.5-flash-lite）カスケード導入",
        "typical_reduction_percent": 60.0,
    },
    "compute": {
        "daily_baseline_usd": 200.0,
        "daily_actual_usd": 360.0,
        "spike_ratio": 1.8,
        "root_cause": "負荷試験後に min-instances=20 の設定がステージング環境に残存していた",
        "recommended_action": "ステージング環境の min-instances を 0 に戻し、夜間自動縮退スケジュールを設定",
        "typical_reduction_percent": 45.0,
    },
}


def inspect_cost_spike(service_name: str) -> dict[str, Any]:
    """指定されたサービスカテゴリの直近コスト急増要因と推奨対策を取得する。

    Args:
        service_name: 調査対象カテゴリ。'bigquery', 'llm_inference', 'compute' のいずれか。

    Returns:
        コスト急増のベースライン・実績・原因・推奨対策を含む辞書。
    """
    key = service_name.strip().lower()
    if key not in _ANOMALY_SNAPSHOTS:
        return {
            "found": False,
            "supported_services": sorted(_ANOMALY_SNAPSHOTS.keys()),
            "hint": "supported_services のいずれかを指定してください。",
        }
    return {"found": True, "service": key, **_ANOMALY_SNAPSHOTS[key]}


def estimate_savings(monthly_spend_usd: float, reduction_rate_percent: float) -> dict[str, Any]:
    """月額コスト（USD）と削減率（%）から、月間・年間の削減見込み額と改善後月額を算出する。

    Args:
        monthly_spend_usd: 現在の月額コスト（USD、0 以上）。
        reduction_rate_percent: 見込み削減率（0〜100）。

    Returns:
        削減見込み額（月間・年間）および対策後の予測月額（USD）。
    """
    if monthly_spend_usd < 0:
        return {"error": "monthly_spend_usd は 0 以上を指定してください。"}
    if not (0.0 <= reduction_rate_percent <= 100.0):
        return {"error": "reduction_rate_percent は 0 以上 100 以下を指定してください。"}

    monthly_saved = monthly_spend_usd * (reduction_rate_percent / 100.0)
    projected_monthly = monthly_spend_usd - monthly_saved
    annual_saved = monthly_saved * 12.0
    return {
        "current_monthly_usd": round(monthly_spend_usd, 2),
        "reduction_rate_percent": round(reduction_rate_percent, 1),
        "monthly_savings_usd": round(monthly_saved, 2),
        "annual_savings_usd": round(annual_saved, 2),
        "projected_monthly_usd": round(projected_monthly, 2),
    }


root_agent = Agent(
    name="billing_triage_agent",
    model=DEFAULT_MODEL,
    description="クラウド利用料の急増原因の切り分けと削減額試算を行う FinOps 支援エージェント。",
    instruction="""あなたは FinOps（クラウドコスト最適化）支援エージェントです。

1. 特定サービスのコスト急増について質問された場合は、必ず `inspect_cost_spike` を呼び出して事実データを取得してください。
2. 削減額の試算を求められた場合は、必ず `estimate_savings` を呼び出して正確な金額（USD）を算出してください。
3. 回答は「① 原因」「② 推奨アクション」「③ 削減効果（試算値がある場合）」の構成で簡潔にまとめてください。
""",
    tools=[inspect_cost_spike, estimate_savings],
    generate_content_config=types.GenerateContentConfig(
        temperature=0.1,
        thinking_config=types.ThinkingConfig(thinking_level="LOW"),
    ),
)

app = App(name="app", root_agent=root_agent)
