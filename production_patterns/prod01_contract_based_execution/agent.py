"""PROD-01: Contract-Based Execution パターン（事前条件・上限付き自己修正・事後不変条件ゲート）。

設計意図:
    確率的な推論を行う `LlmAgent` に入力検証・再試行制御・完了判定まで委ねると、
    不正入力でトークンを消費したり、業務制約を満たしていない計画を「完了」と誤報告する問題が生じる。

    ソフトウェア工学の「契約による設計（Design by Contract）」に基づき、以下の構造を `Workflow` で強制する:
      1. 事前条件ゲート（Precondition `@node`）: 入力スキーマ検証・正規化・再試行付きマスタ参照（違反時は LLM 呼び出しゼロで即時拒否）
      2. 生成ステップ（`LlmAgent`）: 制約境界内でのリリース計画 JSON 生成
      3. 事後条件・不変条件ゲート（Postcondition `@node`）: スキーマ検証 + 業務不変条件のコード判定 + 反復回数上限管理
      4. 終端分岐（Terminal `@node`）: 全条件合格時のみ確定（`VERIFIED_READY`）、上限超過時は完了を装わず安全停止（`HALTED_FOR_HUMAN`）
"""

from __future__ import annotations

import json
import re
from typing import Any, Literal

from google.adk.agents import LlmAgent
from google.adk.agents.context import Context
from google.adk.apps import App
from google.adk.models.base_llm import BaseLlm
from google.adk.workflow import RetryConfig, Workflow, node
from google.genai import types
from pydantic import BaseModel, Field, ValidationError

from shared.config import get_settings

MAX_REFINEMENT_ITERATIONS = 3


class ChangeTicketInput(BaseModel):
    """事前条件ゲートで確定させる変更チケットの入力スキーマ。"""

    ticket_id: str = Field(pattern=r"^CHG-\d{4,}$")
    service_name: str = Field(min_length=2)
    requested_replicas: int = Field(ge=1, le=200)
    environment: Literal["staging", "prod"]


class DeploymentPlanOutput(BaseModel):
    """事後条件ゲートで検証するエージェント出力の厳格なスキーマ。"""

    ticket_id: str
    service_name: str
    target_replicas: int = Field(ge=1, le=200)
    canary_percent: int = Field(ge=1, le=100)
    rollback_command: str = Field(min_length=10)
    safety_checks: list[str] = Field(min_length=2)


# サービスごとの許容レプリカ数・本番カナリア比率の上限マスタ
_SERVICE_BOUNDS: dict[str, dict[str, int]] = {
    "checkout-api": {"min_replicas": 3, "max_replicas": 40, "max_prod_canary_percent": 20},
    "inventory-worker": {"min_replicas": 2, "max_replicas": 25, "max_prod_canary_percent": 25},
    "search-gateway": {"min_replicas": 4, "max_replicas": 80, "max_prod_canary_percent": 15},
}


def lookup_service_bounds(service_name: str) -> dict[str, Any]:
    """サービスの許容レプリカ範囲とカナリア上限を取得するツール。

    未登録のサービス名が指定された場合も例外で中断せず、登録済みサービス一覧と修正案内を
    構造化辞書として返すことで、呼び出し元エージェントの自律的な引数修正を可能にする。

    Args:
        service_name: 照会対象のサービス名（例: 'checkout-api'）。

    Returns:
        制約情報、または有効な選択肢一覧を含む構造化エラー辞書。
    """
    normalized = service_name.strip().lower()
    bounds = _SERVICE_BOUNDS.get(normalized)
    if bounds is None:
        return {
            "found": False,
            "error": f"未登録のサービス名です: '{service_name}'",
            "available_services": sorted(_SERVICE_BOUNDS.keys()),
            "hint": "available_services のいずれかを指定して再呼び出ししてください。",
        }
    return {"found": True, "service_name": normalized, **bounds}


def _extract_json_object(raw_text: str) -> dict[str, Any]:
    """モデル出力からコードフェンスを除去して JSON オブジェクトを抽出する。"""
    cleaned = raw_text.strip()
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, flags=re.DOTALL)
    if fence_match:
        cleaned = fence_match.group(1)
    parsed = json.loads(cleaned)
    if not isinstance(parsed, dict):
        raise ValueError("トップレベル要素は JSON オブジェクトである必要があります。")
    return parsed


def verify_plan_invariants(
    ticket: ChangeTicketInput,
    bounds: dict[str, int],
    raw_plan_text: str,
) -> tuple[DeploymentPlanOutput | None, list[str]]:
    """事後条件および業務上の不変条件（Invariants）を検証する純粋関数。

    Args:
        ticket: 事前条件検証を通過した変更チケット。
        bounds: サービスマスタから取得した制約値。
        raw_plan_text: エージェントが生成した生テキスト。

    Returns:
        `(検証済みモデルまたは None, 違反理由リスト)` のタプル。
    """
    violations: list[str] = []
    try:
        payload = _extract_json_object(raw_plan_text)
    except (ValueError, json.JSONDecodeError) as exc:
        return None, [f"JSON 解析エラー: {exc}"]

    try:
        plan = DeploymentPlanOutput.model_validate(payload)
    except ValidationError as exc:
        for err in exc.errors():
            loc = ".".join(str(x) for x in err["loc"])
            violations.append(f"スキーマ違反 ({loc}): {err['msg']}")
        return None, violations

    if plan.ticket_id != ticket.ticket_id:
        violations.append(
            f"ticket_id の不一致: 期待値 '{ticket.ticket_id}', 実際 '{plan.ticket_id}'"
        )
    if plan.service_name != ticket.service_name:
        violations.append(
            f"service_name の不一致: 期待値 '{ticket.service_name}', 実際 '{plan.service_name}'"
        )
    if not (bounds["min_replicas"] <= plan.target_replicas <= bounds["max_replicas"]):
        violations.append(
            f"target_replicas={plan.target_replicas} が許容範囲 "
            f"[{bounds['min_replicas']}, {bounds['max_replicas']}] を逸脱しています"
        )
    if (
        ticket.environment == "prod"
        and plan.canary_percent > bounds["max_prod_canary_percent"]
    ):
        violations.append(
            f"prod 環境の canary_percent={plan.canary_percent}% が上限 "
            f"{bounds['max_prod_canary_percent']}% を超えています"
        )
    if ticket.service_name not in plan.rollback_command:
        violations.append(
            f"rollback_command に対象サービス名 '{ticket.service_name}' が含まれていません"
        )

    if violations:
        return None, violations
    return plan, []


def build_contract_workflow(
    planner_model: str | BaseLlm | None = None,
    max_iterations: int = MAX_REFINEMENT_ITERATIONS,
    transient_failures_before_success: int = 0,
) -> Workflow:
    """事前条件・事後条件ゲートを備えた `Contract-Based Execution` の `Workflow` を構築する。

    Args:
        planner_model: 計画生成に用いるモデル名またはテスト用 `BaseLlm` インスタンス。
        max_iterations: 事後条件不合格時の最大再試行回数（無限ループ防止上限）。
        transient_failures_before_success: リトライ検証用に模擬する一時的通信失敗回数。

    Returns:
        構築済みの ADK `Workflow`。
    """
    settings = get_settings()
    active_model = planner_model if planner_model is not None else settings.default_model
    remaining_flaky_calls = {"count": transient_failures_before_success}

    @node(
        name="precondition_gate",
        retry_config=RetryConfig(
            max_attempts=3,
            initial_delay=0.02,
            max_delay=0.1,
            backoff_factor=2.0,
            jitter=0.0,
            exceptions=[ConnectionError],
        ),
        timeout=5.0,
    )
    async def precondition_gate(ctx: Context, node_input: Any = None) -> dict[str, Any]:
        """Step 1: LLM 呼び出し前に入力構造とサービス制約を決定論的に検証する。"""
        if remaining_flaky_calls["count"] > 0:
            remaining_flaky_calls["count"] -= 1
            raise ConnectionError("構成マスタ DB への接続が一時的に切断されました")

        raw_text = ""
        if isinstance(node_input, types.Content) and node_input.parts:
            raw_text = "".join(p.text or "" for p in node_input.parts)
        elif isinstance(node_input, str):
            raw_text = node_input
        elif isinstance(node_input, dict):
            raw_text = json.dumps(node_input, ensure_ascii=False)

        try:
            parsed_input = _extract_json_object(raw_text)
            ticket = ChangeTicketInput.model_validate(parsed_input)
        except (ValueError, ValidationError) as exc:
            ctx.state["execution_status"] = "REJECTED_AT_PRECONDITION"
            ctx.state["precondition_error"] = str(exc)
            ctx.route = "REJECT_INPUT"
            return {"status": "REJECTED_AT_PRECONDITION", "reason": str(exc)}

        bounds_res = lookup_service_bounds(ticket.service_name)
        if not bounds_res.get("found"):
            reason = str(bounds_res.get("error", "未登録サービス"))
            ctx.state["execution_status"] = "REJECTED_AT_PRECONDITION"
            ctx.state["precondition_error"] = reason
            ctx.route = "REJECT_INPUT"
            return {"status": "REJECTED_AT_PRECONDITION", "reason": reason}

        ctx.state["validated_ticket"] = ticket.model_dump()
        ctx.state["service_bounds"] = {
            "min_replicas": bounds_res["min_replicas"],
            "max_replicas": bounds_res["max_replicas"],
            "max_prod_canary_percent": bounds_res["max_prod_canary_percent"],
        }
        ctx.state["attempt_count"] = 0
        ctx.state["validation_feedback"] = "初回生成: すべての制約を満たす JSON を出力してください。"
        ctx.route = "RUN_PLANNER"
        return {"status": "PRECONDITION_PASSED", "ticket": ticket.model_dump()}

    planner_kwargs: dict[str, Any] = {
        "name": "release_planner_agent",
        "model": active_model,
        "description": "検証済みチケットとサービス制約から安全なデプロイ計画 JSON を生成する",
        "instruction": """あなたは本番リリース計画エージェントです。
以下の検証済みチケットとサービス制約に従い、JSON オブジェクトのみを出力してください。

## 検証済み変更チケット
{validated_ticket}

## サービス制約（厳守）
{service_bounds}

## 前回検証からのフィードバック
{validation_feedback}

## 必須 JSON キー
- ticket_id (文字列: チケットと同じ ID)
- service_name (文字列: チケットと同じサービス名)
- target_replicas (整数: min_replicas 以上 max_replicas 以下に丸めること)
- canary_percent (整数: prod の場合は max_prod_canary_percent 以下)
- rollback_command (文字列: サービス名を含む具体的な切り戻しコマンド)
- safety_checks (文字列リスト: 2 項目以上の事前・事後ヘルスチェック項目)
""",
        "tools": [lookup_service_bounds],
        "output_key": "raw_plan_json",
    }
    if isinstance(active_model, str):
        planner_kwargs["generate_content_config"] = types.GenerateContentConfig(
            temperature=0.1,
            thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW),
        )
    release_planner_agent = LlmAgent(**planner_kwargs)

    @node(name="postcondition_gate", timeout=5.0)
    async def postcondition_gate(ctx: Context) -> dict[str, Any]:
        """Step 3: エージェント出力を事後条件で検証し、確定・再生成・安全停止を分岐する。"""
        attempt = int(ctx.state.get("attempt_count", 0)) + 1
        ctx.state["attempt_count"] = attempt

        ticket = ChangeTicketInput.model_validate(ctx.state["validated_ticket"])
        bounds: dict[str, int] = dict(ctx.state["service_bounds"])
        raw_plan = str(ctx.state.get("raw_plan_json", ""))

        verified_plan, violations = verify_plan_invariants(ticket, bounds, raw_plan)
        if verified_plan is not None:
            ctx.state["verified_plan"] = verified_plan.model_dump()
            ctx.route = "COMMIT"
            return {"attempt": attempt, "verified": True}

        feedback = " / ".join(violations)
        ctx.state["validation_feedback"] = feedback
        ctx.state["last_violations"] = violations

        if attempt < max_iterations:
            ctx.route = "RETRY_PLAN"
            return {
                "attempt": attempt,
                "verified": False,
                "action": "RETRY_PLAN",
                "violations": violations,
            }

        ctx.route = "ABORT_SAFE"
        return {
            "attempt": attempt,
            "verified": False,
            "action": "ABORT_SAFE",
            "violations": violations,
        }

    @node(name="commit_plan_node")
    async def commit_plan_node(ctx: Context) -> dict[str, Any]:
        """すべての事前条件・事後条件を通過した計画のみを確定状態として出力する。"""
        ctx.state["execution_status"] = "VERIFIED_READY"
        return {
            "status": "VERIFIED_READY",
            "attempts_used": ctx.state.get("attempt_count", 1),
            "plan": ctx.state["verified_plan"],
        }

    @node(name="safe_abort_node")
    async def safe_abort_node(ctx: Context) -> dict[str, Any]:
        """事前条件違反または上限回数超過時に、完了を装わず明示的な停止状態を返す。"""
        pre_err = ctx.state.get("precondition_error")
        if pre_err:
            return {
                "status": "REJECTED_AT_PRECONDITION",
                "llm_invoked": False,
                "reason": pre_err,
            }
        ctx.state["execution_status"] = "HALTED_FOR_HUMAN"
        return {
            "status": "HALTED_FOR_HUMAN",
            "attempts_used": ctx.state.get("attempt_count", max_iterations),
            "unresolved_violations": ctx.state.get("last_violations", []),
            "message": "上限回数内に事後不変条件を満たせなかったため、自動適用を停止し人間レビューへ回送しました。",
        }

    return Workflow(
        name="prod01_contract_based_execution_workflow",
        description="事前条件検証・上限付き自己修正・事後不変条件検証を強制するワークフロー",
        edges=[
            (
                "START",
                precondition_gate,
                {
                    "RUN_PLANNER": release_planner_agent,
                    "REJECT_INPUT": safe_abort_node,
                },
            ),
            (
                release_planner_agent,
                postcondition_gate,
                {
                    "COMMIT": commit_plan_node,
                    "RETRY_PLAN": release_planner_agent,
                    "ABORT_SAFE": safe_abort_node,
                },
            ),
        ],
    )


root_agent = build_contract_workflow()
app = App(name="prod01_contract_based_execution", root_agent=root_agent)
