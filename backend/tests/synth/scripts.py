# 크기별 합성 대본(syn3 · syn40 · syn150) — 크기는 대본의 연산 수다(의미 이벤트 수가 아니다, 반대 검토 P-04)
"""대본은 `(연산, 인자)` 의 목록이고 생성기(`app/devseed.py`)가 그것을 어댑터 결과 쌍으로 만든다.

- syn3 — 부품 12. 두께 감소 · 재질 교체 · 경계 계면 간극 감소. 셋 다 이름에 판단어가 든 부품이다
  (계면 이벤트의 글은 지금 생산자가 부품 이름 대신 nid 로 적는다 — WP1 R-8).
- syn40 — 부품 60. 생산자가 내는 코드 31종 각 1건 + 감소 변형 3 · 부품 키 없는 이벤트 2 · 경계 계면 2 · 단위 섞기 2.
  33종 가운데 `asm.rollup_changed` 는 계면 증감이 끌고 오는 파생이고 `contact.type_changed` 는 지금 생산자가 내지 못해
  (devseed.PRODUCER_GAPS) 따로 시험한다.
- syn150 — 부품 180 · 조립 단위 16. 이동 · 크기 · 간극이 많은 쏠린 분포, 한 조립 단위(MAIN_ASM)에 60건, 변경 1건짜리
  조립 단위 12개, 경계 계면 20, 이벤트가 없는 변화(잡음 · 한쪽 미측정 · 상태만 바뀜) 10.
"""
from __future__ import annotations

from app import devseed

SIZES = (3, 40, 150)
SEED = 20261009

SYN150_ASMS = ("MAIN_ASM", "DISPLAY_ASM", "REAR_ASM", "FRAME_ASM", "BATTERY_ASM", "CAMERA_ASM", "ANT_ASM",
               "SPK_ASM", "KEY_ASM", "USB_ASM", "SIM_ASM", "VIB_ASM", "MIC_ASM", "RCV_ASM", "FLASH_ASM", "SENSOR_ASM")
HEAVY_ASM = SYN150_ASMS[0]
SPREAD_ASMS = SYN150_ASMS[1:4]
SINGLE_ASMS = SYN150_ASMS[4:]

# syn40 의 기본 31종 — 생산자가 내는 의미 이벤트 코드마다 연산 하나(파생인 asm.rollup_changed 와 PRODUCER_GAPS 는 뺀다).
SYN40_KINDS = (
    "part.added", "part.removed", "part.replaced", "part.split", "part.merged", "part.tree_moved",
    "iface.added", "iface.removed", "iface.clearance_appeared", "iface.clearance_cleared", "iface.rank_up",
    "iface.rank_down", "iface.interference_new", "iface.interference_cleared", "iface.gap_changed",
    "iface.band_area_changed", "iface.penetration_changed",
    "contact.added", "contact.removed", "contact.friction_changed", "contact.scope_changed",
    "part.thickness_changed", "part.resized", "part.moved", "part.rotated", "mesh.density_changed",
    "part.material_changed", "cross.bridge_stale", "dim.named_changed", "dim.named_unmeasured",
    "result.part_metric_shift",
)


def spec_for(size: int, seed: int = SEED) -> devseed.SynthSpec:
    if size == 3:
        return devseed.SynthSpec(seed=seed, n_parts=12, asms=devseed.DEFAULT_ASMS[:3], named_dims=1)
    if size == 40:
        return devseed.SynthSpec(seed=seed, n_parts=60)
    if size == 150:
        return devseed.SynthSpec(seed=seed, n_parts=180, asms=SYN150_ASMS, asm_parts=(60,) + (8,) * 15)
    raise ValueError(f"크기는 {SIZES} 가운데 하나다 — {size}")


def script_for(size: int, seed: int = SEED) -> list[tuple[str, dict]]:
    if size == 3:
        return [
            ("part.thickness_changed", {"sign": -1, "subject": "HOOK_LATCH"}),
            ("part.material_changed", {"subject": "강화유리 WINDOW"}),
            ("iface.gap_changed", {"sign": -1, "boundary": True, "subject": "PASSIVE_PAD"}),
        ]
    if size == 40:
        named = {"part.material_changed": "강화유리 WINDOW", "part.moved": "PASSIVE_PAD"}
        base = [(kind, {"subject": named[kind]} if kind in named else {}) for kind in SYN40_KINDS]
        extra = [
            ("part.thickness_changed", {"sign": -1, "subject": "HOOK_LATCH"}),      # 감소 변형 셋
            ("iface.gap_changed", {"sign": -1}),
            ("result.part_metric_shift", {"sign": -1, "metric": "worst_g"}),
            ("contact.scope_changed", {}),                                         # 부품 키 없는 이벤트 둘
            ("dim.named_changed", {"sign": -1}),
            ("iface.added", {"boundary": True}),                                   # 경계 계면 둘
            ("iface.gap_changed", {"sign": -1, "boundary": True}),
            ("iface.band_area_changed", {"sign": -1}),                             # 단위 섞기(mm2 감소 · mm 결과)
            ("result.part_metric_shift", {"metric": "worst_disp"}),
        ]
        return base + extra
    if size == 150:
        return _syn150()
    raise ValueError(f"크기는 {SIZES} 가운데 하나다 — {size}")


def _syn150() -> list[tuple[str, dict]]:
    heavy = ([("part.moved", {})] * 15 + [("part.resized", {})] * 12 + [("iface.gap_changed", {})] * 10
             + [("iface.gap_changed", {"boundary": True, "asm_b": SPREAD_ASMS[0]})] * 5
             + [("part.thickness_changed", {"sign": -1})] * 4 + [("part.thickness_changed", {})] * 4
             + [("part.material_changed", {})] * 3 + [("iface.rank_up", {})] * 2 + [("iface.rank_down", {})] * 2
             + [("part.added", {})] * 2 + [("part.removed", {})])
    out = [(op, {**params, "asm": HEAVY_ASM}) for op, params in heavy]
    singles = ["part.moved"] * 4 + ["part.resized"] * 4 + ["iface.gap_changed"] * 4
    out += [(op, {"asm": asm}) for op, asm in zip(singles, SINGLE_ASMS)]
    spread = (["part.moved"] * 8 + ["part.resized"] * 7 + ["iface.gap_changed"] * 8
              + ["part.thickness_changed"] * 4 + ["part.material_changed"] * 2 + ["iface.added"] * 6
              + ["iface.removed"] * 3 + ["iface.clearance_appeared"] * 2 + ["iface.clearance_cleared"] * 2
              + ["iface.interference_new", "iface.interference_cleared"] + ["iface.band_area_changed"] * 3
              + ["iface.penetration_changed", "part.replaced", "part.split", "part.merged", "part.tree_moved"]
              + ["part.rotated"] * 2 + ["mesh.density_changed"] * 3 + ["cross.bridge_stale"]
              + ["result.part_metric_shift"] * 4 + ["contact.added", "contact.removed", "contact.friction_changed",
                                                    "contact.scope_changed", "dim.named_changed",
                                                    "dim.named_unmeasured"])
    boundary_left = 15                                     # 무거운 단위의 5건과 합쳐 경계 계면 20
    for i, op in enumerate(spread):
        asm = SPREAD_ASMS[i % len(SPREAD_ASMS)]
        params: dict = {"asm": asm, "sign": -1 if i % 3 == 0 else 1}
        if op.startswith("iface.") and boundary_left > 0:
            params.update(boundary=True, asm_b=SPREAD_ASMS[(i + 1) % len(SPREAD_ASMS)])
            boundary_left -= 1
        if op == "part.tree_moved":
            params["to"] = SPREAD_ASMS[(i + 1) % len(SPREAD_ASMS)]
        out.append((op, params))
    excluded = ["part.noise"] * 4 + ["part.min_dim_unknown"] * 3 + ["iface.status_changed"] * 3
    out += [(op, {"asm": SPREAD_ASMS[i % len(SPREAD_ASMS)]}) for i, op in enumerate(excluded)]
    return out
