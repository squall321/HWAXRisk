# ECAD(ODB 보드) → MCAD(StepForge) 좌표 변환의 계산 — 원점 · 뒤집기 · 면, 등록 검증(손대칭 · 평면 · 외곽 · 구멍 · 뒤집기 모호함) · 제안 · 단면 고르기(입출력 없는 순수 함수)
"""F2 `risk_locate_for_section` 의 계산 몫(설계 docs/f2-locate-for-section.md 2 · 3절).

변환은 `x_CAD = s_x · x_ODB + offset_x`, `y_CAD = s_y · y_ODB + offset_y` 이고 s 는 뒤집으면 −1 이다. 길이는 전부 mm 다(ODB 허브는 mm 로 맞춰
주고 StepForge 는 STEP 머리 단위를 mm 로 바꿔 읽는다 — 머리 단위가 mm 가 아니면 그 값이 25.4배일 수 있어 검증이 거절한다).

ODB 는 top 에서 본 오른손 좌표계(x, y, top 법선)이고 보드는 강체라 거울상이 될 수 없다 — top 법선은 `s_x · s_y · ẑ` 로 간다(`implied_top_face`).
등록부는 면(`top_face`)을 따로 받되 이 손대칭과 어긋나면 검증이 거절한다. 보드 법선은 CAD z 다(검증의 평면 검사가 지킨다).
"""
from __future__ import annotations

import bisect
import math
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

UNIT = "mm"
# 등록 검증의 오차 상한(mm) — 외곽 크기 · 외곽 자리 · 구멍 짝 거리 가운데 큰 것. 뒤집기 · 면을 잘못 적으면 보드 크기만큼(수십 mm) 어긋나고
# 같은 보드의 ECAD 와 MCAD 는 0.01 mm 대로 맞으므로, 모델링 차를 넉넉히 받으면서 부호 실수는 잡는 값이다.
MAX_ERROR_MM = 0.5
# 구멍 짝짓기 — 지름 차 상한(ODB 는 마감 지름, CAD 는 모델의 지름이라 도금만큼 다를 수 있다)과 짝을 찾는 반경(오차 상한보다 넉넉히 — 상한을
# 넘는 짝도 짝으로 세워 '오차가 크다' 고 말한다. 반경 밖은 짝이 없는 구멍이다).
HOLE_DIAMETER_TOL_MM = 0.3
HOLE_PAIR_RADIUS_MM = 2.0
# 보드 두께 — CAD 보드 몸체의 z 변과 ODB 두께의 차 상한은 이 둘 가운데 큰 것이다(0.3 mm · ODB 두께의 절반). ODB 안의 두께는 자주 틀려(허브
# 문서) 넉넉히 두되, 보드가 아닌 몸체(아래 면 부품 · 하우징과 합쳐진 몸체 — 두께가 몇 배다)를 고르면 부품 면의 z 가 그 몸체 면으로 가므로
# 거절한다(반대 검토 F2-9 — 종전에는 알려 주기만 해서 2.35 mm 몸체가 0.65 mm 보드로 verified 였다).
THICKNESS_TOL_MM = 0.3
THICKNESS_TOL_RATIO = 0.5
# CAD 구멍의 축이 z 와 이루는 각 상한(약 5°) — 보드를 꿰뚫는 구멍만 평면 위 한 점으로 줄일 수 있다.
HOLE_AXIS_COS_MIN = math.cos(math.radians(5.0))
# 외곽 자리를 모를 때 자리 근거가 되는 구멍 짝의 수 — 둘이어야 원점과 뒤집기를 함께 가른다(하나는 원점만 정한다).
MIN_HOLE_PAIRS = 2
# 일의 상한(반대 검토 F2-9) — 원점 찾기는 지름이 맞는 (ODB, CAD) 구멍 짝마다 한 번 표를 던지고(구멍 수의 곱), 짝짓기는 짝 반경 칸 색인으로
# 이웃만 본다. 한쪽 구멍이 이보다 많으면 찾지 않고 거절한다(holes_too_many — 강제 사유와 적을 수는 있다). 읽기 상한(ODB 고정홀 5쪽 × 100 ·
# StepForge corner_proximity 500줄)과 같은 값이라 산 근거로는 넘지 않는다 — 순수 함수를 직접 부르는 쪽의 울타리다.
HOLES_MAX = 500
# 원점 투표 칸(mm) — 오차 상한과 같다. 한 원점에 맞는 짝의 원점은 그 원점에서 상한 안이라 그 칸과 이웃 칸(3 × 3) 안에 든다.
VOTE_CELL_MM = MAX_ERROR_MM
# 한 뒤집기에서 정밀하게 재는 원점 후보(이웃을 접은 칸)의 상한 — 표가 많은 칸부터. 남은 칸에 아직 견줄 만큼 표가 있으면 다 재지 못한
# 것이라 모호함을 확인하지 못했다고 말한다(holes_too_many).
VOTE_EVAL_MAX = 64
FACES: tuple[str, ...] = ("zmax", "zmin")
SIDES: tuple[str, ...] = ("top", "bottom")
FACE_WORDS = {"zmax": "위 면", "zmin": "아래 면"}
# 단면 창(F1 window_mm)의 제안 — 대상 긴 변의 세 배, 이 범위로 죈다.
WINDOW_MIN_MM, WINDOW_MAX_MM, WINDOW_FACTOR = 10.0, 100.0, 3.0
# 소수 자리 — 0.1 µm. 82.13 − 30 이 52.129999… 로 나오는 부동소수 찌꺼기를 지운다.
DIGITS = 4

# 거절 까닭(검증의 reasons) — 화면 · 감사가 그대로 싣는다.
REASONS: dict[str, str] = {
    "handedness_mismatch": "뒤집기와 면이 손대칭에 어긋난다 — 한 축만 뒤집으면 ODB top 은 CAD 아래 면(zmin), 안 뒤집거나 둘 다 뒤집으면 위 면(zmax)이다",
    "board_plane_not_xy": "CAD 보드 몸체의 가장 얇은 변이 z 가 아니다 — 보드 법선이 CAD z 인 배치만 이 변환으로 적는다",
    "cad_board_unread": "CAD 보드 몸체의 bbox 를 읽지 못했다",
    "odb_size_unread": "ODB 보드 외곽 크기(get_volume_result.board.x_mm · y_mm)를 읽지 못했다",
    "size_mismatch": "ODB 외곽 크기와 CAD 보드 몸체 크기가 오차 상한보다 다르다 — 엉뚱한 몸체 · 단위(인치 머리) · 90° 회전을 의심한다",
    "thickness_mismatch": ("CAD 보드 몸체 두께가 ODB 보드 두께와 상한(0.3 mm 와 ODB 두께의 절반 가운데 큰 것)보다 다르다 — 보드가 아닌 몸체(부품 ·"
                           " 하우징과 합쳐진 몸체)를 골랐거나 단위가 다르다 — 부품 면의 z 가 그 몸체의 면으로 간다"),
    "outline_mismatch": "ODB 외곽 bbox 를 옮긴 자리가 CAD 보드 몸체 bbox 와 오차 상한보다 어긋난다",
    "holes_mismatch": "짝지은 구멍 가운데 오차 상한보다 먼 것이 있다",
    "holes_mostly_unmatched": "ODB 고정홀의 절반 이상이 CAD 구멍과 짝을 찾지 못했다",
    "position_unverified": "자리 근거가 없다 — ODB 외곽 bbox 를 모르고 짝지은 구멍이 둘 미만이다(원점 · 뒤집기를 확인하지 못했다)",
    "mirror_ambiguous": "다른 뒤집기도 같은 근거를 같은 오차 안에서 설명한다 — 외곽 · 구멍이 대칭이라 뒤집기 · 면을 가르지 못한다",
    "origin_ambiguous": ("같은 뒤집기의 다른 원점(상한의 두 배 넘게 떨어진)이 근거를 같은 수 이상 상한 안에서 설명한다 — 적은 원점을 확인하지"
                         " 못했다(더 많이 맞추면 적은 원점이 틀렸다 — 제안을 본다)"),
    "cad_unit_suspect": "StepForge 과제에 mm 가 아닌 머리 단위로 선언된 파일이 있다 — CAD 값이 그 배수만큼 클 수 있다",
    "holes_too_many": (f"구멍이 너무 많아(한쪽 {HOLES_MAX}개 넘게, 또는 견줄 원점 후보가 {VOTE_EVAL_MAX}칸 넘게) 다른 원점 · 뒤집기를 다 재지"
                       " 못했다 — 모호하지 않은지 확인하지 못했다"),
}


def _r(value: float) -> float:
    return round(float(value), DIGITS) + 0.0          # -0.0 을 0.0 으로


def implied_top_face(mirror_x: bool, mirror_y: bool) -> str:
    """손대칭이 정하는 ODB top 면의 CAD 면 — 한 축만 뒤집으면 zmin, 아니면 zmax."""
    return "zmin" if bool(mirror_x) != bool(mirror_y) else "zmax"


def face_of(side: str, top_face: str) -> str:
    """그 면(top · bottom)의 부품이 닿는 CAD 보드 몸체의 면 — top 은 top_face, bottom 은 그 반대."""
    if side not in SIDES or top_face not in FACES:
        raise ValueError(f"side={side!r} · top_face={top_face!r}")
    if side == "top":
        return top_face
    return "zmin" if top_face == "zmax" else "zmax"


def face_z(face: str, z_min: float, z_max: float) -> float:
    return float(z_max if face == "zmax" else z_min)


def outward(face: str) -> int:
    """그 면에서 보드 밖으로 향하는 z 부호 — 부품은 이쪽에 있다."""
    return 1 if face == "zmax" else -1


@dataclass(frozen=True)
class Transform:
    """등록부 한 행의 변환 — 길이는 mm."""

    mirror_x: bool
    mirror_y: bool
    offset_x: float
    offset_y: float
    top_face: str

    @property
    def sx(self) -> int:
        return -1 if self.mirror_x else 1

    @property
    def sy(self) -> int:
        return -1 if self.mirror_y else 1

    def apply(self, x: float, y: float) -> tuple[float, float]:
        return _r(self.sx * float(x) + self.offset_x), _r(self.sy * float(y) + self.offset_y)

    def formula(self) -> str:
        """사람이 읽는 식 — 손 셈과 같은 꼴(`x_CAD = 82.13 − x_ODB` · `y_CAD = y_ODB + 2.82` · 면)."""
        def one(axis: str, s: int, offset: float) -> str:
            o = _r(offset)
            if s < 0:
                return f"{axis}_CAD = {o:g} − {axis}_ODB"
            if o == 0:
                return f"{axis}_CAD = {axis}_ODB"
            return f"{axis}_CAD = {axis}_ODB {'+' if o > 0 else '−'} {abs(o):g}"
        face = FACE_WORDS.get(self.top_face, self.top_face)
        return (f"{one('x', self.sx, self.offset_x)} · {one('y', self.sy, self.offset_y)} · ODB top → CAD {face}({self.top_face})"
                f" · 단위 {UNIT}")

    def as_dict(self) -> dict:
        return {"mirror_x": bool(self.mirror_x), "mirror_y": bool(self.mirror_y), "offset_x": _r(self.offset_x),
                "offset_y": _r(self.offset_y), "top_face": self.top_face, "unit": UNIT}


# ---------------------------------------------------------------- 근거의 꼴
def _holes(raw: Iterable[Any]) -> list[tuple[float, float, float]]:
    """(x, y, 지름) 목록 — 부르는 쪽이 이미 걸러 준 것을 수로만 다듬는다."""
    out = []
    for h in raw or ():
        x, y, d = (float(v) for v in h)
        out.append((x, y, d))
    return out


def board_extents(bbox: Sequence[float]) -> tuple[float, float, float]:
    x0, y0, z0, x1, y1, z1 = (float(v) for v in bbox)
    return x1 - x0, y1 - y0, z1 - z0


def _cell(x: float, y: float, size: float) -> tuple[int, int]:
    return math.floor(x / size), math.floor(y / size)


_NEIGHBOURS: tuple[tuple[int, int], ...] = tuple((dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1))


class _Evidence:
    """한 근거의 구멍 — 수로 다듬은 두 목록과 CAD 구멍의 색인 둘(짝 반경 칸 · 지름 차례). 검증 · 제안이 같은 근거를 여러 번 재도 한 번만
    짓는다."""

    def __init__(self, odb: Mapping[str, Any], cad: Mapping[str, Any]) -> None:
        self.odb_holes = _holes(odb.get("holes"))
        self.cad_holes = _holes(cad.get("holes"))
        self.cells: dict[tuple[int, int], list[int]] = {}
        for j, (x, y, _d) in enumerate(self.cad_holes):
            self.cells.setdefault(_cell(x, y, HOLE_PAIR_RADIUS_MM), []).append(j)
        self.by_diameter = sorted((d, j) for j, (_x, _y, d) in enumerate(self.cad_holes))
        self.diameters = [d for d, _j in self.by_diameter]

    def near(self, x: float, y: float) -> Iterable[int]:
        """(x, y) 에서 짝 반경 안일 수 있는 CAD 구멍 번호 — 칸 크기가 반경이라 이웃 아홉 칸이면 다 든다."""
        cx, cy = _cell(x, y, HOLE_PAIR_RADIUS_MM)
        for dx, dy in _NEIGHBOURS:
            yield from self.cells.get((cx + dx, cy + dy), ())

    def same_diameter(self, diameter: float) -> Iterable[int]:
        """지름 차가 상한 안인 CAD 구멍 번호(차례로 찾은 범위를 같은 비교로 다시 거른다 — 부동소수 경계까지 짝짓기와 같다)."""
        lo = bisect.bisect_left(self.diameters, diameter - HOLE_DIAMETER_TOL_MM - 1e-9)
        hi = bisect.bisect_right(self.diameters, diameter + HOLE_DIAMETER_TOL_MM + 1e-9)
        for cd, j in self.by_diameter[lo:hi]:
            if abs(diameter - cd) <= HOLE_DIAMETER_TOL_MM:
                yield j


def pair_holes(t: Transform, odb_holes: Sequence[tuple[float, float, float]],
               cad_holes: Sequence[tuple[float, float, float]],
               evidence: _Evidence | None = None) -> tuple[list[dict], list[int], list[int]]:
    """ODB 구멍을 옮겨 CAD 구멍과 짝짓는다 — 지름 차가 `HOLE_DIAMETER_TOL_MM` 안이고 `HOLE_PAIR_RADIUS_MM` 안인 쌍을 가까운 것부터 겹치지
    않게. 반환 (짝[{odb, cad, odb_mapped, distance_mm}], 짝 없는 ODB 번호, 짝 없는 CAD 번호). CAD 구멍은 짝 반경 칸 색인으로 이웃만 본다
    (같은 짝 후보 · 같은 차례 — 구멍 수의 곱이 아니라 합에 비례한다)."""
    if evidence is None:
        evidence = _Evidence({"holes": odb_holes}, {"holes": cad_holes})
    mapped = [t.apply(x, y) for x, y, _d in odb_holes]
    options = []
    for i, ((ox, oy), (_x, _y, od)) in enumerate(zip(mapped, odb_holes)):
        for j in evidence.near(ox, oy):
            cx, cy, cd = cad_holes[j]
            if abs(od - cd) > HOLE_DIAMETER_TOL_MM:
                continue
            dist = math.hypot(cx - ox, cy - oy)
            if dist <= HOLE_PAIR_RADIUS_MM:
                options.append((dist, i, j))
    options.sort()
    used_i: set[int] = set()
    used_j: set[int] = set()
    pairs = []
    for dist, i, j in options:
        if i in used_i or j in used_j:
            continue
        used_i.add(i)
        used_j.add(j)
        ox, oy, od = odb_holes[i]
        cx, cy, cd = cad_holes[j]
        pairs.append({"odb": {"x": _r(ox), "y": _r(oy), "d": _r(od)}, "cad": {"x": _r(cx), "y": _r(cy), "d": _r(cd)},
                      "odb_mapped": {"x": mapped[i][0], "y": mapped[i][1]}, "distance_mm": _r(dist)})
    pairs.sort(key=lambda p: (p["odb"]["x"], p["odb"]["y"]))
    return (pairs, [i for i in range(len(odb_holes)) if i not in used_i],
            [j for j in range(len(cad_holes)) if j not in used_j])


def _outline_error(t: Transform, outline: Sequence[float] | None, cad_bbox: Sequence[float]) -> dict | None:
    """ODB 외곽 bbox 네 변을 옮긴 자리와 CAD 몸체 bbox 의 차 — 모르면 None."""
    if outline is None:
        return None
    ox0, oy0, ox1, oy1 = (float(v) for v in outline)
    xs = sorted(t.apply(x, oy0)[0] for x in (ox0, ox1))
    ys = sorted(t.apply(ox0, y)[1] for y in (oy0, oy1))
    cx0, cy0, _z0, cx1, cy1, _z1 = (float(v) for v in cad_bbox)
    edges = {"x_min": _r(xs[0] - cx0), "x_max": _r(xs[1] - cx1), "y_min": _r(ys[0] - cy0), "y_max": _r(ys[1] - cy1)}
    return {"mapped": [xs[0], ys[0], xs[1], ys[1]], "edges": edges, "error_mm": _r(max(abs(v) for v in edges.values()))}


def _position(t: Transform, odb: Mapping[str, Any], cad: Mapping[str, Any], evidence: _Evidence | None = None) -> dict:
    """원점 · 뒤집기의 근거(외곽 자리 · 구멍 짝)만 잰다 — 크기 · 손대칭과 무관한 몫."""
    ev = evidence if evidence is not None else _Evidence(odb, cad)
    outline = _outline_error(t, odb.get("outline_bbox"), cad["bbox"])
    pairs, lone_odb, lone_cad = pair_holes(t, ev.odb_holes, ev.cad_holes, ev)
    hole_err = max((p["distance_mm"] for p in pairs), default=None)
    return {"outline": outline, "pairs": pairs, "lone_odb": lone_odb, "lone_cad": lone_cad, "hole_error_mm": hole_err,
            "matched": len(pairs)}


def _position_ok(pos: Mapping[str, Any], max_error: float) -> bool:
    """자리 근거가 있고(외곽 자리 또는 구멍 짝 둘 이상) 그 오차가 상한 안이다."""
    outline = pos["outline"]
    if outline is None and pos["matched"] < MIN_HOLE_PAIRS:
        return False
    if outline is not None and outline["error_mm"] > max_error:
        return False
    return pos["hole_error_mm"] is None or pos["hole_error_mm"] <= max_error


def _votes(sx: int, sy: int, ev: _Evidence) -> dict[tuple[int, int], list]:
    """지름이 맞는 (ODB, CAD) 구멍 짝마다 그 짝을 겹치는 원점에 표를 던진다 — {칸: [ODB 구멍 번호 집합, 원점 x 합, y 합, 짝 수]}."""
    cells: dict[tuple[int, int], list] = {}
    for i, (ox, oy, od) in enumerate(ev.odb_holes):
        for j in ev.same_diameter(od):
            cx, cy, _cd = ev.cad_holes[j]
            tx, ty = cx - sx * ox, cy - sy * oy
            key = _cell(tx, ty, VOTE_CELL_MM)
            slot = cells.get(key)
            if slot is None:
                slot = cells[key] = [set(), 0.0, 0.0, 0]
            slot[0].add(i)
            slot[1] += tx
            slot[2] += ty
            slot[3] += 1
    return cells


def _ranked(cells: Mapping[tuple[int, int], list]) -> list[tuple[int, float, float]]:
    """원점 후보 칸의 차례 — [(표, 그 칸과 이웃 칸 원점의 평균 x, y)], 표가 많은 것부터(같으면 칸 차례).

    표는 이웃 아홉 칸의 서로 다른 ODB 구멍 수를 칸마다 더한 것이다 — 한 구멍이 두 칸에 들면 두 번 세어 위로만 어림한다(정밀한 짝 수는
    `_position` 이 잰다). 한 원점에 맞는 짝은 그 원점의 칸과 이웃 칸 안에 들어 그 칸의 표가 짝 수 이상이다. 뽑은 칸의 이웃은 접는다 — 한
    원점이 칸 경계에 걸쳐 여러 후보가 되지 않게. 상한의 두 배 넘게 떨어진 두 원점의 칸은 서로 이웃이 아니라 접히지 않는다."""
    score: dict[tuple[int, int], int] = {}
    for kx, ky in cells:
        score[(kx, ky)] = sum(len(cells[(kx + dx, ky + dy)][0]) for dx, dy in _NEIGHBOURS if (kx + dx, ky + dy) in cells)
    out: list[tuple[int, float, float]] = []
    folded: set[tuple[int, int]] = set()
    for kx, ky in sorted(score, key=lambda k: (-score[k], k)):
        if (kx, ky) in folded:
            continue
        sum_x = sum_y = 0.0
        count = 0
        for dx, dy in _NEIGHBOURS:
            folded.add((kx + dx, ky + dy))
            slot = cells.get((kx + dx, ky + dy))
            if slot is not None:
                sum_x, sum_y, count = sum_x + slot[1], sum_y + slot[2], count + slot[3]
        out.append((score[(kx, ky)], sum_x / count, sum_y / count))
    return out


class _Search:
    """한 근거에서 뒤집기마다의 원점 후보를 재 둔다 — 투표는 뒤집기마다 한 번이고 검증 · 제안이 그 결과를 함께 쓴다.

    후보는 외곽 bbox 가운데 맞춤(외곽을 알 때)과 투표 칸(표가 많은 것부터 `VOTE_EVAL_MAX` 칸)이다. 후보마다 짝을 재고 짝의 평균으로 다듬어
    (평행이동만의 최소 제곱 — 같은 짝 수에서 오차가 줄어든다) 짝 수가 많고 외곽 오차 · 구멍 오차가 작은 차례로 세운다. 상한 안으로 겹치는
    원점은 하나로 접는다. 종전에는 지름이 맞는 짝마다 짝짓기 전부를 다시 해 ODB² · CAD² 에 비례했다(10 × 100 구멍에 제안 3.3 초)."""

    def __init__(self, odb: Mapping[str, Any], cad: Mapping[str, Any], max_error: float = MAX_ERROR_MM) -> None:
        self.odb, self.cad, self.max_error = odb, cad, max_error
        self.ev = _Evidence(odb, cad)
        self.too_many = len(self.ev.odb_holes) > HOLES_MAX or len(self.ev.cad_holes) > HOLES_MAX
        self._found: dict[tuple[bool, bool], tuple[list[tuple[Transform, dict]], int]] = {}

    def solutions(self, mirror_x: bool, mirror_y: bool) -> tuple[list[tuple[Transform, dict]], int]:
        """그 뒤집기의 원점 후보 [(변환, 근거)] 를 좋은 차례로, 그리고 재지 못하고 남은 칸 가운데 가장 많은 표(남은 칸이 없으면 0)."""
        key = (bool(mirror_x), bool(mirror_y))
        if key not in self._found:
            self._found[key] = self._solve(*key)
        return self._found[key]

    def _solve(self, mirror_x: bool, mirror_y: bool) -> tuple[list[tuple[Transform, dict]], int]:
        sx, sy = (-1 if mirror_x else 1), (-1 if mirror_y else 1)
        face = implied_top_face(mirror_x, mirror_y)
        starts: list[tuple[float, float]] = []
        outline = self.odb.get("outline_bbox")
        if outline is not None and self.cad.get("bbox") is not None:
            ox0, oy0, ox1, oy1 = (float(v) for v in outline)
            cx0, cy0, _z0, cx1, cy1, _z1 = (float(v) for v in self.cad["bbox"])
            starts.append(((cx0 + cx1) / 2 - sx * (ox0 + ox1) / 2, (cy0 + cy1) / 2 - sy * (oy0 + oy1) / 2))
        left = 0
        if not self.too_many:
            ranked = _ranked(_votes(sx, sy, self.ev))
            starts += [(x, y) for _score, x, y in ranked[:VOTE_EVAL_MAX]]
            left = ranked[VOTE_EVAL_MAX][0] if len(ranked) > VOTE_EVAL_MAX else 0
        found: list[tuple[tuple, Transform, dict]] = []
        for tx, ty in starts:
            t = Transform(mirror_x, mirror_y, tx, ty, face)
            pos = _position(t, self.odb, self.cad, self.ev)
            if pos["pairs"]:
                mx = sum(p["cad"]["x"] - sx * p["odb"]["x"] for p in pos["pairs"]) / len(pos["pairs"])
                my = sum(p["cad"]["y"] - sy * p["odb"]["y"] for p in pos["pairs"]) / len(pos["pairs"])
                refined = Transform(mirror_x, mirror_y, mx, my, face)
                again = _position(refined, self.odb, self.cad, self.ev)
                if again["matched"] >= pos["matched"]:
                    t, pos = refined, again
            t = Transform(mirror_x, mirror_y, _r(t.offset_x), _r(t.offset_y), face)
            pos = _position(t, self.odb, self.cad, self.ev)
            score = (-pos["matched"], pos["outline"]["error_mm"] if pos["outline"] else 0.0,
                     pos["hole_error_mm"] if pos["hole_error_mm"] is not None else 0.0, (t.offset_x, t.offset_y))
            found.append((score, t, pos))
        found.sort(key=lambda f: f[0])
        unique: list[tuple[Transform, dict]] = []
        for _score, t, pos in found:
            if not any(math.hypot(t.offset_x - u.offset_x, t.offset_y - u.offset_y) <= self.max_error for u, _p in unique):
                unique.append((t, pos))
        return unique, left


def best_offset(mirror_x: bool, mirror_y: bool, odb: Mapping[str, Any], cad: Mapping[str, Any], *,
                search: _Search | None = None) -> Transform | None:
    """그 뒤집기에서 근거를 가장 잘 설명하는 원점(`_Search`) — 근거가 하나도 없으면(또는 구멍이 상한보다 많고 외곽을 모르면) None."""
    found, _left = (search or _Search(odb, cad)).solutions(mirror_x, mirror_y)
    return found[0][0] if found else None


def verify(t: Transform, odb: Mapping[str, Any], cad: Mapping[str, Any], *, max_error: float = MAX_ERROR_MM,
           alternatives: bool = True, search: _Search | None = None) -> dict:
    """등록 검증 — `{ok, error_mm, max_error_mm, reasons[], reason_text[], checks{…}}`.

    `odb` = {size: (x_mm, y_mm) | None, outline_bbox: [x0, y0, x1, y1] | None, thickness_mm, holes: [(x, y, d)]},
    `cad` = {bbox: [x0, y0, z0, x1, y1, z1] | None, holes: [(x, y, d)] — z 축 구멍만, unit_suspect: bool}.
    거절 까닭이 하나도 없을 때만 ok 다. 오차는 외곽 크기 · 외곽 자리 · 구멍 짝 가운데 큰 것(잰 것만)이다. `search` 는 같은 근거의 원점 찾기를
    나눠 쓸 때(제안)만 준다."""
    reasons: list[str] = []
    checks: dict[str, Any] = {}
    implied = implied_top_face(t.mirror_x, t.mirror_y)
    checks["parity"] = {"ok": t.top_face == implied, "top_face": t.top_face, "implied_top_face": implied}
    if t.top_face != implied:
        reasons.append("handedness_mismatch")
    bbox = cad.get("bbox")
    if bbox is None:
        reasons.append("cad_board_unread")
        return _verdict(reasons, checks, [], max_error)
    ext = board_extents(bbox)
    thin = "xyz"[min(range(3), key=lambda i: ext[i])]
    plane_ok = ext[2] < ext[0] and ext[2] < ext[1]
    checks["plane"] = {"ok": plane_ok, "thin_axis": thin, "cad_extents_mm": [_r(v) for v in ext]}
    if not plane_ok:
        reasons.append("board_plane_not_xy")
    errors: list[float] = []
    size = odb.get("size")
    if size is None:
        checks["size"] = {"ok": None, "odb_mm": None, "cad_mm": [_r(ext[0]), _r(ext[1])], "error_mm": None}
        reasons.append("odb_size_unread")
    else:
        size_err = _r(max(abs(float(size[0]) - ext[0]), abs(float(size[1]) - ext[1])))
        checks["size"] = {"ok": size_err <= max_error, "odb_mm": [_r(size[0]), _r(size[1])],
                          "cad_mm": [_r(ext[0]), _r(ext[1])], "error_mm": size_err}
        errors.append(size_err)
        if size_err > max_error:
            reasons.append("size_mismatch")
    thickness = odb.get("thickness_mm")
    thickness = float(thickness) if thickness is not None and float(thickness) > 0 else None
    if thickness is None or not plane_ok:
        checks["thickness"] = {"ok": None, "odb_mm": None if thickness is None else _r(thickness), "cad_mm": _r(ext[2]),
                               "diff_mm": None if thickness is None else _r(thickness - ext[2]), "tol_mm": None,
                               "note": ("ODB 두께를 몰라 재지 않았다" if thickness is None
                                        else "보드 법선이 z 가 아니라 z 변이 두께가 아니다 — 재지 않았다")}
    else:
        tol = _r(max(THICKNESS_TOL_MM, THICKNESS_TOL_RATIO * thickness))
        diff = _r(thickness - ext[2])
        checks["thickness"] = {"ok": abs(diff) <= tol, "odb_mm": _r(thickness), "cad_mm": _r(ext[2]), "diff_mm": diff, "tol_mm": tol,
                               "note": "ODB 안의 두께는 자주 틀려(허브 문서) 상한을 넉넉히 둔다 — 보드가 아닌 몸체(두께가 몇 배)를 잡는다"}
        if abs(diff) > tol:
            reasons.append("thickness_mismatch")
    if search is None:
        search = _Search(odb, cad, max_error)
    pos = _position(t, odb, cad, search.ev)
    outline = pos["outline"]
    checks["outline"] = ({"measured": False, "note": "ODB 외곽 bbox(OH-04)가 없어 외곽 자리를 재지 못했다"} if outline is None
                         else {"measured": True, **outline, "ok": outline["error_mm"] <= max_error})
    if outline is not None:
        errors.append(outline["error_mm"])
        if outline["error_mm"] > max_error:
            reasons.append("outline_mismatch")
    odb_holes = search.ev.odb_holes
    checks["holes"] = {"odb": len(odb_holes), "cad": len(search.ev.cad_holes), "matched": pos["matched"],
                       "pairs": pos["pairs"], "error_mm": pos["hole_error_mm"],
                       "rms_mm": (_r(math.sqrt(sum(p["distance_mm"] ** 2 for p in pos["pairs"]) / len(pos["pairs"])))
                                  if pos["pairs"] else None),
                       "unmatched_odb": [{"x": _r(odb_holes[i][0]), "y": _r(odb_holes[i][1]), "d": _r(odb_holes[i][2])}
                                         for i in pos["lone_odb"]],
                       "unmatched_cad": len(pos["lone_cad"]),
                       # ODB 고정홀 목록이 잘렸는가(받은 수 < 허브가 말한 수 · 쪽 상한) — 거절하지 않고 알린다(받은 구멍만으로 짝 · 모호함을 잰다).
                       "odb_truncated": bool(odb.get("holes_truncated"))}
    if pos["hole_error_mm"] is not None:
        errors.append(pos["hole_error_mm"])
        if pos["hole_error_mm"] > max_error:
            reasons.append("holes_mismatch")
    # 짝 없는 ODB 고정홀이 절반 이상이면 거절한다 — 종전(절반 넘게)은 절반이 짝 없이 남아도 받아, 고정홀 무리가 평행이동으로 되풀이되는
    # 보드에서 틀린 원점이 절반을 오차 0 으로 맞추고 지났다(반대 검토 F2-9). 모델에 없는 구멍 몇은 그대로 받는다.
    if odb_holes and len(pos["lone_odb"]) >= pos["matched"]:
        reasons.append("holes_mostly_unmatched")
    if outline is None and pos["matched"] < MIN_HOLE_PAIRS:
        reasons.append("position_unverified")
    if alternatives and search.too_many:
        # 다른 뒤집기를 재지 않았다 — 모호하지 않다고 말할 수 없어 거절한다(강제 사유와 적을 수는 있다).
        checks["ambiguity"] = {"ok": None, "alternatives": [], "same_mirror": None,
                               "capped": {"odb_holes": len(odb_holes), "cad_holes": len(search.ev.cad_holes), "holes_max": HOLES_MAX}}
        reasons.append("holes_too_many")
    elif alternatives:
        def rival(found: list[tuple[Transform, dict]]) -> dict | None:
            # 겨루는 후보(상한 안에서 같은 수 이상)가 있으면 그것을 — 짝은 더 많아도 오차 상한 밖인 느슨한 후보가 앞에 서서 겨루는 후보를
            # 가리지 않게 한다. 겨루는 것이 없으면 가장 좋은 후보를 싣는다.
            if not found:
                return None
            other, opos = next(((o, p) for o, p in found if _position_ok(p, max_error) and p["matched"] >= pos["matched"]), found[0])
            return {**other.as_dict(), "matched": opos["matched"], "hole_error_mm": opos["hole_error_mm"],
                    "outline_error_mm": opos["outline"]["error_mm"] if opos["outline"] else None,
                    "competes": _position_ok(opos, max_error) and opos["matched"] >= pos["matched"]}

        rivals = []
        unchecked = []
        same = None
        for mx, my in ((t.mirror_x, t.mirror_y), (not t.mirror_x, t.mirror_y), (t.mirror_x, not t.mirror_y),
                       (not t.mirror_x, not t.mirror_y)):
            found, left = search.solutions(mx, my)
            if left >= max(pos["matched"], 1):
                # 재지 못한 칸에 견줄 만큼 표가 남았다 — 그 칸에 같은 수 이상을 설명하는 원점이 있을 수 있다.
                unchecked.append({"mirror_x": bool(mx), "mirror_y": bool(my), "votes_left": left})
            if (mx, my) == (t.mirror_x, t.mirror_y):
                # 같은 뒤집기의 다른 원점(반대 검토 F2-9) — 상한의 두 배 넘게 떨어진 원점은 적은 원점과 짝 하나도 나누지 못한다(둘 다 상한
                # 안이면 같은 짝의 두 원점 차는 상한의 두 배 안이다). 고정홀 무리가 되풀이되면 틀린 원점이 그 한 무리를 맞춘다.
                same = rival([(o, p) for o, p in found
                              if math.hypot(o.offset_x - t.offset_x, o.offset_y - t.offset_y) > 2 * max_error])
                continue
            other = rival(found)
            if other is not None:
                rivals.append(other)
        ambiguous = any(r["competes"] for r in rivals)
        shifted = bool(same and same["competes"])
        checks["ambiguity"] = {"ok": not ambiguous and not shifted and not unchecked, "alternatives": rivals, "same_mirror": same}
        if unchecked:
            checks["ambiguity"]["capped"] = {"vote_eval_max": VOTE_EVAL_MAX, "unchecked": unchecked}
        if ambiguous:
            reasons.append("mirror_ambiguous")
        if shifted:
            reasons.append("origin_ambiguous")
        if unchecked:
            reasons.append("holes_too_many")
    checks["units"] = {"cad_unit_suspect": bool(cad.get("unit_suspect")), "unit": UNIT}
    if cad.get("unit_suspect"):
        reasons.append("cad_unit_suspect")
    return _verdict(reasons, checks, errors, max_error)


def _verdict(reasons: list[str], checks: dict, errors: list[float], max_error: float) -> dict:
    return {"ok": not reasons, "error_mm": _r(max(errors)) if errors else None, "max_error_mm": max_error,
            "reasons": reasons, "reason_text": [REASONS[r] for r in reasons], "checks": checks}


def propose(odb: Mapping[str, Any], cad: Mapping[str, Any], *, max_error: float = MAX_ERROR_MM) -> list[dict]:
    """뒤집기 넷마다 가장 잘 맞는 원점(면은 손대칭으로)과 그 검증 — 검증을 지난 것 → 짝 수 → 오차 차례. 근거가 없으면 빈 목록. 원점 찾기는
    뒤집기마다 한 번이고 네 검증이 나눠 쓴다(`_Search`)."""
    out = []
    if cad.get("bbox") is None:
        return out
    search = _Search(odb, cad, max_error)
    for mx in (False, True):
        for my in (False, True):
            t = best_offset(mx, my, odb, cad, search=search)
            if t is None:
                continue
            check = verify(t, odb, cad, max_error=max_error, search=search)
            out.append({"transform": t.as_dict(), "formula": t.formula(), "verification": check})
    out.sort(key=lambda c: (not c["verification"]["ok"], -c["verification"]["checks"]["holes"]["matched"],
                            c["verification"]["error_mm"] if c["verification"]["error_mm"] is not None else math.inf,
                            c["transform"]["mirror_x"], c["transform"]["mirror_y"]))
    return out


# ---------------------------------------------------------------- 단면 고르기
def section_planes(point: Mapping[str, float], extents: Mapping[str, float]) -> tuple[list[dict], dict]:
    """자리를 지나는 세로 단면 둘 — (planes[긴 축 평면, 짧은 축 평면], plane_basis).

    두 평면은 늘 보드 법선 z 를 품는 세로 단면이라 법선은 x · y 가운데 하나다(설계 1절 — 반대 검토 F2-9: 종전에는 대상 bbox 의 가장 얇은 변을
    두께로 보아 옆으로 선 FPCB · 브래킷에 z 법선의 가로 단면을 냈다). `extents` 는 대상의 축별 길이 {x, y, z} 이고 z 는 보지 않는다(없는 축은
    0). x · y 가운데 긴 축을 품는 평면(법선 = 짧은 축)이 앞, 긴 축에 수직인 평면(법선 = 긴 축)이 뒤다(같으면 x 가 긴 축). 평면은
    {axis, offset, unit} 이고 axis 는 평면의 법선 축이다(StepForge section_view 와 같은 뜻). F1 section_pair_view 에는 offset 이 아니라 그 점 +
    axis 로 넘긴다(locate.f1_calls — offset 에 창을 더하면 F1 이 거절한다)."""
    ext = {a: float(extents.get(a) or 0.0) for a in "xy"}
    long_axis = max("xy", key=lambda a: (ext[a], -"xy".index(a)))
    short_axis = "y" if long_axis == "x" else "x"
    planes = [{"axis": short_axis, "offset": _r(point[short_axis]), "unit": UNIT},
              {"axis": long_axis, "offset": _r(point[long_axis]), "unit": UNIT}]
    basis = {"long_axis": long_axis, "short_axis": short_axis, "thickness_axis": "z",
             "order": ["long", "short"],
             "note": (f"앞 평면은 긴 축({long_axis})을 품는 단면(법선 {short_axis}), 뒤 평면은 짧은 축({short_axis})을 품는 단면(법선 {long_axis}) — "
                      "둘 다 보드 법선 z 를 품는 세로 단면이다")}
    return planes, basis


def window_for(long_extent: float | None) -> float:
    """F1 window_mm 의 제안 — 대상 긴 변의 세 배를 10 ~ 100 mm 로 죈다(모르면 10)."""
    if long_extent is None or not math.isfinite(long_extent) or long_extent <= 0:
        return WINDOW_MIN_MM
    return _r(min(WINDOW_MAX_MM, max(WINDOW_MIN_MM, WINDOW_FACTOR * long_extent)))
