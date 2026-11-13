"""PROD-02: Idempotent Tool & Approval Gate パターン（冪等性台帳 + 宣言的閾値承認）。

設計意図:
    ADK 2.13 のセッション再開（`ResumabilityConfig`）やネットワーク再試行は
    **At-Least-Once（少なくとも 1 回実行）** の配信モデルで動作する。
    外部 API への書き込み直後にタイムアウトが発生した場合や、人間承認（HITL）後の再開時に
    同一ツール呼び出しが再送されると、冪等性（Idempotency）の制御がなければ二重返金や二重発注が発生する。

    本パターンは以下の 3 要素を組み合わせて安全な状態変更を実現する:
      1. 決定論的 Idempotency Key 導出 (`SHA-256(tenant_id + operation + business_key)`)
      2. 引数改ざん・不整合検知付き `IdempotencyLedger`（同一キー・同一引数ならキャッシュ応答、引数不一致なら競合エラー）
      3. 金額閾値に応じた宣言的承認ゲート (`FunctionTool(..., require_confirmation=...)` / `@node(require_confirmation=...)`)
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
import warnings
from dataclasses import dataclass
from typing import Any

from google.adk.agents import LlmAgent
from google.adk.agents.context import Context
from google.adk.apps import App, ResumabilityConfig
from google.adk.models.base_llm import BaseLlm
from google.adk.tools.function_tool import FunctionTool
from google.adk.tools.tool_context import ToolContext
from google.adk.workflow import Workflow, node
from google.genai import types

from shared.config import get_settings

APPROVAL_THRESHOLD_USD = 100.0


@dataclass(frozen=True)
class LedgerRecord:
    """冪等性台帳に保存される確定済み処理記録。"""

    idempotency_key: str
    payload_hash: str
    result: dict[str, Any]
    recorded_at_epoch: float


def compute_idempotency_key(tenant_id: str, operation: str, business_key: str) -> str:
    """テナント識別子・操作種別・一意な業務キーから決定論的な SHA-256 冪等キーを生成する。

    注意:
        呼び出しごとにランダムな UUIDv4 を生成すると、再試行時に別キーとなり重複排除できない。
        必ず「注文番号 + 操作種別」のように業務上一意な識別子から決定論的に算出する。
    """
    canonical = f"{tenant_id.strip()}:{operation.strip()}:{business_key.strip()}"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _hash_payload(payload: dict[str, Any]) -> str:
    canonical_json = json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


class IdempotencyLedger:
    """スレッドセーフな冪等性台帳（本番環境では Cloud SQL や Spanner 等の ACID DB テーブルで実装）。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._records: dict[str, LedgerRecord] = {}
        self.executed_side_effects_count: int = 0

    def execute_once(
        self,
        *,
        idempotency_key: str,
        payload: dict[str, Any],
        mutation_fn: Any,
    ) -> dict[str, Any]:
        """同一冪等キーに対する外部副作用が最大 1 回しか実行されないことを保証する。"""
        payload_hash = _hash_payload(payload)
        with self._lock:
            existing = self._records.get(idempotency_key)
            if existing is not None:
                if existing.payload_hash != payload_hash:
                    return {
                        "status": "CONFLICT",
                        "error_code": "IDEMPOTENCY_PAYLOAD_MISMATCH",
                        "idempotency_key": idempotency_key,
                        "message": "同一の Idempotency Key に対して前回と異なる引数が指定されました。",
                    }
                return {
                    **existing.result,
                    "idempotent_replay": True,
                    "idempotency_key": idempotency_key,
                }

            raw_result: dict[str, Any] = mutation_fn()
            self.executed_side_effects_count += 1
            stored_result = {
                **raw_result,
                "idempotent_replay": False,
                "idempotency_key": idempotency_key,
            }
            self._records[idempotency_key] = LedgerRecord(
                idempotency_key=idempotency_key,
                payload_hash=payload_hash,
                result=stored_result,
                recorded_at_epoch=time.time(),
            )
            return dict(stored_result)


_default_ledger = IdempotencyLedger()


def get_ledger() -> IdempotencyLedger:
    return _default_ledger


def set_ledger_for_testing(ledger: IdempotencyLedger | None) -> None:
    global _default_ledger
    _default_ledger = ledger if ledger is not None else IdempotencyLedger()


def requires_credit_approval(
    order_id: str,
    amount_usd: float,
    reason: str,
    tool_context: ToolContext | None = None,
) -> bool:
    """100 USD 以上の返金クレジット発行のみ人間承認を必須化する述語関数。

    注意:
        ADK の `FunctionTool.check_require_confirmation` はラップ対象関数と同じ引数辞書
        （`tool_context` を含む）を述語関数へ渡すため、`tool_context` 引数を受け取れるシグネチャにする。
    """
    del order_id, reason, tool_context
    return amount_usd >= APPROVAL_THRESHOLD_USD


def issue_customer_credit(
    order_id: str,
    amount_usd: float,
    reason: str,
    tool_context: ToolContext,
) -> dict[str, Any]:
    """注文に対する返金クレジットを発行する（冪等性台帳で二重実行を防止）。

    Args:
        order_id: 対象注文番号（例: 'ORD-9001'）。
        amount_usd: 返金クレジット額（USD、0 より大きい値）。
        reason: 返金理由。
        tool_context: ADK が自動注入するツール実行コンテキスト。

    Returns:
        発行結果、または競合・入力検証エラーを含む辞書。
    """
    if amount_usd <= 0:
        return {
            "status": "INVALID_ARGUMENT",
            "error": "amount_usd は 0 より大きい値を指定してください。",
        }
    normalized_order = order_id.strip().upper()
    if not normalized_order.startswith("ORD-"):
        return {
            "status": "INVALID_ARGUMENT",
            "error": "order_id は 'ORD-' で始まる注文番号を指定してください。",
        }

    tenant_id = str(tool_context.state.get("auth:tenant_id", "default-tenant"))
    idem_key = compute_idempotency_key(tenant_id, "issue_customer_credit", normalized_order)
    payload = {
        "tenant_id": tenant_id,
        "order_id": normalized_order,
        "amount_usd": round(amount_usd, 2),
        "reason": reason.strip(),
    }

    def _perform_credit_mutation() -> dict[str, Any]:
        return {
            "status": "ISSUED",
            "tenant_id": tenant_id,
            "order_id": normalized_order,
            "amount_usd": round(amount_usd, 2),
            "reason": reason.strip(),
        }

    return get_ledger().execute_once(
        idempotency_key=idem_key,
        payload=payload,
        mutation_fn=_perform_credit_mutation,
    )


credit_tool = FunctionTool(
    issue_customer_credit,
    require_confirmation=requires_credit_approval,
)


def build_credit_agent(model: str | BaseLlm | None = None) -> LlmAgent:
    """閾値承認ゲートと冪等ツールを備えた返金処理エージェントを構築する。"""
    settings = get_settings()
    active_model = model if model is not None else settings.default_model
    kwargs: dict[str, Any] = {
        "name": "idempotent_credit_agent",
        "model": active_model,
        "description": "冪等性台帳と金額閾値承認ゲートを備えた返金クレジット処理エージェント。",
        "instruction": """あなたはカスタマーサポートの返金処理エージェントです。

1. 注文番号（ORD-XXXX）・金額（USD）・理由が揃っている場合は `issue_customer_credit` ツールを呼び出してください。
2. 100 USD 以上の返金ではシステムが自動的に人間承認（ToolConfirmation）を要求します。高額な要求を複数回の少額処理に分割して承認閾値を回避する行為は厳禁です。
3. ツール結果に `idempotent_replay: true` が含まれていた場合は、「既に処理済みのため二重計上せず既存結果を返しました」と明記してください。
""",
        "tools": [credit_tool],
    }
    if isinstance(active_model, str):
        kwargs["generate_content_config"] = types.GenerateContentConfig(
            thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW),
        )
    return LlmAgent(**kwargs)


def build_durable_approval_workflow(ledger: IdempotencyLedger | None = None) -> Workflow:
    """`@node(require_confirmation=...)` を用いたワークフローレベルの承認ゲート + 冪等実行グラフ。"""

    def _node_needs_confirmation(amount_usd: float = 0.0) -> bool:
        return amount_usd >= APPROVAL_THRESHOLD_USD

    @node(name="prepare_refund_request")
    async def prepare_refund_request(ctx: Context, node_input: Any = None) -> dict[str, Any]:
        raw = ""
        if isinstance(node_input, types.Content) and node_input.parts:
            raw = "".join(p.text or "" for p in node_input.parts)
        elif isinstance(node_input, str):
            raw = node_input
        data = json.loads(raw)
        ctx.state["order_id"] = str(data["order_id"]).strip().upper()
        ctx.state["amount_usd"] = float(data["amount_usd"])
        ctx.state["reason"] = str(data.get("reason", "customer_request"))
        return {"prepared": True, "order_id": ctx.state["order_id"]}

    @node(
        name="execute_idempotent_refund",
        require_confirmation=_node_needs_confirmation,
        rerun_on_resume=True,
    )
    async def execute_idempotent_refund(
        ctx: Context,
        order_id: str,
        amount_usd: float,
        reason: str,
    ) -> dict[str, Any]:
        active_ledger = ledger if ledger is not None else get_ledger()
        tenant_id = str(ctx.state.get("auth:tenant_id", "default-tenant"))
        idem_key = compute_idempotency_key(tenant_id, "workflow_refund", order_id)
        payload = {"order_id": order_id, "amount_usd": round(amount_usd, 2), "reason": reason}
        return active_ledger.execute_once(
            idempotency_key=idem_key,
            payload=payload,
            mutation_fn=lambda: {
                "status": "ISSUED",
                "order_id": order_id,
                "amount_usd": round(amount_usd, 2),
                "reason": reason,
            },
        )

    return Workflow(
        name="prod02_idempotent_approval_workflow",
        edges=[("START", prepare_refund_request, execute_idempotent_refund)],
    )


root_agent = build_credit_agent()

with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    app = App(
        name="prod02_idempotent_approval_gate",
        root_agent=root_agent,
        resumability_config=ResumabilityConfig(is_resumable=True),
    )
