"""差し替え可能な Grounded RAG リトリーバー抽象化レイヤー。

ローカル開発・単体テスト時はインメモリコーパス（`LocalCorpusRetriever`）で高速・無料に検証し、
本番環境で `AGENT_SEARCH_DATA_STORE_ID` が設定された際は Google Cloud Agent Search
（旧 Vertex AI Search / Discovery Engine API）へコード変更なしで切り替える。
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Protocol

import httpx


@dataclass(frozen=True)
class RetrievedChunk:
    """検索で取得された根拠ドキュメント断片。"""

    doc_id: str
    title: str
    snippet: str
    score: float


class KnowledgeRetriever(Protocol):
    """検索バックエンドの共通インターフェース（依存性逆転の原則）。"""

    def search(self, query: str, top_k: int = 3) -> list[RetrievedChunk]:
        """クエリに関連する根拠チャンクを上位 top_k 件返す。"""


_DEFAULT_POLICY_CORPUS: tuple[tuple[str, str, str], ...] = (
    (
        "DOC-ARCH-001",
        "マルチリージョン DR 設計基準",
        "決済・基幹 API の目標復旧時点（RPO）は 0（ゼロデータロス）、目標復旧時間（RTO）は 5 分以内とする。"
        "データ層は強整合マルチリージョン構成または同期レプリケーションを採用し、変更系 API には必ずクライアント生成の Idempotency-Key を要求する。",
    ),
    (
        "DOC-ARCH-002",
        "AI エージェント本番セキュリティ基準",
        "本番稼働する AI エージェントは最小権限の専用サービスアカウントで実行し、roles/owner や roles/editor の付与を禁止する。"
        "ユーザー識別子はプロンプト引数ではなく認証済みセッションコンテキスト（ToolContext）から取得しなければならない。",
    ),
    (
        "DOC-ARCH-003",
        "非同期バッチ・イベント駆動設計基準",
        "外部 Webhook や Pub/Sub コンシューマは At-Least-Once（少なくとも1回）配信を前提とし、"
        "イベント ID による重複排除テーブル（Idempotency Ledger）をトランザクション内で記録すること。",
    ),
    (
        "DOC-ARCH-004",
        "コンテナ・サーバーレス運用基準",
        "本番コンテナイメージは非 root ユーザー（UID >= 10000）で実行し、シークレットは環境変数への平文埋め込みではなく Secret Manager からマウントする。",
    ),
)


def _tokenize(text: str) -> set[str]:
    """日本語・英数字双方のクエリで決定論的に部分一致スコアを計算するためのトークナイザ。"""
    lowered = text.lower()
    ascii_words = set(re.findall(r"[a-z0-9_-]{2,}", lowered))
    # 日本語文字列からも 2 文字バイグラムを抽出して語彙一致を捉える
    cjk_chars = re.sub(r"[\s\x00-\x7f]+", "", lowered)
    bigrams = {cjk_chars[i : i + 2] for i in range(len(cjk_chars) - 1)} if len(cjk_chars) >= 2 else set()
    return ascii_words | bigrams


class LocalCorpusRetriever:
    """ローカル開発・CI 単体テスト用の決定論的インメモリ Retriever。"""

    def __init__(self, corpus: tuple[tuple[str, str, str], ...] = _DEFAULT_POLICY_CORPUS) -> None:
        self._corpus = corpus

    def search(self, query: str, top_k: int = 3) -> list[RetrievedChunk]:
        q_tokens = _tokenize(query)
        if not q_tokens:
            return []

        scored: list[RetrievedChunk] = []
        for doc_id, title, body in self._corpus:
            doc_tokens = _tokenize(f"{title} {body}")
            overlap = len(q_tokens & doc_tokens)
            if overlap > 0:
                score = round(overlap / max(1, len(q_tokens)), 4)
                scored.append(
                    RetrievedChunk(
                        doc_id=doc_id,
                        title=title,
                        snippet=body,
                        score=score,
                    )
                )

        scored.sort(key=lambda c: (-c.score, c.doc_id))
        return scored[: max(1, top_k)]


class AgentSearchRetriever:
    """Google Cloud Agent Search（Discovery Engine REST API）アダプター。"""

    def __init__(
        self,
        project_id: str,
        data_store_id: str,
        location: str = "global",
    ) -> None:
        self.project_id = project_id
        self.data_store_id = data_store_id
        self.location = location

    def search(self, query: str, top_k: int = 3) -> list[RetrievedChunk]:
        import google.auth
        import google.auth.transport.requests

        credentials, _ = google.auth.default()
        credentials.refresh(google.auth.transport.requests.Request())

        host = (
            "discoveryengine.googleapis.com"
            if self.location == "global"
            else f"{self.location}-discoveryengine.googleapis.com"
        )
        url = (
            f"https://{host}/v1/projects/{self.project_id}/locations/{self.location}"
            f"/collections/default_collection/dataStores/{self.data_store_id}"
            f"/servingConfigs/default_search:search"
        )
        resp = httpx.post(
            url,
            headers={"Authorization": f"Bearer {credentials.token}"},
            json={"query": query, "pageSize": max(1, top_k)},
            timeout=15.0,
        )
        resp.raise_for_status()
        payload: dict[str, Any] = resp.json()

        chunks: list[RetrievedChunk] = []
        for rank, item in enumerate(payload.get("results", []), start=1):
            doc = item.get("document", {})
            derived = doc.get("derivedStructData", {})
            snippets = derived.get("snippets") or []
            snippet_text = snippets[0].get("snippet", "") if snippets else str(doc.get("structData", ""))
            chunks.append(
                RetrievedChunk(
                    doc_id=str(doc.get("id") or f"SEARCH-{rank}"),
                    title=str(derived.get("title") or doc.get("name") or "Agent Search Result"),
                    snippet=snippet_text,
                    score=round(1.0 / rank, 4),
                )
            )
        return chunks


def build_retriever_from_env() -> KnowledgeRetriever:
    """環境変数に応じて本番 Agent Search またはローカルコーパスを選択する。"""
    data_store_id = os.environ.get("AGENT_SEARCH_DATA_STORE_ID", "").strip()
    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "").strip()
    if data_store_id and project_id:
        search_location = os.environ.get("AGENT_SEARCH_LOCATION", "global").strip()
        return AgentSearchRetriever(
            project_id=project_id,
            data_store_id=data_store_id,
            location=search_location,
        )
    return LocalCorpusRetriever()
