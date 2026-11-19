"""PROD-08: AI Gateway Mediation パターン デモスクリプト。

パート 1: オフラインのインプロセス HTTP (FastAPI + httpx.ASGITransport) 上で、
    - Model Discovery (`GET /v1/models`)
    - サーキットブレーカー自動フェイルオーバー (`503` -> セカンダリ切替)
    - プレフィックス親和性 + 負荷スコア選出
    - 共有枠逼迫時の `batch` 先行 `429` シェディングと `critical` 対話保護
を決定論的に実演する。

パート 2: 実モデルバックエンドを AI Gateway 背後に接続し、ADK `Runner` から
    `GatewayClientLlm` -> FastAPI AI Gateway 経由で推論を実行する。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from production_patterns.prod08_ai_gateway_mediation.agent import (
    DEFAULT_TENANT_API_KEY,
    AiGatewayService,
    BackendEndpoint,
    TenantPolicy,
    app,
    create_gateway_fastapi_app,
)
from production_patterns.prod08_ai_gateway_mediation.routing import (
    FailoverRoutingStrategy,
    MockInferenceBackend,
    PrefixLoadAwareRoutingStrategy,
)
from shared.demo_runner import run_demo


async def _run_offline_gateway_showcase() -> None:
    tenant = TenantPolicy.from_raw_key(
        tenant_id="team-platform",
        raw_api_key="demo-offline-key",
        allowed_models={"tier:standard", "tier:shared-pool"},
        token_budget_per_window=600,
        window_seconds=60,
        shedding_utilization_threshold=0.50,
    )

    # 1) Failover + Priority Shedding デモ
    gw_failover = AiGatewayService(
        tenants=[tenant],
        endpoints=[
            BackendEndpoint(
                backend_id="primary-a",
                logical_model="tier:standard",
                backend=MockInferenceBackend(
                    backend_id="primary-a",
                    physical_model="model-std-a",
                    failure_script=[503],
                    input_tokens=100,
                    output_tokens=60,
                    thought_tokens=0,
                ),
                priority_order=0,
            ),
            BackendEndpoint(
                backend_id="secondary-b",
                logical_model="tier:standard",
                backend=MockInferenceBackend(
                    backend_id="secondary-b",
                    physical_model="model-std-b",
                    input_tokens=100,
                    output_tokens=60,
                    thought_tokens=0,
                ),
                priority_order=1,
            ),
        ],
        routing_strategy=FailoverRoutingStrategy(),
        circuit_failure_threshold=1,
    )
    fastapi_app = create_gateway_fastapi_app(gw_failover)
    headers = {"Authorization": "Bearer demo-offline-key"}

    async with httpx.AsyncClient(
        base_url="http://ai-gateway.local",
        transport=httpx.ASGITransport(app=fastapi_app),
    ) as client:
        models = (await client.get("/v1/models", headers=headers)).json()["data"]
        print("1. Model Discovery:", [m["id"] for m in models])

        r1 = await client.post(
            "/v1/chat/completions",
            headers={**headers, "X-Request-Priority": "critical"},
            json={"model": "tier:standard", "messages": [{"role": "user", "content": "障害時の切替確認"}]},
        )
        print(
            f"2. 自動フェイルオーバー: HTTP {r1.status_code}, "
            f"backend={r1.headers.get('X-Gateway-Backend')}, "
            f"failovers={r1.headers.get('X-Gateway-Failover-Count')}, "
            f"remaining={r1.headers.get('X-RateLimit-Remaining')}"
        )

        # 利用率 50% 超過後に batch は先行 429、critical は通過
        r_batch = await client.post(
            "/v1/chat/completions",
            headers={**headers, "X-Request-Priority": "batch"},
            json={"model": "tier:standard", "messages": [{"role": "user", "content": "夜間の要約バッチ"}]},
        )
        r_crit = await client.post(
            "/v1/chat/completions",
            headers={**headers, "X-Request-Priority": "critical"},
            json={"model": "tier:standard", "messages": [{"role": "user", "content": "対話ユーザー質問"}]},
        )
        print(
            f"3. 優先度シェディング: batch -> HTTP {r_batch.status_code} "
            f"(Retry-After={r_batch.headers.get('Retry-After')}s) / "
            f"critical -> HTTP {r_crit.status_code}"
        )

    # 2) Prefix Affinity + Load-Aware デモ
    ep_warm = BackendEndpoint(
        backend_id="replica-warm",
        logical_model="tier:shared-pool",
        backend=MockInferenceBackend(backend_id="replica-warm", physical_model="pool-m1"),
        queue_depth=2,
        max_queue_depth=10,
        cached_prefixes={"sys:finance-analyst:v2"},
    )
    ep_cold = BackendEndpoint(
        backend_id="replica-cold",
        logical_model="tier:shared-pool",
        backend=MockInferenceBackend(backend_id="replica-cold", physical_model="pool-m1"),
        queue_depth=0,
        max_queue_depth=10,
    )
    gw_prefix = AiGatewayService(
        tenants=[tenant],
        endpoints=[ep_warm, ep_cold],
        routing_strategy=PrefixLoadAwareRoutingStrategy(),
    )
    async with httpx.AsyncClient(
        base_url="http://ai-gateway.local",
        transport=httpx.ASGITransport(app=create_gateway_fastapi_app(gw_prefix)),
    ) as client:
        r_pref = await client.post(
            "/v1/chat/completions",
            headers={**headers, "X-Prefix-Key": "sys:finance-analyst:v2"},
            json={"model": "tier:shared-pool", "messages": [{"role": "user", "content": "キャッシュ親和性テスト"}]},
        )
        print(
            f"4. プレフィックス親和性ルーティング: selected={r_pref.headers.get('X-Gateway-Backend')} "
            f"(strategy={r_pref.headers.get('X-Gateway-Routing-Strategy')})"
        )
    print("5. テナント会計サマリ:", gw_failover.telemetry.tenant_summary("team-platform"))


def main() -> None:
    print("=== Part 1: AI Gateway オフライン決定論デモ ===")
    asyncio.run(_run_offline_gateway_showcase())
    print("\n=== Part 2: ADK エージェント -> AI Gateway -> 実モデル 結合デモ ===")
    print(f"(エージェントはゲートウェイ用テナントトークンのみ保持: len={len(DEFAULT_TENANT_API_KEY)})")
    run_demo(
        agent=app,
        app_name="prod08_ai_gateway_mediation",
        queries=[
            "マルチテナント推論基盤で、リクエスト回数ではなくトークン数でレート制限する理由を 3 行で教えてください。",
        ],
    )


if __name__ == "__main__":
    main()
