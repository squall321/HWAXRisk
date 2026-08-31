# 크로스도메인 same-as 사다리(§2.6)·클러스터/dn·전역 정규 키 ckey 부여(§2.7)와 rr_sameas·rr_part_keys·rr_iface_alias 원장 재적용(§2.10)
from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Mapping, Sequence

from .common import canonical_json, new_uuid, now_epoch
from .errors import AppError

try:                                                        # pragma: no cover - 선택 의존성(설치 여부가 결과를 바꾸지 않는다)
    from scipy.optimize import linear_sum_assignment as _scipy_lsa   # type: ignore
except ImportError:                                         # pragma: no cover
    _scipy_lsa = None

__all__ = [
    "SAMEAS_METHODS",
    "AUTO_SCORE",
    "PENDING_SCORE",
    "FUZZY_WEIGHTS",
    "stable_key",
    "load_ledger",
    "resolve",
    "score_pair",
    "build_clusters",
    "material_norm_of",
    "geom_bucket",
    "compute_ckey",
    "resolve_ckey",
    "assign_ckeys",
    "inherit_ckeys",
    "record_iface_aliases",
    "record_decision",
    "review_rows",
]

# ---------------------------------------------------------------- 상수(§2.6)
SAMEAS_METHODS: tuple[str, ...] = (
    "ledger", "pid_map", "exact_path", "fingerprint", "name_norm", "fuzzy", "manual",
)
AUTO_SCORE = 0.90          # 이 값 이상이면 status='auto' 이고 클러스터에 들어간다.
PENDING_SCORE = 0.70       # 이 값 미만은 레코드를 만들지 않는다.
FUZZY_WEIGHTS = {"name": 0.35, "geom": 0.35, "material": 0.10, "neighbor": 0.20}
DUMMY_COST = 1.0 - PENDING_SCORE   # 헝가리안 미배정 더미 비용 0.30(§2.6.3).
PRUNE_MIN = 0.5            # geom_sim ≥ 0.5 OR name_sim ≥ 0.5 인 쌍만 비용 행렬에 넣는다.
_BIG = 1.0e6               # 가지치기된 쌍의 유한 비용(무한대는 포텐셜 계산을 깨뜨린다).

# 이웃 유사도에 쓰는 엣지 계열(§2.6.3 — iface·contact family 1홉).
NEIGHBOR_FAMILIES: tuple[str, ...] = ("iface", "contact")
# 계면 별칭 사전이 받는 엣지 kind(§5.9.3).
ALIAS_EDGE_KINDS: tuple[str, ...] = ("tied", "touching", "clearance", "interference", "contact")

# 대표 nid 우선순위(§2.7.5) — mcad part > dyna pid > ecad component.
_DN_RANK = {("mcad", "part"): 0, ("dyna", "pid"): 1, ("ecad", "component"): 2}
_DN_FALLBACK = 9

MERGE_CHAIN_MAX = 5        # merged_into 체인 추적 상한(§2.7.3).


# ---------------------------------------------------------------- 작은 유틸
def _sha1_12(text: str) -> str:
    """sha1 소문자 hex 앞 12자 — nid·eid·cid 와 같은 폭이다."""
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def _tokens(text: str | None) -> set[str]:
    """`_` 로 끊은 토큰 집합(빈 토큰 제거)."""
    if not text:
        return set()
    return {t for t in str(text).split("_") if t}


def _levenshtein_ratio(a: str, b: str) -> float:
    """편집거리 기반 0..1 유사도. 두 문자열이 모두 비면 0.0 이다."""
    if not a and not b:
        return 0.0
    if a == b:
        return 1.0
    if not a or not b:
        return 0.0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        cur = [i]
        for j, cb in enumerate(b, start=1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (0 if ca == cb else 1)))
        prev = cur
    return 1.0 - prev[-1] / max(len(a), len(b))


def _jaccard(a: set, b: set) -> float:
    """두 집합의 자카드 지수. 둘 다 비면 0.0 이다(0.5 로 올리는 것은 호출자의 규칙이다)."""
    if not a and not b:
        return 0.0
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def _attrs(node: Mapping[str, Any]) -> Mapping[str, Any]:
    value = node.get("attrs")
    return value if isinstance(value, Mapping) else {}


def _size_sorted(node: Mapping[str, Any]) -> list[float]:
    """노드의 size_sorted(내림차순 3축). 없으면 빈 목록이다."""
    raw = _attrs(node).get("size_sorted")
    if not isinstance(raw, (list, tuple)):
        return []
    out: list[float] = []
    for v in raw:
        if not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v):
            return []
        out.append(float(v))
    return out


def _volume(node: Mapping[str, Any]) -> float | None:
    v = _attrs(node).get("volume")
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        return None
    if not math.isfinite(v):
        return None
    return float(v)


def _is_solid(node: Mapping[str, Any]) -> bool:
    """부피 비교를 걸 수 있는 solid 인지(mcad shape_kind · dyna elem_class)."""
    at = _attrs(node)
    return at.get("shape_kind") == "solid" or at.get("elem_class") == "solid"


def _domain(node: Mapping[str, Any]) -> str:
    return str(node.get("domain") or "")


def _canon(node: Mapping[str, Any]) -> str:
    """name_norm_canon(없으면 name_norm, 그것도 없으면 빈 문자열)."""
    return str(node.get("name_norm_canon") or node.get("name_norm") or "")


def _canon_key(node: Mapping[str, Any]) -> str:
    return str(node.get("canon_key") or node.get("nid") or "")


def _auto_named(node: Mapping[str, Any]) -> bool:
    flags = node.get("status_flags")
    return bool(isinstance(flags, (list, tuple)) and "auto_named" in flags)


def _by_nid(nodes: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    return {str(n.get("nid")): n for n in nodes if n.get("nid")}


def _sorted_nodes(nodes: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """canon_key 오름차순 고정 — 헝가리안 동점 처리와 재현성의 전제다(§2.6.3)."""
    return sorted(nodes, key=lambda n: (_canon_key(n), str(n.get("nid") or "")))


# ---------------------------------------------------------------- stable key(§2.6.2 1단계)
def stable_key(node: Mapping[str, Any]) -> str | None:
    """원장 대조용 안정 키. mcad canon_key · dyna name_norm_canon@elem_class · ecad refdes.

    pid·sha 는 K파일마다 바뀌므로 dyna 는 canon_key 를 쓰지 않는다. 만들 수 없으면 None 이다.
    """
    domain = _domain(node)
    if domain == "mcad":
        return _canon_key(node) or None
    if domain == "dyna":
        canon = _canon(node)
        if not canon:
            return None
        elem_class = _attrs(node).get("elem_class") or "na"
        return f"{canon}@{elem_class}"
    if domain == "ecad":
        return str(node.get("local_key") or node.get("label") or "") or None
    return _canon_key(node) or None


def load_ledger(store, scope: str, pair_key: str, owner_sub: str) -> dict[tuple[str, str], dict]:
    """rr_sameas 에서 (scope, pair_key) 원장 행을 읽어 정렬한 stable 키 쌍으로 색인한다.

    `scope='global'` 행은 ckey 쌍이므로 호출자가 별도로 읽는다(§2.6.2 1단계).
    """
    rows = store.query(
        "SELECT id, scope, pair_key, a_stable, b_stable, method, score, status, evidence,"
        " decided_by, decided_at, snapshot_id_at_decision"
        " FROM rr_sameas WHERE scope=? AND pair_key=? AND owner_sub=?",
        (scope, pair_key, owner_sub),
    )
    out: dict[tuple[str, str], dict] = {}
    for row in rows:
        key = tuple(sorted((str(row["a_stable"]), str(row["b_stable"]))))
        out[key] = dict(row)
    return out


# ---------------------------------------------------------------- 점수(§2.6.3)
def _name_sim(a: Mapping[str, Any], b: Mapping[str, Any]) -> float:
    ca, cb = _canon(a), _canon(b)
    sim = max(_jaccard(_tokens(ca), _tokens(cb)), _levenshtein_ratio(ca, cb))
    # G1 fail 의 effect — auto_named 노드는 이름 신호를 낮춘다(§3.2.2).
    if _auto_named(a) or _auto_named(b):
        sim *= 0.5
    return sim


def _geom_sim(a: Mapping[str, Any], b: Mapping[str, Any]) -> float:
    sa, sb = _size_sorted(a), _size_sorted(b)
    if len(sa) != 3 or len(sb) != 3:
        return 0.0
    denom = sum(sb)
    if denom <= 0:
        return 0.0
    size_part = 1.0 - min(1.0, sum(abs(x - y) for x, y in zip(sa, sb)) / denom)
    va, vb = _volume(a), _volume(b)
    if _is_solid(a) and _is_solid(b) and va is not None and vb is not None and vb > 0:
        vol_part = 1.0 - min(1.0, abs(va - vb) / vb)
        return 0.5 * size_part + 0.5 * vol_part
    return size_part


def _material_eq(a: Mapping[str, Any], b: Mapping[str, Any]) -> float:
    ta = _tokens(material_norm_of(a)) - {"na"}
    tb = _tokens(material_norm_of(b)) - {"na"}
    if not ta or not tb:
        return 0.5
    return 1.0 if (ta & tb) else 0.0


def score_pair(
    a: Mapping[str, Any],
    b: Mapping[str, Any],
    neighbors_a: set[str] | None = None,
    neighbors_b: set[str] | None = None,
) -> dict:
    """§2.6.3 fuzzy 점수 하나. `neighbors_*` 는 이미 확정된 대응으로 사상한 이웃 식별자 집합이다.

    반환은 `{score, name_sim, geom_sim, material_eq, neighbor_sim}` 이고 판단은 담지 않는다.
    """
    name_sim = _name_sim(a, b)
    geom_sim = _geom_sim(a, b)
    material_eq = _material_eq(a, b)
    na = neighbors_a or set()
    nb = neighbors_b or set()
    neighbor_sim = 0.5 if (not na and not nb) else _jaccard(na, nb)
    score = (
        FUZZY_WEIGHTS["name"] * name_sim
        + FUZZY_WEIGHTS["geom"] * geom_sim
        + FUZZY_WEIGHTS["material"] * material_eq
        + FUZZY_WEIGHTS["neighbor"] * neighbor_sim
    )
    return {
        "score": round(score, 6),
        "name_sim": round(name_sim, 6),
        "geom_sim": round(geom_sim, 6),
        "material_eq": material_eq,
        "neighbor_sim": round(neighbor_sim, 6),
    }


# ---------------------------------------------------------------- 이웃 사상
class _UnionFind:
    """확정 대응으로 두 스냅샷·두 도메인의 노드를 한 식별자로 접는다(이웃 유사도용)."""

    def __init__(self) -> None:
        self._parent: dict[str, str] = {}

    def find(self, x: str) -> str:
        self._parent.setdefault(x, x)
        root = x
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[x] != root:
            self._parent[x], x = root, self._parent[x]
        return root

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if rb < ra:            # 대표는 사전순으로 작은 쪽 — 결정론.
            ra, rb = rb, ra
        self._parent[rb] = ra


def _neighbor_index(edges: Sequence[Mapping[str, Any]]) -> dict[str, set[str]]:
    """iface·contact family 1홉 이웃 색인."""
    index: dict[str, set[str]] = {}
    for edge in edges:
        if str(edge.get("kind_family") or "") not in NEIGHBOR_FAMILIES:
            continue
        if str(edge.get("status") or "") == "rejected":
            continue
        ends = [edge.get("a"), edge.get("b")]
        members = edge.get("members")
        if isinstance(members, (list, tuple)):
            ends.extend(members)
        ends = [str(x) for x in ends if x]
        for x in ends:
            for y in ends:
                if x != y:
                    index.setdefault(x, set()).add(y)
    return index


# ---------------------------------------------------------------- 헝가리안(§2.6.3)
def _hungarian(cost: list[list[float]]) -> list[int]:
    """정사각 비용 행렬의 최소비용 완전 배정. 행 i → 열 result[i].

    scipy 가 있으면 그것을, 없으면 동봉한 O(n³) JV 구현을 쓴다(노드 ≤ 500 이라 충분하다).
    """
    n = len(cost)
    if n == 0:
        return []
    if _scipy_lsa is not None:
        # 계산 예외는 삼키지 않는다 — 조용한 폴백은 같은 입력에 다른 배정(=다른 ir_hash)을 만든다.
        _, col = _scipy_lsa(cost)
        return [int(c) for c in col]
    inf = float("inf")
    u = [0.0] * (n + 1)
    v = [0.0] * (n + 1)
    p = [0] * (n + 1)
    way = [0] * (n + 1)
    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv = [inf] * (n + 1)
        used = [False] * (n + 1)
        while True:
            used[j0] = True
            i0, delta, j1 = p[j0], inf, 0
            for j in range(1, n + 1):
                if used[j]:
                    continue
                cur = cost[i0 - 1][j - 1] - u[i0] - v[j]
                if cur < minv[j]:
                    minv[j], way[j] = cur, j0
                if minv[j] < delta:
                    delta, j1 = minv[j], j
            for j in range(n + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while j0:
            j1 = way[j0]
            p[j0], j0 = p[j1], j1
    result = [-1] * n
    for j in range(1, n + 1):
        if p[j]:
            result[p[j] - 1] = j - 1
    return result


# ---------------------------------------------------------------- 사다리 본체
def _record(scope: str, a: str, b: str, method: str, score: float, status: str, evidence: dict) -> dict:
    """same_as 레코드 하나(§2.6.1). id 는 (scope, a, b) 결정론 해시라 재실행해도 같다."""
    return {
        "id": "sa:" + _sha1_12(f"{scope}|{a}|{b}"),
        "scope": scope,
        "a": a,
        "b": b,
        "method": method,
        "score": round(float(score), 6),
        "status": status,
        "evidence": evidence,
        "decided_by": None,
        "decided_at": None,
        "ledger_id": None,
    }


def _status_for(method: str, score: float) -> str:
    """§2.6.1 status 규칙 — 결정론 단계와 score ≥ 0.90 은 auto, 0.70~0.90 은 pending."""
    if method in ("pid_map", "exact_path"):
        return "auto"
    return "auto" if score >= AUTO_SCORE else "pending"


def resolve(
    nodes_a: Sequence[Mapping[str, Any]],
    nodes_b: Sequence[Mapping[str, Any]],
    edges_a: Sequence[Mapping[str, Any]],
    edges_b: Sequence[Mapping[str, Any]],
    scope: str,
    ledger: Mapping[tuple[str, str], Mapping[str, Any]] | None = None,
) -> list[dict]:
    """§2.6.2 사다리 7단계 중 코드가 도는 1~6 단계. 스냅샷 내부(intra)와 스냅샷 간(pair)이 같은 함수다.

    `nodes_a`·`nodes_b` 는 이분 그래프의 두 쪽이다 — intra 는 도메인 쌍(mcad↔dyna 등)마다,
    pair 는 base↔target 으로 호출한다. 앞 단계에서 확정된 노드는 뒤 단계 후보에서 빠지고
    원장 `rejected` 쌍은 뒤 단계가 다시 제안하지 못한다. 반환은 §2.6.1 레코드 목록이며 판단어를 담지 않는다.
    """
    if scope not in ("intra", "pair"):
        raise AppError("E100", f"sameas.resolve(): scope 는 intra|pair 여야 합니다 — {scope!r}.", 400)

    a_nodes = _sorted_nodes(nodes_a)
    b_nodes = _sorted_nodes(nodes_b)
    a_by_nid = _by_nid(a_nodes)
    b_by_nid = _by_nid(b_nodes)
    neighbors = _neighbor_index(list(edges_a) + list(edges_b))
    uf = _UnionFind()

    records: list[dict] = []
    taken_a: set[str] = set()
    taken_b: set[str] = set()
    blocked: set[tuple[str, str]] = set()

    def accept(a_nid: str, b_nid: str, method: str, score: float, evidence: dict, status: str | None = None) -> None:
        if scope == "intra" and a_nid == b_nid:
            return                       # intra 는 도메인 쌍 호출이라 같은 nid 쌍이 없다(pair 의 자기-diff 는 정상).
        st = status or _status_for(method, score)
        records.append(_record(scope, a_nid, b_nid, method, score, st, evidence))
        if st in ("confirmed", "auto") and score >= AUTO_SCORE:
            taken_a.add(a_nid)
            taken_b.add(b_nid)
            uf.union(a_nid, b_nid)

    def free_pairs() -> list[tuple[str, Mapping[str, Any], str, Mapping[str, Any]]]:
        out = []
        for a_nid, a in ((str(n["nid"]), n) for n in a_nodes):
            if a_nid in taken_a:
                continue
            for b_nid, b in ((str(n["nid"]), n) for n in b_nodes):
                if b_nid in taken_b or (a_nid, b_nid) in blocked:
                    continue
                out.append((a_nid, a, b_nid, b))
        return out

    def ident(nid: str) -> str:
        return uf.find(nid)

    def mapped_neighbors(nid: str) -> set[str]:
        return {ident(x) for x in neighbors.get(nid, set())}

    # --- 1단계 ledger — 사람 확정이 재검출·재추출을 이긴다(§2.10 우선순위).
    ledger = dict(ledger or {})
    if ledger:
        stable_a = {str(n["nid"]): stable_key(n) for n in a_nodes}
        stable_b = {str(n["nid"]): stable_key(n) for n in b_nodes}
        for a_nid, a in ((str(n["nid"]), n) for n in a_nodes):
            sa = stable_a.get(a_nid)
            if not sa:
                continue
            for b_nid, b in ((str(n["nid"]), n) for n in b_nodes):
                sb = stable_b.get(b_nid)
                if not sb or (scope == "intra" and a_nid == b_nid):
                    continue
                row = ledger.get(tuple(sorted((sa, sb))))
                if row is None:
                    continue
                status = str(row.get("status") or "confirmed")
                evidence = {"ledger": {"a_stable": sa, "b_stable": sb, "row_id": row.get("id")}}
                rec = _record(scope, a_nid, b_nid, "ledger", 1.0, status, evidence)
                rec["decided_by"] = row.get("decided_by")
                rec["decided_at"] = row.get("decided_at")
                rec["ledger_id"] = row.get("id")
                records.append(rec)
                if status == "confirmed":
                    taken_a.add(a_nid)
                    taken_b.add(b_nid)
                    uf.union(a_nid, b_nid)
                else:
                    blocked.add((a_nid, b_nid))

    ecad_here = any(_domain(n) == "ecad" for n in a_nodes) or any(_domain(n) == "ecad" for n in b_nodes)

    # --- 2단계 pid_map — bridge 엣지(part_mesh 표)가 살아 있을 때만(§2.6.2).
    if scope == "intra" and not ecad_here:
        for edge in sorted(list(edges_a) + list(edges_b), key=lambda e: str(e.get("eid") or "")):
            if str(edge.get("kind") or "") != "bridge":
                continue
            at = _attrs(edge)
            if bool(at.get("bridge_stale")):
                continue                       # stale 이면 이 단계를 건너뛰고 6단계로 내린다.
            x, y = str(edge.get("a") or ""), str(edge.get("b") or "")
            for a_nid, b_nid in ((x, y), (y, x)):
                if a_nid in a_by_nid and b_nid in b_by_nid and a_nid not in taken_a and b_nid not in taken_b:
                    if (a_nid, b_nid) in blocked:
                        continue
                    accept(a_nid, b_nid, "pid_map", 1.0,
                           {"bridge": {"mesh_key": at.get("mesh_key"), "stale": False}})
                    break

    # --- 3단계 exact_path — pair 스코프의 mcad 만.
    # dyna 는 canon_key 에 sha 가 들어 있어 대상이 아니고(5단계로), ecad 는 1차에서 1·5·7 단계만 허용한다(§2.6.4).
    if scope == "pair":
        for a_nid, a, b_nid, b in free_pairs():
            if a_nid in taken_a or b_nid in taken_b:
                continue
            if _domain(a) != "mcad" or _domain(b) != "mcad":
                continue
            if _canon_key(a) and _canon_key(a) == _canon_key(b):
                accept(a_nid, b_nid, "exact_path", 1.0, {"canon_key": _canon_key(a)})

    # --- 4단계 fingerprint — 같은 도메인은 geom_fp, mcad↔dyna 는 size/volume 상대오차(§2.6.2).
    if not ecad_here:
        fp_pairs: list[tuple[str, str, float, str, dict]] = []
        for a_nid, a, b_nid, b in free_pairs():
            da, db = _domain(a), _domain(b)
            if da == db and scope == "pair":
                fp = a.get("geom_fp")
                if fp and fp == b.get("geom_fp"):
                    name_sim = _name_sim(a, b)
                    if name_sim >= 0.5:
                        fp_pairs.append((a_nid, b_nid, 0.95, "auto",
                                         {"geom_fp": fp, "name_sim": round(name_sim, 6)}))
                    else:
                        fp_pairs.append((a_nid, b_nid, 0.85, "pending",
                                         {"geom_fp": fp, "name_sim": round(name_sim, 6)}))
            elif {da, db} == {"mcad", "dyna"} and scope == "intra":
                sa, sb = _size_sorted(a), _size_sorted(b)
                if len(sa) != 3 or len(sb) != 3 or min(sb) <= 0:
                    continue
                if any(abs(x - y) / y > 0.02 for x, y in zip(sa, sb)):
                    continue
                va, vb = _volume(a), _volume(b)
                penalty = 0.0
                if _is_solid(a) and _is_solid(b) and va is not None and vb is not None and vb > 0:
                    if abs(va - vb) / vb > 0.03:
                        continue
                elif va is None or vb is None:
                    penalty = 0.05
                fp_pairs.append((a_nid, b_nid, 0.90 - penalty, "auto",
                                 {"size_rel_max": round(max(abs(x - y) / y for x, y in zip(sa, sb)), 6),
                                  "volume_penalty": penalty}))
        # 1:1 인 쌍만 확정하고 1:N 은 6단계로 내린다(§2.6.2 4단계).
        count_a: dict[str, int] = {}
        count_b: dict[str, int] = {}
        for a_nid, b_nid, _s, _st, _ev in fp_pairs:
            count_a[a_nid] = count_a.get(a_nid, 0) + 1
            count_b[b_nid] = count_b.get(b_nid, 0) + 1
        for a_nid, b_nid, score, status, evidence in sorted(fp_pairs, key=lambda t: (-t[2], t[0], t[1])):
            if a_nid in taken_a or b_nid in taken_b:
                continue
            if count_a[a_nid] > 1 or count_b[b_nid] > 1:
                continue
            accept(a_nid, b_nid, "fingerprint", score, evidence, status)

    # --- 5단계 name_norm — name_norm_canon 완전 일치이고 후보가 1:1 일 때만.
    name_pairs: list[tuple[str, str]] = []
    for a_nid, a, b_nid, b in free_pairs():
        ca, cb = _canon(a), _canon(b)
        if not ca or ca != cb:
            continue
        if "ecad" in (_domain(a), _domain(b)) and _domain(a) != _domain(b):
            # ecad↔mcad/dyna 는 refdes 또는 part_number 토큰이 상대 name_norm_canon 토큰과 겹칠 때만(§2.6.2 5단계).
            ecad_node = a if _domain(a) == "ecad" else b
            other = b if ecad_node is a else a
            at = _attrs(ecad_node)
            tokens = _tokens(str(at.get("refdes") or ecad_node.get("local_key") or "").lower())
            tokens |= _tokens(str(at.get("part_number") or "").lower())
            if not (tokens & _tokens(_canon(other))):
                continue
        name_pairs.append((a_nid, b_nid))
    count_a = {}
    count_b = {}
    for a_nid, b_nid in name_pairs:
        count_a[a_nid] = count_a.get(a_nid, 0) + 1
        count_b[b_nid] = count_b.get(b_nid, 0) + 1
    for a_nid, b_nid in sorted(name_pairs):
        if a_nid in taken_a or b_nid in taken_b:
            continue
        if count_a[a_nid] > 1 or count_b[b_nid] > 1:
            continue
        accept(a_nid, b_nid, "name_norm", 0.95, {"name_norm_canon": _canon(a_by_nid[a_nid])})

    # --- 6단계 fuzzy — 남은 노드로 이분 그래프를 만들어 헝가리안 배정(ecad 는 제외, §2.6.4).
    rest_a = [n for n in a_nodes if str(n["nid"]) not in taken_a and _domain(n) != "ecad"]
    rest_b = [n for n in b_nodes if str(n["nid"]) not in taken_b and _domain(n) != "ecad"]
    if rest_a and rest_b:
        scores: dict[tuple[str, str], dict] = {}
        for a in rest_a:
            a_nid = str(a["nid"])
            for b in rest_b:
                b_nid = str(b["nid"])
                if (a_nid, b_nid) in blocked:
                    continue
                s = score_pair(a, b, mapped_neighbors(a_nid), mapped_neighbors(b_nid))
                if s["geom_sim"] < PRUNE_MIN and s["name_sim"] < PRUNE_MIN:
                    continue                                   # 가지치기 — 비용 ∞ 로 둔다.
                scores[(a_nid, b_nid)] = s
        if scores:
            na, nb = len(rest_a), len(rest_b)
            size = na + nb
            eps_den = float(na * nb + 1)
            matrix = [[0.0] * size for _ in range(size)]
            for i, a in enumerate(rest_a):
                a_nid = str(a["nid"])
                for j, b in enumerate(rest_b):
                    s = scores.get((a_nid, str(b["nid"])))
                    base = _BIG if s is None else 1.0 - s["score"]
                    # 동점 처리 — 입력이 (canon_key_a asc, canon_key_b asc) 로 정렬돼 있으므로 지수가 곧 그 순서다.
                    # 제곱은 i·j 에 대해 분리되지 않아 같은 행·열 집합을 쓰는 두 배정의 합을 실제로 가른다
                    # (선형 섭동은 모든 완전배정에서 합이 같아 동점을 하나도 못 깬다 — 솔버를 바꾸면 ir_hash 가
                    # 바뀐다). 어느 배정이 이기는지는 이 식이 고정하며, 보장하는 것은 '입력이 같으면 결과가 같다' 다.
                    matrix[i][j] = base + 1e-9 * ((i * nb + j) ** 2) / (eps_den * eps_den)
                for j in range(nb, size):
                    matrix[i][j] = DUMMY_COST
            for i in range(na, size):
                for j in range(nb):
                    matrix[i][j] = DUMMY_COST
                for j in range(nb, size):
                    matrix[i][j] = 0.0
            assignment = _hungarian(matrix)
            for i, a in enumerate(rest_a):
                j = assignment[i] if i < len(assignment) else -1
                if j < 0 or j >= nb:
                    continue
                a_nid, b_nid = str(a["nid"]), str(rest_b[j]["nid"])
                s = scores.get((a_nid, b_nid))
                if s is None or s["score"] < PENDING_SCORE:
                    continue
                row = sorted(
                    ((k[1], v["score"]) for k, v in scores.items() if k[0] == a_nid),
                    key=lambda t: (-t[1], t[0]),
                )
                rank = next((idx + 1 for idx, (nid, _sc) in enumerate(row) if nid == b_nid), None)
                evidence = dict(s)
                evidence.pop("score", None)
                evidence["rank_in_row"] = rank
                evidence["n_candidates"] = len(row)
                accept(a_nid, b_nid, "fuzzy", s["score"], evidence)

    records.sort(key=lambda r: (r["a"], r["b"], r["method"]))
    return records


# ---------------------------------------------------------------- 클러스터·conflict·dn(§2.6.4·§2.7.5)
def _dn_rank(node: Mapping[str, Any]) -> tuple[int, str]:
    return (_DN_RANK.get((_domain(node), str(node.get("kind") or "")), _DN_FALLBACK), _canon_key(node))


def build_clusters(nodes: Sequence[Mapping[str, Any]], links: Sequence[Mapping[str, Any]]) -> dict:
    """확정 대응의 연결 성분을 만들고 대표 nid(dn)·conflict 를 판정한다.

    성분에 드는 링크는 `status='confirmed'` 이거나 `status='auto' AND score ≥ 0.90` 이다(pending 제외).
    한 성분에 같은 도메인 노드가 2개 이상이면 conflict 이고 ckey=null·dn=자기 nid 다.
    반환 `{clusters, dn, conflicts, warnings}` — warnings 는 §2.9 코드 `sameas_conflict` 행이다.
    """
    by_nid = _by_nid(nodes)
    uf = _UnionFind()
    for nid in sorted(by_nid):
        uf.find(nid)
    for link in links:
        if str(link.get("status")) == "confirmed" or (
            str(link.get("status")) == "auto" and float(link.get("score") or 0.0) >= AUTO_SCORE
        ):
            a, b = str(link.get("a") or ""), str(link.get("b") or "")
            if a in by_nid and b in by_nid:
                uf.union(a, b)

    groups: dict[str, list[str]] = {}
    for nid in sorted(by_nid):
        groups.setdefault(uf.find(nid), []).append(nid)

    clusters: list[dict] = []
    dn_map: dict[str, str] = {}
    conflicts: list[dict] = []
    warnings: list[dict] = []
    for root in sorted(groups):
        members = sorted(groups[root])
        domains = [_domain(by_nid[nid]) for nid in members]
        conflict = any(domains.count(d) > 1 for d in set(domains))
        if conflict:
            for nid in members:
                dn_map[nid] = nid
            conflicts.append({"root": root, "members": members})
            warnings.append({
                "severity": "WARNING",
                "code": "sameas_conflict",
                "message": f"same-as 클러스터에 같은 도메인 노드가 {len(members)}개 들어 있습니다.",
                "ref": ",".join(members),
                "source_kind": None,
            })
        else:
            rep = min(members, key=lambda nid: _dn_rank(by_nid[nid]))
            for nid in members:
                dn_map[nid] = rep
        clusters.append({"root": root, "members": members, "conflict": conflict,
                         "dn": None if conflict else dn_map[members[0]]})
    return {"clusters": clusters, "dn": dn_map, "conflicts": conflicts, "warnings": warnings}


# ---------------------------------------------------------------- 전역 정규 키(§2.7.3·§5.9.1)
def material_norm_of(node: Mapping[str, Any]) -> str:
    """mcad attrs.material · dyna material.db.tag ?? name ?? kfile name · ecad part_number 의 첫 토큰. 없으면 'na'."""
    at = _attrs(node)
    stored = node.get("material_norm")
    if isinstance(stored, str) and stored:
        return stored
    raw: Any = None
    domain = _domain(node)
    if domain == "mcad":
        raw = at.get("material")
    elif domain == "dyna":
        material = at.get("material")
        if isinstance(material, Mapping):
            db = material.get("db")
            if isinstance(db, Mapping):
                raw = db.get("tag") or db.get("name")
            if not raw:
                raw = material.get("name")
    elif domain == "ecad":
        raw = at.get("part_number")
    if not raw:
        return "na"
    token = str(raw).strip().lower().replace("-", "_").replace(" ", "_")
    first = next((t for t in token.split("_") if t), "")
    return first or "na"


def geom_bucket(size_sorted: Sequence[float] | None, volume: float | None) -> str:
    """`'x'.join(round(s/0.5)*0.5) + '@v' + round(log(volume)/log(1.05))`(§2.7.3). volume 이 없으면 `@v?`."""
    sizes = list(size_sorted or [])
    base = "x".join(str(round(float(s) / 0.5) * 0.5) for s in sizes)
    if volume is not None and isinstance(volume, (int, float)) and not isinstance(volume, bool) and volume > 0:
        tail = str(round(math.log(float(volume)) / math.log(1.05)))
    else:
        tail = "?"
    return f"{base}@v{tail}"


def compute_ckey(name_norm_canon: str, size_sorted: Sequence[float] | None,
                 volume: float | None, material_norm: str) -> str:
    """`ck: + sha1(name_norm_canon|geom_bucket|material_norm)[:12]`(§2.7.3). 과제 id·nid·path 는 입력에 없다."""
    payload = f"{name_norm_canon}|{geom_bucket(size_sorted, volume)}|{material_norm}"
    return "ck:" + _sha1_12(payload)


def ckey_of_node(node: Mapping[str, Any]) -> str:
    """클러스터 대표 노드 하나에서 ckey 를 계산한다(§2.7.3 — 입력은 대표 dn 의 attrs)."""
    return compute_ckey(_canon(node), _size_sorted(node), _volume(node), material_norm_of(node))


def resolve_ckey(store, ckey: str, owner_sub: str | None = None) -> str:
    """`merged_into` 체인을 끝까지(최대 5단) 따라가 유효 ckey 를 돌려준다(§2.7.3·§5.9.1)."""
    current = ckey
    for _ in range(MERGE_CHAIN_MAX):
        params: list[Any] = [current]
        sql = "SELECT ckey, status, merged_into FROM rr_part_keys WHERE ckey=?"
        if owner_sub:
            sql += " AND owner_sub=?"
            params.append(owner_sub)
        row = store.query_one(sql, params)
        if row is None or row["status"] != "merged" or not row["merged_into"]:
            return current
        current = str(row["merged_into"])
    return current


def _alias_entry(node: Mapping[str, Any], project_id: str) -> dict:
    return {
        "project_id": project_id,
        "domain": _domain(node),
        "label": node.get("label"),
        "local_key": node.get("local_key"),
        "name_norm": node.get("name_norm"),
    }


def _merge_aliases(existing: Any, entry: Mapping[str, Any]) -> tuple[list, bool]:
    """별칭 목록에 항목 하나를 중복 없이 더한다. (목록, 변경여부)."""
    items = existing if isinstance(existing, list) else []
    key = canonical_json({k: entry.get(k) for k in ("project_id", "domain", "label", "local_key", "name_norm")})
    for item in items:
        if isinstance(item, Mapping):
            if canonical_json({k: item.get(k) for k in ("project_id", "domain", "label", "local_key", "name_norm")}) == key:
                return items, False
    return items + [dict(entry)], True


def assign_ckeys(store, nodes: Sequence[Mapping[str, Any]], links: Sequence[Mapping[str, Any]], *,
                 owner_sub: str, project_id: str, snapshot_id: str) -> dict:
    """클러스터마다 ckey 를 계산해 노드에 부여하고 `rr_part_keys` 원장을 갱신한다(§2.7.3·§5.9.2).

    계산 입력은 클러스터 대표 dn 의 attrs 이고 클러스터의 모든 노드가 같은 ckey 를 받는다.
    conflict 클러스터는 ckey=null 이다. 계산값이 `merged` 면 `merged_into` 를 따라간 유효 ckey 를 준다.
    반환 `{ckeys, dn, clusters, conflicts, warnings}`.
    """
    result = build_clusters(nodes, links)
    by_nid = _by_nid(nodes)
    dn_map = result["dn"]
    ckeys: dict[str, str | None] = {}
    now = now_epoch()

    with store.tx():
        for cluster in result["clusters"]:
            members = cluster["members"]
            if cluster["conflict"]:
                for nid in members:
                    ckeys[nid] = None
                continue
            rep_nid = dn_map[members[0]]
            rep = by_nid[rep_nid]
            computed = ckey_of_node(rep)
            effective = resolve_ckey(store, computed, owner_sub)
            row = store.query_one(
                "SELECT ckey, aliases_json, n_projects, n_snapshots, first_project_id"
                " FROM rr_part_keys WHERE ckey=? AND owner_sub=?",
                (effective, owner_sub),
            )
            entries = [_alias_entry(by_nid[nid], project_id) for nid in members]
            if row is None:
                aliases: list = []
                for entry in entries:
                    aliases, _ = _merge_aliases(aliases, entry)
                store.execute(
                    "INSERT OR IGNORE INTO rr_part_keys"
                    " (ckey, owner_sub, visibility, status, merged_into, display_name,"
                    "  name_norm_canon, geom_bucket, material_norm, aliases_json,"
                    "  first_project_id, first_snapshot_id, first_nid, n_projects, n_snapshots,"
                    "  created_by, created_at, updated_at)"
                    " VALUES (?,?,'private','candidate',NULL,NULL,?,?,?,?,?,?,?,1,1,?,?,?)",
                    (effective, owner_sub, _canon(rep),
                     geom_bucket(_size_sorted(rep), _volume(rep)), material_norm_of(rep),
                     canonical_json(aliases), project_id, snapshot_id, rep_nid, owner_sub, now, now),
                )
            else:
                try:
                    aliases = json.loads(row["aliases_json"]) if row["aliases_json"] else []
                except (TypeError, ValueError):
                    aliases = []
                if not isinstance(aliases, list):
                    aliases = []
                seen_projects = {a.get("project_id") for a in aliases if isinstance(a, Mapping)}
                for entry in entries:
                    aliases, _ = _merge_aliases(aliases, entry)
                n_projects = int(row["n_projects"] or 1) + (0 if project_id in seen_projects else 1)
                store.execute(
                    "UPDATE rr_part_keys SET aliases_json=?, n_projects=?, n_snapshots=?, updated_at=?"
                    " WHERE ckey=? AND owner_sub=?",
                    (canonical_json(aliases), n_projects, int(row["n_snapshots"] or 1) + 1, now,
                     effective, owner_sub),
                )
            for nid in members:
                ckeys[nid] = effective

    for nid in by_nid:
        ckeys.setdefault(nid, None)
        dn_map.setdefault(nid, nid)
    return {"ckeys": ckeys, "dn": dn_map, "clusters": result["clusters"],
            "conflicts": result["conflicts"], "warnings": result["warnings"]}


# ---------------------------------------------------------------- 결정론 대응에 의한 ckey 승계(§2.7.3)
INHERIT_METHODS_ALWAYS = ("ledger", "exact_path", "pid_map")
INHERIT_METHODS_SCORED = ("fingerprint", "name_norm")
INHERIT_SCORE = 0.95


def inherit_ckeys(store, links: Sequence[Mapping[str, Any]],
                  base_nodes: Sequence[Mapping[str, Any]], target_nodes: Sequence[Mapping[str, Any]], *,
                  owner_sub: str, pair_kind: str, base_snapshot_id: str, target_snapshot_id: str) -> list[dict]:
    """pair 대응이 결정론일 때 target 계산 ckey 가 base 유효 ckey 를 승계하게 한다(§2.7.3 자동 병합).

    `pair_kind='same_project_revision'` 이면 `rr_part_keys` 에 merged 행을 `INSERT OR IGNORE` 하고,
    `cross_project` 면 target 계산 ckey 행의 `aliases_json.merged_candidates[]` 에 제안만 적는다.
    이미 `confirmed` 이거나 사람이 만든 `merged` 행은 건드리지 않는다. 반환은 처리 목록이다.
    """
    base_by = _by_nid(base_nodes)
    target_by = _by_nid(target_nodes)
    now = now_epoch()
    applied: list[dict] = []

    with store.tx():
        for link in sorted(links, key=lambda l: (str(l.get("a")), str(l.get("b")))):
            method = str(link.get("method") or "")
            score = float(link.get("score") or 0.0)
            if str(link.get("status")) not in ("confirmed", "auto"):
                continue
            if method not in INHERIT_METHODS_ALWAYS and not (
                method in INHERIT_METHODS_SCORED and score >= INHERIT_SCORE
            ):
                continue
            a_nid, b_nid = str(link.get("a") or ""), str(link.get("b") or "")
            base_node, target_node = base_by.get(a_nid), target_by.get(b_nid)
            if base_node is None or target_node is None:
                continue
            base_ckey = resolve_ckey(store, ckey_of_node(base_node), owner_sub)
            target_ckey = ckey_of_node(target_node)
            if target_ckey == base_ckey:
                continue
            row = store.query_one(
                "SELECT ckey, status, merged_into, decided_by, aliases_json FROM rr_part_keys"
                " WHERE ckey=? AND owner_sub=?", (target_ckey, owner_sub),
            )
            evidence = {"method": method, "score": score,
                        "base_snapshot_id": base_snapshot_id, "target_snapshot_id": target_snapshot_id,
                        "base_nid": a_nid, "target_nid": b_nid}
            if pair_kind == "same_project_revision":
                if row is not None and (row["status"] == "confirmed"
                                        or (row["status"] == "merged" and row["decided_by"] != "code:pair_correspondence")):
                    applied.append({"ckey": target_ckey, "action": "skipped_human_row"})
                    continue
                store.execute(
                    "INSERT OR IGNORE INTO rr_part_keys"
                    " (ckey, owner_sub, visibility, status, merged_into, name_norm_canon, geom_bucket,"
                    "  material_norm, aliases_json, merge_evidence_json, created_by, decided_by, decided_at,"
                    "  created_at, updated_at)"
                    " VALUES (?,?,'private','merged',?,?,?,?,?,?,?,'code:pair_correspondence',?,?,?)",
                    (target_ckey, owner_sub, base_ckey, _canon(target_node),
                     geom_bucket(_size_sorted(target_node), _volume(target_node)),
                     material_norm_of(target_node), canonical_json([]), canonical_json(evidence),
                     owner_sub, now, now, now),
                )
                applied.append({"ckey": target_ckey, "merged_into": base_ckey, "action": "merged", **evidence})
            else:
                if row is None:
                    continue
                try:
                    aliases = json.loads(row["aliases_json"]) if row["aliases_json"] else []
                except (TypeError, ValueError):
                    aliases = []
                container = aliases if isinstance(aliases, dict) else {"items": aliases if isinstance(aliases, list) else []}
                candidates = container.get("merged_candidates") if isinstance(container, dict) else None
                candidates = candidates if isinstance(candidates, list) else []
                proposal = {"ckey_into": base_ckey, "method": method, "score": score}
                if proposal not in candidates:
                    candidates.append(proposal)
                container["merged_candidates"] = candidates
                store.execute(
                    "UPDATE rr_part_keys SET aliases_json=?, updated_at=? WHERE ckey=? AND owner_sub=?",
                    (canonical_json(container), now, target_ckey, owner_sub),
                )
                applied.append({"ckey": target_ckey, "action": "proposed", "ckey_into": base_ckey})
    return applied


# ---------------------------------------------------------------- 계면 별칭 사전(§5.9.3)
def record_iface_aliases(store, nodes: Sequence[Mapping[str, Any]], edges: Sequence[Mapping[str, Any]],
                         ckeys: Mapping[str, str | None], *, owner_sub: str,
                         project_id: str, snapshot_id: str) -> int:
    """계면 엣지마다 무순서 ckey 쌍 `alias_key` 행을 만들고 이름·asm_key 를 누적한다. 삽입·갱신한 행 수를 돌려준다."""
    by_nid = _by_nid(nodes)
    now = now_epoch()
    touched = 0
    with store.tx():
        for edge in sorted(edges, key=lambda e: str(e.get("eid") or "")):
            if str(edge.get("kind") or "") not in ALIAS_EDGE_KINDS:
                continue
            if str(edge.get("status") or "") == "rejected":
                continue
            a_nid, b_nid = str(edge.get("a") or ""), str(edge.get("b") or "")
            ck_a, ck_b = ckeys.get(a_nid), ckeys.get(b_nid)
            if not ck_a or not ck_b:
                continue                        # conflict·미결 클러스터는 별칭을 만들지 않는다.
            ck_a = resolve_ckey(store, ck_a, owner_sub)
            ck_b = resolve_ckey(store, ck_b, owner_sub)
            first, second = sorted((ck_a, ck_b))
            alias_key = f"{first}|{second}"
            node_a, node_b = by_nid.get(a_nid, {}), by_nid.get(b_nid, {})
            entry = {
                "name_a": node_a.get("name_norm"), "name_b": node_b.get("name_norm"),
                "asm_key_a": node_a.get("asm_key"), "asm_key_b": node_b.get("asm_key"),
                "project_id": project_id, "snapshot_id": snapshot_id,
            }
            row = store.query_one(
                "SELECT alias_key, aliases_json FROM rr_iface_alias WHERE alias_key=? AND owner_sub=?",
                (alias_key, owner_sub),
            )
            if row is None:
                store.execute(
                    "INSERT OR IGNORE INTO rr_iface_alias"
                    " (alias_key, canonical_a, canonical_b, owner_sub, visibility, aliases_json,"
                    "  source, score, n_targets, created_at, updated_at)"
                    " VALUES (?,?,?,?,'private',?, 'auto', 1.0, 0, ?, ?)",
                    (alias_key, first, second, owner_sub, canonical_json([entry]), now, now),
                )
                touched += 1
                continue
            try:
                aliases = json.loads(row["aliases_json"]) if row["aliases_json"] else []
            except (TypeError, ValueError):
                aliases = []
            if not isinstance(aliases, list):
                aliases = []
            if entry not in aliases:
                aliases.append(entry)
                store.execute(
                    "UPDATE rr_iface_alias SET aliases_json=?, updated_at=? WHERE alias_key=? AND owner_sub=?",
                    (canonical_json(aliases), now, alias_key, owner_sub),
                )
                touched += 1
    return touched


# ---------------------------------------------------------------- 사람 확정(§2.6.2 7단계 · §2.7.3)
DECISIONS = ("confirm", "reject", "merge_key", "rename_key", "confirm_key", "unmerge_key")


def record_decision(store, payload: Mapping[str, Any], *, owner_sub: str,
                    decided_by: str | None = None) -> dict:
    """`POST /api/sameas/decide` 본문 하나를 원장에 기록한다.

    `confirm|reject` 는 `rr_sameas`(scope·pair_key·stable 키 쌍), `merge_key|rename_key|confirm_key|unmerge_key`
    는 `rr_part_keys` 에 쓴다. 스냅샷은 바뀌지 않고 다음 스냅샷·'재해석 적용' 이 1단계에서 흡수한다.
    """
    decision = str(payload.get("decision") or "")
    if decision not in DECISIONS:
        raise AppError("E100", f"decision 은 {list(DECISIONS)} 중 하나여야 합니다 — {decision!r}.", 400)
    now = now_epoch()
    actor = decided_by or owner_sub

    if decision in ("confirm", "reject"):
        scope = str(payload.get("scope") or "")
        if scope not in ("intra", "pair", "global"):
            raise AppError("E100", f"scope 는 intra|pair|global 여야 합니다 — {scope!r}.", 400)
        a_stable = str(payload.get("a_stable") or payload.get("a") or "")
        b_stable = str(payload.get("b_stable") or payload.get("b") or "")
        if not a_stable or not b_stable:
            raise AppError("E100", "a·b(stable 키)가 필요합니다.", 400)
        a_stable, b_stable = sorted((a_stable, b_stable))
        pair_key = str(payload.get("pair_key") or ("-" if scope == "global" else ""))
        if not pair_key:
            raise AppError("E100", "pair_key 가 필요합니다(intra=project_id, pair=정렬한 두 project_id).", 400)
        status = "confirmed" if decision == "confirm" else "rejected"
        evidence = payload.get("evidence")
        with store.tx():
            store.execute(
                "INSERT INTO rr_sameas (id, owner_sub, scope, pair_key, a_stable, b_stable, method, score,"
                " status, evidence, decided_by, decided_at, snapshot_id_at_decision)"
                " VALUES (?,?,?,?,?,?,'manual',1.0,?,?,?,?,?)"
                " ON CONFLICT(scope, pair_key, a_stable, b_stable) DO UPDATE SET"
                " status=excluded.status, method='manual', score=1.0, evidence=excluded.evidence,"
                " decided_by=excluded.decided_by, decided_at=excluded.decided_at,"
                " snapshot_id_at_decision=excluded.snapshot_id_at_decision",
                (new_uuid(), owner_sub, scope, pair_key, a_stable, b_stable, status,
                 canonical_json(evidence) if evidence is not None else None,
                 actor, now, payload.get("snapshot_id")),
            )
        return {"ok": True, "table": "rr_sameas", "scope": scope,
                "a_stable": a_stable, "b_stable": b_stable, "status": status}

    ckey = str(payload.get("ckey") or payload.get("ckey_from") or "")
    if not ckey:
        raise AppError("E100", "ckey(또는 ckey_from)가 필요합니다.", 400)
    row = store.query_one("SELECT ckey FROM rr_part_keys WHERE ckey=? AND owner_sub=?", (ckey, owner_sub))
    if row is None:
        raise AppError("E404", f"rr_part_keys 에 없는 ckey 입니다 — {ckey}.", 404)

    with store.tx():
        if decision == "merge_key":
            into = str(payload.get("ckey_into") or "")
            if not into:
                raise AppError("E100", "ckey_into 가 필요합니다.", 400)
            if into == ckey:
                raise AppError("E100", "자기 자신으로 병합할 수 없습니다.", 400)
            store.execute(
                "UPDATE rr_part_keys SET status='merged', merged_into=?, merge_evidence_json=NULL,"
                " decided_by=?, decided_at=?, updated_at=? WHERE ckey=? AND owner_sub=?",
                (into, actor, now, now, ckey, owner_sub),
            )
            detail = {"ckey": ckey, "merged_into": into}
        elif decision == "unmerge_key":
            store.execute(
                "UPDATE rr_part_keys SET status='confirmed', merged_into=NULL, merge_evidence_json=NULL,"
                " decided_by=?, decided_at=?, updated_at=? WHERE ckey=? AND owner_sub=?",
                (actor, now, now, ckey, owner_sub),
            )
            detail = {"ckey": ckey, "merged_into": None}
        elif decision == "confirm_key":
            store.execute(
                "UPDATE rr_part_keys SET status='confirmed', decided_by=?, decided_at=?, updated_at=?"
                " WHERE ckey=? AND owner_sub=?", (actor, now, now, ckey, owner_sub),
            )
            detail = {"ckey": ckey, "status": "confirmed"}
        else:                                  # rename_key
            display_name = payload.get("display_name")
            if not display_name:
                raise AppError("E100", "display_name 이 필요합니다.", 400)
            store.execute(
                "UPDATE rr_part_keys SET display_name=?, decided_by=?, decided_at=?, updated_at=?"
                " WHERE ckey=? AND owner_sub=?", (str(display_name), actor, now, now, ckey, owner_sub),
            )
            detail = {"ckey": ckey, "display_name": str(display_name)}
    return {"ok": True, "table": "rr_part_keys", "decision": decision, **detail}


def review_rows(links: Sequence[Mapping[str, Any]], nodes_a: Sequence[Mapping[str, Any]],
                nodes_b: Sequence[Mapping[str, Any]], conflicts: Sequence[Mapping[str, Any]] = ()) -> list[dict]:
    """SameAsResolver 표(§2.6.4) — `pending`·`conflict`·`auto(fuzzy)` 를 사람이 볼 행으로 편다.

    각 행은 stable 키를 함께 실어 `POST /api/sameas/decide` 가 그대로 받게 한다. 판단은 담지 않는다.
    """
    by_nid = {**_by_nid(nodes_a), **_by_nid(nodes_b)}
    conflict_members = {nid for c in conflicts for nid in c.get("members", [])}
    rows: list[dict] = []
    for link in links:
        status = str(link.get("status") or "")
        method = str(link.get("method") or "")
        a, b = str(link.get("a") or ""), str(link.get("b") or "")
        needs = status == "pending" or (status == "auto" and method == "fuzzy") \
            or a in conflict_members or b in conflict_members
        if not needs:
            continue
        node_a, node_b = by_nid.get(a, {}), by_nid.get(b, {})
        rows.append({
            "id": link.get("id"), "scope": link.get("scope"),
            "a": a, "b": b,
            "a_stable": stable_key(node_a) if node_a else None,
            "b_stable": stable_key(node_b) if node_b else None,
            "a_label": node_a.get("label"), "b_label": node_b.get("label"),
            "a_domain": _domain(node_a), "b_domain": _domain(node_b),
            "method": method, "score": link.get("score"), "status": status,
            "conflict": a in conflict_members or b in conflict_members,
            "evidence": link.get("evidence"),
        })
    rows.sort(key=lambda r: (str(r["a"]), str(r["b"])))
    return rows
