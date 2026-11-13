"""CLI-03: A2A Interoperability パターン実装（IAM・セキュリティ診断専門エージェント）。"""

from __future__ import annotations

import os
from typing import Any

from google.adk.agents import Agent
from google.adk.apps import App
from google.genai import types

os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "global")
os.environ.setdefault("GOOGLE_GENAI_USE_ENTERPRISE", "True")

DEFAULT_MODEL = os.environ.get("DEFAULT_MODEL", "gemini-4-hydrogen")

_IAM_RISK_RULES: dict[str, dict[str, Any]] = {
    "roles/owner": {
        "risk_level": "CRITICAL",
        "reason": "IAM ポリシー変更・請求操作・全リソース削除を含む無制限の基本ロールです。",
        "least_privilege_alternatives": [
            "roles/run.invoker",
            "roles/aiplatform.user",
            "roles/storage.objectViewer",
        ],
    },
    "roles/editor": {
        "risk_level": "HIGH",
        "reason": "プロジェクト内の大半の既存サービスに対する変更・削除権限を持つ過剰な基本ロールです。",
        "least_privilege_alternatives": [
            "roles/aiplatform.user",
            "roles/bigquery.dataViewer",
            "roles/bigquery.jobUser",
        ],
    },
    "roles/aiplatform.user": {
        "risk_level": "LOW",
        "reason": "モデル推論およびエンドポイント呼び出しに限定された事前定義ロールです。",
        "least_privilege_alternatives": ["roles/aiplatform.user（現状維持で適切）"],
    },
}

_ADVISORY_DB: dict[str, dict[str, str]] = {
    "ADV-2026-0101": {
        "severity": "CRITICAL",
        "summary": "開発用 Web UI エンドポイントの無認証外部公開によるリモートコード実行リスク",
        "remediation": "本番環境では開発用 Web UI を無効化（web=False）するか IAP / Cloud Run IAM 認証を必須化し、フレームワークを最新安定版へ更新する。",
    },
    "ADV-2026-0204": {
        "severity": "HIGH",
        "summary": "ツール出力に含まれる外部テキスト経由の間接プロンプトインジェクション",
        "remediation": "外部入力とシステム命令を分離し、ツール出力（function_response）に対するサニタイズプラグインを導入する。",
    },
}


def evaluate_iam_binding(role_name: str, principal_type: str = "serviceAccount") -> dict[str, Any]:
    """指定された IAM ロール付与のリスクレベルと最小権限の代替ロールを診断する。

    Args:
        role_name: 診断対象の IAM ロール名（例: 'roles/owner', 'roles/editor', 'roles/aiplatform.user'）。
        principal_type: 付与対象の種別（例: 'serviceAccount', 'user', 'allUsers'）。

    Returns:
        リスクレベル、理由、最小権限の推奨代替ロール一覧を含む辞書。
    """
    normalized_role = role_name.strip()
    if principal_type.strip() in {"allUsers", "allAuthenticatedUsers"}:
        return {
            "role": normalized_role,
            "principal_type": principal_type,
            "risk_level": "CRITICAL",
            "reason": "インターネット上の不特定多数へ無制限に公開される設定です。",
            "least_privilege_alternatives": [
                "特定の呼び出し元 serviceAccount のみに roles/run.invoker 等を付与してください"
            ],
        }

    info = _IAM_RISK_RULES.get(normalized_role)
    if info is None:
        return {
            "role": normalized_role,
            "principal_type": principal_type,
            "risk_level": "MEDIUM",
            "reason": "個別精査対象のロールです。ワイルドカード権限（*.admin / *.*）が含まれないか確認してください。",
            "known_roles": sorted(_IAM_RISK_RULES.keys()),
        }
    return {"role": normalized_role, "principal_type": principal_type, **info}


def lookup_security_advisory(advisory_id: str) -> dict[str, Any]:
    """セキュリティ勧告 ID から深刻度と推奨対策を検索する。

    Args:
        advisory_id: セキュリティ勧告 ID（例: 'ADV-2026-0101', 'ADV-2026-0204'）。

    Returns:
        勧告の概要と推奨対策を含む辞書。
    """
    key = advisory_id.strip().upper()
    if key not in _ADVISORY_DB:
        return {
            "found": False,
            "available_advisories": sorted(_ADVISORY_DB.keys()),
        }
    return {"found": True, "advisory_id": key, **_ADVISORY_DB[key]}


root_agent = Agent(
    name="security_advisory_agent",
    model=DEFAULT_MODEL,
    description="IAM ロール最小権限診断とセキュリティ勧告照会を提供する A2A 対応専門エージェント。",
    instruction="""あなたはクラウドセキュリティ審査エージェントです。他のエージェントや開発者からの問い合わせに対し、以下を実行してください。

1. IAM ロールや公開設定のリスク診断では、必ず `evaluate_iam_binding` ツールを呼び出して客観的なリスクレベルと最小権限の代替案を提示してください。
2. セキュリティ勧告 ID が指定された場合は、`lookup_security_advisory` ツールで詳細を取得してください。
3. 回答は「リスク判定」「根拠」「推奨される最小権限アクション」の3点で簡潔に返してください。
""",
    tools=[evaluate_iam_binding, lookup_security_advisory],
    generate_content_config=types.GenerateContentConfig(
        thinking_config=types.ThinkingConfig(thinking_level="LOW"),
    ),
)

app = App(name="app", root_agent=root_agent)
