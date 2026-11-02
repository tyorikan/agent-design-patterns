"""CLI-01: Spec-Driven Agent パターン実装。

`.agents-cli-spec.md` で定義した仕様（目的・スコープ・ツール契約・受け入れ基準）に
1 対 1 で対応する ADK `App` および `root_agent` を定義する。
"""

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

# 決定論的な標準復旧手順（Runbook）カタログ
_RUNBOOK_CATALOG: dict[str, dict[str, Any]] = {
    "latency": {
        "title": "API レイテンシ急増（p95 / p99 悪化）一次切り分け",
        "checks": [
            "直近 30 分のデプロイ履歴とトラフィック急増の有無を確認する",
            "下流 DB / 外部 API の応答時間スパンを分散トレースで特定する",
            "接続プール枯渇またはコールドスタート頻発の有無を確認する",
        ],
        "safe_mitigation": "原因リビジョンが特定できた場合のみ、人間承認のもとトラフィックを直前リビジョンへ切り戻す。",
    },
    "error_rate": {
        "title": "5xx エラー率上昇 一次切り分け",
        "checks": [
            "ステータスコード内訳（500 / 502 / 503 / 504）を集計する",
            "直近の環境変数・シークレット変更や IAM 権限エラーを確認する",
            "依存サービスのクォータ上限到達（429 / RESOURCE_EXHAUSTED）を確認する",
        ],
        "safe_mitigation": "設定不備による 500 多発時はロールバック手順書に従い人間が切り戻しを実施する。",
    },
    "memory_pressure": {
        "title": "コンテナ OOM / メモリ逼迫 一次切り分け",
        "checks": [
            "コンテナメモリ使用率の推移と OOMKilled イベントを確認する",
            "1 リクエストあたりのペイロード肥大化やインメモリキャッシュ肥大を確認する",
            "同時実行数（concurrency）設定がメモリ上限に対して過大でないか検証する",
        ],
        "safe_mitigation": "一時緩和としてメモリ上限引き上げまたは concurrency 引き下げのステージング検証を行う。",
    },
    "cold_start": {
        "title": "コールドスタート遅延 一次切り分け",
        "checks": [
            "コンテナ起動時の重いモジュール import や同期初期化処理を特定する",
            "最小インスタンス数（min-instances）が 0 になっていないか確認する",
            "コンテナイメージサイズと起動プローブ設定を確認する",
        ],
        "safe_mitigation": "クリティカル経路では min-instances の設定と遅延 import 化を検討する。",
    },
}


def calculate_error_budget(
    slo_target_percent: float,
    consumed_downtime_minutes: float,
    window_days: int = 30,
) -> dict[str, Any]:
    """SLO 目標値（%）と消費済みダウンタイム（分）から残余エラーバジェットを算出する。

    Args:
        slo_target_percent: SLO 目標値（例: 99.9）。0 より大きく 100 未満の数値。
        consumed_downtime_minutes: 対象期間内に既に発生したダウンタイム合計（分）。0 以上。
        window_days: SLO 評価期間の日数（デフォルト: 30 日）。

    Returns:
        許容ダウンタイム分数、残余分数、消費率（%）、健全性ステータスを含む辞書。
    """
    if not (0.0 < slo_target_percent < 100.0):
        return {
            "error": "slo_target_percent は 0 より大きく 100 未満で指定してください（例: 99.9）。"
        }
    if consumed_downtime_minutes < 0:
        return {"error": "consumed_downtime_minutes は 0 以上の分数を指定してください。"}
    if window_days <= 0:
        return {"error": "window_days は 1 以上の日数を指定してください。"}

    total_minutes = float(window_days * 24 * 60)
    allowed_minutes = total_minutes * ((100.0 - slo_target_percent) / 100.0)
    remaining_minutes = allowed_minutes - consumed_downtime_minutes
    burn_percent = (
        (consumed_downtime_minutes / allowed_minutes) * 100.0 if allowed_minutes > 0 else 100.0
    )

    if remaining_minutes <= 0:
        status = "EXHAUSTED"
    elif burn_percent >= 70.0:
        status = "WARNING"
    else:
        status = "HEALTHY"

    return {
        "window_days": window_days,
        "slo_target_percent": slo_target_percent,
        "allowed_downtime_minutes": round(allowed_minutes, 2),
        "consumed_downtime_minutes": round(consumed_downtime_minutes, 2),
        "remaining_budget_minutes": round(remaining_minutes, 2),
        "budget_burn_percent": round(burn_percent, 1),
        "status": status,
    }


def lookup_runbook(symptom_category: str) -> dict[str, Any]:
    """障害の症状カテゴリに対応する標準一次切り分け手順（Runbook）を取得する。

    Args:
        symptom_category: 症状カテゴリ。'latency', 'error_rate', 'memory_pressure', 'cold_start' のいずれか。

    Returns:
        対応する Runbook 情報、または有効なカテゴリ一覧を含む案内辞書。
    """
    normalized = symptom_category.strip().lower()
    if normalized not in _RUNBOOK_CATALOG:
        return {
            "found": False,
            "available_categories": sorted(_RUNBOOK_CATALOG.keys()),
            "hint": "available_categories のいずれかを指定して再呼び出ししてください。",
        }
    return {
        "found": True,
        "category": normalized,
        **_RUNBOOK_CATALOG[normalized],
    }


root_agent = Agent(
    name="slo_diagnostics_agent",
    model=DEFAULT_MODEL,
    description="SLO エラーバジェット計算と標準復旧手順（Runbook）の案内を行う仕様駆動エージェント。",
    instruction="""あなたは SRE オンコール支援エージェントです。以下の仕様を厳守してください。

1. SLO やエラーバジェットの計算を求められた場合は、絶対に暗算せず必ず `calculate_error_budget` ツールを呼び出し、返却された数値を正確に伝えてください。
2. 障害切り分けや復旧手順を求められた場合は、`lookup_runbook` ツールで該当カテゴリの標準手順を検索して提示してください。
3. 本番環境の再起動・ロールバック・設定変更などの直接実行を求められた場合は、「本エージェントは読み取り・診断専用であり、本番変更コマンドの直接実行は行いません」と明示した上で、人間が確認・実行するための手順のみを案内してください。
""",
    tools=[calculate_error_budget, lookup_runbook],
    generate_content_config=types.GenerateContentConfig(
        temperature=0.1,
        thinking_config=types.ThinkingConfig(thinking_level="LOW"),
    ),
)

# agents-cli 1.12+ が標準エントリーポイントとして認識する App コンテナ
app = App(
    name="app",
    root_agent=root_agent,
)
