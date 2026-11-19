"""製品非依存の推論バックエンド抽象と差し替え可能ルーティング戦略モジュール。

設計の核心:
    1. バックエンド抽象 (`InferenceBackend` Protocol):
       推論エンジンやクラウド API の詳細をゲートウェイ背後に隠蔽し、エージェント本体から
       プロバイダ資格情報・物理エンドポイント URL を完全に分離する。
    2. 差し替え可能なルーティング戦略 (`RoutingStrategy` Protocol):
       - `FailoverRoutingStrategy`: 一時障害 (`429`/`502`/`503`/`504`) の連続発生で
         サーキットブレーカーを開放し、自動でセカンダリバックエンドへフェイルオーバーする。
         一定時間経過後はハーフオープン状態で回復確認を行う。
       - `PrefixLoadAwareRoutingStrategy`: 共有推論プール向けに、プロンプト先頭プレフィックスの
         キャッシュ親和性と待機キュー長を重み付けスコアリングし、最適なバックエンドを選出する。
         キュー飽和・不健全・サーキット開放中のバックエンドは候補から除外する。
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from shared.config import get_settings

RequestPriority = Literal["critical", "standard", "batch"]
RETRYABLE_STATUS_CODES = frozenset({429, 502, 503, 504})


@dataclass(frozen=True)
class ChatMessage:
    """ゲートウェイ HTTP 契約でやり取りする標準メッセージ。"""

    role: str
    content: str


@dataclass(frozen=True)
class InferenceRequest:
    """ゲートウェイがバックエンドへ転送する推論リクエスト。"""

    logical_model: str
    messages: tuple[ChatMessage, ...]
    tenant_id: str
    priority: RequestPriority = "standard"
    prefix_key: str = ""
    max_output_tokens: int | None = None
    temperature: float | None = None


@dataclass(frozen=True)
class TokenUsage:
    """推論バックエンドが返却する確定トークン内訳。"""

    input_tokens: int
    output_tokens: int
    cached_input_tokens: int = 0
    thought_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens + self.thought_tokens


@dataclass(frozen=True)
class InferenceResult:
    """推論バックエンドの応答およびレイテンシ計測結果。"""

    backend_id: str
    physical_model: str
    content: str
    usage: TokenUsage
    ttft_seconds: float
    duration_seconds: float


class InferenceBackendError(Exception):
    """バックエンド呼び出し時の構造化エラー。"""

    def __init__(
        self,
        message: str,
        *,
        status_code: int = 503,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retry_after_seconds = retry_after_seconds

    @property
    def is_retryable(self) -> bool:
        return self.status_code in RETRYABLE_STATUS_CODES


class InferenceBackend(Protocol):
    """ゲートウェイ背後に接続する推論バックエンドの抽象契約。"""

    @property
    def backend_id(self) -> str: ...

    @property
    def physical_model(self) -> str: ...

    async def invoke(
        self,
        request: InferenceRequest,
        *,
        credential_ref: str,
    ) -> InferenceResult: ...


@dataclass
class BackendEndpoint:
    """ゲートウェイが管理するバックエンド 1 インスタンスの動的状態。"""

    backend_id: str
    logical_model: str
    backend: InferenceBackend
    credential_ref: str = "gateway-managed-credential"
    priority_order: int = 0
    max_queue_depth: int = 16
    queue_depth: int = 0
    cached_prefixes: set[str] = field(default_factory=set)
    healthy: bool = True
    failure_count: int = 0
    circuit_open_until: float | None = None

    def is_circuit_open(self, now: float) -> bool:
        """現在時刻 `now` においてサーキットブレーカーが開放中 (呼出不可) かを返す。"""
        if self.circuit_open_until is None:
            return False
        return now < self.circuit_open_until

    def record_success(self, *, prefix_key: str = "") -> None:
        """成功時にサーキットを閉鎖し、プレフィックスキャッシュを温める。"""
        self.failure_count = 0
        self.circuit_open_until = None
        if prefix_key:
            self.cached_prefixes.add(prefix_key)

    def record_transient_failure(
        self,
        *,
        now: float,
        failure_threshold: int,
        recovery_timeout_seconds: float,
    ) -> bool:
        """一時障害を記録し、閾値到達時にサーキットを開放する。開放したかを返す。"""
        self.failure_count += 1
        if self.failure_count >= max(1, failure_threshold):
            self.circuit_open_until = now + max(0.1, recovery_timeout_seconds)
            return True
        return False


class RoutingStrategy(Protocol):
    """論理モデルに紐づくバックエンド候補から、試行順序を決定する抽象契約。"""

    @property
    def name(self) -> str: ...

    def select_candidates(
        self,
        endpoints: list[BackendEndpoint],
        request: InferenceRequest,
        *,
        now: float,
    ) -> list[BackendEndpoint]: ...


class FailoverRoutingStrategy:
    """プライマリ/セカンダリ優先順とサーキットブレーカーに基づく自動フェイルオーバー戦略。"""

    @property
    def name(self) -> str:
        return "failover_circuit_breaker"

    def select_candidates(
        self,
        endpoints: list[BackendEndpoint],
        request: InferenceRequest,
        *,
        now: float,
    ) -> list[BackendEndpoint]:
        del request
        eligible = [
            ep
            for ep in endpoints
            if ep.healthy
            and not ep.is_circuit_open(now)
            and ep.queue_depth < ep.max_queue_depth
        ]
        eligible.sort(key=lambda ep: (ep.priority_order, ep.queue_depth, ep.backend_id))
        return eligible


def compute_prefix_affinity(prefix_key: str, cached_prefixes: set[str]) -> float:
    """リクエストの `prefix_key` とバックエンド保持プレフィックス群の最大前方一致率 [0.0, 1.0] を算出する。"""
    if not prefix_key or not cached_prefixes:
        return 0.0
    if prefix_key in cached_prefixes:
        return 1.0

    best_ratio = 0.0
    req_len = len(prefix_key)
    for cached in cached_prefixes:
        if not cached:
            continue
        common = 0
        limit = min(req_len, len(cached))
        while common < limit and prefix_key[common] == cached[common]:
            common += 1
        ratio = common / req_len
        if ratio > best_ratio:
            best_ratio = ratio
    return best_ratio


class PrefixLoadAwareRoutingStrategy:
    """プレフィックス親和性 (キャッシュ一致率) と待機キュー長を重み付け評価するルーティング戦略。

    スコア式:
        S(b) = w_prefix * prefix_hit(b) - w_load * (queue_depth(b) / max_queue_depth(b))

    キューが飽和 (`queue_depth >= max_queue_depth`) またはサーキット開放中のバックエンドは
    候補から除外する。
    """

    def __init__(
        self,
        *,
        prefix_weight: float = 0.65,
        load_weight: float = 0.35,
    ) -> None:
        if prefix_weight < 0 or load_weight < 0:
            raise ValueError("重み係数は 0 以上を指定してください。")
        self._prefix_weight = prefix_weight
        self._load_weight = load_weight

    @property
    def name(self) -> str:
        return "prefix_and_load_aware"

    def score_endpoint(self, endpoint: BackendEndpoint, prefix_key: str) -> float:
        """単一バックエンドのルーティングスコアを算出する。"""
        prefix_hit = compute_prefix_affinity(prefix_key, endpoint.cached_prefixes)
        normalized_load = endpoint.queue_depth / max(1, endpoint.max_queue_depth)
        return (self._prefix_weight * prefix_hit) - (self._load_weight * normalized_load)

    def select_candidates(
        self,
        endpoints: list[BackendEndpoint],
        request: InferenceRequest,
        *,
        now: float,
    ) -> list[BackendEndpoint]:
        eligible = [
            ep
            for ep in endpoints
            if ep.healthy
            and not ep.is_circuit_open(now)
            and ep.queue_depth < ep.max_queue_depth
        ]
        # スコア降順、同点時はキュー長昇順・priority_order 昇順・ID 昇順で決定論的に整列
        eligible.sort(
            key=lambda ep: (
                -self.score_endpoint(ep, request.prefix_key),
                ep.queue_depth,
                ep.priority_order,
                ep.backend_id,
            )
        )
        return eligible


class MockInferenceBackend:
    """オフライン単体・結合テスト用の決定論的バックエンド。障害注入やレイテンシ再現に対応。"""

    def __init__(
        self,
        *,
        backend_id: str,
        physical_model: str = "mock-model-v1",
        response_prefix: str = "",
        failure_script: list[int] | None = None,
        input_tokens: int = 120,
        output_tokens: int = 60,
        cached_input_tokens: int = 0,
        thought_tokens: int = 20,
        simulated_latency_seconds: float = 0.0,
    ) -> None:
        self._backend_id = backend_id
        self._physical_model = physical_model
        self._response_prefix = response_prefix
        self._failure_script = list(failure_script or [])
        self._input_tokens = input_tokens
        self._output_tokens = output_tokens
        self._cached_input_tokens = cached_input_tokens
        self._thought_tokens = thought_tokens
        self._simulated_latency_seconds = simulated_latency_seconds
        self.received_credentials: list[str] = []
        self.call_count: int = 0

    @property
    def backend_id(self) -> str:
        return self._backend_id

    @property
    def physical_model(self) -> str:
        return self._physical_model

    async def invoke(
        self,
        request: InferenceRequest,
        *,
        credential_ref: str,
    ) -> InferenceResult:
        self.call_count += 1
        self.received_credentials.append(credential_ref)
        if self._simulated_latency_seconds > 0:
            await asyncio.sleep(self._simulated_latency_seconds)

        if self._failure_script:
            status = self._failure_script.pop(0)
            if status >= 400:
                raise InferenceBackendError(
                    f"バックエンド {self._backend_id} が HTTP {status} を返却しました。",
                    status_code=status,
                    retry_after_seconds=2.0 if status in {429, 503} else None,
                )

        last_user = next(
            (m.content for m in reversed(request.messages) if m.role == "user"),
            "",
        )
        prefix = f"[{self._response_prefix}] " if self._response_prefix else ""
        text = f"{prefix}{self._backend_id} ({self._physical_model}) からの応答: {last_user}"
        return InferenceResult(
            backend_id=self._backend_id,
            physical_model=self._physical_model,
            content=text,
            usage=TokenUsage(
                input_tokens=self._input_tokens,
                output_tokens=self._output_tokens,
                cached_input_tokens=self._cached_input_tokens,
                thought_tokens=self._thought_tokens,
            ),
            ttft_seconds=0.05,
            duration_seconds=0.12,
        )


class GeminiInferenceBackend:
    """実モデル呼び出しをゲートウェイ内部にのみ閉じ込めるバックエンド実装。

    エージェント本体にはプロバイダ資格情報を渡さず、ゲートウェイプロセス内でのみ
    `google.genai.Client` を遅延初期化する。
    """

    def __init__(
        self,
        *,
        backend_id: str,
        physical_model: str,
        thinking_level: str = "LOW",
    ) -> None:
        self._backend_id = backend_id
        self._physical_model = physical_model
        self._thinking_level = thinking_level
        self._client: Any = None

    @property
    def backend_id(self) -> str:
        return self._backend_id

    @property
    def physical_model(self) -> str:
        return self._physical_model

    def _get_client(self) -> Any:
        if self._client is None:
            from google import genai

            settings = get_settings()
            self._client = genai.Client(
                enterprise=settings.google_genai_use_enterprise,
                project=settings.google_cloud_project,
                location=settings.google_cloud_location,
            )
        return self._client

    async def invoke(
        self,
        request: InferenceRequest,
        *,
        credential_ref: str,
    ) -> InferenceResult:
        del credential_ref
        from google.genai import types

        client = self._get_client()
        system_parts = [m.content for m in request.messages if m.role == "system"]
        contents: list[types.Content] = []
        for msg in request.messages:
            if msg.role == "system":
                continue
            role = "model" if msg.role in {"assistant", "model"} else "user"
            contents.append(types.Content(role=role, parts=[types.Part.from_text(text=msg.content)]))

        config_kwargs: dict[str, Any] = {
            "thinking_config": types.ThinkingConfig(
                thinking_level=getattr(types.ThinkingLevel, self._thinking_level)
            )
        }
        if system_parts:
            config_kwargs["system_instruction"] = "\n".join(system_parts)
        if request.max_output_tokens is not None:
            config_kwargs["max_output_tokens"] = request.max_output_tokens
        if request.temperature is not None:
            config_kwargs["temperature"] = request.temperature

        start = time.monotonic()
        try:
            response = await client.aio.models.generate_content(
                model=self._physical_model,
                contents=contents,
                config=types.GenerateContentConfig(**config_kwargs),
            )
        except Exception as exc:
            status = getattr(exc, "code", None)
            code = int(status) if isinstance(status, int) and 400 <= status < 600 else 503
            raise InferenceBackendError(
                f"実モデルバックエンド {self._backend_id} の呼び出しに失敗しました: {exc}",
                status_code=code,
            ) from exc
        elapsed = time.monotonic() - start

        text = response.text or ""
        um = response.usage_metadata
        usage = TokenUsage(
            input_tokens=int(getattr(um, "prompt_token_count", 0) or 0),
            output_tokens=int(getattr(um, "candidates_token_count", 0) or 0),
            cached_input_tokens=int(getattr(um, "cached_content_token_count", 0) or 0),
            thought_tokens=int(getattr(um, "thoughts_token_count", 0) or 0),
        )
        return InferenceResult(
            backend_id=self._backend_id,
            physical_model=self._physical_model,
            content=text,
            usage=usage,
            ttft_seconds=elapsed,
            duration_seconds=elapsed,
        )
