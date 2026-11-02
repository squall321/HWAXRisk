# ECAD(ODB 보드) → MCAD(StepForge) 좌표 변환의 계산 — 원점 · 뒤집기 · 면, 등록 검증(손대칭 · 평면 · 외곽 · 구멍 · 뒤집기 모호함) · 제안 · 단면 고르기(입출력 없는 순수 함수)
"""F2 `risk_locate_for_section` 의 계산 몫(설계 docs/f2-locate-for-section.md 2 · 3절).

변환은 `x_CAD = s_x · x_ODB + offset_x`, `y_CAD = s_y · y_ODB + offset_y` 이고 s 는 뒤집으면 −1 이다. 길이는 전부 mm 다(ODB 허브는 mm 로 맞춰
주고 StepForge 는 STEP 머리 단위를 mm 로 바꿔 읽는다 — 머리 단위가 mm 가 아니면 그 값이 25.4배일 수 있어 검증이 거절한다).

ODB 는 top 에서 본 오른손 좌표계(x, y, top 법선)이고 보드는 강체라 거울상이 될 수 없다 — top 법선은 `s_x · s_y · ẑ` 로 간다(`implied_top_face`).
등록부는 면(`top_face`)을 따로 받되 이 손대칭과 어긋나면 검증이 거절한다. 보드 법선은 CAD z 다(검증의 평면 검사가 지킨다).
"""
from __future__ import annotations

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
# CAD 구멍의 축이 z 와 이루는 각 상한(약 5°) — 보드를 꿰뚫는 구멍만 평면 위 한 점으로 줄일 수 있다.
HOLE_AXIS_COS_MIN = math.cos(math.radians(5.0))
# 외곽 자리를 모를 때 자리 근거가 되는 구멍 짝의 수 — 둘이어야 원점과 뒤집기를 함께 가른다(하나는 원점만 정한다).
MIN_HOLE_PAIRS = 2
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
    "outline_mismatch": "ODB 외곽 bbox 를 옮긴 자리가 CAD 보드 몸체 bbox 와 오차 상한보다 어긋난다",
    "holes_mismatch": "짝지은 구멍 가운데 오차 상한보다 먼 것이 있다",
    "holes_mostly_unmatched": "ODB 고정홀 대부분이 CAD 구멍과 짝을 찾지 못했다",
    "position_unverified": "자리 근거가 없다 — ODB 외곽 bbox 를 모르고 짝지은 구멍이 둘 미만이다(원점 · 뒤집기를 확인하지 못했다)",
    "mirror_ambiguous": "다른 뒤집기도 같은 근거를 같은 오차 안에서 설명한다 — 외곽 · 구멍이 대칭이라 뒤집기 · 면을 가르지 못한다",
    "cad_unit_suspect": "StepForge 과제에 mm 가 아닌 머리 단위로 선언된 파일이 있다 — CAD 값이 그 배수만큼 클 수 있다",
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


def pair_holes(t: Transform, odb_holes: Sequence[tuple[float, float, float]],
               cad_holes: Sequence[tuple[float, float, float]]) -> tuple[list[dict], list[int], list[int]]:
    """ODB 구멍을 옮겨 CAD 구멍과 짝짓는다 — 지름 차가 `HOLE_DIAMETER_TOL_MM` 안이고 `HOLE_PAIR_RADIUS_MM` 안인 쌍을 가까운 것부터 겹치지
    않게. 반환 (짝[{odb, cad, odb_mapped, distance_mm}], 짝 없는 ODB 번호, 짝 없는 CAD 번호)."""
    mapped = [t.apply(x, y) for x, y, _d in odb_holes]
    options = []
    for i, ((ox, oy), (_x, _y, od)) in enumerate(zip(mapped, odb_holes)):
        for j, (cx, cy, cd) in enumerate(cad_holes):
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


def _position(t: Transform, odb: Mapping[str, Any], cad: Mapping[str, Any]) -> dict:
    """원점 · 뒤집기의 근거(외곽 자리 · 구멍 짝)만 잰다 — 크기 · 손대칭과 무관한 몫."""
    outline = _outline_error(t, odb.get("outline_bbox"), cad["bbox"])
    pairs, lone_odb, lone_cad = pair_holes(t, _holes(odb.get("holes")), _holes(cad.get("holes")))
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


def best_offset(mirror_x: bool, mirror_y: bool, odb: Mapping[str, Any], cad: Mapping[str, Any]) -> Transform | None:
    """그 뒤집기에서 근거를 가장 잘 설명하는 원점 — 후보는 외곽 bbox 가운데 맞춤과 지름이 맞는 구멍 짝마다의 원점이다. 짝 수가 많고, 외곽
    오차 · 구멍 오차가 작은 것을 고른 뒤 짝의 평균으로 다듬는다. 근거가 하나도 없으면 None."""
    sx, sy = (-1 if mirror_x else 1), (-1 if mirror_y else 1)
    face = implied_top_face(mirror_x, mirror_y)
    odb_holes, cad_holes = _holes(odb.get("holes")), _holes(cad.get("holes"))
    candidates: list[tuple[float, float]] = []
    outline = odb.get("outline_bbox")
    if outline is not None:
        ox0, oy0, ox1, oy1 = (float(v) for v in outline)
        cx0, cy0, _z0, cx1, cy1, _z1 = (float(v) for v in cad["bbox"])
        candidates.append(((cx0 + cx1) / 2 - sx * (ox0 + ox1) / 2, (cy0 + cy1) / 2 - sy * (oy0 + oy1) / 2))
    for ox, oy, od in odb_holes:
        for cx, cy, cd in cad_holes:
            if abs(od - cd) <= HOLE_DIAMETER_TOL_MM:
                candidates.append((cx - sx * ox, cy - sy * oy))
    if not candidates:
        return None
    seen: set[tuple[float, float]] = set()
    best: tuple[tuple, Transform] | None = None
    for tx, ty in candidates:
        key = (round(tx, 6), round(ty, 6))
        if key in seen:
            continue
        seen.add(key)
        t = Transform(bool(mirror_x), bool(mirror_y), tx, ty, face)
        pos = _position(t, odb, cad)
        if pos["pairs"]:
            # 짝 평균으로 다듬는다(평행이동만의 최소 제곱) — 같은 짝 수에서 오차가 줄어든다.
            mx = sum(p["cad"]["x"] - sx * p["odb"]["x"] for p in pos["pairs"]) / len(pos["pairs"])
            my = sum(p["cad"]["y"] - sy * p["odb"]["y"] for p in pos["pairs"]) / len(pos["pairs"])
            refined = Transform(bool(mirror_x), bool(mirror_y), mx, my, face)
            again = _position(refined, odb, cad)
            if again["matched"] >= pos["matched"]:
                t, pos = refined, again
        score = (-pos["matched"], pos["outline"]["error_mm"] if pos["outline"] else 0.0,
                 pos["hole_error_mm"] if pos["hole_error_mm"] is not None else 0.0, key)
        if best is None or score < best[0]:
            best = (score, t)
    assert best is not None
    t = best[1]
    return Transform(t.mirror_x, t.mirror_y, _r(t.offset_x), _r(t.offset_y), t.top_face)


def verify(t: Transform, odb: Mapping[str, Any], cad: Mapping[str, Any], *, max_error: float = MAX_ERROR_MM,
           alternatives: bool = True) -> dict:
    """등록 검증 — `{ok, error_mm, max_error_mm, reasons[], reason_text[], checks{…}}`.

    `odb` = {size: (x_mm, y_mm) | None, outline_bbox: [x0, y0, x1, y1] | None, thickness_mm, holes: [(x, y, d)]},
    `cad` = {bbox: [x0, y0, z0, x1, y1, z1] | None, holes: [(x, y, d)] — z 축 구멍만, unit_suspect: bool}.
    거절 까닭이 하나도 없을 때만 ok 다. 오차는 외곽 크기 · 외곽 자리 · 구멍 짝 가운데 큰 것(잰 것만)이다."""
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
    checks["thickness"] = {"odb_mm": None if thickness is None else _r(thickness), "cad_mm": _r(ext[2]),
                           "diff_mm": None if thickness is None else _r(float(thickness) - ext[2]),
                           "note": "알려 주기만 한다 — ODB 안의 두께는 자주 틀린다(허브 문서)"}
    pos = _position(t, odb, cad)
    outline = pos["outline"]
    checks["outline"] = ({"measured": False, "note": "ODB 외곽 bbox(OH-04)가 없어 외곽 자리를 재지 못했다"} if outline is None
                         else {"measured": True, **outline, "ok": outline["error_mm"] <= max_error})
    if outline is not None:
        errors.append(outline["error_mm"])
        if outline["error_mm"] > max_error:
            reasons.append("outline_mismatch")
    odb_holes = _holes(odb.get("holes"))
    checks["holes"] = {"odb": len(odb_holes), "cad": len(_holes(cad.get("holes"))), "matched": pos["matched"],
                       "pairs": pos["pairs"], "error_mm": pos["hole_error_mm"],
                       "rms_mm": (_r(math.sqrt(sum(p["distance_mm"] ** 2 for p in pos["pairs"]) / len(pos["pairs"])))
                                  if pos["pairs"] else None),
                       "unmatched_odb": [{"x": _r(odb_holes[i][0]), "y": _r(odb_holes[i][1]), "d": _r(odb_holes[i][2])}
                                         for i in pos["lone_odb"]],
                       "unmatched_cad": len(pos["lone_cad"])}
    if pos["hole_error_mm"] is not None:
        errors.append(pos["hole_error_mm"])
        if pos["hole_error_mm"] > max_error:
            reasons.append("holes_mismatch")
    if odb_holes and len(pos["lone_odb"]) > pos["matched"]:
        reasons.append("holes_mostly_unmatched")
    if outline is None and pos["matched"] < MIN_HOLE_PAIRS:
        reasons.append("position_unverified")
    if alternatives:
        rivals = []
        for mx, my in ((not t.mirror_x, t.mirror_y), (t.mirror_x, not t.mirror_y), (not t.mirror_x, not t.mirror_y)):
            other = best_offset(mx, my, odb, cad)
            if other is None:
                continue
            opos = _position(other, odb, cad)
            competes = _position_ok(opos, max_error) and opos["matched"] >= pos["matched"]
            rivals.append({**other.as_dict(), "matched": opos["matched"], "hole_error_mm": opos["hole_error_mm"],
                           "outline_error_mm": opos["outline"]["error_mm"] if opos["outline"] else None,
                           "competes": competes})
        ambiguous = any(r["competes"] for r in rivals)
        checks["ambiguity"] = {"ok": not ambiguous, "alternatives": rivals}
        if ambiguous:
            reasons.append("mirror_ambiguous")
    checks["units"] = {"cad_unit_suspect": bool(cad.get("unit_suspect")), "unit": UNIT}
    if cad.get("unit_suspect"):
        reasons.append("cad_unit_suspect")
    return _verdict(reasons, checks, errors, max_error)


def _verdict(reasons: list[str], checks: dict, errors: list[float], max_error: float) -> dict:
    return {"ok": not reasons, "error_mm": _r(max(errors)) if errors else None, "max_error_mm": max_error,
            "reasons": reasons, "reason_text": [REASONS[r] for r in reasons], "checks": checks}


def propose(odb: Mapping[str, Any], cad: Mapping[str, Any], *, max_error: float = MAX_ERROR_MM) -> list[dict]:
    """뒤집기 넷마다 가장 잘 맞는 원점(면은 손대칭으로)과 그 검증 — 검증을 지난 것 → 짝 수 → 오차 차례. 근거가 없으면 빈 목록."""
    out = []
    if cad.get("bbox") is None:
        return out
    for mx in (False, True):
        for my in (False, True):
            t = best_offset(mx, my, odb, cad)
            if t is None:
                continue
            check = verify(t, odb, cad, max_error=max_error)
            out.append({"transform": t.as_dict(), "formula": t.formula(), "verification": check})
    out.sort(key=lambda c: (not c["verification"]["ok"], -c["verification"]["checks"]["holes"]["matched"],
                            c["verification"]["error_mm"] if c["verification"]["error_mm"] is not None else math.inf,
                            c["transform"]["mirror_x"], c["transform"]["mirror_y"]))
    return out


# ---------------------------------------------------------------- 단면 고르기
def section_planes(point: Mapping[str, float], extents: Mapping[str, float]) -> tuple[list[dict], dict]:
    """자리를 지나는 세로 단면 둘 — (planes[긴 축 평면, 짧은 축 평면], plane_basis).

    `extents` 는 대상의 축별 길이 {x, y, z}(모르는 축은 빼도 된다 — 없는 축은 0). 가장 얇은 축(두께)을 두 평면이 다 품는다. 나머지 둘 가운데
    긴 축을 품는 평면(법선 = 짧은 축)이 앞, 긴 축에 수직인 평면(법선 = 긴 축)이 뒤다. 평면은 F1 이 받는 꼴 그대로 {axis, offset, unit} 이고
    axis 는 평면의 법선 축이다(StepForge section_view 와 같은 뜻)."""
    ext = {a: float(extents.get(a) or 0.0) for a in "xyz"}
    thin = "z" if "z" not in extents else min("xyz", key=lambda a: (ext[a], "zyx".index(a)))
    rest = [a for a in "xyz" if a != thin]
    long_axis = max(rest, key=lambda a: (ext[a], -"xyz".index(a)))
    short_axis = next(a for a in rest if a != long_axis)
    planes = [{"axis": short_axis, "offset": _r(point[short_axis]), "unit": UNIT},
              {"axis": long_axis, "offset": _r(point[long_axis]), "unit": UNIT}]
    basis = {"long_axis": long_axis, "short_axis": short_axis, "thickness_axis": thin,
             "order": ["long", "short"],
             "note": (f"앞 평면은 긴 축({long_axis})을 품는 단면(법선 {short_axis}), 뒤 평면은 짧은 축({short_axis})을 품는 단면(법선 {long_axis}) — "
                      f"둘 다 두께 축({thin})을 품는다")}
    return planes, basis


def window_for(long_extent: float | None) -> float:
    """F1 window_mm 의 제안 — 대상 긴 변의 세 배를 10 ~ 100 mm 로 죈다(모르면 10)."""
    if long_extent is None or not math.isfinite(long_extent) or long_extent <= 0:
        return WINDOW_MIN_MM
    return _r(min(WINDOW_MAX_MM, max(WINDOW_MIN_MM, WINDOW_FACTOR * long_extent)))
