"""PROD-07: Governed Knowledge & Attested Computation パターン。

設計の核心:
    1. OKF (Open Knowledge Format) v0.3 準拠の段階的開示 (Progressive Disclosure):
       全ドキュメントをコンテキストへ一括投入せず、`list_bundle_index` と `scan_bundle_concepts`
       でフロントマターと `index.md` から必要な Concept のみを絞り込み、`read_concept` で取得する。
       すべてのパス解決は `bundle_root` 境界内に厳格制限され、パストラバーサルを遮断する。
    2. 決定論的な信頼ティア・鮮度・ライフサイクル評価:
       - Trust Tier: `verified[].at >= generated.at` の現行検証のみを有効とし、エージェント編集後に
         古い人間承認が残っている場合は自動的に `unverified` / `machine-confirmed` へ降格する (§5.3)。
       - Lifecycle: `status: deprecated` の参照時は `superseded_by` の後継 Concept へ自動転送する (§5.4)。
       - Freshness: `now >= stale_after` や書式不正の `stale_after` を鮮度切れとして警告する (§5.5)。
    3. 非 LLM Attester による `Attested Computation` の実行証明と `KnowledgeGovernancePlugin` の Fail-Closed 強制:
       LLM は宣言済み `parameters` のみ渡し、承認済み SQL の実行結果と権威ジョブログの一致を
       決定論的 Attester が検証する。さらに `KnowledgeGovernancePlugin.after_tool_callback` が
       未検証・検証失敗時の数値ペイロードを強制除去 (Fail-Closed) し、全参照・計算の監査ログを記録する。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from google.adk.agents import LlmAgent
from google.adk.apps.app import App
from google.adk.models.base_llm import BaseLlm
from google.adk.plugins.base_plugin import BasePlugin
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext
from google.genai import types

from production_patterns.prod07_governed_knowledge_attestation.attestation import (
    ComputationAttester,
    ComputationExecutor,
    SqlEqualityAttester,
    SqliteComputationExecutor,
    execute_and_attest_computation,
)
from production_patterns.prod07_governed_knowledge_attestation.okf_bundle import (
    OkfBundle,
    OkfError,
    PathTraversalError,
    resolve_concept_conflict,
)
from shared.config import get_settings

DEFAULT_BUNDLE_DIR = Path(__file__).resolve().parent / "bundle"
_REDACTED_VALUE_KEYS = ("rows", "value", "values", "result", "data")


class KnowledgeGovernancePlugin(BasePlugin):
    """知識参照・検証済み計算ツールの出力に対し Fail-Closed 遮断と監査記録を強制する ADK プラグイン。

    ツール層 (Executor / Attester) に万が一バグがあり、`attestation_ok=False` にもかかわらず
    生の数値フィールド (`rows`, `value`, `result` 等) が含まれて返却された場合でも、
    `after_tool_callback` で確定的に削除して LLM への流出を遮断する多層防御を担う。
    """

    def __init__(self) -> None:
        super().__init__(name="knowledge_governance_plugin")
        self.audit_log: list[dict[str, Any]] = []
        self.fail_closed_blocks: int = 0
        self.stale_warnings: int = 0
        self.superseded_redirects: int = 0

    async def after_tool_callback(
        self,
        *,
        tool: BaseTool,
        tool_args: dict[str, Any],
        tool_context: ToolContext,
        result: dict[str, Any],
    ) -> dict[str, Any] | None:
        del tool_args, tool_context
        if not isinstance(result, dict):
            return None

        entry: dict[str, Any] = {
            "tool": tool.name,
            "concept_id": result.get("concept_id"),
            "trust_tier": result.get("trust_tier"),
            "status": result.get("status"),
            "is_stale": result.get("is_stale"),
        }

        if result.get("is_stale") is True:
            self.stale_warnings += 1

        redirects = result.get("redirected_from")
        if isinstance(redirects, list) and redirects:
            self.superseded_redirects += 1
            entry["redirected_from"] = list(redirects)

        if tool.name == "run_attested_computation":
            attested = result.get("attested") is True and result.get("attestation_ok") is True
            entry["attested"] = attested
            entry["receipt_ref"] = result.get("receipt_ref")

            if not attested:
                self.fail_closed_blocks += 1
                sanitized = dict(result)
                stripped_keys: list[str] = []
                for key in _REDACTED_VALUE_KEYS:
                    if key in sanitized:
                        sanitized.pop(key)
                        stripped_keys.append(key)
                sanitized["value_redacted_fail_closed"] = True
                sanitized["attested"] = False
                sanitized["attestation_ok"] = False
                entry["fail_closed_blocked"] = True
                entry["stripped_keys"] = stripped_keys
                self.audit_log.append(entry)
                return sanitized

        self.audit_log.append(entry)
        return None


def _build_bundle_tools(
    *,
    bundle: OkfBundle,
    executor: ComputationExecutor,
    attester: ComputationAttester,
) -> list[Any]:
    """指定バンドルと実行器・検証器に束縛された ADK ツール関数群を生成する。"""

    def list_bundle_index(directory: str = "") -> dict[str, Any]:
        """段階的開示の起点として、指定ディレクトリの `index.md` と子要素一覧を返す。

        Args:
            directory: バンドルルートからの相対ディレクトリパス (ルートは空文字 `""`)。
        """
        try:
            return bundle.list_directory(directory)
        except PathTraversalError as exc:
            return {"error": "PATH_TRAVERSAL_BLOCKED", "message": str(exc)}
        except OkfError as exc:
            return {"error": "OKF_ERROR", "message": str(exc)}

    def scan_bundle_concepts(
        type_filter: str = "",
        tag: str = "",
        query: str = "",
        current_only: bool = True,
    ) -> dict[str, Any]:
        """本文を読まずにフロントマターだけで Concept 候補と信頼ティア・鮮度を軽量スキャンする。

        Args:
            type_filter: Concept の `type` 完全一致フィルタ (例: `"Attested Computation"`, `"Policy"`).
            tag: タグフィルタ (例: `"revenue"`).
            query: ID・タイトル・説明・タグに対する部分一致キーワード。
            current_only: `True` の場合、`status` が現行 (`stable` / `draft`) のみを返す。
        """
        docs = bundle.scan_concepts(
            type_filter=type_filter,
            tag=tag,
            query=query,
            current_only=current_only,
        )
        return {
            "count": len(docs),
            "concepts": [d.to_summary_dict() for d in docs],
        }

    def read_concept(concept_id: str, follow_superseded: bool = True) -> dict[str, Any]:
        """指定した Concept ID の本文・信頼ティア・鮮度・脚注出典・リンク先を読み込む。

        `status: deprecated` かつ `superseded_by` が定義されている場合は後継 Concept へ自動転送する。

        Args:
            concept_id: 拡張子 `.md` を除いた Concept ID (例: `"metrics/income_statement"`).
            follow_superseded: `True` の場合、`deprecated` Concept の `superseded_by` を自動追跡する。
        """
        try:
            doc, redirect_chain = bundle.read_concept(
                concept_id, follow_superseded=follow_superseded
            )
        except PathTraversalError as exc:
            return {"error": "PATH_TRAVERSAL_BLOCKED", "message": str(exc)}
        except OkfError as exc:
            return {"error": "CONCEPT_NOT_FOUND", "message": str(exc)}

        return {
            **doc.to_summary_dict(),
            "redirected_from": redirect_chain,
            "resource": doc.resource,
            "runtime": doc.runtime,
            "parameters": [
                {"name": p.name, "type": p.type, "required": p.required} for p in doc.parameters
            ],
            "attestable": bool(doc.runtime and doc.attester_resource),
            "citations": [
                {
                    "id": s.id,
                    "title": s.title,
                    "resource": s.resource,
                    "author": s.author,
                    "usage_count": s.usage_count,
                }
                for s in doc.cited_sources
            ],
            "linked_concepts": [
                link.concept_id for link in doc.links if not link.is_external and link.concept_id
            ],
            "body": doc.body,
        }

    def run_attested_computation(concept_id: str, parameters_json: str) -> dict[str, Any]:
        """OKF `Attested Computation` を承認済み SQL で実行し、非 LLM 検証器でレシート照合する。

        LLM は SQL を書かず、宣言済みパラメータを JSON オブジェクト文字列として渡すこと。

        Args:
            concept_id: `type: Attested Computation` の Concept ID (例: `"computations/recognized_revenue"`).
            parameters_json: 宣言済みパラメータの JSON 文字列 (例: `'{"year": 2026}'`).
        """
        try:
            raw_params = json.loads(parameters_json)
        except json.JSONDecodeError as exc:
            return {
                "attested": False,
                "attestation_ok": False,
                "concept_id": concept_id,
                "attestation_reason": f"parameters_json の JSON 解析に失敗しました: {exc}",
            }

        if not isinstance(raw_params, dict):
            return {
                "attested": False,
                "attestation_ok": False,
                "concept_id": concept_id,
                "attestation_reason": "parameters_json は JSON オブジェクトである必要があります。",
            }

        try:
            return execute_and_attest_computation(
                bundle=bundle,
                concept_id=concept_id,
                parameters=raw_params,
                executor=executor,
                attester=attester,
            )
        except PathTraversalError as exc:
            return {
                "attested": False,
                "attestation_ok": False,
                "concept_id": concept_id,
                "attestation_reason": f"PATH_TRAVERSAL_BLOCKED: {exc}",
            }
        except OkfError as exc:
            return {
                "attested": False,
                "attestation_ok": False,
                "concept_id": concept_id,
                "attestation_reason": str(exc),
            }

    return [
        list_bundle_index,
        scan_bundle_concepts,
        read_concept,
        run_attested_computation,
    ]


def build_governed_knowledge_app(
    *,
    model: str | BaseLlm | None = None,
    bundle_dir: Path | str = DEFAULT_BUNDLE_DIR,
    executor: ComputationExecutor | None = None,
    attester: ComputationAttester | None = None,
    now: datetime | None = None,
) -> tuple[App, KnowledgeGovernancePlugin]:
    """OKF v0.3 ガバナンスツール群と `KnowledgeGovernancePlugin` を統合した ADK `App` を構築する。"""
    settings = get_settings()
    active_model = model if model is not None else settings.default_model
    bundle = OkfBundle(bundle_dir, now=now)
    active_executor = executor if executor is not None else SqliteComputationExecutor()
    active_attester = attester if attester is not None else SqlEqualityAttester()
    tools = _build_bundle_tools(
        bundle=bundle,
        executor=active_executor,
        attester=active_attester,
    )

    agent_kwargs: dict[str, Any] = {
        "name": "governed_knowledge_agent",
        "model": active_model,
        "description": (
            "OKF v0.3 バンドルを段階的に探索し、信頼ティア・鮮度・検証済み計算 (Attested Computation) "
            "のステータスを明示して回答する本番ガバナンスエージェント。"
        ),
        "instruction": """あなたは OKF v0.3 バンドルを参照して回答するガバナンス付き知識エージェントです。

必ず次の手順と制約を守ってください:
1. 最初に `list_bundle_index` または `scan_bundle_concepts` を使って対象 Concept を特定し、必要な Concept だけ `read_concept` で読み込んでください。
2. 数値集計が求められ、該当 Concept が `Attested Computation` へリンクしている場合は、自分で SQL や数値を推測・計算せず、必ず `run_attested_computation` に宣言済みパラメータのみを渡して実行してください。
3. `run_attested_computation` が `attested: false` を返した場合、数値を一切出力せず、失敗理由のみを報告してください (Fail-Closed)。
4. 回答の末尾に、使用した各 Concept について次を必ず明記してください:
   - Concept ID、信頼ティア (`human-reviewed` / `machine-confirmed` / `unverified`)、ステータス (`stable` / `draft` / `deprecated`)、鮮度 (`fresh` または期限超過警告)
   - `verified_before_last_change: true` の場合は「最終変更後に未再検証である」旨の注意
   - `redirected_from` がある場合は廃止 Concept から後継へ転送した旨
   - 検証済み計算を実行した場合は `attested` / `not attested` と `receipt_ref`
   - 根拠となった `citations` (出典タイトルと URL)
""",
        "tools": tools,
    }
    if isinstance(active_model, str):
        agent_kwargs["generate_content_config"] = types.GenerateContentConfig(
            thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW),
        )

    agent = LlmAgent(**agent_kwargs)
    governance_plugin = KnowledgeGovernancePlugin()
    governed_app = App(
        name="prod07_governed_knowledge_attestation",
        root_agent=agent,
        plugins=[governance_plugin],
    )
    return governed_app, governance_plugin


__all__ = [
    "DEFAULT_BUNDLE_DIR",
    "KnowledgeGovernancePlugin",
    "OkfBundle",
    "SqliteComputationExecutor",
    "SqlEqualityAttester",
    "app",
    "build_governed_knowledge_app",
    "resolve_concept_conflict",
    "root_agent",
]

app, _default_governance_plugin = build_governed_knowledge_app()
assert app.root_agent is not None
root_agent = app.root_agent
