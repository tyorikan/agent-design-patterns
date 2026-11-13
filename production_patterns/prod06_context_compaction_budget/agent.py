"""PROD-06: Context Compaction & Budget Guard パターン。

設計の核心:
    1. ステートレス対話における $O(D^2)$ 累積入力トークン膨張の抑制:
       ツールが数千行のログや JSON をそのまま会話履歴へ返すと、以降の全ターンで毎回再課金・再処理される。
       `ArtifactOffloadPlugin`（`after_tool_callback`）が閾値超過のツール出力を `ArtifactService` へ自動退避し、
       会話履歴には短い要約とページング取得ツール（`read_artifact_lines`）の参照ポインタのみを残す。
    2. ADK 2.13 `EventsCompactionConfig` との組み合わせ:
       古いイベント履歴は `EventsCompactionConfig(token_threshold=..., event_retention_size=...)` で要約圧縮し、
       巨大な単発ツール出力は `ArtifactOffloadPlugin` で退避する二段構えでコンテキスト肥大化を防ぐ。
    3. 同期インプロセス予算サーキットブレーカー（`CostBudgetPlugin`）と請求ラベル検証:
       Cloud Billing の予算アラートは非同期通知であり、暴走ループをミリ秒単位で即座に遮断するハードストップにはならない。
       `before_model_callback` / `after_model_callback` でトークン数と推論単価を同期集計し、上限超過時は LLM 呼び出し前に遮断する。
       また、請求ラベルの高カーディナリティ違反（1 キーあたり通算 1,000 種類上限）を事前検証する。
"""

from __future__ import annotations

import json
import math
import re
import warnings
from dataclasses import dataclass
from typing import Any

from google.adk.agents import LlmAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.apps.app import App, EventsCompactionConfig
from google.adk.apps.llm_event_summarizer import LlmEventSummarizer
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.plugins.base_plugin import BasePlugin
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext
from google.genai import types

from shared.config import get_settings

_LABEL_KEY_RE = re.compile(r"^[a-z][a-z0-9_-]{0,62}$")
_LABEL_VAL_RE = re.compile(r"^[a-z0-9_-]{0,63}$")
_HIGH_CARDINALITY_LABEL_KEYS = frozenset(
    {
        "session_id",
        "user_id",
        "request_id",
        "trace_id",
        "invocation_id",
        "conversation_id",
        "turn_id",
        "timestamp",
        "uuid",
    }
)


@dataclass(frozen=True)
class ModelPricing:
    """100 万トークンあたりの USD 単価（global / Standard ティア）。

    注意: Gemini の課金仕様上、出力単価（`output_per_1m`）は思考トークン（`thoughts_token_count`）にも適用される。
    """

    input_per_1m: float
    cached_input_per_1m: float
    output_per_1m: float


# Gemini Enterprise Agent Platform 公開料金（global / Standard ティア、プロモーション期間単価を含む）
VERIFIED_MODEL_PRICING_USD_PER_1M: dict[str, ModelPricing] = {
    "gemini-4-hydrogen": ModelPricing(
        input_per_1m=1.50,
        cached_input_per_1m=0.075,
        output_per_1m=7.50,
    ),
    "gemini-4-carbon": ModelPricing(
        input_per_1m=2.00,
        cached_input_per_1m=0.10,
        output_per_1m=10.00,
    ),
    "gemini-4-argon": ModelPricing(
        input_per_1m=2.00,
        cached_input_per_1m=0.10,
        output_per_1m=10.00,
    ),
    "gemini-3.8-flash": ModelPricing(
        input_per_1m=0.75,
        cached_input_per_1m=0.075,
        output_per_1m=3.75,
    ),
    "gemini-3.5-flash-lite": ModelPricing(
        input_per_1m=0.30,
        cached_input_per_1m=0.03,
        output_per_1m=2.50,
    ),
}


def estimate_cumulative_input_tokens(
    turns: int,
    system_tokens: int,
    turn_tokens: int,
    inline_tool_tokens: int = 0,
) -> int:
    """圧縮・退避を行わないステートレス $D$ ターン対話の累積入力トークン数を算出する。

    数式:
        第 $t$ ターン（$t = 1, \\dots, D$）に送信される入力トークン数は
        $T_{\\text{sys}} + t \\cdot T_{\\text{turn}} + (t - 1) \\cdot T_{\\text{tool}}$ であるため、
        全 $D$ ターンの合計は $O(D^2)$ で増加する:
            $\\text{Total} = D \\cdot T_{\\text{sys}} + \\frac{D(D + 1)}{2} T_{\\text{turn}} + \\frac{D(D - 1)}{2} T_{\\text{tool}}$
    """
    if turns < 0 or system_tokens < 0 or turn_tokens < 0 or inline_tool_tokens < 0:
        raise ValueError("すべての引数は 0 以上である必要があります。")
    return (
        turns * system_tokens
        + (turns * (turns + 1) // 2) * turn_tokens
        + (turns * (turns - 1) // 2) * inline_tool_tokens
    )


def calculate_cache_break_even_calls(
    *,
    input_price_per_1m: float,
    cached_price_per_1m: float,
    storage_price_per_1m_hour: float,
    ttl_hours: float,
) -> int:
    """明示的コンテキストキャッシュ（Explicit Caching）が採算分岐を超える最小呼び出し回数 $K_{\\min}$ を返す。

    数式:
        キャッシュ作成時の入力課金 $P_{\\text{in}}$ + 保持時間 $H$ のストレージ課金 $H \\cdot P_{\\text{storage}}$ +
        $K$ 回のキャッシュ参照課金 $K \\cdot P_{\\text{cached}}$ が、キャッシュなしの $K \\cdot P_{\\text{in}}$ 以下になる条件:
            $P_{\\text{in}} + H \\cdot P_{\\text{storage}} + K \\cdot P_{\\text{cached}} \\le K \\cdot P_{\\text{in}}$
            $\\iff K \\ge \\left\\lceil \\frac{P_{\\text{in}} + H \\cdot P_{\\text{storage}}}{P_{\\text{in}} - P_{\\text{cached}}} \\right\\rceil$
    """
    if cached_price_per_1m < 0 or input_price_per_1m <= cached_price_per_1m:
        raise ValueError("input_price_per_1m > cached_price_per_1m >= 0 が必要です。")
    if storage_price_per_1m_hour < 0 or ttl_hours < 0:
        raise ValueError("storage_price_per_1m_hour >= 0 かつ ttl_hours >= 0 が必要です。")

    savings_per_call = input_price_per_1m - cached_price_per_1m
    creation_and_storage = input_price_per_1m + (ttl_hours * storage_price_per_1m_hour)
    return max(2, math.ceil(creation_and_storage / savings_per_call))


def validate_billing_labels(labels: dict[str, str]) -> tuple[bool, list[str]]:
    """`GenerateContentConfig(labels=...)` に付与する Cloud Billing ラベルの構文とカーディナリティ規約を検証する。

    規約:
        1. ラベル数は最大 64 個まで。
        2. キーは `^[a-z][a-z0-9_-]{0,62}$`、値は `^[a-z0-9_-]{0,63}$`。
        3. Cloud Billing エクスポートでは「1 キーあたり請求先アカウントの存続期間を通じて一意な値は最大 1,000 個」に制限されるため、
           `session_id` や `user_id` などの高カーディナリティ識別子をラベルに入れてはならない（それらは BigQuery Agent Analytics 等で追跡する）。
    """
    errors: list[str] = []
    if len(labels) > 64:
        errors.append(f"ラベル数が上限 64 を超えています: {len(labels)}")

    for key, val in sorted(labels.items()):
        if key in _HIGH_CARDINALITY_LABEL_KEYS or key.endswith(("_id", "_uuid")):
            errors.append(
                f"高カーディナリティキー禁止違反: '{key}' "
                "(Cloud Billing の 1 キーあたり通算 1,000 値上限を枯渇させます)"
            )
        if not _LABEL_KEY_RE.match(key):
            errors.append(f"不正なラベルキー形式: '{key}'")
        if not _LABEL_VAL_RE.match(val):
            errors.append(f"不正なラベル値形式 ({key}): '{val}'")

    return (len(errors) == 0, errors)


class ArtifactOffloadPlugin(BasePlugin):
    """閾値を超える巨大なツール出力を `ArtifactService` へ退避し、会話履歴の肥大化を防ぐプラグイン。"""

    def __init__(
        self,
        *,
        max_inline_chars: int = 800,
        preview_lines: int = 5,
        exempt_tools: set[str] | None = None,
    ) -> None:
        super().__init__(name="artifact_offload_plugin")
        self._max_inline_chars = max_inline_chars
        self._preview_lines = preview_lines
        self._exempt_tools = exempt_tools or {"read_artifact_lines"}
        self.offloaded_count = 0

    async def after_tool_callback(
        self,
        *,
        tool: BaseTool,
        tool_args: dict[str, Any],
        tool_context: ToolContext,
        result: dict[str, Any],
    ) -> dict[str, Any] | None:
        del tool_args
        if tool.name in self._exempt_tools:
            return None

        serialized = json.dumps(result, ensure_ascii=False, indent=2)
        if len(serialized) <= self._max_inline_chars:
            return None

        self.offloaded_count += 1
        filename = f"tool_output_{tool.name}_{self.offloaded_count}.json"
        version = await tool_context.save_artifact(
            filename,
            types.Part.from_text(text=serialized),
        )
        lines = serialized.splitlines()
        preview = "\n".join(lines[: self._preview_lines])
        return {
            "offloaded_to_artifact": filename,
            "artifact_version": version,
            "total_chars": len(serialized),
            "total_lines": len(lines),
            "preview_head": preview,
            "instruction": (
                f"出力が {self._max_inline_chars} 文字を超えたため Artifact '{filename}' に保存しました。"
                "詳細を確認する場合は read_artifact_lines で必要な行範囲のみを取得してください。"
            ),
        }


class CostBudgetPlugin(BasePlugin):
    """トークン消費量と推論コスト（USD）を同期追跡し、予算上限超過時に LLM 呼び出しを即座に遮断するプラグイン。"""

    def __init__(
        self,
        *,
        pricing_model_name: str = "gemini-4-hydrogen",
        max_total_tokens: int = 50_000,
        max_cost_usd: float = 0.10,
        billing_labels: dict[str, str] | None = None,
    ) -> None:
        super().__init__(name="cost_budget_plugin")
        if pricing_model_name not in VERIFIED_MODEL_PRICING_USD_PER_1M:
            raise ValueError(f"未登録の料金モデルです: {pricing_model_name}")

        self._pricing = VERIFIED_MODEL_PRICING_USD_PER_1M[pricing_model_name]
        self._max_total_tokens = max_total_tokens
        self._max_cost_usd = max_cost_usd

        labels = dict(billing_labels or {"env": "prod", "pattern": "prod06"})
        valid, errors = validate_billing_labels(labels)
        if not valid:
            raise ValueError(f"請求ラベル規約違反: {'; '.join(errors)}")
        self._billing_labels = labels

        self.total_prompt_tokens = 0
        self.total_cached_tokens = 0
        self.total_output_tokens = 0
        self.total_thoughts_tokens = 0
        self.accumulated_cost_usd = 0.0
        self.tripped_count = 0

    @property
    def total_tokens(self) -> int:
        return self.total_prompt_tokens + self.total_output_tokens + self.total_thoughts_tokens

    async def before_model_callback(
        self,
        *,
        callback_context: CallbackContext,
        llm_request: LlmRequest,
    ) -> LlmResponse | None:
        if self.total_tokens >= self._max_total_tokens or (
            self.accumulated_cost_usd >= self._max_cost_usd
        ):
            self.tripped_count += 1
            callback_context.state["budget:tripped"] = True
            return LlmResponse(
                content=types.Content(
                    role="model",
                    parts=[
                        types.Part.from_text(
                            text=(
                                "[BUDGET_EXCEEDED] セッションの推論予算上限に到達したため、"
                                f"追加のモデル呼び出しを遮断しました (tokens={self.total_tokens}, "
                                f"cost_usd={self.accumulated_cost_usd:.6f})。"
                            )
                        )
                    ],
                )
            )

        existing_labels = dict(llm_request.config.labels or {})
        existing_labels.update(self._billing_labels)
        llm_request.config.labels = existing_labels
        return None

    async def after_model_callback(
        self,
        *,
        callback_context: CallbackContext,
        llm_response: LlmResponse,
    ) -> LlmResponse | None:
        usage = llm_response.usage_metadata
        if usage is None:
            return None

        prompt_tokens = int(usage.prompt_token_count or 0)
        cached_tokens = int(usage.cached_content_token_count or 0)
        non_cached_prompt = max(0, prompt_tokens - cached_tokens)
        output_tokens = int(usage.candidates_token_count or 0)
        thoughts_tokens = int(usage.thoughts_token_count or 0)

        step_cost = (
            (non_cached_prompt / 1_000_000.0) * self._pricing.input_per_1m
            + (cached_tokens / 1_000_000.0) * self._pricing.cached_input_per_1m
            + ((output_tokens + thoughts_tokens) / 1_000_000.0) * self._pricing.output_per_1m
        )

        self.total_prompt_tokens += prompt_tokens
        self.total_cached_tokens += cached_tokens
        self.total_output_tokens += output_tokens
        self.total_thoughts_tokens += thoughts_tokens
        self.accumulated_cost_usd = round(self.accumulated_cost_usd + step_cost, 8)

        callback_context.state["budget:total_tokens"] = self.total_tokens
        callback_context.state["budget:cost_usd"] = self.accumulated_cost_usd
        return None


# =============================================================================
# ログ調査エージェント用のツール群（大容量出力ツール + Artifact ページング取得ツール）
# =============================================================================


def fetch_incident_log_dump(service_name: str, line_count: int = 120) -> dict[str, Any]:
    """障害調査対象のサービスログを取得する（意図的に大容量ペイロードを返すデモ用ツール）。"""
    safe_count = max(1, min(line_count, 500))
    entries = []
    for idx in range(1, safe_count + 1):
        level = "ERROR" if idx == safe_count // 2 else "INFO"
        msg = (
            "DB connection pool exhausted (max_connections=100)"
            if level == "ERROR"
            else f"Processed health probe seq={idx} latency_ms=12"
        )
        entries.append(f"2026-11-02T03:00:{idx % 60:02d}Z [{level}] {service_name}: {msg}")
    return {
        "service_name": service_name,
        "entry_count": safe_count,
        "entries": entries,
    }


async def read_artifact_lines(
    artifact_name: str,
    start_line: int,
    max_lines: int,
    tool_context: ToolContext,
) -> dict[str, Any]:
    """`ArtifactService` に退避された大容量出力から、指定した行範囲（1 始まり）のみを読み出す。"""
    part = await tool_context.load_artifact(artifact_name)
    if part is None or part.text is None:
        return {"found": False, "error": f"Artifact が見つかりません: {artifact_name}"}

    all_lines = part.text.splitlines()
    start_idx = max(0, start_line - 1)
    bounded_count = max(1, min(max_lines, 80))
    sliced = all_lines[start_idx : start_idx + bounded_count]
    return {
        "found": True,
        "artifact_name": artifact_name,
        "start_line": start_idx + 1,
        "returned_lines": len(sliced),
        "total_lines": len(all_lines),
        "content": "\n".join(sliced),
    }


def build_compacted_budget_app(
    *,
    model: str | BaseLlm | None = None,
    summarizer_model: BaseLlm | None = None,
    max_inline_chars: int = 800,
    max_total_tokens: int = 50_000,
    max_cost_usd: float = 0.10,
    compaction_token_threshold: int = 32_000,
    compaction_retention_size: int = 4,
    billing_labels: dict[str, str] | None = None,
) -> tuple[App, ArtifactOffloadPlugin, CostBudgetPlugin]:
    """`EventsCompactionConfig` + `ArtifactOffloadPlugin` + `CostBudgetPlugin` を統合した `App` を構築する。"""
    settings = get_settings()
    active_model = model if model is not None else settings.default_model

    agent_kwargs: dict[str, Any] = {
        "name": "log_diagnostics_agent",
        "model": active_model,
        "description": "大容量ログを Artifact 退避しつつ予算上限内で原因特定を行う診断エージェント。",
        "instruction": """あなたは本番障害のログ診断エージェントです。

1. `fetch_incident_log_dump` でログを取得してください。
2. 出力が Artifact に退避された場合は、全文を一度に読もうとせず `read_artifact_lines` で必要な行範囲のみを確認してください。
3. 特定したエラー原因と推奨対処を簡潔に報告してください。
""",
        "tools": [fetch_incident_log_dump, read_artifact_lines],
    }
    if isinstance(active_model, str):
        agent_kwargs["generate_content_config"] = types.GenerateContentConfig(
            thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW),
        )
    agent = LlmAgent(**agent_kwargs)

    offload_plugin = ArtifactOffloadPlugin(max_inline_chars=max_inline_chars)
    budget_plugin = CostBudgetPlugin(
        max_total_tokens=max_total_tokens,
        max_cost_usd=max_cost_usd,
        billing_labels=billing_labels,
    )

    compaction_kwargs: dict[str, Any] = {
        "token_threshold": compaction_token_threshold,
        "event_retention_size": compaction_retention_size,
    }
    if summarizer_model is not None:
        compaction_kwargs["summarizer"] = LlmEventSummarizer(llm=summarizer_model)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        compaction_cfg = EventsCompactionConfig(**compaction_kwargs)
        compacted_app = App(
            name="prod06_context_compaction_budget",
            root_agent=agent,
            plugins=[offload_plugin, budget_plugin],
            events_compaction_config=compaction_cfg,
        )

    return compacted_app, offload_plugin, budget_plugin


app, _default_offload_plugin, _default_budget_plugin = build_compacted_budget_app()
assert app.root_agent is not None
root_agent = app.root_agent
