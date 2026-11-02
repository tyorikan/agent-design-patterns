"""CLI-03: A2A Interoperability デモスクリプト（AgentCard 発見 + JSON-RPC 呼び出し）。"""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from pathlib import Path

import httpx

PROJECT_DIR = Path(__file__).resolve().parent
REPO_ROOT = PROJECT_DIR.parent.parent
for p in (str(PROJECT_DIR), str(REPO_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from app.fast_api_app import app, lifespan  # noqa: E402

from shared.config import get_settings  # noqa: E402


async def main() -> None:
    """インプロセス ASGI クライアントから A2A AgentCard 取得と message/send 呼び出しを実行する。"""
    get_settings()

    async with lifespan(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8013") as client:
            # Step 1: AgentCard の動的ディスカバリ
            card_resp = await client.get("/a2a/app/.well-known/agent-card.json")
            card_resp.raise_for_status()
            card = card_resp.json()
            print("=== 1. Discovered A2A AgentCard ===")
            print(
                json.dumps(
                    {
                        "name": card.get("name"),
                        "description": card.get("description"),
                        "version": card.get("version"),
                        "skills": [s.get("name") for s in card.get("skills", [])],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )

            # Step 2: A2A JSON-RPC でメッセージ送信
            rpc_payload = {
                "jsonrpc": "2.0",
                "id": str(uuid.uuid4()),
                "method": "message/send",
                "params": {
                    "message": {
                        "messageId": str(uuid.uuid4()),
                        "role": "user",
                        "parts": [
                            {
                                "kind": "text",
                                "text": "本番用サービスアカウントに roles/owner を付与する案のリスクを診断してください。",
                            }
                        ],
                    }
                },
            }
            rpc_resp = await client.post("/a2a/app", json=rpc_payload, timeout=60.0)
            rpc_resp.raise_for_status()
            print("\n=== 2. A2A JSON-RPC Response ===")
            print(json.dumps(rpc_resp.json(), ensure_ascii=False, indent=2)[:1500])


if __name__ == "__main__":
    asyncio.run(main())
