# 런타임 JSON 자산 로더 — backend/app/assets/*.v1.json(taxonomy·character-vocab·seat-contract·rules-seed·adjacency·character-seed-rules·mech-owners)과 메커니즘 → 영역 배정표 읽기
from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.errors import AppError

# 자산 정본은 앱 패키지 안(plan §0.4.5) — pyproject package-data 로 wheel 에도 실린다.
ASSETS_DIR = Path(__file__).resolve().parent / "assets"
ASSET_VERSION = "v1"

# /meta/vocab 이 이름·버전을 나열하는 어휘 자산(taxonomy 는 /meta/taxonomy 로 따로 낸다).
VOCAB_ASSETS: tuple[str, ...] = (
    "character-vocab",
    "seat-contract",
    "rules-seed",
    "adjacency",
    "character-seed-rules",
    "mech-owners",            # 메커니즘 → 영역 배정표(재설계 M3 S3-2 — 승인 문 review_status)
    "change-routing",         # 변경 → 메커니즘·부품 역할 → 영역 표(재설계 M3 C3-5 — 승인 문 review_status)
)
# 메커니즘 → 영역 배정표(assets/mech-owners.v1.json). 택소노미 파일 밖에 둔다 — 배정은 사람이 고치는 정책이라 고칠 때마다
# taxonomy_version(지표 키의 접미)을 올리면 안 된다(M3.md 4.1). 승인 문은 review_status 가 이 값일 때만 열린다.
MECH_OWNERS_ASSET = "mech-owners"
APPROVED = "approved"


def asset_path(name: str) -> Path:
    """assets/<name>.v1.json 경로."""
    return ASSETS_DIR / f"{name}.{ASSET_VERSION}.json"


@lru_cache(maxsize=None)
def load_json(name: str) -> dict:
    """assets/<name>.v1.json 을 읽어 dict 로 돌려준다(프로세스 캐시). 없거나 깨지면 E300."""
    path = asset_path(name)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise AppError("E300", f"자산 파일이 없습니다: {path}", http_status=503) from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise AppError("E300", f"자산 파일을 읽을 수 없습니다: {path} — {exc}") from exc


def load_taxonomy() -> dict:
    """리스크 택소노미 v1(assets/taxonomy.v1.json)."""
    return load_json("taxonomy")


def mechanism_majors(doc: Mapping[str, Any] | None = None) -> tuple[str, ...]:
    """메커니즘 대분류 — 택소노미 메커니즘 축에 나온 차례 그대로(1.2 는 thermal … process · optical · acoustic · rf 아홉).
    risk_spec 스키마의 finding.mechanism enum 과 같다(시험이 본다). 정규화는 이 집합 밖의 대분류를 process 로 접는다."""
    doc = load_taxonomy() if doc is None else doc
    out: list[str] = []
    for item in doc["axes"]["mechanism"]:
        major = str(item.get("mechanism") or "")
        if major and major not in out:
            out.append(major)
    return tuple(out)


def mech_owners() -> dict[str, dict[str, tuple[str, ...]]]:
    """메커니즘 코드 → {owners, related}(배정표 행 차례 그대로). 소유는 그 메커니즘을 아무도 안 봤을 때 먼저 묻는 영역이고 차례에
    뜻이 있다(첫째가 먼저), 관련은 그 영역 사람이 말해도 믿는 영역이다. 승인 여부와 상관없이 표를 그대로 준다 — 승인 문은
    거르기의 코드 신호(`domains_for` 의 `signal`)에만 걸린다."""
    return {str(row["code"]): {"owners": tuple(row["owners"]), "related": tuple(row["related"])}
            for row in load_json(MECH_OWNERS_ASSET)["rows"]}


def mech_owners_meta() -> dict:
    """배정표의 판과 승인 문 — {version, taxonomy_version, review_status, reviewed_by, reviewed_at, approved}."""
    doc = load_json(MECH_OWNERS_ASSET)
    status = str(doc.get("review_status") or "draft")
    return {"version": str(doc.get("mech_owners_version") or ""), "taxonomy_version": str(doc.get("taxonomy_version") or ""),
            "review_status": status, "reviewed_by": doc.get("reviewed_by"), "reviewed_at": doc.get("reviewed_at"),
            "approved": status == APPROVED}


class DomainRoles(dict):
    """`domains_for` 의 결과 — {영역: 'owner' | 'related'} 에 승인 여부(`approved`)와 표에 없는 코드(`unknown`)를 단다.

    거르기의 코드 신호 가운데 메커니즘 몫은 `signal(domain)` 이다 — 배정표가 승인 전이면 어느 영역이든 'unknown'(승인 문, M3.md #40
    — 거르기가 일어나지 않는다), 승인 뒤면 소유 ∪ 관련은 'related', 표에 없는 코드가 하나라도 있으면 나머지는 'unknown', 그 밖은
    'unrelated' 다. 메커니즘이 하나도 없으면(설계 변경이 아니다) 'unrelated' 다. 셀 꾸러미의 코드 신호(relevance)는 여기에 부품 역할·
    always·풀리지 않은 변경 줄과 변경 → 메커니즘 표의 승인(status)을 더한다 — 어느 한 표라도 승인 전이면 전 영역 'unknown' 이다."""

    def __init__(self, roles: Mapping[str, str], *, approved: bool, unknown: Iterable[str] = ()) -> None:
        super().__init__(roles)
        self.approved = bool(approved)
        self.unknown: tuple[str, ...] = tuple(unknown)

    def signal(self, domain: str) -> str:
        if not self.approved:
            return "unknown"
        if domain in self:
            return "related"
        return "unknown" if self.unknown else "unrelated"


def domains_for(codes: Iterable[str]) -> DomainRoles:
    """메커니즘 코드 묶음 → 영역(소유가 관련을 이긴다). 표에 없는 코드는 `unknown` 에 모은다(차례 그대로, 겹침 없이)."""
    table = mech_owners()
    roles: dict[str, str] = {}
    unknown: list[str] = []
    for code in codes:
        row = table.get(str(code))
        if row is None:
            if str(code) not in unknown:
                unknown.append(str(code))
            continue
        for domain in row["owners"]:
            roles[domain] = "owner"
        for domain in row["related"]:
            roles.setdefault(domain, "related")
    return DomainRoles(roles, approved=mech_owners_meta()["approved"], unknown=unknown)


def mechanisms_of(domain: str) -> dict[str, list[str]]:
    """영역 → 그 영역이 소유·관련인 메커니즘 코드(배정표 행 차례). 한 행에서 소유와 관련은 겹치지 않는다(시험이 본다)."""
    out: dict[str, list[str]] = {"owner": [], "related": []}
    for code, row in mech_owners().items():
        if domain in row["owners"]:
            out["owner"].append(code)
        elif domain in row["related"]:
            out["related"].append(code)
    return out


def version_of(doc: dict) -> str | None:
    """자산 dict 의 버전 문자열 — 'version' 또는 '*_version' 키 중 첫 값."""
    if "version" in doc:
        return str(doc["version"])
    for key, value in doc.items():
        if key.endswith("_version"):
            return str(value)
    return None


def vocab_index() -> list[dict]:
    """어휘 자산(VOCAB_ASSETS)의 {name, file, present, version} 목록(/meta/vocab 용). 파일이 없어도 오류 없이 present=false."""
    out = []
    for name in VOCAB_ASSETS:
        path = asset_path(name)
        item = {"name": name, "file": path.name, "present": path.exists(), "version": None}
        if item["present"]:
            try:
                item["version"] = version_of(load_json(name))
            except AppError as exc:
                item["error"] = exc.message
        out.append(item)
    return out
