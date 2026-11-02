# F2 변환 계산 시험 — 손 셈 예(x 뒤집기 · y 원점 · ODB top = CAD 아래 면)를 되짚고, 손대칭 · 평면 · 크기 · 외곽 · 구멍 · 뒤집기 모호함 · 제안 · 단면 고르기를 본다
"""설계 docs/f2-locate-for-section.md 2 · 3절. 순수 함수만 부른다(저장소 · 게이트웨이 없음).

손 셈 예 — 한 메인 보드에서 사람이 셈한 것은 `x_CAD = 82.13 − x_ODB`, `y_CAD = y_ODB + 2.82`, ODB top 면 = CAD 보드 몸체의 아래 면이었다.
아래 보드는 그 변환으로 지은 합성 보드다(외곽 70 × 50 mm, 대칭이 아닌 고정홀 셋, 두께 0.65 mm, CAD 아래 면 z = 0.5).
"""
from __future__ import annotations

import random
import time

import pytest

from app import board_transform as bt

HAND = bt.Transform(mirror_x=True, mirror_y=False, offset_x=82.13, offset_y=2.82, top_face="zmin")
ODB_OUTLINE = [5.0, -48.0, 75.0, 2.0]
ODB_HOLES = [(8.0, -44.0, 1.6), (70.0, -5.0, 1.6), (40.0, -30.0, 2.0)]
CAD_BBOX = [7.13, -45.18, 0.5, 77.13, 4.82, 1.15]
CAD_HOLES = [(74.13, -41.18, 1.6), (12.13, -2.18, 1.6), (42.13, -27.18, 2.0)]


def _odb(*, outline=True, holes=ODB_HOLES, size=(70.0, 50.0)) -> dict:
    return {"size": size, "outline_bbox": ODB_OUTLINE if outline else None, "thickness_mm": 0.65, "holes": list(holes)}


def _cad(*, bbox=CAD_BBOX, holes=CAD_HOLES, unit_suspect=False) -> dict:
    return {"bbox": list(bbox), "holes": list(holes), "unit_suspect": unit_suspect}


def test_the_hand_transform_maps_points_and_reads_like_the_hand_formula():
    """손 셈 그대로 — (30, −20) 은 (52.13, −17.18) 이고 식은 사람이 적은 꼴이다. 한 축만 뒤집으면 ODB top 은 CAD 아래 면이다(손대칭)."""
    assert HAND.apply(30.0, -20.0) == (52.13, -17.18)
    assert HAND.apply(0.0, 0.0) == (82.13, 2.82)
    assert HAND.formula() == "x_CAD = 82.13 − x_ODB · y_CAD = y_ODB + 2.82 · ODB top → CAD 아래 면(zmin) · 단위 mm"
    assert bt.implied_top_face(True, False) == bt.implied_top_face(False, True) == "zmin"
    assert bt.implied_top_face(False, False) == bt.implied_top_face(True, True) == "zmax"
    # top 면 부품은 아래 면(z 0.5)에 앉아 −z 쪽에 있고, bottom 면 부품은 위 면(z 1.15)에 앉아 +z 쪽에 있다.
    assert (bt.face_of("top", "zmin"), bt.face_of("bottom", "zmin")) == ("zmin", "zmax")
    assert (bt.face_z("zmin", 0.5, 1.15), bt.face_z("zmax", 0.5, 1.15)) == (0.5, 1.15)
    assert (bt.outward("zmin"), bt.outward("zmax")) == (-1, 1)
    assert bt.Transform(False, False, -3.5, 0.0, "zmax").formula().startswith("x_CAD = x_ODB − 3.5 · y_CAD = y_ODB ·")


@pytest.mark.parametrize("outline", [True, False], ids=["with-outline", "holes-only"])
def test_the_hand_transform_verifies_on_its_own_board(outline):
    """외곽 bbox(OH-04)가 있든 없든(지금 허브는 없다) 손 셈은 오차 0 으로 지나고 다른 뒤집기는 구멍 셋을 다 설명하지 못한다 — 같은 지름의
    구멍 둘은 가운데에 늘 점대칭이라(180° 돌림이 둘을 맞바꾼다) 셋째 구멍이 가른다."""
    check = bt.verify(HAND, _odb(outline=outline), _cad())
    assert check["ok"], check["reasons"]
    assert check["error_mm"] == 0.0 and check["reasons"] == [] and check["max_error_mm"] == bt.MAX_ERROR_MM
    assert check["checks"]["holes"]["matched"] == 3 and check["checks"]["holes"]["unmatched_odb"] == []
    assert check["checks"]["outline"]["measured"] is outline
    rivals = check["checks"]["ambiguity"]["alternatives"]
    assert len(rivals) == 3 and not any(r["competes"] for r in rivals) and max(r["matched"] for r in rivals) == 2
    assert check["checks"]["thickness"]["diff_mm"] == 0.0


def test_a_face_that_breaks_handedness_is_refused():
    """x 만 뒤집고 위 면(zmax)이라 적으면 거울상 보드다 — 자리는 다 맞아도 거절한다(뒤집기 · 면 가운데 하나만 틀린 부호 실수)."""
    wrong = bt.Transform(True, False, 82.13, 2.82, "zmax")
    check = bt.verify(wrong, _odb(), _cad())
    assert not check["ok"] and check["reasons"] == ["handedness_mismatch"]
    assert check["checks"]["parity"] == {"ok": False, "top_face": "zmax", "implied_top_face": "zmin"}


def test_forgetting_the_mirror_is_refused_by_outline_and_holes():
    """뒤집기를 빠뜨리면(같은 원점) 외곽은 80 mm 어긋나고 구멍은 하나도 짝이 없다."""
    check = bt.verify(bt.Transform(False, False, 82.13, 2.82, "zmax"), _odb(), _cad())
    assert not check["ok"]
    assert {"outline_mismatch", "holes_mostly_unmatched"} <= set(check["reasons"])
    assert check["checks"]["outline"]["error_mm"] == 80.0 and check["checks"]["holes"]["matched"] == 0
    # 외곽 자리를 모르면 자리 근거가 없다는 것이 까닭이다(0 이 '맞다' 로 읽히지 않는다).
    blind = bt.verify(bt.Transform(False, False, 82.13, 2.82, "zmax"), _odb(outline=False), _cad())
    assert {"position_unverified", "holes_mostly_unmatched"} <= set(blind["reasons"]) and blind["error_mm"] == 0.0


def test_a_symmetric_hole_pattern_cannot_tell_the_mirror():
    """고정홀 넷이 가운데에 대칭이면 다른 뒤집기도 넷 다 맞힌다 — 외곽 자리를 모르면 모호해서 거절한다(뒤집기 · 면을 확인하지 못했다)."""
    odb_holes = [(10.0, -40.0, 1.6), (60.0, -40.0, 1.6), (10.0, -5.0, 1.6), (60.0, -5.0, 1.6)]
    cad_holes = [(*HAND.apply(x, y), d) for x, y, d in odb_holes]
    check = bt.verify(HAND, _odb(outline=False, holes=odb_holes), _cad(holes=cad_holes))
    assert check["checks"]["holes"]["matched"] == 4 and check["error_mm"] == 0.0
    assert check["reasons"] == ["mirror_ambiguous"]
    assert sum(r["competes"] for r in check["checks"]["ambiguity"]["alternatives"]) == 3


def test_the_outline_alone_cannot_tell_the_mirror():
    """외곽 bbox 는 늘 점대칭이다 — 구멍 없이 외곽만으로는 뒤집기를 가르지 못한다."""
    check = bt.verify(HAND, _odb(holes=()), _cad(holes=()))
    assert check["checks"]["outline"]["error_mm"] == 0.0 and check["reasons"] == ["mirror_ambiguous"]


def test_one_hole_without_the_outline_is_not_position_evidence():
    check = bt.verify(HAND, _odb(outline=False, holes=ODB_HOLES[:1]), _cad())
    assert "position_unverified" in check["reasons"] and check["checks"]["holes"]["matched"] == 1


def test_an_inch_header_board_fails_the_size_check_and_says_so():
    """머리 단위가 inch 로 잘못 선언된 판은 CAD 값이 25.4배다 — 크기 검사가 거절하고 단위 의심을 함께 말한다."""
    big = [v * 25.4 for v in CAD_BBOX]
    check = bt.verify(HAND, _odb(outline=False), _cad(bbox=big, holes=(), unit_suspect=True))
    assert {"size_mismatch", "cad_unit_suspect"} <= set(check["reasons"]) and check["checks"]["size"]["error_mm"] > 1000


def test_a_board_standing_on_its_side_is_refused():
    """보드 법선이 CAD x 인 배치(가장 얇은 변이 x)는 이 변환으로 적지 않는다."""
    side = [0.5, 7.13, -45.18, 1.15, 77.13, 4.82]
    check = bt.verify(HAND, _odb(outline=False), _cad(bbox=side))
    assert "board_plane_not_xy" in check["reasons"] and check["checks"]["plane"]["thin_axis"] == "x"


def test_an_unread_cad_board_is_refused_before_anything_else():
    check = bt.verify(HAND, _odb(), {"bbox": None, "holes": []})
    assert check["reasons"] == ["cad_board_unread"] and check["error_mm"] is None


def test_the_proposal_finds_the_hand_transform_from_the_holes_alone():
    """지금 허브(외곽 bbox 없음)로도 제안의 첫 후보가 손 셈이다 — 뒤집기 · 원점 · 면(손대칭)과 식까지."""
    candidates = bt.propose(_odb(outline=False), _cad())
    assert len(candidates) == 4
    first = candidates[0]
    assert first["verification"]["ok"] and first["transform"] == HAND.as_dict()
    assert first["formula"] == HAND.formula()
    assert not any(c["verification"]["ok"] for c in candidates[1:])


def test_the_proposal_has_nothing_without_position_evidence():
    assert bt.propose(_odb(outline=False, holes=()), _cad(holes=())) == []
    assert bt.propose(_odb(), {"bbox": None, "holes": []}) == []


def test_the_search_is_not_quadratic_in_both_hole_lists():
    """원점 찾기는 지름이 맞는 짝마다 칸에 표를 던지고 짝짓기는 짝 반경 칸 색인으로 이웃만 본다 — 종전에는 후보(짝)마다 짝짓기 전부를 다시
    해 ODB² · CAD² 에 비례했고 20 × 100 구멍의 제안이 11초였다(반대 검토 F2-9, 보기 구성원도 부를 수 있었다). 손 셈 보드에 같은 지름의 구멍
    17 개를 더하고 CAD 에는 그 짝과 소음 구멍 80 개를 섞어도 첫 후보가 손 셈(짝 20)이고 넉넉한 상한(2초 — 지금은 0.1초 안팎) 안에 끝난다."""
    rng = random.Random(1)
    extra = [(rng.uniform(1, 69), rng.uniform(-49, -1), 1.6) for _ in range(17)]
    odb_holes = ODB_HOLES + extra
    noise = [(rng.uniform(8, 76), rng.uniform(-44, 4), 1.6) for _ in range(80)]
    cad_holes = [(*HAND.apply(x, y), d) for x, y, d in odb_holes] + noise
    started = time.perf_counter()
    candidates = bt.propose(_odb(outline=False, holes=odb_holes), _cad(holes=cad_holes))
    elapsed = time.perf_counter() - started
    assert elapsed < 2.0, elapsed
    first = candidates[0]
    assert first["transform"] == HAND.as_dict() and first["verification"]["ok"], first["verification"]["reasons"]
    assert first["verification"]["checks"]["holes"]["matched"] == 20


def test_too_many_holes_are_refused_with_the_reason_instead_of_a_long_search():
    """한쪽 구멍이 상한(HOLES_MAX — 읽기 상한과 같다)보다 많으면 다른 원점 · 뒤집기를 재지 않고 그 까닭으로 거절한다(모호하지 않다고 말할 수
    없다). 제안은 외곽을 모르면 후보가 없다."""
    many = [(10.0 + 0.1 * i, -40.0, 1.6) for i in range(bt.HOLES_MAX + 1)]
    check = bt.verify(HAND, _odb(outline=False, holes=many), _cad())
    assert "holes_too_many" in check["reasons"] and not check["ok"]
    assert check["checks"]["ambiguity"]["capped"]["odb_holes"] == bt.HOLES_MAX + 1
    assert bt.propose(_odb(outline=False, holes=many), _cad()) == []


def test_section_planes_follow_the_long_side_and_carry_the_unit():
    """긴 축이 x 면 앞 평면은 y 법선(긴 축을 품는다), 뒤 평면은 x 법선이다 — F1 이 받는 꼴 그대로(unit mm)."""
    point = {"x": 52.13, "y": -17.18, "z": 0.5}
    planes, basis = bt.section_planes(point, {"x": 2.4, "y": 1.2})
    assert planes == [{"axis": "y", "offset": -17.18, "unit": "mm"}, {"axis": "x", "offset": 52.13, "unit": "mm"}]
    assert (basis["long_axis"], basis["short_axis"], basis["thickness_axis"]) == ("x", "y", "z")
    tall, _ = bt.section_planes(point, {"x": 1.0, "y": 3.0})
    assert tall == [{"axis": "x", "offset": 52.13, "unit": "mm"}, {"axis": "y", "offset": -17.18, "unit": "mm"}]
    # 세 축을 다 주면 가장 얇은 축이 두께다 — 옆으로 선 브래킷(두께 x)은 y · z 평면이다.
    bracket, basis = bt.section_planes({"x": 1.0, "y": 2.0, "z": 3.0}, {"x": 0.8, "y": 20.0, "z": 6.0})
    assert bracket == [{"axis": "z", "offset": 3.0, "unit": "mm"}, {"axis": "y", "offset": 2.0, "unit": "mm"}]
    assert basis["thickness_axis"] == "x"


def test_the_window_is_three_times_the_long_side_within_bounds():
    assert bt.window_for(2.4) == 10.0 and bt.window_for(8.0) == 24.0 and bt.window_for(400.0) == 100.0
    assert bt.window_for(None) == 10.0 and bt.window_for(0.0) == 10.0
