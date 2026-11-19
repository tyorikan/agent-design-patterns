"""製品非依存 AI Gateway コアおよび標準 HTTP エンドポイント層 (FastAPI ASGI)。

設計の核心:
    1. テナント認証・認可と資格情報隔離:
       エージェントはゲートウェイ発行のテナントトークン (SHA-256 + 定数時間比較) のみを提示し、
       プロバイダ資格情報はゲートウェイ内部でのみ注入する。
    2. 2 段階トークン基準レート制限 (Reserve -> Settle) と優先度シェディング:
       `asyncio.Lock` 下で呼出前に推定入力トークンを予約し、レスポンス確定後に実測の
       重み付きトークンコスト (入力・キャッシュ・出力・思考) へ精算する。
       テナント枠または共有プール枠が閾値を超えた場合、`batch` 優先度を先行して `HTTP 429`
       で遮断し、`critical` / `standard` 対話を保護する。
    3. Model Discovery (`GET /v1/models`) と Body-Based Routing (`POST /v1/chat/completions`):
       パスではなくリクエスト JSON の `model` フィールドを見てルーティング戦略を適用し、
       一時障害 (`429`/`502`/`503`/`504`) 時はサーキットブレーカーを更新して自動フェイルオーバーする。
    4. OpenTelemetry GenAI Semantic Conventions 準拠の横断メトリクス・会計台帳:
       複数エージェント・複数テナントの全利用量・TTFT・フェイルオーバー回数を単一通過点で集計する。
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Response
from pydantic import BaseModel, Field

from production_patterns.prod08_ai_gateway_mediation.routing import (
    BackendEndpoint,
    ChatMessage,
    FailoverRoutingStrategy,
    InferenceBackendError,
    InferenceRequest,
    InferenceResult,
    RequestPriority,
    RoutingStrategy,
    TokenUsage,
)


def hash_api_key(raw_key: str) -> str:
    """API トークンの SHA-256 ダイジェストを返す (生トークンをログやメモリ比較へ露出しない)。"""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class TokenCostWeights:
    """トークン種別ごとの重み係数 (出力・思考トークンの計算コスト差をレート制限へ反映する)。"""

    input_weight: float = 1.0
    cached_input_weight: float = 0.1
    output_weight: float = 4.0
    thought_weight: float = 4.0

    def compute_weighted_tokens(self, usage: TokenUsage) -> int:
        """確定トークン内訳から重み付き実効トークン消費量を算出する。"""
        non_cached_input = max(0, usage.input_tokens - usage.cached_input_tokens)
        weighted = (
            non_cached_input * self.input_weight
            + usage.cached_input_tokens * self.cached_input_weight
            + usage.output_tokens * self.output_weight
            + usage.thought_tokens * self.thought_weight
        )
        return max(1, math.ceil(weighted))


@dataclass(frozen=True)
class TenantPolicy:
    """マルチテナント制御ポリシー。"""

    tenant_id: str
    api_key_hash: str
    allowed_models: frozenset[str]
    token_budget_per_window: int
    window_seconds: int = 60
    shedding_utilization_threshold: float = 0.75

    @classmethod
    def from_raw_key(
        cls,
        *,
        tenant_id: str,
        raw_api_key: str,
        allowed_models: set[str] | frozenset[str],
        token_budget_per_window: int,
        window_seconds: int = 60,
        shedding_utilization_threshold: float = 0.75,
    ) -> TenantPolicy:
        return cls(
            tenant_id=tenant_id,
            api_key_hash=hash_api_key(raw_api_key),
            allowed_models=frozenset(allowed_models),
            token_budget_per_window=token_budget_per_window,
            window_seconds=window_seconds,
            shedding_utilization_threshold=shedding_utilization_threshold,
        )


@dataclass(frozen=True)
class RateLimitDecision:
    """レート制限および優先度アドミッションの判定結果。"""

    allowed: bool
    limit: int
    remaining: int
    reset_epoch_seconds: int
    retry_after_seconds: int | None = None
    reason: str = ""
    reserved_tokens: int = 0
    shed_due_to_priority: bool = False
    tenant_window_start: float | None = None
    shared_window_start: float | None = None

    def to_headers(self) -> dict[str, str]:
        headers = {
            "X-RateLimit-Limit": str(self.limit),
            "X-RateLimit-Remaining": str(max(0, self.remaining)),
            "X-RateLimit-Reset": str(self.reset_epoch_seconds),
        }
        if self.retry_after_seconds is not None:
            headers["Retry-After"] = str(max(1, self.retry_after_seconds))
        return headers


@dataclass
class _WindowCounter:
    window_start: float
    used_tokens: int = 0


class TokenRateLimiter:
    """2 段階 (Reserve -> Settle) トークン基準レート制限および優先度シェディング制御器。"""

    def __init__(
        self,
        *,
        tenants: dict[str, TenantPolicy],
        shared_pool_budget: int | None = None,
        shared_pool_window_seconds: int = 60,
        shared_shedding_threshold: float = 0.75,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._tenants = dict(tenants)
        self._shared_pool_budget = shared_pool_budget
        self._shared_pool_window = shared_pool_window_seconds
        self._shared_shedding_threshold = shared_shedding_threshold
        self._clock = clock
        self._lock = asyncio.Lock()
        self._tenant_windows: dict[str, _WindowCounter] = {}
        self._shared_window: _WindowCounter | None = None

    def _get_or_roll_window(
        self,
        counter: _WindowCounter | None,
        *,
        window_seconds: int,
        now: float,
    ) -> _WindowCounter:
        if counter is None or (now - counter.window_start) >= window_seconds:
            return _WindowCounter(window_start=now, used_tokens=0)
        return counter

    async def reserve(
        self,
        *,
        tenant_id: str,
        estimated_tokens: int,
        priority: RequestPriority,
    ) -> RateLimitDecision:
        """呼出前に推定トークン量をアトミック予約し、上限超過または優先度シェディングを判定する。"""
        async with self._lock:
            now = self._clock()
            policy = self._tenants[tenant_id]
            t_win = self._get_or_roll_window(
                self._tenant_windows.get(tenant_id),
                window_seconds=policy.window_seconds,
                now=now,
            )
            self._tenant_windows[tenant_id] = t_win
            reset_epoch = math.ceil(t_win.window_start + policy.window_seconds)
            retry_after = max(1, math.ceil((t_win.window_start + policy.window_seconds) - now))

            safe_estimate = max(1, estimated_tokens)

            # 1) テナント枠のハード上限チェック
            if t_win.used_tokens + safe_estimate > policy.token_budget_per_window:
                return RateLimitDecision(
                    allowed=False,
                    limit=policy.token_budget_per_window,
                    remaining=max(0, policy.token_budget_per_window - t_win.used_tokens),
                    reset_epoch_seconds=reset_epoch,
                    retry_after_seconds=retry_after,
                    reason=(
                        f"テナント '{tenant_id}' のトークン予算上限 "
                        f"({policy.token_budget_per_window}) を超過しました。"
                    ),
                )

            # 2) テナント枠逼迫時の batch 先行シェディング (critical / standard 保護)
            tenant_util = t_win.used_tokens / max(1, policy.token_budget_per_window)
            if priority == "batch" and tenant_util >= policy.shedding_utilization_threshold:
                return RateLimitDecision(
                    allowed=False,
                    limit=policy.token_budget_per_window,
                    remaining=max(0, policy.token_budget_per_window - t_win.used_tokens),
                    reset_epoch_seconds=reset_epoch,
                    retry_after_seconds=retry_after,
                    reason=(
                        f"テナント利用率が {tenant_util:.0%} に達したため、"
                        "critical 対話保護のため batch リクエストを先行制限しました。"
                    ),
                    shed_due_to_priority=True,
                )

            # 3) 共有プール枠のチェックおよび batch シェディング
            if self._shared_pool_budget is not None:
                s_win = self._get_or_roll_window(
                    self._shared_window,
                    window_seconds=self._shared_pool_window,
                    now=now,
                )
                self._shared_window = s_win
                s_reset = math.ceil(s_win.window_start + self._shared_pool_window)
                s_retry = max(1, math.ceil((s_win.window_start + self._shared_pool_window) - now))

                if s_win.used_tokens + safe_estimate > self._shared_pool_budget:
                    return RateLimitDecision(
                        allowed=False,
                        limit=self._shared_pool_budget,
                        remaining=max(0, self._shared_pool_budget - s_win.used_tokens),
                        reset_epoch_seconds=s_reset,
                        retry_after_seconds=s_retry,
                        reason=(
                            f"共有推論プールのトークン上限 ({self._shared_pool_budget}) を超過しました。"
                        ),
                    )

                shared_util = s_win.used_tokens / max(1, self._shared_pool_budget)
                if priority == "batch" and shared_util >= self._shared_shedding_threshold:
                    return RateLimitDecision(
                        allowed=False,
                        limit=self._shared_pool_budget,
                        remaining=max(0, self._shared_pool_budget - s_win.used_tokens),
                        reset_epoch_seconds=s_reset,
                        retry_after_seconds=s_retry,
                        reason=(
                            f"共有プール利用率が {shared_util:.0%} に達したため、"
                            "高優先度トラフィック保護のため batch リクエストを先行制限しました。"
                        ),
                        shed_due_to_priority=True,
                    )
                s_win.used_tokens += safe_estimate

            t_win.used_tokens += safe_estimate
            shared_start = (
                self._shared_window.window_start
                if self._shared_pool_budget is not None and self._shared_window is not None
                else None
            )
            return RateLimitDecision(
                allowed=True,
                limit=policy.token_budget_per_window,
                remaining=max(0, policy.token_budget_per_window - t_win.used_tokens),
                reset_epoch_seconds=reset_epoch,
                reserved_tokens=safe_estimate,
                tenant_window_start=t_win.window_start,
                shared_window_start=shared_start,
            )

    async def settle(
        self,
        *,
        tenant_id: str,
        reserved_tokens: int,
        actual_weighted_tokens: int,
        tenant_window_start: float | None = None,
        shared_window_start: float | None = None,
    ) -> RateLimitDecision:
        """レスポンス確定トークンで事前予約分を精算する (障害時は actual=0 で予約解放)。

        予約から精算までの間に時間ウィンドウが切り替わった場合は、旧ウィンドウの予約分を
        新ウィンドウから減算せず、新ウィンドウへ確定値のみを安全に反映する。
        """
        async with self._lock:
            now = self._clock()
            policy = self._tenants[tenant_id]
            t_win = self._get_or_roll_window(
                self._tenant_windows.get(tenant_id),
                window_seconds=policy.window_seconds,
                now=now,
            )
            self._tenant_windows[tenant_id] = t_win
            if tenant_window_start is None or t_win.window_start == tenant_window_start:
                t_win.used_tokens = max(
                    0, t_win.used_tokens + (actual_weighted_tokens - reserved_tokens)
                )
            else:
                t_win.used_tokens = max(0, t_win.used_tokens + actual_weighted_tokens)

            if self._shared_pool_budget is not None and self._shared_window is not None:
                s_win = self._get_or_roll_window(
                    self._shared_window,
                    window_seconds=self._shared_pool_window,
                    now=now,
                )
                self._shared_window = s_win
                if shared_window_start is None or s_win.window_start == shared_window_start:
                    s_win.used_tokens = max(
                        0, s_win.used_tokens + (actual_weighted_tokens - reserved_tokens)
                    )
                else:
                    s_win.used_tokens = max(0, s_win.used_tokens + actual_weighted_tokens)

            reset_epoch = math.ceil(t_win.window_start + policy.window_seconds)
            return RateLimitDecision(
                allowed=True,
                limit=policy.token_budget_per_window,
                remaining=max(0, policy.token_budget_per_window - t_win.used_tokens),
                reset_epoch_seconds=reset_epoch,
                tenant_window_start=t_win.window_start,
            )


@dataclass
class GenAiTelemetryLedger:
    """OpenTelemetry GenAI Semantic Conventions 準拠の横断メトリクス・会計台帳。"""

    records: list[dict[str, Any]] = field(default_factory=list)

    def record_event(
        self,
        *,
        tenant_id: str,
        logical_model: str,
        priority: RequestPriority,
        status_code: int,
        outcome: str,
        routing_strategy: str,
        failover_attempts: int = 0,
        result: InferenceResult | None = None,
        weighted_tokens: int = 0,
    ) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "tenant.id": tenant_id,
            "request.priority": priority,
            "gen_ai.request.model": logical_model,
            "gen_ai.response.model": result.physical_model if result else None,
            "gen_ai.usage.input_tokens": result.usage.input_tokens if result else 0,
            "gen_ai.usage.output_tokens": result.usage.output_tokens if result else 0,
            "gen_ai.usage.cached_input_tokens": (
                result.usage.cached_input_tokens if result else 0
            ),
            "gen_ai.usage.thought_tokens": result.usage.thought_tokens if result else 0,
            "gen_ai.server.time_to_first_token": result.ttft_seconds if result else None,
            "gen_ai.server.request.duration": result.duration_seconds if result else None,
            "gateway.backend_id": result.backend_id if result else None,
            "gateway.routing_strategy": routing_strategy,
            "gateway.failover_attempts": failover_attempts,
            "gateway.weighted_tokens": weighted_tokens,
            "gateway.outcome": outcome,
            "http.response.status_code": status_code,
        }
        self.records.append(entry)
        return entry

    def tenant_summary(self, tenant_id: str) -> dict[str, int]:
        """指定テナントの集計サマリ (チャージバック・SLO 監視用) を返す。"""
        rows = [r for r in self.records if r["tenant.id"] == tenant_id]
        return {
            "requests": len(rows),
            "succeeded": sum(1 for r in rows if r["http.response.status_code"] == 200),
            "rate_limited_429": sum(1 for r in rows if r["http.response.status_code"] == 429),
            "total_input_tokens": sum(int(r["gen_ai.usage.input_tokens"]) for r in rows),
            "total_output_tokens": sum(int(r["gen_ai.usage.output_tokens"]) for r in rows),
            "total_weighted_tokens": sum(int(r["gateway.weighted_tokens"]) for r in rows),
            "total_failover_attempts": sum(int(r["gateway.failover_attempts"]) for r in rows),
        }


def estimate_input_tokens(messages: tuple[ChatMessage, ...]) -> int:
    """事前予約用の軽量な入力トークン推定値 (約 4 文字 = 1 トークン基準)。"""
    total_chars = sum(len(m.content) for m in messages)
    return max(10, math.ceil(total_chars / 4))


class AiGatewayService:
    """認証・認可・トークン基準レート制限・Body-Based Routing・フェイルオーバー・会計を統合する中核サービス。"""

    def __init__(
        self,
        *,
        tenants: list[TenantPolicy],
        endpoints: list[BackendEndpoint],
        routing_strategy: RoutingStrategy | None = None,
        cost_weights: TokenCostWeights | None = None,
        shared_pool_budget: int | None = None,
        shared_pool_window_seconds: int = 60,
        shared_shedding_threshold: float = 0.75,
        circuit_failure_threshold: int = 2,
        circuit_recovery_timeout_seconds: float = 30.0,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._tenants: dict[str, TenantPolicy] = {t.tenant_id: t for t in tenants}
        self._endpoints_by_model: dict[str, list[BackendEndpoint]] = {}
        for ep in endpoints:
            self._endpoints_by_model.setdefault(ep.logical_model, []).append(ep)

        self.routing_strategy: RoutingStrategy = routing_strategy or FailoverRoutingStrategy()
        self.cost_weights = cost_weights or TokenCostWeights()
        self.rate_limiter = TokenRateLimiter(
            tenants=self._tenants,
            shared_pool_budget=shared_pool_budget,
            shared_pool_window_seconds=shared_pool_window_seconds,
            shared_shedding_threshold=shared_shedding_threshold,
            clock=clock,
        )
        self.telemetry = GenAiTelemetryLedger()
        self._circuit_failure_threshold = circuit_failure_threshold
        self._circuit_recovery_timeout = circuit_recovery_timeout_seconds
        self._clock = clock

    def authenticate(self, authorization_header: str | None) -> TenantPolicy:
        """`Authorization: Bearer <token>` を定数時間比較で検証する。"""
        if not authorization_header or not authorization_header.startswith("Bearer "):
            raise HTTPException(
                status_code=401,
                detail="認証トークン (`Authorization: Bearer <token>`) が必要です。",
                headers={"WWW-Authenticate": "Bearer"},
            )
        raw_token = authorization_header[len("Bearer ") :].strip()
        if not raw_token:
            raise HTTPException(
                status_code=401,
                detail="認証トークンが空です。",
                headers={"WWW-Authenticate": "Bearer"},
            )
        candidate_hash = hash_api_key(raw_token)
        for policy in self._tenants.values():
            if hmac.compare_digest(candidate_hash, policy.api_key_hash):
                return policy
        raise HTTPException(
            status_code=401,
            detail="無効なテナント認証トークンです。",
            headers={"WWW-Authenticate": "Bearer"},
        )

    def list_models_for_tenant(self, tenant: TenantPolicy) -> list[dict[str, Any]]:
        """Model Discovery (`GET /v1/models`): 当該テナントに認可済みの論理モデルのみ公開する。"""
        discovered: list[dict[str, Any]] = []
        now = self._clock()
        for logical_model in sorted(self._endpoints_by_model.keys()):
            if logical_model not in tenant.allowed_models:
                continue
            eps = self._endpoints_by_model[logical_model]
            available_count = sum(
                1 for ep in eps if ep.healthy and not ep.is_circuit_open(now)
            )
            discovered.append(
                {
                    "id": logical_model,
                    "object": "model",
                    "owned_by": "ai-gateway",
                    "available_backends": available_count,
                    "routing_strategy": self.routing_strategy.name,
                }
            )
        return discovered

    async def handle_chat_completion(
        self,
        *,
        tenant: TenantPolicy,
        logical_model: str,
        messages: list[ChatMessage],
        priority: RequestPriority = "standard",
        prefix_key: str = "",
        max_output_tokens: int | None = None,
        temperature: float | None = None,
    ) -> tuple[dict[str, Any], dict[str, str]]:
        """Body-Based Routing・レート制限・フェイルオーバー・会計を一貫処理する。"""
        if logical_model not in self._endpoints_by_model:
            self.telemetry.record_event(
                tenant_id=tenant.tenant_id,
                logical_model=logical_model,
                priority=priority,
                status_code=404,
                outcome="model_not_found",
                routing_strategy=self.routing_strategy.name,
            )
            raise HTTPException(
                status_code=404,
                detail=f"論理モデル '{logical_model}' は登録されていません。",
            )

        if logical_model not in tenant.allowed_models:
            self.telemetry.record_event(
                tenant_id=tenant.tenant_id,
                logical_model=logical_model,
                priority=priority,
                status_code=403,
                outcome="forbidden_model",
                routing_strategy=self.routing_strategy.name,
            )
            raise HTTPException(
                status_code=403,
                detail=f"テナント '{tenant.tenant_id}' にはモデル '{logical_model}' の利用権限がありません。",
            )

        msg_tuple = tuple(messages)
        estimated = estimate_input_tokens(msg_tuple)
        reservation = await self.rate_limiter.reserve(
            tenant_id=tenant.tenant_id,
            estimated_tokens=estimated,
            priority=priority,
        )
        if not reservation.allowed:
            self.telemetry.record_event(
                tenant_id=tenant.tenant_id,
                logical_model=logical_model,
                priority=priority,
                status_code=429,
                outcome="priority_shed" if reservation.shed_due_to_priority else "rate_limited",
                routing_strategy=self.routing_strategy.name,
            )
            raise HTTPException(
                status_code=429,
                detail=reservation.reason,
                headers=reservation.to_headers(),
            )

        req = InferenceRequest(
            logical_model=logical_model,
            messages=msg_tuple,
            tenant_id=tenant.tenant_id,
            priority=priority,
            prefix_key=prefix_key,
            max_output_tokens=max_output_tokens,
            temperature=temperature,
        )

        endpoints = self._endpoints_by_model[logical_model]
        now = self._clock()
        candidates = self.routing_strategy.select_candidates(endpoints, req, now=now)
        if not candidates:
            await self.rate_limiter.settle(
                tenant_id=tenant.tenant_id,
                reserved_tokens=reservation.reserved_tokens,
                actual_weighted_tokens=0,
                tenant_window_start=reservation.tenant_window_start,
                shared_window_start=reservation.shared_window_start,
            )
            self.telemetry.record_event(
                tenant_id=tenant.tenant_id,
                logical_model=logical_model,
                priority=priority,
                status_code=503,
                outcome="no_healthy_backend",
                routing_strategy=self.routing_strategy.name,
            )
            raise HTTPException(
                status_code=503,
                detail=f"モデル '{logical_model}' で利用可能なバックエンドがありません (サーキット開放または飽和)。",
                headers={"Retry-After": str(int(max(1, self._circuit_recovery_timeout)))},
            )

        failover_attempts = 0
        last_error: InferenceBackendError | None = None

        for idx, ep in enumerate(candidates):
            ep.queue_depth += 1
            try:
                result = await ep.backend.invoke(req, credential_ref=ep.credential_ref)
                ep.record_success(prefix_key=prefix_key)
                weighted = self.cost_weights.compute_weighted_tokens(result.usage)
                settled = await self.rate_limiter.settle(
                    tenant_id=tenant.tenant_id,
                    reserved_tokens=reservation.reserved_tokens,
                    actual_weighted_tokens=weighted,
                    tenant_window_start=reservation.tenant_window_start,
                    shared_window_start=reservation.shared_window_start,
                )
                self.telemetry.record_event(
                    tenant_id=tenant.tenant_id,
                    logical_model=logical_model,
                    priority=priority,
                    status_code=200,
                    outcome="ok_after_failover" if failover_attempts > 0 else "ok",
                    routing_strategy=self.routing_strategy.name,
                    failover_attempts=failover_attempts,
                    result=result,
                    weighted_tokens=weighted,
                )
                headers = {
                    **settled.to_headers(),
                    "X-Gateway-Backend": result.backend_id,
                    "X-Gateway-Failover-Count": str(failover_attempts),
                    "X-Gateway-Routing-Strategy": self.routing_strategy.name,
                }
                payload = {
                    "id": f"gw-{tenant.tenant_id}-{len(self.telemetry.records)}",
                    "object": "chat.completion",
                    "model": logical_model,
                    "resolved_model": result.physical_model,
                    "backend_id": result.backend_id,
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": result.content},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": result.usage.input_tokens,
                        "cached_prompt_tokens": result.usage.cached_input_tokens,
                        "completion_tokens": result.usage.output_tokens,
                        "thought_tokens": result.usage.thought_tokens,
                        "total_tokens": result.usage.total_tokens,
                        "weighted_tokens": weighted,
                    },
                }
                return payload, headers
            except InferenceBackendError as exc:
                last_error = exc
                if not exc.is_retryable:
                    # 400 系クライアント起因エラーはサーキットを開放せず即座に返却する
                    await self.rate_limiter.settle(
                        tenant_id=tenant.tenant_id,
                        reserved_tokens=reservation.reserved_tokens,
                        actual_weighted_tokens=0,
                        tenant_window_start=reservation.tenant_window_start,
                        shared_window_start=reservation.shared_window_start,
                    )
                    self.telemetry.record_event(
                        tenant_id=tenant.tenant_id,
                        logical_model=logical_model,
                        priority=priority,
                        status_code=exc.status_code,
                        outcome="non_retryable_backend_error",
                        routing_strategy=self.routing_strategy.name,
                        failover_attempts=failover_attempts,
                    )
                    raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

                ep.record_transient_failure(
                    now=self._clock(),
                    failure_threshold=self._circuit_failure_threshold,
                    recovery_timeout_seconds=self._circuit_recovery_timeout,
                )
                if idx + 1 < len(candidates):
                    failover_attempts += 1
            finally:
                ep.queue_depth = max(0, ep.queue_depth - 1)

        # 全候補バックエンドが一時障害で失敗
        await self.rate_limiter.settle(
            tenant_id=tenant.tenant_id,
            reserved_tokens=reservation.reserved_tokens,
            actual_weighted_tokens=0,
            tenant_window_start=reservation.tenant_window_start,
            shared_window_start=reservation.shared_window_start,
        )
        status_out = last_error.status_code if last_error is not None else 503
        retry_after_out = (
            int(math.ceil(last_error.retry_after_seconds))
            if last_error is not None and last_error.retry_after_seconds is not None
            else int(max(1, self._circuit_recovery_timeout))
        )
        self.telemetry.record_event(
            tenant_id=tenant.tenant_id,
            logical_model=logical_model,
            priority=priority,
            status_code=status_out,
            outcome="all_backends_failed",
            routing_strategy=self.routing_strategy.name,
            failover_attempts=failover_attempts,
        )
        raise HTTPException(
            status_code=status_out,
            detail=str(last_error) if last_error is not None else "すべてのバックエンドが失敗しました。",
            headers={"Retry-After": str(max(1, retry_after_out))},
        )


class _ChatMessageBody(BaseModel):
    role: str
    content: str


class _ChatCompletionBody(BaseModel):
    model: str = Field(..., min_length=1)
    messages: list[_ChatMessageBody] = Field(..., min_length=1)
    max_tokens: int | None = None
    temperature: float | None = None


def _normalize_priority(raw_priority: str | None) -> RequestPriority:
    if not raw_priority:
        return "standard"
    lowered = raw_priority.strip().lower()
    if lowered == "critical":
        return "critical"
    if lowered == "batch":
        return "batch"
    return "standard"


def create_gateway_fastapi_app(service: AiGatewayService) -> FastAPI:
    """製品非依存の標準 HTTP AI Gateway (FastAPI ASGI アプリ) を構築する。"""
    gateway_app = FastAPI(
        title="AI Gateway Mediation Reference",
        version="1.0.0",
    )

    @gateway_app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "routing_strategy": service.routing_strategy.name}

    @gateway_app.get("/v1/models")
    async def list_models(
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        tenant = service.authenticate(authorization)
        return {"object": "list", "data": service.list_models_for_tenant(tenant)}

    @gateway_app.post("/v1/chat/completions")
    async def chat_completions(
        body: _ChatCompletionBody,
        response: Response,
        authorization: str | None = Header(default=None),
        x_request_priority: str | None = Header(default=None),
        x_prefix_key: str | None = Header(default=None),
    ) -> dict[str, Any]:
        tenant = service.authenticate(authorization)
        priority = _normalize_priority(x_request_priority)
        messages = [ChatMessage(role=m.role, content=m.content) for m in body.messages]
        payload, headers = await service.handle_chat_completion(
            tenant=tenant,
            logical_model=body.model,
            messages=messages,
            priority=priority,
            prefix_key=(x_prefix_key or "").strip(),
            max_output_tokens=body.max_tokens,
            temperature=body.temperature,
        )
        for key, value in headers.items():
            response.headers[key] = value
        return payload

    return gateway_app
