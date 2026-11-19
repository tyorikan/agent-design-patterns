"""OKF (Open Knowledge Format) v0.3 準拠バンドルパーサおよび決定論的ガバナンス評価モジュール。

Open Knowledge Format v0.3 仕様 (https://github.com/open-knowledge-format/open-knowledge-format/blob/main/SPEC.md) に基づき、
LLM に判断を委ねず決定論的に以下を実行する:
    1. 段階的開示 (Progressive Disclosure): `index.md` メタデータとディレクトリ構造の探索 (§8)
    2. 境界保護とパス解決: `bundle_root` 外へのパストラバーサルおよびシンボリックリンク脱出の拒否 (§3.2, §6)
    3. 信頼ティア自動算出: `verified[].at >= generated.at` の現行検証のみを有効とし、`human:` のみ
       `human-reviewed` と判定する (§5.2, §5.3 — エージェント編集後の自動降格)
    4. 鮮度・ライフサイクル判定: `stale_after` の絶対時刻評価 (パース不能値は非鮮度扱い、§5.5) および
       `status: deprecated` から `superseded_by` への転送 (§5.4)
    5. 寛容な消費と競合解決: 未知キーや単一値リストの吸収 (§11.2)、および 4 段階の決定論的競合解決
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import unquote

import yaml

TrustTier = Literal["unverified", "machine-confirmed", "human-reviewed"]

_RESERVED_FILENAMES = frozenset({"index.md", "log.md"})
_URI_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")
_DATE_ONLY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATETIME_OFFSET_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[Tt ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[Zz]|[+-]\d{2}:\d{2})$"
)
_FOOTNOTE_DEF_RE = re.compile(r"^\[\^([^\]]+)\]:", re.MULTILINE)
_FOOTNOTE_REF_RE = re.compile(r"\[\^([^\]]+)\](?!:)")
_MARKDOWN_LINK_RE = re.compile(r"(?<!!)\[([^\]]+)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_INLINE_CODE_RE = re.compile(r"`[^`]*`")
_ATX_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_FENCE_OPEN_RE = re.compile(r"^(`{3,}|~{3,})([^\n]*)$")
_BOM = "\ufeff"

_TRUST_RANK: dict[TrustTier, int] = {
    "unverified": 0,
    "machine-confirmed": 1,
    "human-reviewed": 2,
}


class OkfError(Exception):
    """OKF バンドル処理時の基底例外。"""


class PathTraversalError(OkfError):
    """`bundle_root` の外部を指すローカルパス参照を検知した際の例外 (§3.2, §6)。"""


class DuplicateFrontmatterKeyError(OkfError):
    """YAML フロントマター内の重複キーを検知した際の例外 (§4)。"""


class _NoDuplicateSafeLoader(yaml.SafeLoader):  # type: ignore[misc]
    """YAML マッピング内の重複キーを拒否する `SafeLoader` サブクラス (§4)。"""


def _construct_mapping_no_duplicates(
    loader: yaml.SafeLoader,
    node: yaml.MappingNode,
    deep: bool = False,
) -> dict[Any, Any]:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise DuplicateFrontmatterKeyError(f"フロントマターに重複キーがあります: {key!r}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_NoDuplicateSafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_mapping_no_duplicates,
)
# YAML 1.1 の暗黙 timestamp 変換を無効化し、RFC 3339 文字列として厳格検証する (§4, §5)
_NoDuplicateSafeLoader.yaml_implicit_resolvers = {
    ch: [(tag, rx) for tag, rx in resolvers if tag != "tag:yaml.org,2002:timestamp"]
    for ch, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


def _is_empty(value: Any) -> bool:
    """OKF §11.2 に従い、null・空文字列・空リストを欠損と同一視する。"""
    return value is None or value == "" or value == []


def _as_list(value: Any) -> list[Any]:
    """OKF §11.2 に従い、単一要素を要素数 1 のリストとして正規化する (カンマ分割はしない)。"""
    if _is_empty(value):
        return []
    if isinstance(value, list):
        return value
    return [value]


def parse_okf_timestamp(value: Any) -> datetime | None:
    """RFC 3339 準拠の日時文字列または YAML ネイティブ日時を UTC `datetime` へ変換する (§5)。

    - `full-date` (`YYYY-MM-DD` または `date`): 当日 00:00:00 UTC として解釈する。
    - `date-time`: タイムゾーンオフセット (`Z` または `±HH:MM`) が必須。オフセットなしは無効 (`None`)。
    """
    if _is_empty(value):
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return None
        return value.astimezone(UTC)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=UTC)
    if isinstance(value, str):
        raw = value.strip()
        if _DATE_ONLY_RE.match(raw):
            try:
                parsed_date = date.fromisoformat(raw)
            except ValueError:
                return None
            return datetime(parsed_date.year, parsed_date.month, parsed_date.day, tzinfo=UTC)
        if _DATETIME_OFFSET_RE.match(raw):
            normalized = raw.replace("z", "+00:00").replace("Z", "+00:00")
            try:
                parsed_dt = datetime.fromisoformat(normalized)
            except ValueError:
                return None
            if parsed_dt.tzinfo is None:
                return None
            return parsed_dt.astimezone(UTC)
    return None


def split_frontmatter(text: str) -> tuple[dict[str, Any] | None, str]:
    """Markdown テキストから YAML 1.2 フロントマターと本文を分離する (§4)。"""
    cleaned = text.lstrip(_BOM)
    lines = cleaned.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != "---":
        return None, cleaned

    end_idx: int | None = None
    for idx in range(1, len(lines)):
        if lines[idx].rstrip("\r\n") == "---":
            end_idx = idx
            break
    if end_idx is None:
        return None, cleaned

    yaml_text = "".join(lines[1:end_idx])
    body = "".join(lines[end_idx + 1 :])
    try:
        parsed = yaml.load(yaml_text, Loader=_NoDuplicateSafeLoader)
    except DuplicateFrontmatterKeyError:
        raise
    except yaml.YAMLError as exc:
        raise OkfError(f"フロントマターの YAML 解析に失敗しました: {exc}") from exc
    if parsed is None:
        return {}, body
    if not isinstance(parsed, dict):
        raise OkfError("フロントマターは YAML マッピングである必要があります (§4)。")
    return {str(k): v for k, v in parsed.items()}, body


def _parse_version_tuple(version_str: str | None) -> tuple[int, int] | None:
    if not version_str:
        return None
    parts = str(version_str).strip().split(".")
    if len(parts) < 2:
        return None
    try:
        return (int(parts[0]), int(parts[1]))
    except ValueError:
        return None


@dataclass(frozen=True)
class BundleMetadata:
    """バンドルルート `index.md` のフロントマターメタデータ (§8.1)。"""

    okf_version: str | None = None
    title: str | None = None
    description: str | None = None
    license: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SourceEntry:
    """Concept の出典 (`sources[]`) エントリ (§5.1)。"""

    resource: str
    id: str | None = None
    title: str | None = None
    author: str | None = None
    usage_count: int | None = None
    last_modified: datetime | None = None
    usage_window: dict[str, str] | None = None


@dataclass(frozen=True)
class VerificationEvent:
    """Concept の検証イベント (`verified[]`, §5.2)。"""

    by: str
    at: datetime


@dataclass(frozen=True)
class ParameterSpec:
    """`Attested Computation` の宣言パラメータ仕様 (§10.2)。"""

    name: str
    type: str
    required: bool = False


@dataclass(frozen=True)
class ResolvedTarget:
    """リンクまたはパスフィールドの解決結果 (§6)。"""

    raw: str
    is_external: bool
    resolved_path: Path | None = None
    concept_id: str | None = None


@dataclass(frozen=True)
class ConceptDocument:
    """パース済みの OKF v0.3 Concept と決定論的ガバナンス評価結果。"""

    concept_id: str
    file_path: Path
    concept_type: str
    title: str
    description: str
    resource: str | None
    tags: tuple[str, ...]
    status: str
    is_current_status: bool
    superseded_by: str | None
    generated_by: str | None
    generated_at: datetime | None
    generated_at_malformed: bool
    current_verifications: tuple[VerificationEvent, ...]
    historical_verifications: tuple[VerificationEvent, ...]
    trust_tier: TrustTier
    verified_before_last_change: bool
    stale_after: datetime | None
    is_stale: bool
    stale_malformed: bool
    sources: tuple[SourceEntry, ...]
    cited_sources: tuple[SourceEntry, ...]
    body: str
    links: tuple[ResolvedTarget, ...]
    runtime: str | None = None
    parameters: tuple[ParameterSpec, ...] = ()
    computation_path: str | None = None
    executor_resource: str | None = None
    executor_receipt: tuple[str, ...] = ()
    attester_resource: str | None = None
    frontmatter: dict[str, Any] = field(default_factory=dict)

    def to_summary_dict(self) -> dict[str, Any]:
        """段階的開示 (スキャン結果) 向けの軽量サマリ辞書を返す。"""
        return {
            "concept_id": self.concept_id,
            "type": self.concept_type,
            "title": self.title,
            "description": self.description,
            "tags": list(self.tags),
            "status": self.status,
            "is_current_status": self.is_current_status,
            "superseded_by": self.superseded_by,
            "trust_tier": self.trust_tier,
            "verified_before_last_change": self.verified_before_last_change,
            "is_stale": self.is_stale,
            "stale_after": self.stale_after.isoformat() if self.stale_after else None,
            "stale_malformed": self.stale_malformed,
            "generated_by": self.generated_by,
            "generated_at": self.generated_at.isoformat() if self.generated_at else None,
            "generated_at_malformed": self.generated_at_malformed,
        }


def compute_trust_tier(
    *,
    generated_at: datetime | None,
    verifications: list[VerificationEvent],
    generated_at_malformed: bool = False,
) -> tuple[TrustTier, tuple[VerificationEvent, ...], tuple[VerificationEvent, ...], bool]:
    """OKF v0.3 §5.3 に従い、現行検証イベントのみから信頼ティアを算出する。

    `verified[].at >= generated.at` (または `generated` 不在) のイベントのみを現行扱いとし、
    `human:` スキームのみ `human-reviewed` を付与する (`team:` や `process:` は `machine-confirmed`)。
    `generated.at` が非空かつ書式不正な場合は現行性を証明できないため安全側 (`unverified`) へ倒す。
    """
    current: list[VerificationEvent] = []
    historical: list[VerificationEvent] = []
    for event in verifications:
        if not generated_at_malformed and (generated_at is None or event.at >= generated_at):
            current.append(event)
        else:
            historical.append(event)

    current.sort(key=lambda e: e.at)
    historical.sort(key=lambda e: e.at)
    verified_before_last_change = len(current) == 0 and len(historical) > 0

    if not current:
        return "unverified", (), tuple(historical), verified_before_last_change

    has_human = any(
        ev.by.startswith("human:") and len(ev.by) > len("human:") for ev in current
    )
    tier: TrustTier = "human-reviewed" if has_human else "machine-confirmed"
    return tier, tuple(current), tuple(historical), verified_before_last_change


def resolve_concept_conflict(concepts: list[ConceptDocument]) -> ConceptDocument:
    """複数 Concept が競合した際に OKF 推奨の 4 段階優先順位で勝者を決定論的に選択する。

    優先順位:
        1. 現行ステータス (`stable` または `draft`) > 廃止/未知ステータス
        2. 信頼ティア (`human-reviewed` > `machine-confirmed` > `unverified`)
        3. 鮮度 (`is_stale == False` > `is_stale == True`)
        4. より新しい `generated_at`
    """
    if not concepts:
        raise ValueError("競合解決の対象 Concept が空です。")

    epoch_min = datetime(1970, 1, 1, tzinfo=UTC)

    def _rank_key(doc: ConceptDocument) -> tuple[int, int, int, datetime]:
        return (
            1 if doc.is_current_status else 0,
            _TRUST_RANK[doc.trust_tier],
            0 if doc.is_stale else 1,
            doc.generated_at or epoch_min,
        )

    return max(concepts, key=_rank_key)


def _iter_prose_lines(body: str) -> list[str]:
    """フェンスコードブロック・インデントコード・インラインコードを除外した本文行を返す。"""
    prose: list[str] = []
    fence_char = ""
    fence_len = 0
    in_fence = False

    for line in body.splitlines():
        stripped = line.lstrip()
        if in_fence:
            end_s = line.strip()
            if end_s and set(end_s) == {fence_char} and len(end_s) >= fence_len:
                in_fence = False
            continue

        m_fence = _FENCE_OPEN_RE.match(stripped)
        if m_fence:
            in_fence = True
            token = m_fence.group(1)
            fence_char = token[0]
            fence_len = len(token)
            continue

        if line.startswith(("    ", "\t")):
            continue
        prose.append(_INLINE_CODE_RE.sub("", line))

    return prose


def extract_inline_computation(body: str) -> str | None:
    """本文の `Computation` 見出しセクションから最初のコードブロックを抽出する (§10.3)。

    コードフェンス状態を先頭行から追跡するため、コードブロック内の `# Computation` コメントを
    見出しと誤認しない。
    """
    lines = body.splitlines()
    in_section = False
    section_level = 0
    in_fence = False
    fence_char = ""
    fence_len = 0
    code_lines: list[str] = []

    for line in lines:
        stripped_end = line.strip()
        if in_fence:
            if stripped_end and set(stripped_end) == {fence_char} and len(stripped_end) >= fence_len:
                if in_section:
                    return "\n".join(code_lines).strip()
                in_fence = False
                continue
            if in_section:
                code_lines.append(line)
            continue

        m_fence = _FENCE_OPEN_RE.match(line.lstrip())
        if m_fence:
            in_fence = True
            token = m_fence.group(1)
            fence_char = token[0]
            fence_len = len(token)
            if in_section:
                code_lines = []
            continue

        m_head = _ATX_HEADING_RE.match(line)
        if m_head:
            depth = len(m_head.group(1))
            if in_section and depth <= section_level:
                break
            if not in_section and m_head.group(2).strip().lower() == "computation":
                in_section = True
                section_level = depth

    return None


class OkfBundle:
    """OKF v0.3 バンドルを読み取り専用で探索・評価するクラス。"""

    def __init__(self, root: Path | str, *, now: datetime | None = None) -> None:
        self._root = Path(root).resolve()
        if not self._root.is_dir():
            raise OkfError(f"バンドルルートディレクトリが存在しません: {self._root}")
        self._fixed_now = now.astimezone(UTC) if now is not None else None
        self.metadata = self._load_root_metadata()

    @property
    def root(self) -> Path:
        return self._root

    def _current_time(self) -> datetime:
        return self._fixed_now if self._fixed_now is not None else datetime.now(UTC)

    def _is_v02_or_older(self) -> bool:
        parsed = _parse_version_tuple(self.metadata.okf_version)
        return parsed is None or parsed <= (0, 2)

    def _load_root_metadata(self) -> BundleMetadata:
        index_path = self._root / "index.md"
        if not index_path.is_file():
            return BundleMetadata()
        fm, _ = split_frontmatter(index_path.read_text(encoding="utf-8"))
        if not fm:
            return BundleMetadata()
        known_keys = {"okf_version", "title", "description", "license"}
        extra = {k: v for k, v in fm.items() if k not in known_keys}
        return BundleMetadata(
            okf_version=str(fm["okf_version"]) if not _is_empty(fm.get("okf_version")) else None,
            title=str(fm["title"]) if not _is_empty(fm.get("title")) else None,
            description=str(fm["description"]) if not _is_empty(fm.get("description")) else None,
            license=str(fm["license"]) if not _is_empty(fm.get("license")) else None,
            extra=extra,
        )

    def _assert_within_root(self, candidate: Path, raw_input: str) -> Path:
        resolved = candidate.resolve(strict=False)
        if not resolved.is_relative_to(self._root):
            raise PathTraversalError(
                f"バンドルルート外へのローカルパス参照は禁止されています: {raw_input!r}"
            )
        return resolved

    def resolve_path(
        self,
        raw_target: str,
        *,
        from_file: Path | None = None,
        is_path_field: bool = True,
        raise_on_escape: bool = False,
    ) -> ResolvedTarget:
        """OKF v0.3 §6 の統一ルールでリンクまたはパスフィールドを解決する。

        1. URI スキームあり -> 外部 URL (`is_external=True`)
        2. 先頭 `/` -> バンドルルート基準
        3. それ以外 -> 記述ファイル所在ディレクトリ基準 (v0.2 以下かつ path field はルートフォールバック可)
        """
        target_no_frag = raw_target.split("#", 1)[0].strip()
        if not target_no_frag or _URI_SCHEME_RE.match(target_no_frag):
            return ResolvedTarget(raw=raw_target, is_external=True)

        decoded = unquote(target_no_frag)
        base_dir = from_file.parent if from_file is not None else self._root

        if decoded.startswith("/"):
            candidate = self._root / decoded.lstrip("/")
        else:
            candidate = base_dir / decoded
            if (
                is_path_field
                and self._is_v02_or_older()
                and not candidate.exists()
                and (self._root / decoded).exists()
            ):
                candidate = self._root / decoded

        resolved = candidate.resolve(strict=False)
        if not resolved.is_relative_to(self._root):
            if raise_on_escape:
                raise PathTraversalError(
                    f"バンドルルート外へのパス参照を遮断しました: {raw_target!r}"
                )
            return ResolvedTarget(raw=raw_target, is_external=True)

        concept_id: str | None = None
        if resolved.is_file() and resolved.suffix == ".md":
            rel = resolved.relative_to(self._root)
            if rel.name not in _RESERVED_FILENAMES and not any(
                part.startswith(".") for part in rel.parts
            ):
                concept_id = rel.with_suffix("").as_posix()

        return ResolvedTarget(
            raw=raw_target,
            is_external=False,
            resolved_path=resolved,
            concept_id=concept_id,
        )

    def list_directory(self, relative_dir: str = "") -> dict[str, Any]:
        """段階的開示 (Progressive Disclosure) 用に指定ディレクトリの `index.md` と子要素一覧を返す。"""
        cleaned = unquote(relative_dir.strip()).lstrip("/")
        target_dir = self._assert_within_root(self._root / cleaned, relative_dir)
        if not target_dir.is_dir():
            raise OkfError(f"ディレクトリが見つかりません: {relative_dir!r}")

        index_content: str | None = None
        index_path = target_dir / "index.md"
        if index_path.is_file():
            self._assert_within_root(index_path, str(index_path))
            index_content = index_path.read_text(encoding="utf-8")

        children: list[dict[str, Any]] = []
        for entry in sorted(target_dir.iterdir(), key=lambda p: (not p.is_dir(), p.name)):
            if entry.name.startswith("."):
                continue
            resolved_entry = entry.resolve(strict=False)
            if not resolved_entry.is_relative_to(self._root):
                continue
            rel_posix = entry.relative_to(self._root).as_posix()
            if entry.is_dir():
                children.append({"name": entry.name, "kind": "directory", "path": rel_posix})
            elif entry.name in _RESERVED_FILENAMES:
                children.append({"name": entry.name, "kind": "reserved", "path": rel_posix})
            elif entry.suffix == ".md":
                try:
                    concept = self._try_load_concept_file(entry)
                except OkfError as exc:
                    children.append(
                        {
                            "name": entry.name,
                            "kind": "malformed_markdown",
                            "path": rel_posix,
                            "error": str(exc),
                        }
                    )
                    continue
                if concept is not None:
                    children.append(
                        {
                            "name": entry.name,
                            "kind": "concept",
                            "concept_id": concept.concept_id,
                            "type": concept.concept_type,
                            "title": concept.title,
                            "description": concept.description,
                            "trust_tier": concept.trust_tier,
                            "status": concept.status,
                            "is_stale": concept.is_stale,
                        }
                    )
                else:
                    # §3.2: type のない .md (README.md, AGENTS.md 等) は非 Concept としてスキップ可能
                    children.append({"name": entry.name, "kind": "non_concept_markdown", "path": rel_posix})
            else:
                children.append({"name": entry.name, "kind": "asset", "path": rel_posix})

        return {
            "directory": target_dir.relative_to(self._root).as_posix() or ".",
            "bundle_metadata": {
                "okf_version": self.metadata.okf_version,
                "title": self.metadata.title,
                "description": self.metadata.description,
                "license": self.metadata.license,
            },
            "index_markdown": index_content,
            "children": children,
        }

    def iter_concepts(self) -> list[ConceptDocument]:
        """バンドル配下の全有効 Concept を決定論的順序で読み込む (§3.2)。

        単一の破損ファイルでバンドル全体の探索が停止しないよう、フロントマター解析に失敗した
        ファイルはスキップして正常な Concept の読込を継続する (`read_concept` 直接指定時は例外送出)。
        """
        concepts: list[ConceptDocument] = []
        for path in sorted(self._root.rglob("*.md")):
            rel = path.relative_to(self._root)
            if any(part.startswith(".") for part in rel.parts):
                continue
            if rel.name in _RESERVED_FILENAMES:
                continue
            resolved = path.resolve(strict=False)
            if not resolved.is_relative_to(self._root):
                continue
            try:
                doc = self._try_load_concept_file(path)
            except OkfError:
                continue
            if doc is not None:
                concepts.append(doc)
        return concepts

    def scan_concepts(
        self,
        *,
        type_filter: str = "",
        tag: str = "",
        query: str = "",
        current_only: bool = True,
    ) -> list[ConceptDocument]:
        """本文を全展開せずフロントマター条件で Concept を絞り込む。"""
        results: list[ConceptDocument] = []
        q_lower = query.strip().lower()
        t_lower = type_filter.strip().lower()
        tag_lower = tag.strip().lower()

        for doc in self.iter_concepts():
            if current_only and not doc.is_current_status:
                continue
            if t_lower and doc.concept_type.lower() != t_lower:
                continue
            if tag_lower and not any(t.lower() == tag_lower for t in doc.tags):
                continue
            if q_lower:
                haystack = " ".join(
                    [doc.concept_id, doc.concept_type, doc.title, doc.description, *doc.tags]
                ).lower()
                if q_lower not in haystack:
                    continue
            results.append(doc)
        return results

    def read_concept(
        self,
        concept_id: str,
        *,
        follow_superseded: bool = True,
    ) -> tuple[ConceptDocument, list[str]]:
        """Concept ID を読み込む。`status: deprecated` かつ `superseded_by` がある場合は転送する (§5.4)。

        Returns:
            `(解決後の ConceptDocument, 転送元の concept_id 履歴)`
        """
        cleaned = unquote(concept_id.strip()).lstrip("/")
        if cleaned.endswith(".md"):
            cleaned = cleaned[:-3]
        if not cleaned:
            raise OkfError("concept_id が空です。")

        candidate = self._assert_within_root(self._root / f"{cleaned}.md", concept_id)
        if candidate.name in _RESERVED_FILENAMES:
            raise OkfError(f"予約ファイル {candidate.name} は Concept ではありません (§3.1)。")
        if not candidate.is_file():
            raise OkfError(f"Concept が見つかりません: {concept_id!r}")

        doc = self._try_load_concept_file(candidate)
        if doc is None:
            raise OkfError(
                f"{concept_id!r} には有効な `type` フロントマターがなく Concept ではありません (§3.2)。"
            )

        redirect_chain: list[str] = []
        visited = {doc.concept_id}
        while (
            follow_superseded
            and doc.status == "deprecated"
            and doc.superseded_by is not None
            and len(redirect_chain) < 8
        ):
            target = self.resolve_path(
                doc.superseded_by,
                from_file=doc.file_path,
                is_path_field=True,
                raise_on_escape=True,
            )
            if target.is_external or target.resolved_path is None or not target.resolved_path.is_file():
                break
            next_doc = self._try_load_concept_file(target.resolved_path)
            if next_doc is None or next_doc.concept_id in visited:
                break
            redirect_chain.append(doc.concept_id)
            visited.add(next_doc.concept_id)
            doc = next_doc

        return doc, redirect_chain

    def load_computation_source(self, doc: ConceptDocument) -> str | None:
        """`Attested Computation` の計算本体をファイルまたは `# Computation` セクションから取得する (§10.3)。"""
        if doc.computation_path:
            target = self.resolve_path(
                doc.computation_path,
                from_file=doc.file_path,
                is_path_field=True,
                raise_on_escape=True,
            )
            if target.is_external or target.resolved_path is None or not target.resolved_path.is_file():
                return None
            return target.resolved_path.read_text(encoding="utf-8").strip()
        return extract_inline_computation(doc.body)

    def _try_load_concept_file(self, path: Path) -> ConceptDocument | None:
        raw_text = path.read_text(encoding="utf-8")
        fm, body = split_frontmatter(raw_text)
        if not fm:
            return None
        raw_type = fm.get("type")
        if _is_empty(raw_type):
            return None

        concept_type = str(raw_type).strip()
        rel = path.relative_to(self._root)
        concept_id = rel.with_suffix("").as_posix()
        title = (
            str(fm["title"]).strip()
            if not _is_empty(fm.get("title"))
            else rel.stem.replace("_", " ").replace("-", " ")
        )
        description = (
            str(fm["description"]).strip() if not _is_empty(fm.get("description")) else ""
        )
        resource = str(fm["resource"]).strip() if not _is_empty(fm.get("resource")) else None
        tags = tuple(str(t).strip() for t in _as_list(fm.get("tags")) if not _is_empty(t))

        # Status (§5.4)
        raw_status = fm.get("status")
        status = "stable" if _is_empty(raw_status) else str(raw_status).strip()
        is_current_status = status in {"stable", "draft"}
        raw_superseded = fm.get("superseded_by")
        superseded_by = (
            str(raw_superseded).strip()
            if status == "deprecated" and not _is_empty(raw_superseded)
            else None
        )

        # Generated (§5.2) + v0.1 timestamp fallback (§12.1)
        generated_by: str | None = None
        generated_at: datetime | None = None
        generated_at_malformed = False
        raw_gen = fm.get("generated")
        if isinstance(raw_gen, dict) and not _is_empty(raw_gen.get("by")):
            generated_by = str(raw_gen["by"]).strip()
            raw_gen_at = raw_gen.get("at")
            if not _is_empty(raw_gen_at):
                generated_at = parse_okf_timestamp(raw_gen_at)
                if generated_at is None:
                    generated_at_malformed = True
        elif self._is_v02_or_older() and not _is_empty(fm.get("timestamp")):
            raw_ts = fm.get("timestamp")
            generated_at = parse_okf_timestamp(raw_ts)
            if generated_at is None:
                generated_at_malformed = True

        # Verified (§5.2, §5.3)
        verifications: list[VerificationEvent] = []
        for item in _as_list(fm.get("verified")):
            if not isinstance(item, dict):
                continue
            by_val = item.get("by")
            at_dt = parse_okf_timestamp(item.get("at"))
            if not _is_empty(by_val) and at_dt is not None:
                verifications.append(VerificationEvent(by=str(by_val).strip(), at=at_dt))

        trust_tier, current_ver, historical_ver, ver_before_change = compute_trust_tier(
            generated_at=generated_at,
            verifications=verifications,
            generated_at_malformed=generated_at_malformed,
        )

        # Freshness (§5.5)
        raw_stale = fm.get("stale_after")
        stale_after: datetime | None = None
        is_stale = False
        stale_malformed = False
        if not _is_empty(raw_stale):
            stale_after = parse_okf_timestamp(raw_stale)
            if stale_after is None:
                # §5.5: パース不能な stale_after を決して鮮度内 (fresh) 扱いしてはならない
                is_stale = True
                stale_malformed = True
            else:
                is_stale = self._current_time() >= stale_after

        # Provenance / Sources (§5.1)
        default_window: dict[str, str] | None = None
        raw_uw = fm.get("usage_window")
        if isinstance(raw_uw, dict) and not _is_empty(raw_uw.get("from")) and not _is_empty(raw_uw.get("to")):
            default_window = {"from": str(raw_uw["from"]), "to": str(raw_uw["to"])}

        sources: list[SourceEntry] = []
        source_by_id: dict[str, SourceEntry] = {}
        for item in _as_list(fm.get("sources")):
            if not isinstance(item, dict) or _is_empty(item.get("resource")):
                continue
            item_uw = default_window
            if isinstance(item.get("usage_window"), dict):
                uw_map = item["usage_window"]
                if not _is_empty(uw_map.get("from")) and not _is_empty(uw_map.get("to")):
                    item_uw = {"from": str(uw_map["from"]), "to": str(uw_map["to"])}
            raw_uc = item.get("usage_count")
            usage_count = (
                int(raw_uc)
                if isinstance(raw_uc, int) and not isinstance(raw_uc, bool)
                else None
            )
            entry = SourceEntry(
                resource=str(item["resource"]).strip(),
                id=str(item["id"]).strip() if not _is_empty(item.get("id")) else None,
                title=str(item["title"]).strip() if not _is_empty(item.get("title")) else None,
                author=str(item["author"]).strip() if not _is_empty(item.get("author")) else None,
                usage_count=usage_count,
                last_modified=parse_okf_timestamp(item.get("last_modified")),
                usage_window=item_uw,
            )
            sources.append(entry)
            if entry.id:
                source_by_id[entry.id] = entry

        # Per-claim footnote resolution (§5.1) — コードブロック・インラインコードを除外した本文から抽出
        prose_text = "\n".join(_iter_prose_lines(body))
        prose_without_defs = _FOOTNOTE_DEF_RE.sub("", prose_text)
        cited_ids = list(dict.fromkeys(_FOOTNOTE_REF_RE.findall(prose_without_defs)))
        cited_sources = tuple(source_by_id[cid] for cid in cited_ids if cid in source_by_id)

        # Markdown links (§6.1) — コード外の本文リンクのみ抽出
        links: list[ResolvedTarget] = []
        for _, raw_link in _MARKDOWN_LINK_RE.findall(prose_text):
            links.append(
                self.resolve_path(
                    raw_link,
                    from_file=path,
                    is_path_field=False,
                    raise_on_escape=False,
                )
            )

        # Attested Computation fields (§10.2)
        runtime = str(fm["runtime"]).strip() if not _is_empty(fm.get("runtime")) else None
        computation_path = (
            str(fm["computation"]).strip() if not _is_empty(fm.get("computation")) else None
        )
        parameters: list[ParameterSpec] = []
        for p_item in _as_list(fm.get("parameters")):
            if not isinstance(p_item, dict):
                continue
            p_name = p_item.get("name")
            p_type = p_item.get("type")
            if _is_empty(p_name) or _is_empty(p_type):
                continue
            parameters.append(
                ParameterSpec(
                    name=str(p_name).strip(),
                    type=str(p_type).strip().lower(),
                    required=bool(p_item.get("required", False)),
                )
            )

        executor_resource: str | None = None
        executor_receipt: tuple[str, ...] = ()
        raw_exec = fm.get("executor")
        if isinstance(raw_exec, dict):
            if not _is_empty(raw_exec.get("resource")):
                executor_resource = str(raw_exec["resource"]).strip()
            executor_receipt = tuple(
                str(r).strip() for r in _as_list(raw_exec.get("receipt")) if not _is_empty(r)
            )

        attester_resource: str | None = None
        raw_att = fm.get("attester")
        if isinstance(raw_att, dict) and not _is_empty(raw_att.get("resource")):
            attester_resource = str(raw_att["resource"]).strip()

        return ConceptDocument(
            concept_id=concept_id,
            file_path=path,
            concept_type=concept_type,
            title=title,
            description=description,
            resource=resource,
            tags=tags,
            status=status,
            is_current_status=is_current_status,
            superseded_by=superseded_by,
            generated_by=generated_by,
            generated_at=generated_at,
            generated_at_malformed=generated_at_malformed,
            current_verifications=current_ver,
            historical_verifications=historical_ver,
            trust_tier=trust_tier,
            verified_before_last_change=ver_before_change,
            stale_after=stale_after,
            is_stale=is_stale,
            stale_malformed=stale_malformed,
            sources=tuple(sources),
            cited_sources=cited_sources,
            body=body.strip(),
            links=tuple(links),
            runtime=runtime,
            parameters=tuple(parameters),
            computation_path=computation_path,
            executor_resource=executor_resource,
            executor_receipt=executor_receipt,
            attester_resource=attester_resource,
            frontmatter=fm,
        )
