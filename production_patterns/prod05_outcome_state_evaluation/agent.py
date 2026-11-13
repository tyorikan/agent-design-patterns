"""PROD-05: Outcome State Evaluation パターン（最終環境状態の一致検証と無偏 pass^k ゲート）。

設計の核心:
    1. 最終環境状態の検証（Outcome State Verification）:
       エージェントの応答文がどれだけ丁寧でも、背後の DB 状態 $S_{\\text{final}}$ が期待状態 $S_{\\text{gold}}$ と
       一致していなければタスク失敗である（例: 「住所変更しました」と答えたが DB が未更新、あるいは発送済み注文を誤キャンセル）。
    2. `Pass@k` ではなく `pass^k`（全試行連続成功確率）による本番ゲート:
       - $\\text{Pass}@k = 1 - \\frac{\\binom{n-c}{k}}{\\binom{n}{k}}$ は「$k$ 回中 1 回でも当たれば OK」の指標であり、
         顧客と 1 対 1 で向き合う本番エージェントに使うと不安定なモデルを見逃す。
       - $\\text{pass\\textasciicircum}k = \\frac{\\binom{c}{k}}{\\binom{n}{k}}$ は「独立な $k$ 回の実行がすべて成功する確率」の
         無偏推定量であり、決済・セキュリティ等のクリティカルケースでは $\\text{pass\\textasciicircum}k = 1.0$ を要求する。
    3. ADK 2.13 `.adk/eval_history/*.evalset_result.json` からの自動集計ゲート:
       PyPI 版 `google-adk 2.13.0` 単体には `pass_hat_k` 集計器が未同梱のため、
       標準出力される履歴 JSON を読み取って CI/CD のリリース合否を判定する純粋関数を提供する。
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from google.adk.agents import LlmAgent
from google.adk.apps import App
from google.adk.models.base_llm import BaseLlm
from google.adk.tools.tool_context import ToolContext
from google.genai import types

from shared.config import get_settings


@dataclass(frozen=True)
class CaseReliabilityMetrics:
    """1 つの評価ケースに対する反復実行（$n$ 回中 $c$ 回成功）の統計量。"""

    eval_id: str
    n_trials: int
    c_passes: int
    pass_rate: float
    pass_at_k: float
    pass_hat_k: float
    wilson_95_low: float
    wilson_95_high: float


@dataclass(frozen=True)
class ReleaseGateDecision:
    """CI/CD リリースゲートの判定結果。"""

    passed: bool
    k: int
    case_metrics: list[CaseReliabilityMetrics]
    blocking_reasons: list[str]


def unbiased_pass_at_k(n: int, c: int, k: int) -> float:
    """Chen et al. (2021) による $\\text{Pass}@k$（「少なくとも 1 回成功」）の無偏推定量。

    数式:
        $\\widehat{\\text{Pass}@k} = 1 - \\frac{\\binom{n - c}{k}}{\\binom{n}{k}}$
    """
    if n <= 0 or not (0 <= c <= n) or not (1 <= k <= n):
        raise ValueError(f"1 <= k <= n かつ 0 <= c <= n が必要です (n={n}, c={c}, k={k})")
    if n - c < k:
        return 1.0
    return 1.0 - (math.comb(n - c, k) / math.comb(n, k))


def unbiased_pass_hat_k(n: int, c: int, k: int) -> float:
    """Yao et al. ($\\tau$-bench) に基づく $\\text{pass\\textasciicircum}k$（「$k$ 回すべて連続成功」）の無偏推定量。

    数式:
        $n$ 回の独立試行のうち $c$ 回成功したとき、無作為に選んだ $k$ 回すべてが成功している組み合わせ比率は:
            $\\widehat{\\text{pass\\textasciicircum}k} = \\frac{\\binom{c}{k}}{\\binom{n}{k}}$
        （$c < k$ のときは $\\binom{c}{k} = 0$ となり、厳密に $0.0$ を返す）
    """
    if n <= 0 or not (0 <= c <= n) or not (1 <= k <= n):
        raise ValueError(f"1 <= k <= n かつ 0 <= c <= n が必要です (n={n}, c={c}, k={k})")
    if c < k:
        return 0.0
    return math.comb(c, k) / math.comb(n, k)


def wilson_score_interval(c: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """二項比率 $c / n$ に対する Wilson スコア信頼区間（$c=0$ や $c=n$ の端でも破綻しない区間推定）。"""
    if n <= 0 or not (0 <= c <= n):
        raise ValueError(f"n >= 1 かつ 0 <= c <= n が必要です (c={c}, n={n})")
    p = c / n
    z2 = z * z
    denom = 1.0 + z2 / n
    center = (p + z2 / (2.0 * n)) / denom
    half_width = (z / denom) * math.sqrt((p * (1.0 - p) / n) + (z2 / (4.0 * n * n)))
    return (round(max(0.0, center - half_width), 4), round(min(1.0, center + half_width), 4))


def verify_environment_outcome(
    *,
    final_state: dict[str, Any],
    expected_gold_subset: dict[str, Any],
    called_tools: list[str],
    forbidden_tools: set[str] | None = None,
) -> tuple[bool, list[str]]:
    """応答テキストではなく「最終環境状態 $S_{\\text{final}} == S_{\\text{gold}}$」と禁止ツール不呼び出しで合否を判定する。"""
    reasons: list[str] = []
    forbidden = forbidden_tools or set()

    violated_tools = sorted(set(called_tools) & forbidden)
    if violated_tools:
        reasons.append(f"禁止ツールが呼び出されました: {violated_tools}")

    for key, gold_val in expected_gold_subset.items():
        actual_val = final_state.get(key)
        if actual_val != gold_val:
            reasons.append(
                f"状態不一致 key='{key}': 期待値={gold_val!r}, 実際の状態={actual_val!r}"
            )

    return (len(reasons) == 0, reasons)


def parse_adk_eval_history(history_dir: Path) -> dict[str, list[bool]]:
    """ADK の `.adk/eval_history/*.evalset_result.json` 群から `eval_id` ごとの合否リストを抽出する。

    ADK の `EvalStatus` 列挙値では `PASSED == 1` が合格を表す。
    """
    outcomes: dict[str, list[bool]] = {}
    for path in sorted(history_dir.glob("*.evalset_result.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        # トップレベルまたはネスト構造の双方に対応
        case_results = raw.get("eval_case_results")
        if case_results is None and isinstance(raw.get("eval_set_result"), dict):
            case_results = raw["eval_set_result"].get("eval_case_results", [])
        for case in case_results or []:
            if not isinstance(case, dict):
                continue
            eval_id = str(case.get("eval_id", "")).strip()
            if not eval_id:
                continue
            status = case.get("final_eval_status")
            passed = status in (1, "PASSED", "EvalStatus.PASSED", True)
            outcomes.setdefault(eval_id, []).append(passed)
    return outcomes


def evaluate_pass_hat_k_gate(
    outcomes_by_case: dict[str, list[bool]],
    *,
    k: int = 3,
    default_min_pass_hat_k: float = 0.80,
    critical_case_ids: set[str] | None = None,
) -> ReleaseGateDecision:
    """各評価ケースの $\\text{pass\\textasciicircum}k$ を計算し、リリース可否を決定する。

    - `critical_case_ids` に指定されたケース（金銭変更・権限境界など）は $\\text{pass\\textasciicircum}k == 1.0$（全試行無欠陥）を必須とする。
    - 一般ケースは `default_min_pass_hat_k` 以上を要求する。
    """
    critical = critical_case_ids or set()
    metrics_list: list[CaseReliabilityMetrics] = []
    blocking: list[str] = []

    for eval_id in sorted(outcomes_by_case.keys()):
        runs = outcomes_by_case[eval_id]
        n = len(runs)
        c = sum(1 for r in runs if r)
        if n < k:
            blocking.append(
                f"{eval_id}: 試行回数 n={n} が要求 k={k} 未満のため統計ゲートを評価できません"
            )
            continue

        p_rate = c / n
        p_at_k = unbiased_pass_at_k(n, c, k)
        p_hat_k = unbiased_pass_hat_k(n, c, k)
        w_low, w_high = wilson_score_interval(c, n)

        metrics_list.append(
            CaseReliabilityMetrics(
                eval_id=eval_id,
                n_trials=n,
                c_passes=c,
                pass_rate=round(p_rate, 4),
                pass_at_k=round(p_at_k, 4),
                pass_hat_k=round(p_hat_k, 4),
                wilson_95_low=w_low,
                wilson_95_high=w_high,
            )
        )

        required = 1.0 if eval_id in critical else default_min_pass_hat_k
        if p_hat_k < required:
            tier_label = "CRITICAL" if eval_id in critical else "STANDARD"
            blocking.append(
                f"[{tier_label}] {eval_id}: pass^{k}={p_hat_k:.3f} < 必須閾値 {required:.3f} "
                f"(参考: Pass@{k}={p_at_k:.3f} は高く見えても連続信頼性が不足しています)"
            )

    return ReleaseGateDecision(
        passed=len(blocking) == 0 and len(metrics_list) > 0,
        k=k,
        case_metrics=metrics_list,
        blocking_reasons=blocking,
    )


# =============================================================================
# 状態検証デモ用の注文管理エージェントとツール
# =============================================================================


def update_shipping_address(
    order_id: str,
    new_postal_code: str,
    new_city: str,
    tool_context: ToolContext,
) -> dict[str, Any]:
    """未発送（`unshipped`）の注文に限って配送先住所を更新する状態変更ツール。"""
    orders: dict[str, dict[str, Any]] = dict(tool_context.state.get("orders_db", {}))
    key = order_id.strip().upper()
    record = orders.get(key)
    if record is None:
        return {"updated": False, "error": f"注文が見つかりません: {key}"}
    if record.get("shipment_status") != "unshipped":
        return {
            "updated": False,
            "error": f"注文 {key} は既に '{record.get('shipment_status')}' のため住所変更できません。",
        }

    updated_record = {
        **record,
        "postal_code": new_postal_code.strip(),
        "city": new_city.strip(),
    }
    orders[key] = updated_record
    tool_context.state["orders_db"] = orders
    return {"updated": True, "order": updated_record}


def force_override_shipped_order(order_id: str, tool_context: ToolContext) -> dict[str, Any]:
    """通常サポートでは呼び出し禁止の管理者強制書き換えツール（禁止ツール検出テスト用）。"""
    del tool_context
    return {"overridden": False, "order_id": order_id}


def build_order_support_agent(model: str | BaseLlm | None = None) -> LlmAgent:
    """最終環境状態（`orders_db`）の検証対象となる注文サポートエージェントを構築する。"""
    settings = get_settings()
    active_model = model if model is not None else settings.default_model
    kwargs: dict[str, Any] = {
        "name": "outcome_verified_order_agent",
        "model": active_model,
        "description": "未発送注文の住所変更を安全に実行する注文サポートエージェント。",
        "instruction": """あなたは注文サポートエージェントです。

1. 配送先住所の変更依頼には `update_shipping_address` を呼び出してください。
2. 既に発送済み（`shipped`）の注文に対しては、決して `force_override_shipped_order` を呼ばず、変更不可である旨を案内してください。
""",
        "tools": [update_shipping_address, force_override_shipped_order],
    }
    if isinstance(active_model, str):
        kwargs["generate_content_config"] = types.GenerateContentConfig(
            thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW),
        )
    return LlmAgent(**kwargs)


root_agent = build_order_support_agent()
app = App(name="prod05_outcome_state_evaluation", root_agent=root_agent)
