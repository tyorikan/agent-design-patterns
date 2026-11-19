"""OKF v0.3 §10 Attested Computation の実行器 Protocol と決定論的非 LLM 検証器。

設計の核心:
    1. LLM は計算式 (SQL 等) を一切生成・編集できず、OKF Concept で宣言された型付き `parameters`
       に値を与えることしかできない (§10.3)。
    2. 実行器 (`ComputationExecutor` Protocol) は名前付きパラメータ束縛で承認済み計算を実行し、
       実行レシート (`ComputationReceipt`) を返す。既定実装は外部依存ゼロのインメモリ SQLite であり、
       本番環境では BigQuery / dbt 実行器へ無変更で差し替え可能。
    3. 非 LLM の検証器 (`SqlEqualityAttester`) は、`job_id` から実行器側の権威ログを直接参照し、
       ① 承認済み SQL と実行 SQL の一致、② パラメータ束縛の一致、③ 結果ダイジェストの整合性を
       決定論的に再検証する。失敗時は値を返さず理由のみを返す (Fail-Closed)。

注意 (OKF v0.3 §12.2):
    レシートと判定結果のワイヤフォーマットおよび Attester の ABI は OKF v0.3 仕様上で将来バージョンへ
    先送りされているため、本モジュールでは標準的な Python `Protocol` / `dataclass` として疎結合に抽象化している。
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from dataclasses import dataclass
from typing import Any, Protocol

from production_patterns.prod07_governed_knowledge_attestation.okf_bundle import (
    ConceptDocument,
    OkfBundle,
    ParameterSpec,
    parse_okf_timestamp,
)


def normalize_sql(sql: str) -> str:
    """比較用に SQL の前後空白・連続空白・末尾セミコロンを正規化する。"""
    return " ".join(sql.strip().rstrip(";").split())


def compute_rows_sha256(rows: list[dict[str, Any]]) -> str:
    """クエリ結果行リストの決定論的 SHA-256 ダイジェストを算出する。"""
    canonical = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_and_bind_parameters(
    specs: tuple[ParameterSpec, ...],
    provided: dict[str, Any],
) -> tuple[dict[str, Any] | None, list[str]]:
    """宣言済み `parameters` 定義に対して、LLM が渡した引数の過不足と型を厳格検証する (§10.2)。"""
    errors: list[str] = []
    spec_map = {spec.name: spec for spec in specs}

    extra_keys = sorted(set(provided.keys()) - set(spec_map.keys()))
    if extra_keys:
        errors.append(f"未宣言のパラメータが渡されました: {extra_keys}")

    bound: dict[str, Any] = {}
    for spec in specs:
        if spec.name not in provided or provided[spec.name] is None:
            if spec.required:
                errors.append(f"必須パラメータが不足しています: '{spec.name}' ({spec.type})")
            continue

        raw_val = provided[spec.name]
        p_type = spec.type.lower()

        if p_type == "integer":
            if isinstance(raw_val, bool) or not isinstance(raw_val, int):
                errors.append(f"パラメータ '{spec.name}' は integer 型である必要があります: {raw_val!r}")
                continue
            bound[spec.name] = raw_val
        elif p_type == "number":
            if isinstance(raw_val, bool) or not isinstance(raw_val, (int, float)):
                errors.append(f"パラメータ '{spec.name}' は number 型である必要があります: {raw_val!r}")
                continue
            bound[spec.name] = float(raw_val)
        elif p_type == "boolean":
            if not isinstance(raw_val, bool):
                errors.append(f"パラメータ '{spec.name}' は boolean 型である必要があります: {raw_val!r}")
                continue
            bound[spec.name] = raw_val
        elif p_type == "string":
            if not isinstance(raw_val, str) or not raw_val.strip():
                errors.append(f"パラメータ '{spec.name}' は空でない string 型である必要があります: {raw_val!r}")
                continue
            bound[spec.name] = raw_val.strip()
        elif p_type in {"date", "timestamp"}:
            if parse_okf_timestamp(raw_val) is None:
                errors.append(f"パラメータ '{spec.name}' は有効な RFC 3339 {p_type} である必要があります: {raw_val!r}")
                continue
            bound[spec.name] = str(raw_val)
        else:
            bound[spec.name] = raw_val

    if errors:
        return None, errors
    return bound, []


@dataclass(frozen=True)
class ComputationReceipt:
    """実行器が返すランタイム証跡 (バンドルには保存しない、§10)。"""

    job_id: str
    runtime: str
    executed_sql: str
    bound_parameters: dict[str, Any]
    rows: list[dict[str, Any]]
    result_sha256: str


@dataclass(frozen=True)
class ExecutionJobRecord:
    """実行器側の権威ジョブログ (Attester が `job_id` で再参照して真偽を照合する、§10.5)。"""

    job_id: str
    runtime: str
    executed_sql: str
    bound_parameters: dict[str, Any]
    rows: list[dict[str, Any]]
    result_sha256: str


@dataclass(frozen=True)
class AttestationVerdict:
    """非 LLM Attester が返す決定論的判定結果 (§10.5)。"""

    ok: bool
    reason: str
    receipt_ref: str | None = None


class ComputationExecutor(Protocol):
    """承認済み計算を実行する抽象インターフェース (SQLite / BigQuery / dbt 等を差し替え可能)。"""

    @property
    def runtime_name(self) -> str: ...

    def execute(
        self,
        *,
        sql: str,
        parameters: dict[str, Any],
    ) -> ComputationReceipt: ...

    def get_job_record(self, job_id: str) -> ExecutionJobRecord | None: ...


class ComputationAttester(Protocol):
    """レシートと承認済み定義を突き合わせる決定論的非 LLM 検証器インターフェース。"""

    def attest(
        self,
        *,
        concept: ConceptDocument,
        sanctioned_sql: str,
        expected_parameters: dict[str, Any],
        receipt: ComputationReceipt,
        executor: ComputationExecutor,
    ) -> AttestationVerdict: ...


class SqliteComputationExecutor:
    """外部依存ゼロで本物の名前付きパラメータ束縛 SQL を実行するインメモリ SQLite 実行器。"""

    def __init__(self) -> None:
        self._conn = sqlite3.connect(":memory:", check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._ledger: dict[str, ExecutionJobRecord] = {}
        self._seed_sample_data()

    @property
    def runtime_name(self) -> str:
        return "sqlite"

    def _seed_sample_data(self) -> None:
        cur = self._conn.cursor()
        cur.executescript(
            """
            CREATE TABLE recognized_revenue (
                fiscal_year INTEGER NOT NULL,
                segment TEXT NOT NULL,
                amount_usd INTEGER NOT NULL
            );
            INSERT INTO recognized_revenue (fiscal_year, segment, amount_usd) VALUES
                (2025, 'retail', 4200000),
                (2025, 'online', 3100000),
                (2025, 'enterprise', 2700000),
                (2026, 'retail', 4850000),
                (2026, 'online', 3950000),
                (2026, 'enterprise', 3400000);

            CREATE TABLE gross_profit_summary (
                fiscal_year INTEGER NOT NULL,
                segment TEXT NOT NULL,
                gross_profit_usd INTEGER NOT NULL,
                margin_pct REAL NOT NULL
            );
            INSERT INTO gross_profit_summary (fiscal_year, segment, gross_profit_usd, margin_pct) VALUES
                (2025, 'retail', 1680000, 40.0),
                (2025, 'online', 1550000, 50.0),
                (2025, 'enterprise', 1620000, 60.0),
                (2026, 'retail', 1988500, 41.0),
                (2026, 'online', 2054000, 52.0),
                (2026, 'enterprise', 2108000, 62.0);
            """
        )
        self._conn.commit()
        # シード完了後はエンジン層で読み取り専用ロックし、更新系 SQL (DELETE / DROP 等) を完全拒否する
        self._conn.execute("PRAGMA query_only = ON")

    def execute(
        self,
        *,
        sql: str,
        parameters: dict[str, Any],
    ) -> ComputationReceipt:
        cur = self._conn.cursor()
        cur.execute(sql, parameters)
        rows = [dict(row) for row in cur.fetchall()]
        digest = compute_rows_sha256(rows)
        job_id = f"sqlite-job-{uuid.uuid4().hex[:12]}"

        record = ExecutionJobRecord(
            job_id=job_id,
            runtime=self.runtime_name,
            executed_sql=sql,
            bound_parameters=dict(parameters),
            rows=rows,
            result_sha256=digest,
        )
        self._ledger[job_id] = record
        return ComputationReceipt(
            job_id=job_id,
            runtime=self.runtime_name,
            executed_sql=sql,
            bound_parameters=dict(parameters),
            rows=rows,
            result_sha256=digest,
        )

    def get_job_record(self, job_id: str) -> ExecutionJobRecord | None:
        return self._ledger.get(job_id)


class SqlEqualityAttester:
    """OKF v0.3 §10.5 に基づく決定論的非 LLM SQL 一致検証器。

    エージェントの説明文ではなく `executor.get_job_record(receipt.job_id)` を直接再照合し、
    1) `runtime` / `attester` 契約の存在
    2) 権威ジョブログの存在とランタイム一致
    3) 承認済み SQL と実実行 SQL の完全一致 (正規化後)
    4) 宣言済みパラメータ束縛の一致
    5) レシート結果と権威結果の SHA-256 ダイジェスト一致
    を機械的に確認する。
    """

    def attest(
        self,
        *,
        concept: ConceptDocument,
        sanctioned_sql: str,
        expected_parameters: dict[str, Any],
        receipt: ComputationReceipt,
        executor: ComputationExecutor,
    ) -> AttestationVerdict:
        if not concept.runtime or not concept.attester_resource:
            return AttestationVerdict(
                ok=False,
                reason="Concept に必須の runtime または attester 定義がありません (§10.2)。",
            )

        missing_receipt_fields = [
            field_name
            for field_name in concept.executor_receipt
            if getattr(receipt, field_name, None) is None
        ]
        if missing_receipt_fields:
            return AttestationVerdict(
                ok=False,
                reason=(
                    f"レシートに executor.receipt で宣言された必須フィールドが不足しています: "
                    f"{missing_receipt_fields} (§10.2)。"
                ),
            )

        record = executor.get_job_record(receipt.job_id)
        if record is None:
            return AttestationVerdict(
                ok=False,
                reason=f"権威ジョブログに job_id={receipt.job_id!r} が存在しません。",
            )

        if record.runtime != concept.runtime:
            return AttestationVerdict(
                ok=False,
                reason=(
                    f"実行ランタイムが不一致です: expected={concept.runtime!r}, "
                    f"actual={record.runtime!r}"
                ),
            )

        if normalize_sql(record.executed_sql) != normalize_sql(sanctioned_sql):
            return AttestationVerdict(
                ok=False,
                reason="実行された SQL が OKF Concept の承認済み SQL と一致しません (改ざん検知)。",
            )

        if record.bound_parameters != expected_parameters:
            return AttestationVerdict(
                ok=False,
                reason=(
                    f"束縛パラメータが不一致です: expected={expected_parameters!r}, "
                    f"actual={record.bound_parameters!r}"
                ),
            )

        expected_digest = compute_rows_sha256(record.rows)
        claimed_digest = compute_rows_sha256(receipt.rows)
        if receipt.result_sha256 != expected_digest or claimed_digest != expected_digest:
            return AttestationVerdict(
                ok=False,
                reason="レシートの結果ダイジェストが権威実行結果と一致しません (結果改ざん検知)。",
            )

        return AttestationVerdict(
            ok=True,
            reason="承認済み SQL・パラメータ束縛・結果ダイジェストの完全一致を検証しました。",
            receipt_ref=record.job_id,
        )


def execute_and_attest_computation(
    *,
    bundle: OkfBundle,
    concept_id: str,
    parameters: dict[str, Any],
    executor: ComputationExecutor,
    attester: ComputationAttester,
) -> dict[str, Any]:
    """OKF `Attested Computation` の読込・検証・実行・非 LLM Attestation・Fail-Closed ゲートを一貫実行する。"""
    doc, redirect_chain = bundle.read_concept(concept_id, follow_superseded=True)
    if doc.concept_type != "Attested Computation":
        return {
            "attested": False,
            "attestation_ok": False,
            "concept_id": doc.concept_id,
            "reason": (
                f"Concept '{doc.concept_id}' の type は '{doc.concept_type}' であり "
                "'Attested Computation' ではありません。"
            ),
        }

    if not doc.runtime or not doc.attester_resource:
        return {
            "attested": False,
            "attestation_ok": False,
            "concept_id": doc.concept_id,
            "trust_tier": doc.trust_tier,
            "status": doc.status,
            "is_stale": doc.is_stale,
            "reason": "runtime または attester 定義が欠落しているため検証対象外です (§10.2)。",
        }

    sanctioned_sql = bundle.load_computation_source(doc)
    if not sanctioned_sql:
        return {
            "attested": False,
            "attestation_ok": False,
            "concept_id": doc.concept_id,
            "reason": "承認済み計算本体 (`# Computation` または `computation:`) が見つかりません (§10.3)。",
        }

    if doc.runtime != executor.runtime_name:
        return {
            "attested": False,
            "attestation_ok": False,
            "concept_id": doc.concept_id,
            "reason": (
                f"実行器ランタイム不一致: concept={doc.runtime!r}, executor={executor.runtime_name!r}"
            ),
        }

    bound_params, param_errors = validate_and_bind_parameters(doc.parameters, parameters)
    if bound_params is None:
        return {
            "attested": False,
            "attestation_ok": False,
            "concept_id": doc.concept_id,
            "reason": "パラメータ検証エラー: " + "; ".join(param_errors),
        }

    try:
        receipt = executor.execute(sql=sanctioned_sql, parameters=bound_params)
    except (sqlite3.Error, RuntimeError, ValueError) as exc:
        return {
            "attested": False,
            "attestation_ok": False,
            "concept_id": doc.concept_id,
            "trust_tier": doc.trust_tier,
            "status": doc.status,
            "is_stale": doc.is_stale,
            "attestation_reason": f"計算実行エラー (Fail-Closed 遮断): {exc}",
        }
    verdict = attester.attest(
        concept=doc,
        sanctioned_sql=sanctioned_sql,
        expected_parameters=bound_params,
        receipt=receipt,
        executor=executor,
    )

    base_meta: dict[str, Any] = {
        "concept_id": doc.concept_id,
        "redirected_from": redirect_chain,
        "trust_tier": doc.trust_tier,
        "verified_before_last_change": doc.verified_before_last_change,
        "status": doc.status,
        "is_stale": doc.is_stale,
        "stale_after": doc.stale_after.isoformat() if doc.stale_after else None,
        "stale_warning": (
            f"定義の鮮度期限 ({doc.stale_after.isoformat()}) を超過しています。再確認を推奨します。"
            if doc.is_stale and doc.stale_after is not None
            else ("stale_after の書式が不正なため鮮度未確認です。" if doc.stale_malformed else None)
        ),
        "attestation_ok": verdict.ok,
        "attested": verdict.ok,
        "attestation_reason": verdict.reason,
        "receipt_ref": verdict.receipt_ref,
        "citations": [
            {"id": s.id, "title": s.title, "resource": s.resource} for s in doc.cited_sources
        ],
    }

    if not verdict.ok:
        # §10.5 Gate: Attestation 失敗時は値をいかなる形式でも返さない (Fail-Closed)
        return base_meta

    base_meta["bound_parameters"] = bound_params
    base_meta["result_sha256"] = receipt.result_sha256
    base_meta["rows"] = receipt.rows
    return base_meta
