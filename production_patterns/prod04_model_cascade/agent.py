"""PROD-04: Model Cascade パターン（段階的モデルエスカレーションと Rogan–Gladen 補正）。

設計の核心:
    すべてのリクエストに上位モデル（や高思考レベル `HIGH`）を使うと、定型質問のレイテンシと推論費が跳ね上がる。
    逆に、すべてを軽量モデル（`gemini-3.5-flash-lite`）で済ませると、複雑な案件で品質事故が起きる。

    カスケードルーティングを本番で機能させる鍵は以下の 3 点である:
      1. 決定論的 Pre-Gate（ミリ秒・0 ドル）: 文字数・必須構造を満たさない軽量モデル出力は、
         Judge LLM すら呼ばずに即座に上位モデルへエスカレーションする。
      2. 二値ルーブリック Fail-Closed 判定: Judge LLM には曖昧な 1〜5 点ではなく具体的な Yes/No 項目を返させ、
         最終的な PASS/FAIL は Python コード側の `all(...)` で決定する。
      3. Rogan–Gladen バイアス補正: Judge 自身の感度 $q_1$・特異度 $q_0$ を測定し、
         観測合格率 $p_{\\text{obs}}$ に含まれる採点誤差を補正して「真の合格率 $\\hat{\\theta}$」と「解決 1 件あたり実効コスト」を算出する。
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

from google.adk.agents import LlmAgent
from google.adk.agents.context import Context
from google.adk.apps import App
from google.adk.models.base_llm import BaseLlm
from google.adk.workflow import Workflow, node
from google.genai import types
from pydantic import BaseModel, ValidationError

from shared.config import get_settings


class BinaryJudgeVerdict(BaseModel):
    """Judge モデルが出力する二値（Boolean）構造化ルーブリック。"""

    addresses_all_questions: bool
    factually_consistent: bool
    actionable_guidance: bool
    rationale: str


@dataclass(frozen=True)
class CascadeEconomicsReport:
    """カスケードの期待呼び出し単価と「解決 1 件あたり実効コスト」の評価結果。"""

    expected_cost_per_request_usd: float
    escalation_rate: float
    estimated_true_solve_rate: float
    effective_cost_per_solved_task_usd: float


def rogan_gladen_estimate(
    observed_pass_rate: float,
    sensitivity_q1: float,
    specificity_q0: float,
) -> float:
    """Rogan–Gladen (1978) 推定量により、不完全な Judge の観測合格率から真の合格率 $\\hat{\\theta}$ を補正する。

    数式:
        観測合格率 $p_{\\text{obs}} = \\theta q_1 + (1 - \\theta)(1 - q_0)$ を $\\theta$ について解くと:
            $\\hat{\\theta} = \\operatorname{clip}_{[0, 1]}\\left( \\frac{p_{\\text{obs}} + q_0 - 1}{q_1 + q_0 - 1} \\right)$

    Args:
        observed_pass_rate: Judge が PASS と判定した割合 $p_{\\text{obs}} \\in [0, 1]$。
        sensitivity_q1: 真に PASS の出力を Judge が PASS と判定する確率（感度 $q_1 \\in [0, 1]$）。
        specificity_q0: 真に FAIL の出力を Judge が FAIL と判定する確率（特異度 $q_0 \\in [0, 1]$）。

    Returns:
        `[0.0, 1.0]` にクリップされた真の合格率推定値 $\\hat{\\theta}$。

    Raises:
        ValueError: 確率が範囲外、または $q_1 + q_0 - 1 \\le 0$（ランダム以下の識別力）の場合。
    """
    for name, val in (
        ("observed_pass_rate", observed_pass_rate),
        ("sensitivity_q1", sensitivity_q1),
        ("specificity_q0", specificity_q0),
    ):
        if not (0.0 <= val <= 1.0):
            raise ValueError(f"{name} は 0.0 以上 1.0 以下である必要があります: {val}")

    youden_j = sensitivity_q1 + specificity_q0 - 1.0
    if youden_j <= 0.0:
        raise ValueError(
            f"Judge の識別力 Youden's J (q1 + q0 - 1 = {youden_j:.3f}) が 0 以下のため、"
            "Rogan–Gladen 補正を適用できません。先に Judge プロンプトまたはルーブリックを改善してください。"
        )

    raw_theta = (observed_pass_rate + specificity_q0 - 1.0) / youden_j
    return max(0.0, min(1.0, raw_theta))


def rogan_gladen_confidence_interval(
    observed_passes: int,
    total_samples: int,
    sensitivity_q1: float,
    specificity_q0: float,
    z_value: float = 1.96,
) -> tuple[float, float]:
    """サンプル数 $N$ における Rogan–Gladen 推定値の近似信頼区間（既定 95%）を返す。"""
    if total_samples <= 0 or not (0 <= observed_passes <= total_samples):
        raise ValueError("total_samples >= 1 かつ 0 <= observed_passes <= total_samples が必要です。")

    p_obs = observed_passes / total_samples
    theta_hat = rogan_gladen_estimate(p_obs, sensitivity_q1, specificity_q0)
    youden_j = sensitivity_q1 + specificity_q0 - 1.0
    se_p = math.sqrt(max(0.0, p_obs * (1.0 - p_obs)) / total_samples)
    se_theta = se_p / youden_j
    low = max(0.0, theta_hat - z_value * se_theta)
    high = min(1.0, theta_hat + z_value * se_theta)
    return (round(low, 4), round(high, 4))


def evaluate_cascade_economics(
    *,
    fast_cost_usd: float,
    judge_cost_usd: float,
    strong_cost_usd: float,
    pre_gate_pass_rate: float,
    judge_observed_pass_rate: float,
    judge_q1: float,
    judge_q0: float,
    strong_solve_rate: float,
) -> CascadeEconomicsReport:
    """カスケード全体の期待単価と「解決 1 件あたり実効コスト（Effective Cost per Solved Task）」を算出する。

    ポイント:
        - Pre-Gate で落ちた割合 `(1 - pre_gate_pass_rate)` は Judge 費用を支払わずに直接 Strong へ送る。
        - Pre-Gate を通過したうち Judge が PASS を出したものはそのまま採用されるが、
          Judge の特異度 $q_0 < 1$ により偽陽性（未解決のまま通過）が混入する点を補正して実効解決率を求める。
    """
    true_fast_quality = rogan_gladen_estimate(judge_observed_pass_rate, judge_q1, judge_q0)
    accepted_at_fast = pre_gate_pass_rate * judge_observed_pass_rate
    escalation_rate = 1.0 - accepted_at_fast

    expected_cost = (
        fast_cost_usd
        + (pre_gate_pass_rate * judge_cost_usd)
        + (escalation_rate * strong_cost_usd)
    )

    # Fast 採用分のうち真に解決している確率 = pre_gate_pass_rate * (true_fast_quality * judge_q1)
    true_solved_via_fast = pre_gate_pass_rate * true_fast_quality * judge_q1
    true_solved_via_strong = escalation_rate * strong_solve_rate
    total_solve_rate = min(1.0, max(1e-9, true_solved_via_fast + true_solved_via_strong))

    return CascadeEconomicsReport(
        expected_cost_per_request_usd=round(expected_cost, 6),
        escalation_rate=round(escalation_rate, 4),
        estimated_true_solve_rate=round(total_solve_rate, 4),
        effective_cost_per_solved_task_usd=round(expected_cost / total_solve_rate, 6),
    )


def check_deterministic_pre_gate(draft_text: str, min_chars: int = 40) -> tuple[bool, str]:
    """ミリ秒で完了する決定論的 Pre-Gate（Judge LLM を呼ぶ価値があるかを事前フィルタ）。"""
    stripped = draft_text.strip()
    if len(stripped) < min_chars:
        return False, f"文字数不足 ({len(stripped)} < {min_chars})"
    lowered = stripped.lower()
    for bad_marker in ("todo:", "わかりません", "i cannot answer", "[placeholder]"):
        if bad_marker in lowered:
            return False, f"未完成マーカー検出: {bad_marker}"
    return True, "OK"


def _parse_judge_verdict_fail_closed(raw_text: str) -> tuple[bool, BinaryJudgeVerdict | None]:
    """Judge の JSON を解析し、全二値項目が True のときのみ合格とする（Fail-Closed）。"""
    cleaned = raw_text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, flags=re.DOTALL)
    if fence:
        cleaned = fence.group(1)
    try:
        verdict = BinaryJudgeVerdict.model_validate_json(cleaned)
    except ValidationError:
        return False, None

    passed = (
        verdict.addresses_all_questions
        and verdict.factually_consistent
        and verdict.actionable_guidance
    )
    return passed, verdict


def build_cascade_workflow(
    *,
    fast_model: str | BaseLlm | None = None,
    judge_model: str | BaseLlm | None = None,
    strong_model: str | BaseLlm | None = None,
    min_draft_chars: int = 40,
) -> Workflow:
    """`Fast Tier → Deterministic Pre-Gate → Binary Judge → Conditional Strong Escalation` の Workflow を構築する。"""
    settings = get_settings()
    m_fast = fast_model if fast_model is not None else settings.fast_model
    m_judge = judge_model if judge_model is not None else settings.default_model
    m_strong = strong_model if strong_model is not None else settings.escalation_model

    @node(name="capture_user_request")
    async def capture_user_request(ctx: Context, node_input: Any = None) -> dict[str, str]:
        text = ""
        if isinstance(node_input, types.Content) and node_input.parts:
            text = "".join(p.text or "" for p in node_input.parts)
        elif isinstance(node_input, str):
            text = node_input
        ctx.state["user_query"] = text
        return {"user_query": text}

    fast_kwargs: dict[str, Any] = {
        "name": "fast_drafter_agent",
        "model": m_fast,
        "description": "低遅延・低単価モデルによる一次回答ドラフト生成",
        "instruction": """以下のユーザー質問に対して、簡潔かつ具体的な手順を含む技術回答を作成してください。

質問:
{user_query}
""",
        "output_key": "fast_draft",
    }
    if isinstance(m_fast, str):
        fast_kwargs["generate_content_config"] = types.GenerateContentConfig(
            temperature=0.1,
            thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.MINIMAL),
        )
    fast_drafter = LlmAgent(**fast_kwargs)

    @node(name="deterministic_pre_gate")
    async def deterministic_pre_gate(ctx: Context) -> dict[str, Any]:
        draft = str(ctx.state.get("fast_draft", ""))
        ok, reason = check_deterministic_pre_gate(draft, min_chars=min_draft_chars)
        ctx.state["pre_gate_passed"] = ok
        ctx.state["pre_gate_reason"] = reason
        if not ok:
            # 構造的に不十分なドラフトには Judge トークンすら使わず直接 Strong へ送る
            ctx.state["judge_invoked"] = False
            ctx.route = "ESCALATE_DIRECT"
            return {"pre_gate_passed": False, "reason": reason}
        ctx.state["judge_invoked"] = True
        ctx.route = "RUN_JUDGE"
        return {"pre_gate_passed": True}

    judge_kwargs: dict[str, Any] = {
        "name": "calibrated_judge_agent",
        "model": m_judge,
        "description": "二値ルーブリックで一次回答の妥当性を JSON 判定する Judge エージェント",
        "instruction": """あなたは厳格な品質審査器です。以下の質問に対する一次回答ドラフトを審査し、JSON のみを出力してください。

## 元の質問
{user_query}

## 一次回答ドラフト
{fast_draft}

## 出力 JSON 形式
{
  "addresses_all_questions": true または false,
  "factually_consistent": true または false,
  "actionable_guidance": true または false,
  "rationale": "1文の根拠"
}
""",
        "output_key": "judge_verdict_raw",
    }
    if isinstance(m_judge, str):
        judge_kwargs["generate_content_config"] = types.GenerateContentConfig(
            temperature=0.0,
            thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW),
        )
    judge_agent = LlmAgent(**judge_kwargs)

    @node(name="cascade_router_node")
    async def cascade_router_node(ctx: Context) -> dict[str, Any]:
        raw_verdict = str(ctx.state.get("judge_verdict_raw", ""))
        passed, parsed = _parse_judge_verdict_fail_closed(raw_verdict)
        ctx.state["judge_passed"] = passed
        ctx.state["judge_rationale"] = parsed.rationale if parsed else "invalid_judge_json"
        if passed:
            ctx.state["selected_tier"] = "fast"
            ctx.state["final_answer"] = str(ctx.state.get("fast_draft", ""))
            ctx.route = "ACCEPT_FAST"
            return {"accepted_fast": True}
        ctx.route = "ESCALATE_STRONG"
        return {"accepted_fast": False}

    strong_kwargs: dict[str, Any] = {
        "name": "strong_escalated_agent",
        "model": m_strong,
        "description": "複雑な質問や一次回答不合格時に深い推論で最終回答を生成する上位モデル",
        "instruction": """一次回答が品質基準を満たさなかったため、上位モデルへエスカレーションされました。
以下の質問に対して、前提条件・具体的な実装/運用手順・注意点を含む高品質な回答を作成してください。

質問:
{user_query}
""",
        "output_key": "strong_answer",
    }
    if isinstance(m_strong, str):
        strong_kwargs["generate_content_config"] = types.GenerateContentConfig(
            temperature=0.1,
            thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.HIGH),
        )
    strong_agent = LlmAgent(**strong_kwargs)

    @node(name="finalize_escalated_node")
    async def finalize_escalated_node(ctx: Context) -> dict[str, Any]:
        ctx.state["selected_tier"] = "escalated"
        ctx.state["final_answer"] = str(ctx.state.get("strong_answer", ""))
        return {
            "selected_tier": "escalated",
            "judge_invoked": bool(ctx.state.get("judge_invoked", False)),
            "final_answer": ctx.state["final_answer"],
        }

    @node(name="finalize_fast_node")
    async def finalize_fast_node(ctx: Context) -> dict[str, Any]:
        return {
            "selected_tier": "fast",
            "judge_invoked": True,
            "final_answer": ctx.state["final_answer"],
        }

    return Workflow(
        name="prod04_model_cascade_workflow",
        description="軽量モデルによる一次応答 + 決定論的 Pre-Gate + 二値審査による段階的エスカレーション",
        edges=[
            (
                "START",
                capture_user_request,
                fast_drafter,
                deterministic_pre_gate,
                {
                    "RUN_JUDGE": judge_agent,
                    "ESCALATE_DIRECT": strong_agent,
                },
            ),
            (
                judge_agent,
                cascade_router_node,
                {
                    "ACCEPT_FAST": finalize_fast_node,
                    "ESCALATE_STRONG": strong_agent,
                },
            ),
            (strong_agent, finalize_escalated_node),
        ],
    )


root_agent = build_cascade_workflow()
app = App(name="prod04_model_cascade", root_agent=root_agent)
