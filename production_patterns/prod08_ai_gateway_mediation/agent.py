"""PROD-08: AI Gateway Mediation — ADK 2.13 クライアント (`GatewayClientLlm`) とアプリビルダー。

設計の核心:
    - エージェント側 (`GatewayClientLlm`) はプロバイダ固有 SDK や生の API キーを一切保持せず、
      ゲートウェイ発行のテナントトークン・論理モデル名 (`tier:standard` 等)・優先度ヘッダーのみを
      標準 HTTP (`POST /v1/chat/completions`) で AI Gateway へ送信する。
    - オフライン検証では `httpx.ASGITransport` で FastAPI ASGI ゲートウェイとインプロセス HTTP 通信し、
      本番環境では `gateway_base_url` を独立した AI Gateway の URL へ差し替えるだけで同じコードが動作する。
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

import httpx
from fastapi import FastAPI
from google.adk.agents import LlmAgent
from google.adk.apps.app import App
from google.adk.models._capabilities import LlmCapabilities
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types
from pydantic import PrivateAttr

from production_patterns.prod08_ai_gateway_mediation.gateway import (
    AiGatewayService,
    TenantPolicy,
    create_gateway_fastapi_app,
)
from production_patterns.prod08_ai_gateway_mediation.routing import (
    BackendEndpoint,
    FailoverRoutingStrategy,
    GeminiInferenceBackend,
    RequestPriority,
    RoutingStrategy,
)
from shared.config import get_settings

DEFAULT_TENANT_API_KEY = "tenant-demo-token-do-not-use-in-prod"


def _extract_messages_from_llm_request(llm_request: LlmRequest) -> list[dict[str, str]]:
    """ADK `LlmRequest` から標準 HTTP チャットメッセージ配列を抽出する。"""
    messages: list[dict[str, str]] = []

    cfg = llm_request.config
    sys_inst = getattr(cfg, "system_instruction", None) if cfg is not None else None
    if isinstance(sys_inst, str) and sys_inst.strip():
        messages.append({"role": "system", "content": sys_inst.strip()})
    elif isinstance(sys_inst, types.Content) and sys_inst.parts:
        sys_text = "\n".join(p.text for p in sys_inst.parts if p.text)
        if sys_text.strip():
            messages.append({"role": "system", "content": sys_text.strip()})

    for content in llm_request.contents or []:
        if not content.parts:
            continue
        text_chunks = [p.text for p in content.parts if p.text and not getattr(p, "thought", False)]
        if not text_chunks:
            continue
        role = "assistant" if content.role == "model" else "user"
        messages.append({"role": role, "content": "\n".join(text_chunks)})

    if not messages:
        messages.append({"role": "user", "content": ""})
    return messages


class GatewayClientLlm(BaseLlm):
    """プロバイダ資格情報を持たず、標準 HTTP で AI Gateway へ推論を委譲する ADK `BaseLlm`。"""

    model: str = "tier:standard"
    _gateway_base_url: str = PrivateAttr(default="http://ai-gateway.local")
    _tenant_api_key: str = PrivateAttr(default="")
    _priority: RequestPriority = PrivateAttr(default="standard")
    _prefix_key: str = PrivateAttr(default="")
    _asgi_app: FastAPI | None = PrivateAttr(default=None)
    _timeout_seconds: float = PrivateAttr(default=60.0)
    _last_response_headers: dict[str, str] = PrivateAttr(default_factory=dict)

    def __init__(
        self,
        *,
        logical_model: str = "tier:standard",
        tenant_api_key: str,
        gateway_base_url: str = "http://ai-gateway.local",
        priority: RequestPriority = "standard",
        prefix_key: str = "",
        asgi_app: FastAPI | None = None,
        timeout_seconds: float = 60.0,
    ) -> None:
        super().__init__(model=logical_model)
        self._gateway_base_url = gateway_base_url.rstrip("/")
        self._tenant_api_key = tenant_api_key
        self._priority = priority
        self._prefix_key = prefix_key
        self._asgi_app = asgi_app
        self._timeout_seconds = timeout_seconds
        self._last_response_headers = {}

    @property
    def capabilities(self) -> LlmCapabilities:
        return LlmCapabilities(output_schema_and_tools=False)

    @property
    def last_response_headers(self) -> dict[str, str]:
        return dict(self._last_response_headers)

    async def discover_models(self) -> list[dict[str, Any]]:
        """`GET /v1/models` で当該テナントに許可された論理モデル一覧を取得する。"""
        transport = httpx.ASGITransport(app=self._asgi_app) if self._asgi_app is not None else None
        headers = {"Authorization": f"Bearer {self._tenant_api_key}"}
        async with httpx.AsyncClient(
            base_url=self._gateway_base_url,
            transport=transport,
            timeout=self._timeout_seconds,
        ) as client:
            resp = await client.get("/v1/models", headers=headers)
            resp.raise_for_status()
            body = resp.json()
            data = body.get("data", [])
            return list(data) if isinstance(data, list) else []

    async def generate_content_async(
        self,
        llm_request: LlmRequest,
        stream: bool = False,
    ) -> AsyncGenerator[LlmResponse, None]:
        del stream
        messages = _extract_messages_from_llm_request(llm_request)
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
        }
        cfg = llm_request.config
        if cfg is not None:
            if cfg.max_output_tokens is not None:
                payload["max_tokens"] = cfg.max_output_tokens
            if cfg.temperature is not None:
                payload["temperature"] = cfg.temperature

        headers = {
            "Authorization": f"Bearer {self._tenant_api_key}",
            "X-Request-Priority": self._priority,
        }
        if self._prefix_key:
            headers["X-Prefix-Key"] = self._prefix_key

        transport = httpx.ASGITransport(app=self._asgi_app) if self._asgi_app is not None else None
        try:
            async with httpx.AsyncClient(
                base_url=self._gateway_base_url,
                transport=transport,
                timeout=self._timeout_seconds,
            ) as client:
                resp = await client.post("/v1/chat/completions", json=payload, headers=headers)
        except httpx.HTTPError as exc:
            self._last_response_headers = {}
            msg = f"AI Gateway ({self._gateway_base_url}) へ接続できませんでした: {type(exc).__name__}"
            yield LlmResponse(
                content=types.Content(
                    role="model",
                    parts=[types.Part.from_text(text=f"[GATEWAY_UNAVAILABLE] {msg}")],
                ),
                error_code="GATEWAY_UNAVAILABLE",
                error_message=msg,
                custom_metadata={"http_status": 503, "gateway_unavailable": True},
            )
            return

        self._last_response_headers = {k.lower(): v for k, v in resp.headers.items()}

        if resp.status_code != 200:
            detail = ""
            try:
                detail = str(resp.json().get("detail", resp.text))
            except ValueError:
                detail = resp.text
            retry_after = resp.headers.get("Retry-After")
            retry_note = f" (Retry-After: {retry_after}s)" if retry_after else ""
            yield LlmResponse(
                content=types.Content(
                    role="model",
                    parts=[
                        types.Part.from_text(
                            text=f"[GATEWAY_HTTP_{resp.status_code}] {detail}{retry_note}"
                        )
                    ],
                ),
                error_code=f"GATEWAY_HTTP_{resp.status_code}",
                error_message=detail,
                custom_metadata={
                    "http_status": resp.status_code,
                    "rate_limit_remaining": resp.headers.get("X-RateLimit-Remaining"),
                    "retry_after": retry_after,
                },
            )
            return

        data = resp.json()
        choices = data.get("choices", [])
        text = ""
        if choices and isinstance(choices[0], dict):
            msg = choices[0].get("message", {})
            if isinstance(msg, dict):
                text = str(msg.get("content", ""))

        usage_raw = data.get("usage", {})
        usage_meta = types.GenerateContentResponseUsageMetadata(
            prompt_token_count=int(usage_raw.get("prompt_tokens", 0)),
            cached_content_token_count=int(usage_raw.get("cached_prompt_tokens", 0)),
            candidates_token_count=int(usage_raw.get("completion_tokens", 0)),
            thoughts_token_count=int(usage_raw.get("thought_tokens", 0)),
            total_token_count=int(usage_raw.get("total_tokens", 0)),
        )

        yield LlmResponse(
            model_version=str(data.get("resolved_model", self.model)),
            content=types.Content(
                role="model",
                parts=[types.Part.from_text(text=text)],
            ),
            usage_metadata=usage_meta,
            custom_metadata={
                "logical_model": self.model,
                "backend_id": data.get("backend_id"),
                "failover_count": int(resp.headers.get("X-Gateway-Failover-Count", "0")),
                "rate_limit_remaining": resp.headers.get("X-RateLimit-Remaining"),
            },
        )


def build_default_gateway_service(
    *,
    endpoints: list[BackendEndpoint] | None = None,
    tenants: list[TenantPolicy] | None = None,
    routing_strategy: RoutingStrategy | None = None,
    shared_pool_budget: int | None = 50_000,
) -> AiGatewayService:
    """実モデル (またはテスト用バックエンド) を背後に持つ既定の AI Gateway サービスを構築する。"""
    settings = get_settings()
    active_tenants = tenants or [
        TenantPolicy.from_raw_key(
            tenant_id="tenant-interactive",
            raw_api_key=DEFAULT_TENANT_API_KEY,
            allowed_models={"tier:standard", "tier:fast"},
            token_budget_per_window=20_000,
            window_seconds=60,
            shedding_utilization_threshold=0.75,
        ),
    ]
    active_endpoints = endpoints or [
        BackendEndpoint(
            backend_id="primary-standard",
            logical_model="tier:standard",
            backend=GeminiInferenceBackend(
                backend_id="primary-standard",
                physical_model=settings.default_model,
                thinking_level="LOW",
            ),
            credential_ref="gateway-vault://primary-standard",
            priority_order=0,
        ),
        BackendEndpoint(
            backend_id="fallback-fast",
            logical_model="tier:standard",
            backend=GeminiInferenceBackend(
                backend_id="fallback-fast",
                physical_model=settings.fast_model,
                thinking_level="LOW",
            ),
            credential_ref="gateway-vault://fallback-fast",
            priority_order=1,
        ),
        BackendEndpoint(
            backend_id="pool-fast",
            logical_model="tier:fast",
            backend=GeminiInferenceBackend(
                backend_id="pool-fast",
                physical_model=settings.fast_model,
                thinking_level="LOW",
            ),
            credential_ref="gateway-vault://pool-fast",
            priority_order=0,
        ),
    ]
    return AiGatewayService(
        tenants=active_tenants,
        endpoints=active_endpoints,
        routing_strategy=routing_strategy or FailoverRoutingStrategy(),
        shared_pool_budget=shared_pool_budget,
    )


def build_gateway_mediated_app(
    *,
    gateway_service: AiGatewayService | None = None,
    logical_model: str = "tier:standard",
    tenant_api_key: str = DEFAULT_TENANT_API_KEY,
    priority: RequestPriority = "critical",
    prefix_key: str = "sys:platform-advisor:v1",
) -> tuple[App, AiGatewayService, GatewayClientLlm]:
    """AI Gateway 経由で推論を行う ADK `App` とゲートウェイサービスを構築する。"""
    service = gateway_service or build_default_gateway_service()
    fastapi_gateway = create_gateway_fastapi_app(service)
    gateway_llm = GatewayClientLlm(
        logical_model=logical_model,
        tenant_api_key=tenant_api_key,
        priority=priority,
        prefix_key=prefix_key,
        asgi_app=fastapi_gateway,
    )
    agent = LlmAgent(
        name="gateway_mediated_agent",
        model=gateway_llm,
        description=(
            "プロバイダ資格情報を直接持たず、共有 AI Gateway の標準 HTTP 境界経由で"
            "推論・レート制御・フェイルオーバーを受ける本番エージェント。"
        ),
        instruction=(
            "あなたは企業のプラットフォーム運用アドバイザーです。"
            "質問に対して、実務的で簡潔な日本語で回答してください。"
        ),
    )
    mediated_app = App(
        name="prod08_ai_gateway_mediation",
        root_agent=agent,
    )
    return mediated_app, service, gateway_llm


__all__ = [
    "AiGatewayService",
    "BackendEndpoint",
    "DEFAULT_TENANT_API_KEY",
    "FailoverRoutingStrategy",
    "GatewayClientLlm",
    "GeminiInferenceBackend",
    "TenantPolicy",
    "app",
    "build_default_gateway_service",
    "build_gateway_mediated_app",
    "create_gateway_fastapi_app",
    "root_agent",
]

app, _default_gateway_service, _default_gateway_llm = build_gateway_mediated_app()
assert app.root_agent is not None
root_agent = app.root_agent
