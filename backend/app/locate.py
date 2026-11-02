# F2 단면 자리 찾기 — 리스크 항목 · refdes · 넷 · 보드 좌표를 MCAD 점 · 몸체 · 단면 둘(F1 section_pair_view 입력)로 바꾸고, 변환 등록의 근거를 그 사람의 PAT 로 읽는다
"""설계 docs/f2-locate-for-section.md.

저장소와 채널(그 사람의 포털 PAT 로 연 게이트웨이 MCP — routes 가 연다)을 받아 계산만 한다. 권한 · 신원 · 감사는 routes 몫이다. 게이트웨이는
호출 전용 별칭(`<백엔드 키 하이픈 뺌>_<도구>`)으로 부르고 도구 지도는 받지 않는다(SP 과제 풀이와 같다). 길이는 전부 mm 이고 F1 에 넘기는 자리마다
`unit: "mm"` 을 싣는다.

자리를 정하지 못한 것은 오류가 아니라 `status: unknown` 과 까닭이다(`unknown`). 채널은 산 호출이 필요할 때만 연다(`channel_factory`) — 항목에
위치가 적혀 있거나 MCAD 몸체가 주제면 게이트웨이를 부르지 않는다.
"""
from __future__ import annotations

import json
import math
import time
from typing import Any, Callable, Mapping, Sequence

from app import board_transform as bt
from app.adapters import ecad as ecad_adapter
from app.errors import AppError
from app.ra_client import DEADLINE_EXCEEDED
from app.sp_subject import gateway_alias

ODB_APP_KEY = ecad_adapter.DEFAULT_APP_KEY
CAD_APP_KEY = "heax-step_forge"
# 산 호출 한 번의 기한(초) — 사람이 기다리는 읽기 · 쓰기 안이다. StepForge 의 구멍 찾기는 형상을 읽어 수십 초가 들 수 있다.
CALL_TIMEOUT_S = 120.0
# ODB 고정홀 쪽 넘김 — 쪽마다 이만큼, 이 쪽 수까지(넘으면 앞의 것만이고 그렇게 말한다).
HOLES_PAGE_SIZE, HOLES_PAGES_MAX = 100, 5
# StepForge corner_proximity 의 줄 상한(MAX_ROWS) — 파트 하나를 지목하므로 구멍 줄의 상한이다.
CAD_HOLES_LIMIT = 500
# 그 자리의 부품 몸체를 찾는 선분 — 부품 면에서 바깥으로 이만큼(반대 검토 F2-9). 몸체의 bbox 가 이 선분에 걸려야 후보다 — 몸체의 아래 면이
# 보드 면에서 이만큼 안이어야 한다(BGA 볼 · 리드의 스탠드오프는 1 mm 안). 종전에는 면 바로 바깥 0.05 mm 의 한 점을 찔러 스탠드오프 0.2 mm 인
# IC 몸체를 놓치고 그 위를 덮은 쉴드캔을 몸체로 냈다. ODB 허브에 부품 높이 칸이 없어 상수다 — 더 깊으면 부품 위에 쌓인 몸체(써멀 패드 ·
# 덮개)까지 걸려 '여럿이라 고르지 않음' 이 는다.
PROBE_REACH_MM = 1.0
CONTAIN_TOL_MM = 0.01
# 몸체가 그 부품이라고 말할 조건 — 면내 두 변(긴 · 짧은)이 각각 부품 크기(패키지 — 없으면 핀 bbox)의 절반 이상이고 두 배(또는 +1 mm) 이하이며,
# 자리가 그 몸체의 가운데 반 안이고, 크기가 맞는 다른 후보를 품지 않는다(쉴드캔 · 하우징은 그 안의 부품을 품는다). 그런 몸체가 꼭 하나일 때만
# 몸체다 — 없거나 여럿이면 null 과 후보(종전에는 위 한계만 있어 부품 가운데의 0.3 mm 볼을 몸체로 냈다).
BODY_SIZE_FACTOR, BODY_SIZE_SLACK_MM = 2.0, 1.0
# 옮긴 자리가 CAD 보드 몸체 bbox 에서 이만큼 넘게 밖이면 이 보드의 자리가 아니다(point_off_board) — 등록 검증의 오차 상한과 같다.
OFF_BOARD_TOL_MM = bt.MAX_ERROR_MM
# 핀 bbox 의 두 변 비가 이만큼 넘어야 긴 축으로 쓴다(정사각에 가까운 BGA 는 보드의 긴 변으로).
PIN_AXIS_RATIO = 1.2
CANDIDATES_MAX = 5
# 제안의 보드 몸체 후보 — ODB 외곽 크기와 면내 두 변이 이 안인 몸체.
BODY_CANDIDATE_TOL_MM = 2.0
PATH_MAX = 1000

INPUT_KINDS: tuple[str, ...] = ("item", "refdes", "net", "xy")

# unknown 의 까닭 — 고칠 곳이 있으면 fix 를 함께 싣는다.
UNKNOWN: dict[str, str] = {
    "board_missing": "보드(ODB job_id)를 모른다 — 과제에 ECAD 보드가 붙지 않았고 odb_job_id 도 주지 않았다",
    "cad_project_missing": "CAD 과제(StepForge project_id)를 모른다 — 과제에 기구 CAD 원천이 없고 stepforge_project_id 도 주지 않았다",
    "transform_missing": "이 보드와 CAD 과제의 좌표 변환이 등록되지 않았다",
    "transform_unverified": ("등록된 변환을 이 박스에서 검증한 기록이 없다 — 다른 박스에서 들여온 행이거나(검증 칸은 들여오지 않는다) 과제 폐기가 검증"
                             " 기록을 지웠다"),
    "transform_stale": ("등록 뒤에 찍은 스냅샷의 CAD 보드 몸체가 등록 때 읽은 자리와 오차 상한보다 다르다 — 그 사이 CAD 가 바뀌어 변환이 낡았다"
                        "(옛 자리를 내지 않는다)"),
    "point_off_board": ("옮긴 자리가 CAD 보드 몸체(bbox, 상한만큼 너그럽게) 밖이다 — 이 보드의 자리가 아니다(다른 보드의 좌표 · 부품이거나 변환이"
                        " 틀렸다)"),
    "refdes_not_found": "ODB 허브가 그 refdes 를 주지 않았다",
    "side_unknown": "그 부품이 보드의 어느 면(top · bottom)에 있는지 모른다",
    "point_unread": "ODB 허브의 답에서 부품 좌표를 읽지 못했다",
    "net_not_found": "ODB 허브가 그 넷을 주지 않았다",
    "net_pins_absent": "ODB 허브의 넷 답에 핀 좌표가 없다 — 넷의 자리를 정하지 못한다",
    "odb_call_failed": "ODB 허브를 부르지 못했다",
    "odb_unit_unexpected": "ODB 허브의 답이 mm 가 아닌 단위라고 말한다",
    "subject_not_placeable": "항목의 주제가 부품 · 계면이 아니다(조립 · 치수 · 빈 주제) — 자리가 하나로 정해지지 않는다",
    "subject_ambiguous": "항목의 주제에 맞는 자리가 여럿이다 — 같은 부품이 여러 자리에 있거나 같은 계면이 여럿이다",
    "subject_nodes_absent": "항목의 스냅샷에 주제의 노드가 없다",
    "bbox_world_absent": "스냅샷의 그 몸체에 월드 bbox 가 없다(MCP 폴백 캡처 — 배치 좌표 없이 읽었다)",
    "item_part_absent": "항목 위치의 몸체 경로가 그 항목의 스냅샷에 없다",
    "item_location_invalid": "항목 위치 칸이 쓰기 꼴에 맞지 않는다(모르는 칸 · mm 가 아닌 단위 · 빠지거나 유한하지 않은 좌표)",
    "snapshot_missing": "항목의 대상에 읽을 스냅샷이 없다",
}
FIXES: dict[str, str] = {
    "board_missing": "odb_job_id 를 주거나 과제에 ECAD 보드를 붙인다(PUT /api/projects/{id}/ecad-board · MCP risk_set_ecad_board).",
    "cad_project_missing": "stepforge_project_id 를 주거나 과제에 기구 CAD 원천을 붙인다(MCP risk_add_source kind=mcad).",
    "transform_missing": ("후보를 GET /api/projects/{id}/board-transforms/proposal(MCP risk_propose_board_transform)로 보고 고른 값을"
                          " PUT /api/projects/{id}/board-transforms(MCP risk_set_board_transform)로 적는다 — 적을 때 이 박스에서 검증한다."),
    "transform_unverified": "같은 값을 다시 적어(PUT /api/projects/{id}/board-transforms · MCP risk_set_board_transform) 이 박스에서 검증한다.",
    "transform_stale": ("지금 CAD 로 다시 맞춘다 — GET /api/projects/{id}/board-transforms/proposal(MCP risk_propose_board_transform)의 후보를 보고"
                        " PUT /api/projects/{id}/board-transforms(MCP risk_set_board_transform)로 다시 적는다(적을 때 지금 CAD 로 다시 검증한다)."),
    "point_off_board": ("좌표 · refdes · 넷이 이 보드(odb_job_id)의 것인지 본다 — 다른 보드면 그 odb_job_id 를 준다. 강제로 적은 변환이면 제안(GET"
                        " /api/projects/{id}/board-transforms/proposal · MCP risk_propose_board_transform)을 보고 다시 적는다."),
    "side_unknown": "x · y 와 side 를 주어 다시 찾는다.",
    "net_pins_absent": "ODB 허브가 get_net 에 핀 좌표(pins[].x · y)를 내야 한다 — 그 전에는 refdes 나 보드 좌표로 찾는다.",
    "subject_not_placeable": "항목에 위치(몸체 경로 · 좌표)를 적거나(PUT /api/projects/{id}/item-location · MCP risk_set_item_location) refdes · 좌표로 찾는다.",
    "subject_ambiguous": "후보 가운데 하나를 항목 위치로 적는다(PUT /api/projects/{id}/item-location · MCP risk_set_item_location).",
    "bbox_world_absent": "REST 로 다시 캡처해 배치 좌표가 든 스냅샷을 만들거나 항목에 좌표를 적는다.",
    "item_location_invalid": ("항목 위치를 다시 적거나 뗀다(PUT /api/projects/{id}/item-location · MCP risk_set_item_location — part 와 point 를"
                              " 둘 다 null 로 주면 뗀다)."),
}


def unknown(code: str, *, message: str | None = None, **extra: Any) -> dict:
    """자리를 정하지 못한 답 — `{status: unknown, reason: {code, message, fix?}}` 와 아는 칸."""
    reason = {"code": code, "message": message or UNKNOWN[code]}
    if code in FIXES:
        reason["fix"] = FIXES[code]
    return {"status": "unknown", "reason": reason, **extra}


def _num(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _vec(value: Any, size: int) -> list[float] | None:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) != size:
        return None
    out = [_num(v) for v in value]
    return None if any(v is None for v in out) else out  # type: ignore[return-value]


def _bbox6(value: Any) -> list[float] | None:
    box = _vec(value, 6)
    if box is None or not (box[0] <= box[3] and box[1] <= box[4] and box[2] <= box[5]):
        return None
    return box


def _loads(raw: Any, default: Any) -> Any:
    try:
        value = json.loads(raw) if raw else default
    except (TypeError, ValueError):
        return default
    return value if isinstance(value, type(default)) else default


# ---------------------------------------------------------------- 산 호출(그 사람의 채널)
def _call(channel: Any, app_key: str, tool: str, args: Mapping[str, Any], calls: list[dict]) -> tuple[Any, str | None]:
    """별칭 하나를 부른다 — (답, None) 또는 (None, 까닭). 부른 것은 `calls` 에 {tool, ok, error} 로 남긴다(근거 원장)."""
    name = gateway_alias(app_key, tool)
    try:
        reply = channel.call(name, dict(args), deadline=time.monotonic() + CALL_TIMEOUT_S)
    except Exception as exc:  # noqa: BLE001 — 전송 층의 예외도 까닭으로 눕힌다(읽기를 터뜨리지 않는다)
        reply = {"ok": False, "error": f"transport_error: {type(exc).__name__}"}
    if reply.get("ok"):
        calls.append({"tool": name, "ok": True, "error": None})
        return reply.get("result"), None
    error = str(reply.get("error") or "unknown_error")
    if error == DEADLINE_EXCEEDED:
        why = f"{name} 가 {CALL_TIMEOUT_S:g}초 안에 답하지 않았다"
    elif error == "tool_error":
        detail = reply.get("detail")
        text = detail if isinstance(detail, str) else json.dumps(detail, ensure_ascii=False, default=str)
        why = f"{name} 가 오류로 답했다 — {' '.join(str(text).split())[:200]}"
    else:
        why = f"{name} 를 부르지 못했다({error})"
    calls.append({"tool": name, "ok": False, "error": why})
    return None, why


def read_odb_board(channel: Any, app_key: str, job_id: str, calls: list[dict]) -> dict:
    """ODB 보드의 외곽 크기 · 두께 · 외곽 bbox(OH-04 — 있을 때만) · 고정홀. 못 읽은 칸은 None · 빈 목록이고 `notes` 가 까닭이다."""
    out: dict[str, Any] = {"job_id": job_id, "size": None, "outline_bbox": None, "thickness_mm": None, "holes": [],
                           "holes_read": False, "notes": []}
    volume, why = _call(channel, app_key, "get_volume_result", {"job_id": job_id}, calls)
    message = ecad_adapter.body_error(volume) if why is None else why
    board = volume.get("board") if why is None and isinstance(volume, Mapping) else None
    if message is not None or not isinstance(board, Mapping):
        out["notes"].append(f"외곽 크기를 읽지 못했다 — {message or 'get_volume_result 에 board 가 없다'}")
    else:
        w, h = _num(board.get("x_mm")), _num(board.get("y_mm"))
        if w is not None and h is not None and w > 0 and h > 0:
            out["size"] = [w, h]
        out["thickness_mm"] = _num(board.get("thickness_mm"))
        outline = _vec(board.get("outline_bbox"), 4)
        if outline is not None and outline[0] < outline[2] and outline[1] < outline[3]:
            out["outline_bbox"] = outline
    holes: list[list[float]] = []
    for page in range(1, HOLES_PAGES_MAX + 1):
        reply, why = _call(channel, app_key, "get_mounting_holes",
                           {"job_id": job_id, "page": page, "page_size": HOLES_PAGE_SIZE}, calls)
        message = ecad_adapter.body_error(reply) if why is None else why
        if message is not None or not isinstance(reply, Mapping):
            out["notes"].append(f"고정홀을 읽지 못했다 — {message or 'get_mounting_holes 답이 객체가 아니다'}")
            break
        out["holes_read"] = True
        for hole in reply.get("holes") or ():
            if isinstance(hole, Mapping):
                x, y, d = _num(hole.get("x")), _num(hole.get("y")), _num(hole.get("diameter_mm"))
                if x is not None and y is not None and d is not None and d > 0:
                    holes.append([x, y, d])
        if reply.get("has_more") is not True:
            break
    else:
        out["notes"].append(f"고정홀이 {HOLES_PAGES_MAX}쪽을 넘어 앞의 {len(holes)}개만 봤다")
    out["holes"] = holes
    return out


def read_cad_board(channel: Any, app_key: str, project_id: str, body_path: str, calls: list[dict]) -> dict:
    """CAD 보드 몸체의 월드 bbox(part_info)와 z 축 원형 구멍(corner_proximity — 평면 위 한 점과 지름) · 단위 의심. StepForge 챗 접기를 끈다
    (full)."""
    out: dict[str, Any] = {"stepforge_project_id": project_id, "path": body_path, "bbox": None, "holes": [], "holes_read": False,
                           "holes_off_axis": 0, "unit_suspect": False, "declared_units": None, "notes": []}
    info, why = _call(channel, app_key, "part_info", {"project_id": project_id, "part": body_path, "full": True}, calls)
    if why is not None or not isinstance(info, Mapping):
        out["notes"].append(f"보드 몸체를 읽지 못했다 — {why or 'part_info 답이 객체가 아니다'}")
        return out
    path = str(info.get("path") or "").strip()
    if path:
        out["path"] = path
    out["bbox"] = _bbox6(info.get("world_bbox"))
    if out["bbox"] is None:
        out["notes"].append("part_info 에 월드 bbox 가 없다(배치 좌표가 없다 — parse 를 다시 돌린다)")
    reply, why = _call(channel, app_key, "corner_proximity",
                       {"project_id": project_id, "part": out["path"], "limit": CAD_HOLES_LIMIT, "full": True}, calls)
    if why is not None or not isinstance(reply, Mapping):
        out["notes"].append(f"CAD 구멍을 읽지 못했다 — {why or 'corner_proximity 답이 객체가 아니다'}")
        return out
    if reply.get("declared_units_count") or reply.get("unit_note"):
        out["unit_suspect"] = True
        out["declared_units"] = reply.get("declared_units_by_unit") or reply.get("declared_units")
    if reply.get("chat_fold"):
        out["notes"].append("StepForge 가 답을 접었다(full 을 받지 않는 판) — 구멍 목록이 잘렸을 수 있다")
    out["holes_read"] = True
    rows = [r for r in reply.get("parts") or () if isinstance(r, Mapping)]
    row = next((r for r in rows if str(r.get("path") or "") == out["path"]), rows[0] if len(rows) == 1 else None)
    if reply.get("partial") or (row is not None and (row.get("unexamined") or row.get("holes_truncated"))):
        out["notes"].append("CAD 구멍을 다 보지 못했다(작업량 상한 · 줄 상한) — 짝이 모자랄 수 있다")
    for hole in (row or {}).get("hole_list") or ():
        if not isinstance(hole, Mapping):
            continue
        center, axis, radius = _vec(hole.get("center"), 3), _vec(hole.get("axis"), 3), _num(hole.get("radius_mm"))
        if center is None or axis is None or radius is None or radius <= 0:
            continue
        norm = math.sqrt(sum(a * a for a in axis))
        if norm <= 0 or abs(axis[2]) / norm < bt.HOLE_AXIS_COS_MIN:
            out["holes_off_axis"] += 1
            continue
        out["holes"].append([center[0], center[1], 2.0 * radius])
    return out


def board_evidence(channel: Any, *, odb_app: str, cad_app: str, job_id: str, stepforge_project_id: str,
                   body_path: str) -> dict:
    """등록 검증의 근거 — {odb, cad, calls}. 호출 실패는 칸이 비고 notes 가 까닭이다(예외로 올리지 않는다)."""
    calls: list[dict] = []
    odb = read_odb_board(channel, odb_app, job_id, calls)
    cad = read_cad_board(channel, cad_app, stepforge_project_id, body_path, calls)
    return {"odb": odb, "cad": cad, "calls": calls}


def verify_inputs(evidence: Mapping[str, Any]) -> tuple[dict, dict]:
    """근거 → board_transform.verify 의 두 입력."""
    odb, cad = evidence["odb"], evidence["cad"]
    return ({"size": odb["size"], "outline_bbox": odb["outline_bbox"], "thickness_mm": odb["thickness_mm"],
             "holes": [tuple(h) for h in odb["holes"]]},
            {"bbox": cad["bbox"], "holes": [tuple(h) for h in cad["holes"]], "unit_suspect": cad["unit_suspect"]})


# ---------------------------------------------------------------- 등록부 행
TRANSFORM_COLUMNS = ("project_id, odb_job_id, stepforge_project_id, owner_sub, board_body_path, mirror_x, mirror_y, offset_x,"
                     " offset_y, top_face, board_z_min, board_z_max, source, status, error_mm, verify_json, reason, created_by,"
                     " created_at, updated_by, updated_at")


def transform_row(store: Any, project_id: str, owner_sub: str, odb_job_id: str, stepforge_project_id: str) -> dict | None:
    """그 과제 주인의 등록 행 — 주인이 다른 행(들여오기가 남의 과제에 매단 것)은 보지 않는다."""
    row = store.query_one(f"SELECT {TRANSFORM_COLUMNS} FROM rr_board_transforms WHERE project_id = ? AND odb_job_id = ?"
                          " AND stepforge_project_id = ? AND owner_sub = ?", (project_id, odb_job_id, stepforge_project_id, owner_sub))
    return dict(row) if row is not None else None


def transform_rows(store: Any, project_id: str, owner_sub: str) -> list[dict]:
    return [dict(r) for r in store.query(f"SELECT {TRANSFORM_COLUMNS} FROM rr_board_transforms WHERE project_id = ? AND owner_sub = ?"
                                         " ORDER BY odb_job_id, stepforge_project_id", (project_id, owner_sub))]


def transform_of(row: Mapping[str, Any]) -> bt.Transform:
    return bt.Transform(bool(row["mirror_x"]), bool(row["mirror_y"]), float(row["offset_x"]), float(row["offset_y"]),
                        str(row["top_face"]))


def transform_view(row: Mapping[str, Any], *, full: bool = False) -> dict:
    """등록 한 행을 사람 · 도구에 보일 꼴 — 식 · 값 · 상태 · 오차 · 검증 요지(full 이면 검증 전부와 근거)."""
    t = transform_of(row)
    stored = _loads(row.get("verify_json"), {})
    check = stored.get("verification") if isinstance(stored.get("verification"), Mapping) else {}
    checks = check.get("checks") if isinstance(check.get("checks"), Mapping) else {}
    out = {"odb_job_id": row["odb_job_id"], "stepforge_project_id": row["stepforge_project_id"],
           "board_body_path": row["board_body_path"], **t.as_dict(), "formula": t.formula(),
           "board_z_min": row["board_z_min"], "board_z_max": row["board_z_max"], "source": row["source"],
           "status": row["status"], "error_mm": row["error_mm"], "max_error_mm": check.get("max_error_mm"),
           "reasons": list(check.get("reasons") or ()), "reason": row["reason"],
           "summary": {"outline_measured": bool((checks.get("outline") or {}).get("measured")),
                       "outline_error_mm": (checks.get("outline") or {}).get("error_mm"),
                       "size_error_mm": (checks.get("size") or {}).get("error_mm"),
                       "holes_matched": (checks.get("holes") or {}).get("matched"),
                       "hole_error_mm": (checks.get("holes") or {}).get("error_mm")},
           "verified_at": stored.get("verified_at"), "verified_by": stored.get("verified_by"),
           "created_by": row["created_by"], "created_at": row["created_at"], "updated_by": row["updated_by"],
           "updated_at": row["updated_at"]}
    if full:
        out["verification"] = check or None
        out["evidence"] = stored.get("evidence")
    return out


# ---------------------------------------------------------------- 스냅샷 읽기
def _ir(store: Any, snapshot_id: str) -> dict | None:
    row = store.query_one("SELECT ir_json FROM rr_snapshots WHERE id = ?", (snapshot_id,))
    ir = _loads(row["ir_json"], {}) if row is not None else {}
    return ir if ir.get("nodes") is not None else None


def _source_ref(ir: Mapping[str, Any], kind: str) -> dict:
    for source in ir.get("sources") or ():
        if isinstance(source, Mapping) and source.get("kind") == kind:
            ref = source.get("ref")
            return dict(ref) if isinstance(ref, Mapping) else {}
    return {}


def _source_app(ir: Mapping[str, Any], kind: str) -> str | None:
    for source in ir.get("sources") or ():
        if isinstance(source, Mapping) and source.get("kind") == kind:
            return str(source.get("app_key") or "") or None
    return None


def cad_snapshot(store: Any, project_id: str, owner_sub: str, stepforge_project_id: str) -> dict | None:
    """그 과제(주인의 행)의 가장 최근 스냅샷 가운데 그 StepForge 과제를 mcad 로 읽은 것 — {snapshot_id, ir, captured_at}(captured_at 은
    그 스냅샷이 CAD 를 읽은 때 — rr_snapshots.created_at)."""
    for row in store.query("SELECT id, created_at FROM rr_snapshots WHERE project_id = ? AND owner_sub = ?"
                           " ORDER BY created_at DESC, rowid DESC", (project_id, owner_sub)):
        ir = _ir(store, row["id"])
        if ir is not None and str(_source_ref(ir, "mcad").get("stepforge_project_id") or "") == stepforge_project_id:
            return {"snapshot_id": row["id"], "ir": ir, "captured_at": row["created_at"]}
    return None


def verification_record(row: Mapping[str, Any]) -> dict | None:
    """등록 행의 이 박스 검증 기록 — {verified_at, board_bbox(등록 때 읽은 CAD 보드 몸체 월드 bbox)}. 상태가 verified · forced 가 아니거나
    검증 기록(verify_json — 검증 · 근거의 보드 bbox · 시각)이 없으면 None 이다: 들여온 행은 상태가 없고, 과제 폐기는 상태를 남긴 채 검증 기록을
    지운다(반대 검토 F2-9 — 종전에는 그 행을 verified 로 읽어 자리를 냈다)."""
    if row.get("status") not in ("verified", "forced"):
        return None
    stored = _loads(row.get("verify_json"), {})
    bbox = _bbox6(((stored.get("evidence") or {}).get("cad") or {}).get("bbox")) if isinstance(stored.get("evidence"), Mapping) else None
    verified_at = stored.get("verified_at")
    if not isinstance(stored.get("verification"), Mapping) or bbox is None or isinstance(verified_at, bool) \
            or not isinstance(verified_at, (int, float)):
        return None
    return {"verified_at": verified_at, "board_bbox": bbox}


def cad_view(store: Any, project: Mapping[str, Any], row: Mapping[str, Any], record: Mapping[str, Any]) -> dict | None:
    """그 CAD 과제를 읽은 최근 스냅샷과 그 안의 등록된 보드 몸체 — {snapshot_id, ir, captured_at, parts, board, box, moved_mm, newer}.
    moved_mm 은 스냅샷 보드 bbox 와 등록 때 읽은 bbox 의 가장 큰 차(보드가 없거나 월드 bbox 가 없으면 None), newer 는 스냅샷이 검증 뒤(같은
    초 포함 — 차례를 모르면 낡은 쪽으로 본다)에 CAD 를 읽었는가. 스냅샷이 없으면 None — 산 CAD 를 다시 부르지 않으므로 그때는 등록 뒤의 CAD
    변경을 알 수 없다(설계 4절)."""
    found = cad_snapshot(store, project["id"], project["owner_sub"], row["stepforge_project_id"])
    if found is None:
        return None
    parts = _parts(found["ir"])
    board = next((n for n in parts if str(n.get("local_key") or "") == row["board_body_path"]), None)
    box = _bbox_of(board) if board is not None else None
    moved = None if box is None else round(max(abs(a - b) for a, b in zip(box, record["board_bbox"])), bt.DIGITS)
    captured = found["captured_at"]
    return {**found, "parts": parts, "board": board, "box": box, "moved_mm": moved,
            "newer": captured is None or captured >= record["verified_at"]}


def _parts(ir: Mapping[str, Any]) -> list[dict]:
    return [n for n in ir.get("nodes") or () if isinstance(n, Mapping) and n.get("domain") == "mcad" and n.get("kind") == "part"]


def _bbox_of(node: Mapping[str, Any]) -> list[float] | None:
    return _bbox6((node.get("attrs") or {}).get("bbox_world"))


def _unit_warning(ir: Mapping[str, Any]) -> str | None:
    """스냅샷의 STEP 머리 단위가 mm 가 아니면 경고 — 좌표가 그 배수만큼 클 수 있다(StepForge 는 머리를 믿고 mm 로 바꿔 읽는다)."""
    odd = sorted({str(f.get("header_unit")) for f in _source_ref(ir, "mcad").get("step_files") or ()
                  if isinstance(f, Mapping) and f.get("header_unit") and str(f.get("header_unit")).lower()
                  not in ("millimetre", "millimeter", "mm")})
    return (f"cad_unit_suspect — STEP 머리 단위가 mm 가 아닌 파일이 있다({', '.join(odd)}) — 좌표가 그 배수만큼 클 수 있다"
            if odd else None)


def _center(box: Sequence[float]) -> dict:
    return {"x": (box[0] + box[3]) / 2, "y": (box[1] + box[4]) / 2, "z": (box[2] + box[5]) / 2}


def _extents(box: Sequence[float]) -> dict:
    return {"x": box[3] - box[0], "y": box[4] - box[1], "z": box[5] - box[2]}


def _point(x: float, y: float, z: float) -> dict:
    return {"x": round(float(x), bt.DIGITS) + 0.0, "y": round(float(y), bt.DIGITS) + 0.0, "z": round(float(z), bt.DIGITS) + 0.0,
            "unit": bt.UNIT}


def _fits(extent: Mapping[str, float], size: Sequence[float]) -> bool:
    """몸체의 면내 두 변(긴 · 짧은)이 각각 부품 크기(긴 · 짧은)의 절반 이상이고 두 배(또는 +1 mm) 이하인가."""
    got = sorted((extent["x"], extent["y"]), reverse=True)
    return all(want / BODY_SIZE_FACTOR <= have <= max(BODY_SIZE_FACTOR * want, want + BODY_SIZE_SLACK_MM) for have, want in zip(got, size))


def _encloses(outer: Sequence[float], inner: Sequence[float]) -> bool:
    """outer bbox 가 inner bbox 를 3차원으로 품는가(너그러움 CONTAIN_TOL_MM) — 같은 bbox 는 품지 않는다(서로 품어 둘 다 빠지지 않게)."""
    if all(abs(outer[i] - inner[i]) <= CONTAIN_TOL_MM for i in range(6)):
        return False
    return all(outer[i] - CONTAIN_TOL_MM <= inner[i] and inner[i + 3] <= outer[i + 3] + CONTAIN_TOL_MM for i in range(3))


# ---------------------------------------------------------------- 답 조립
def located(*, input_: dict, project_id: str, stepforge_project_id: str | None, point: Mapping[str, float],
            extents: Mapping[str, float], plane_basis: str, body: dict | None, body_note: str | None = None,
            candidates: Sequence[dict] = (), feature_long: float | None = None, transform: dict | None = None,
            ecad: dict | None = None, odb_job_id: str | None = None, warnings: Sequence[str] = (), snapshot_id: str | None = None) -> dict:
    """자리를 정한 답 — MCAD 점 · 몸체 · 단면 둘(긴 축 먼저) · 창 · F1 넘김 꼴(모든 자리에 unit mm)."""
    mcad = _point(point["x"], point["y"], point["z"])
    planes, basis = bt.section_planes(mcad, extents)
    window = bt.window_for(feature_long if feature_long is not None else max((float(v) for v in extents.values()), default=None))
    out: dict[str, Any] = {
        "status": "located", "input": input_, "project_id": project_id, "stepforge_project_id": stepforge_project_id,
        "odb_job_id": odb_job_id, "mcad": mcad, "body": body, "body_note": body_note, "body_candidates": list(candidates),
        "planes": planes, "plane_basis": {**basis, "basis": plane_basis}, "window_mm": window,
        "f1": {"stepforge_project_id": stepforge_project_id, "point": mcad, "part": (body or {}).get("path"), "planes": planes,
               "window_mm": window,
               "note": "F1 section_pair_view 의 자리 입력은 part · point · axis+offset 가운데 하나다 — planes 의 항목은 그대로 넘긴다"},
        "warnings": list(warnings)}
    if snapshot_id is not None:
        out["snapshot_id"] = snapshot_id
    if transform is not None:
        out["transform"] = transform
    if ecad is not None:
        out["ecad"] = ecad
    return out


def _body_of(node: Mapping[str, Any], snapshot_id: str) -> dict:
    return {"path": str(node.get("local_key") or ""), "label": node.get("label"), "basis": "snapshot", "snapshot_id": snapshot_id}


# ---------------------------------------------------------------- 보드 길(refdes · 넷 · 좌표)
def _board_body(view: Mapping[str, Any] | None, x: float, y: float, face: str | None, *, size: Sequence[float] | None,
                mid_point: bool) -> tuple[dict | None, str | None, list[dict], str | None]:
    """그 자리의 CAD 몸체 — (body, note, 후보, snapshot_id). 그 CAD 과제의 최근 스냅샷(`cad_view`)을 본다. 스냅샷의 보드 몸체가 등록 때와
    다르면 찾지 않는다 — 여기 오는 것은 등록보다 앞서 찍은 스냅샷뿐이다(뒤에 찍은 스냅샷이면 변환이 낡은 것이라 위에서 transform_stale).

    면 없는 보드 좌표(`mid_point`)는 보드 몸체다. 아니면 (x, y) 에서 부품 면(`face`) 바깥으로 PROBE_REACH_MM 까지의 선분에 걸리는 몸체가
    후보이고, 부품 크기(`size` — 긴 · 짧은 변, 모르면 None)에 맞고 자리가 가운데 반 안이며 크기가 맞는 다른 후보를 품지도 그 위에 얹히지도 않은
    몸체가 꼭 하나면 그것이 body 다. 후보는 크기가 맞는 것(fits_part)부터 부피 차례다."""
    if view is None:
        return None, "no_cad_snapshot — 이 CAD 과제를 읽은 스냅샷이 과제에 없어 몸체를 찾지 않았다(점 · 평면은 그대로 쓴다)", [], None
    snapshot_id, parts, board = view["snapshot_id"], view["parts"], view["board"]
    if view["box"] is None:
        return None, "snapshot_board_absent — 스냅샷에 등록된 보드 몸체(월드 bbox)가 없어 몸체를 찾지 않았다", [], snapshot_id
    if view["moved_mm"] > bt.MAX_ERROR_MM:
        return None, ("snapshot_board_moved — 등록보다 앞서 찍은 스냅샷의 보드 몸체가 등록 때 읽은 자리와 오차 상한보다 달라 그 스냅샷으로는"
                      " 몸체를 찾지 않았다(변환은 그 뒤의 CAD 로 검증됐다 — 다시 캡처하면 몸체를 찾는다)"), [], snapshot_id
    if mid_point or face is None:
        return _body_of(board, snapshot_id), None, [], snapshot_id
    face_z = view["box"][5] if face == "zmax" else view["box"][2]
    reach = sorted((face_z, face_z + bt.outward(face) * PROBE_REACH_MM))
    hits = []
    for node in parts:
        b = _bbox_of(node)
        if node is board or b is None:
            continue
        if not (b[0] - CONTAIN_TOL_MM <= x <= b[3] + CONTAIN_TOL_MM and b[1] - CONTAIN_TOL_MM <= y <= b[4] + CONTAIN_TOL_MM):
            continue
        if b[5] < reach[0] - CONTAIN_TOL_MM or b[2] > reach[1] + CONTAIN_TOL_MM:
            continue                                # 그 면 바깥 선분에 걸리지 않는다(반대 면의 몸체 · 더 높이 쌓인 몸체)
        e = _extents(b)
        centred = abs(x - (b[0] + b[3]) / 2) <= 0.25 * e["x"] + CONTAIN_TOL_MM and abs(y - (b[1] + b[4]) / 2) <= 0.25 * e["y"] + CONTAIN_TOL_MM
        fits = size is not None and centred and _fits(e, size)
        hits.append((not fits, e["x"] * e["y"] * max(e["z"], 1e-9), str(node.get("local_key") or ""), node, b))
    hits.sort(key=lambda h: h[:3])
    listed = [{"path": path, "bbox": [round(v, bt.DIGITS) for v in b], "fits_part": not misfit}
              for misfit, _v, path, _n, b in hits[:CANDIDATES_MAX]]
    if not hits:
        return None, "no_body — 그 자리에서 면 바깥으로 걸리는 몸체가 스냅샷에 없다(부품이 CAD 에 없을 수 있다)", [], snapshot_id
    if size is None:
        return None, "bbox_only — 대상 크기를 몰라(보드 좌표) 몸체로 말하지 않는다(후보를 본다)", listed, snapshot_id
    fitting = [h for h in hits if not h[0]]
    inner = [h for h in fitting if not any(o is not h and _encloses(h[4], o[4]) for o in fitting)]
    # 크기가 맞는 다른 후보의 바깥 쪽에 통째로 얹힌 몸체(써멀 패드 · PoP 의 위 패키지 · 덮개)는 그 자리에 실장된 부품이 아니다 — 보드 면에
    # 가까운 쪽이 부품이다. z 가 겹치면(언더필처럼 옆을 두른 것) 가르지 않는다.
    out_sign = bt.outward(face)
    mounted = [h for h in inner if not any(
        o is not h and (h[4][5] <= o[4][2] + CONTAIN_TOL_MM if out_sign < 0 else h[4][2] >= o[4][5] - CONTAIN_TOL_MM) for o in inner)]
    if len(mounted) == 1:
        return _body_of(mounted[0][3], snapshot_id), None, listed, snapshot_id
    if not fitting:
        return None, ("bbox_only — 그 자리에 걸리는 몸체 가운데 부품 크기 · 자리에 맞는 것이 없어 몸체로 말하지 않는다(bbox 가 품을 뿐이다 —"
                      " 후보를 본다)"), listed, snapshot_id
    return None, ("ambiguous — 부품 크기 · 자리에 맞고 서로 품지 않는 몸체가 여럿이라 고르지 않는다(후보의 fits_part 를 보고 항목 위치로"
                  " 적는다)"), listed, snapshot_id


def _part_detail(channel: Any, app_key: str, job_id: str, refdes: str, calls: list[dict]) -> tuple[dict | None, dict | None]:
    """refdes 의 보드 좌표 · 크기 · 면 — (자리, None) 또는 (None, unknown 답)."""
    detail, why = _call(channel, app_key, "get_part_detail", {"job_id": job_id, "refdes": refdes}, calls)
    if why is not None:
        return None, unknown("odb_call_failed", message=f"{UNKNOWN['odb_call_failed']} — {why}")
    message = ecad_adapter.body_error(detail)
    if message is not None or not isinstance(detail, Mapping):
        return None, unknown("refdes_not_found", message=f"{UNKNOWN['refdes_not_found']} — {message or '답이 객체가 아니다'}")
    x, y = _num(detail.get("x")), _num(detail.get("y"))
    pins = [(px, py) for px, py in ((_num(p.get("x")), _num(p.get("y"))) for p in detail.get("pins") or () if isinstance(p, Mapping))
            if px is not None and py is not None]
    side = str(detail.get("side") or "").strip().lower() or None
    pkg = [v for v in (_num(detail.get("pkg_width")), _num(detail.get("pkg_length"))) if v is not None and v > 0]
    if len(pins) >= 2 and not detail.get("pins_truncated"):
        xs, ys = [p[0] for p in pins], [p[1] for p in pins]
        cx, cy, ex, ey, basis = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, max(xs) - min(xs), max(ys) - min(ys), "pins"
    elif x is not None and y is not None:
        cx, cy, ex, ey, basis = x, y, None, None, "placement"
    else:
        return None, unknown("point_unread")
    return {"x": cx, "y": cy, "ex": ex, "ey": ey, "center_basis": basis, "side": side if side in bt.SIDES else None,
            "placement": {"x": x, "y": y, "rotation": _num(detail.get("rotation"))}, "pkg_long": max(pkg) if pkg else None,
            "pkg_size": sorted(pkg, reverse=True) if len(pkg) == 2 else None,
            "pins": len(pins), "pins_truncated": bool(detail.get("pins_truncated"))}, None


def _snapshot_side(store: Any, project: Mapping[str, Any], job_id: str, refdes: str) -> str | None:
    """그 보드를 읽은 최근 스냅샷의 ECAD 부품 노드 면(list_parts 의 side) — 허브 답에 side 가 없을 때만."""
    for row in store.query("SELECT id FROM rr_snapshots WHERE project_id = ? AND owner_sub = ? ORDER BY created_at DESC, rowid DESC",
                           (project["id"], project["owner_sub"])):
        ir = _ir(store, row["id"])
        if ir is None or str(_source_ref(ir, "ecad").get("board_id") or "").lower() != job_id.lower():
            continue
        for node in ir.get("nodes") or ():
            if isinstance(node, Mapping) and node.get("domain") == "ecad" and node.get("kind") == "component" \
                    and str(node.get("label") or "") == refdes:
                side = str((node.get("attrs") or {}).get("side") or node.get("group") or "").lower()
                return side if side in bt.SIDES else None
    return None


def _net_point(channel: Any, app_key: str, job_id: str, net: str, calls: list[dict]) -> tuple[dict | None, dict | None]:
    reply, why = _call(channel, app_key, "get_net", {"job_id": job_id, "net": net}, calls)
    if why is not None:
        return None, unknown("odb_call_failed", message=f"{UNKNOWN['odb_call_failed']} — {why}")
    message = ecad_adapter.body_error(reply)
    if message is not None or not isinstance(reply, Mapping):
        return None, unknown("net_not_found", message=f"{UNKNOWN['net_not_found']} — {message or '답이 객체가 아니다'}")
    units = str(reply.get("units") or "mm").strip().lower()
    if units not in ("mm", "millimetre", "millimeter"):
        return None, unknown("odb_unit_unexpected", message=f"{UNKNOWN['odb_unit_unexpected']}(units={units[:20]!r})")
    pins = [(px, py) for px, py in ((_num(p.get("x")), _num(p.get("y"))) for p in reply.get("pins") or () if isinstance(p, Mapping))
            if px is not None and py is not None]
    if not pins:
        return None, unknown("net_pins_absent", pin_count=reply.get("pin_count"))
    xs, ys = [p[0] for p in pins], [p[1] for p in pins]
    return {"x": (min(xs) + max(xs)) / 2, "y": (min(ys) + max(ys)) / 2, "ex": max(xs) - min(xs), "ey": max(ys) - min(ys),
            "center_basis": "pins", "pins": len(pins), "pins_truncated": bool(reply.get("pins_truncated"))}, None


def locate_on_board(store: Any, project: Mapping[str, Any], *, input_: dict, odb_job_id: str | None,
                    stepforge_project_id: str | None, channel_factory: Callable[[], Any], odb_app: str = ODB_APP_KEY,
                    echo: dict | None = None) -> dict:
    """refdes · 넷 · 보드 좌표 → 등록된 변환 → MCAD 점 · 몸체 · 평면. 채널은 refdes · 넷일 때만 연다. `echo` 는 답에 되싣는 입력이다(항목이 ECAD
    부품 주제로 이 길을 타면 그 항목 입력)."""
    shown = echo if echo is not None else input_
    context = {"input": shown, "project_id": project["id"], "odb_job_id": odb_job_id, "stepforge_project_id": stepforge_project_id}
    if not odb_job_id:
        return unknown("board_missing", **context)
    if not stepforge_project_id:
        return unknown("cad_project_missing", **context)
    row = transform_row(store, project["id"], project["owner_sub"], odb_job_id, stepforge_project_id)
    if row is None:
        return unknown("transform_missing", **context)
    record = verification_record(row)
    if record is None:
        out = unknown("transform_unverified", **context, transform=transform_view(row))
        if project.get("status") == "purged":
            # 폐기된 과제는 다시 적을 수 없다(409 project_purged) — 고칠 곳 대신 그렇게 말한다.
            out["reason"] = {"code": "transform_unverified",
                             "message": "과제가 폐기되어 변환의 검증 기록이 지워졌다 — 이 과제로는 보드 자리를 찾지 않는다(폐기된 과제는 다시 적을 수 없다)"}
        return out
    t = transform_of(row)
    view = transform_view(row)
    snapshot = cad_view(store, project, row, record)
    if snapshot is not None and snapshot["moved_mm"] is not None and snapshot["moved_mm"] > bt.MAX_ERROR_MM and snapshot["newer"]:
        # 등록 뒤에 찍은 스냅샷이 보드가 옮겨졌다고 말한다 — CAD 가 바뀌어 변환이 낡았다. 옛 자리를 내지 않는다(반대 검토 F2-9 — 종전에는
        # 옛 자리를 located 로 내고 몸체 칸에만 적었다). 산 호출 전이다.
        return unknown("transform_stale", **context, transform=view, snapshot_id=snapshot["snapshot_id"],
                       board_moved_mm=snapshot["moved_mm"], snapshot_board_bbox=[round(v, bt.DIGITS) for v in snapshot["box"]],
                       registered_board_bbox=[round(v, bt.DIGITS) for v in record["board_bbox"]])
    warnings: list[str] = []
    if row["status"] == "forced":
        warnings.append(f"transform_forced — 검증을 지나지 못한 변환을 사람이 강제로 적었다(까닭 {', '.join(view['reasons']) or '-'} ·"
                        f" 사유 {row['reason'] or '-'}) — 자리를 그만큼 덜 믿는다")
    board_extents = _extents(record["board_bbox"])
    calls: list[dict] = []
    kind = input_["kind"]
    if kind == "xy":
        spot = {"x": input_["x"], "y": input_["y"], "ex": None, "ey": None, "center_basis": "given", "side": input_.get("side")}
    elif kind == "refdes":
        spot, failed = _part_detail(channel_factory(), odb_app, odb_job_id, input_["refdes"], calls)
        if failed is not None:
            return {**failed, **context, "calls": calls}
        if spot["side"] is None:
            spot["side"] = _snapshot_side(store, project, odb_job_id, input_["refdes"])
            if spot["side"] is None:
                return {**unknown("side_unknown"), **context, "calls": calls,
                        "ecad": {"x": spot["x"], "y": spot["y"], "unit": bt.UNIT}}
            spot["side_basis"] = "snapshot"
    else:
        spot, failed = _net_point(channel_factory(), odb_app, odb_job_id, input_["net"], calls)
        if failed is not None:
            return {**failed, **context, "calls": calls}
        spot["side"] = None
        if spot["pins_truncated"]:
            warnings.append("net_pins_truncated — 허브가 핀 목록을 잘랐다 — 넷의 bbox 가 모자랄 수 있다")
    x_cad, y_cad = t.apply(spot["x"], spot["y"])
    bx0, by0, _bz0, bx1, by1, _bz1 = record["board_bbox"]
    if not (bx0 - OFF_BOARD_TOL_MM <= x_cad <= bx1 + OFF_BOARD_TOL_MM and by0 - OFF_BOARD_TOL_MM <= y_cad <= by1 + OFF_BOARD_TOL_MM):
        # 보드 밖의 자리 — 종전에는 면 없는 좌표가 어디든 보드 몸체를 몸체(F1 part)로 냈다(반대 검토 F2-9). 자리를 지어내지 않는다.
        off = unknown("point_off_board", **context, transform=view,
                      ecad={"x": round(spot["x"], bt.DIGITS), "y": round(spot["y"], bt.DIGITS), "unit": bt.UNIT},
                      mapped={"x": x_cad, "y": y_cad, "unit": bt.UNIT}, board_bbox=[round(v, bt.DIGITS) for v in record["board_bbox"]])
        if calls:
            off["calls"] = calls
        return off
    side = spot.get("side")
    if side is not None:
        face = bt.face_of(side, t.top_face)
        z = bt.face_z(face, row["board_z_min"], row["board_z_max"])
        z_basis = f"mount_face — {side} 면 부품이 닿는 CAD {bt.FACE_WORDS[face]}({face})"
    else:
        face, z = None, (row["board_z_min"] + row["board_z_max"]) / 2
        z_basis = "board_mid — 면을 몰라 보드 두께 가운데"
    ex, ey = spot.get("ex"), spot.get("ey")
    decisive = ex is not None and ey is not None and max(ex, ey) > 0 and (min(ex, ey) == 0 or max(ex, ey) / min(ex, ey) >= PIN_AXIS_RATIO)
    if decisive:
        extents, plane_basis = {"x": ex, "y": ey}, f"{spot['center_basis']} — 그 bbox 의 긴 변"
    else:
        extents = {"x": board_extents["x"], "y": board_extents["y"]}
        plane_basis = "board — 대상의 긴 변을 몰라(정사각에 가깝거나 핀이 없다) 보드의 긴 변"
    feature_long = max([v for v in (ex, ey, spot.get("pkg_long")) if v is not None] or [0.0]) or None
    if kind == "net":
        body, note, candidates, snapshot_id = None, "net — 넷은 몸체 하나로 정하지 않는다(점 · 평면을 쓴다)", [], None
    else:
        # 부품 크기 — 패키지(긴 · 짧은 변), 없으면 핀 bbox. 좌표에는 대상 크기가 없어 몸체로 말하지 않고 후보만 싣는다(면 없는 좌표는 보드 몸체).
        size = None
        if kind == "refdes":
            size = spot.get("pkg_size") or (sorted((ex, ey), reverse=True) if ex is not None and ey is not None else None)
        body, note, candidates, snapshot_id = _board_body(snapshot, x_cad, y_cad, face, size=size, mid_point=kind == "xy" and side is None)
    ecad = {"x": round(spot["x"], bt.DIGITS), "y": round(spot["y"], bt.DIGITS), "side": side, "unit": bt.UNIT,
            "center_basis": spot["center_basis"], "z_basis": z_basis}
    for key in ("placement", "pins", "pins_truncated", "side_basis"):
        if key in spot:
            ecad[key] = spot[key]
    out = located(input_=shown, project_id=project["id"], stepforge_project_id=row["stepforge_project_id"],
                  odb_job_id=odb_job_id, point={"x": x_cad, "y": y_cad, "z": z}, extents=extents, plane_basis=plane_basis,
                  body=body, body_note=note, candidates=candidates, feature_long=feature_long, transform=view, ecad=ecad,
                  warnings=warnings, snapshot_id=snapshot_id)
    if calls:
        out["calls"] = calls
    return out


# ---------------------------------------------------------------- 항목 길(위치 · 주제)
LOCATION_KEYS: frozenset[str] = frozenset({"part", "point", "set_by", "set_at"})
POINT_KEYS: frozenset[str] = frozenset({"x", "y", "z", "unit"})


def clean_location(raw: Any) -> tuple[dict | None, str | None]:
    """저장된 항목 위치를 쓰기 본문과 같은 엄격한 꼴로 읽는다 — (위치, None) · 없으면 (None, None) · 꼴이 틀리면 (None, 까닭).

    꼴은 {part, point{x, y, z, unit}, set_by, set_at} 이고 규칙은 쓰기 본문(routes.ItemLocationBody · ItemPoint — 모르는 칸 거절 · 좌표는 유한한
    수 · 단위는 mm, 빠지면 mm)과 같다. 들여온 행은 이 박스의 쓰기를 지나지 않아 읽을 때 · 들일 때(export) 다시 본다(반대 검토 F2-9 — 종전에는
    unit inch 를 mm 로 읽었고 y · z 가 없으면 KeyError 로 500 이었다). part 와 point 가 다 비면 위치가 없는 것이다."""
    if raw is None or raw == "":
        return None, None
    value = raw
    if isinstance(raw, (str, bytes)):
        try:
            value = json.loads(raw)
        except ValueError:
            return None, "JSON 이 아니다"
    if not isinstance(value, Mapping):
        return None, "객체가 아니다"
    extra = sorted(str(k) for k in set(value) - LOCATION_KEYS)
    if extra:
        return None, f"모르는 칸 {extra[:5]}"
    part = value.get("part")
    if part is not None:
        if not isinstance(part, str) or len(part) > PATH_MAX:
            return None, "part 가 경로 글이 아니다"
        part = part.strip() or None
    point = value.get("point")
    if point is not None:
        if not isinstance(point, Mapping):
            return None, "point 가 객체가 아니다"
        extra = sorted(str(k) for k in set(point) - POINT_KEYS)
        if extra:
            return None, f"point 에 모르는 칸 {extra[:5]}"
        unit = point.get("unit")
        if str(unit or bt.UNIT).strip().lower() != bt.UNIT:
            return None, f"단위가 mm 가 아니다 — {str(unit)[:20]!r}"
        coords: dict[str, float] = {}
        for axis in "xyz":
            v = point.get(axis)
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
                return None, f"point.{axis} 가 유한한 수(mm)가 아니다"
            coords[axis] = float(v)
        point = {**coords, "unit": bt.UNIT}
    set_by, set_at = value.get("set_by"), value.get("set_at")
    if set_by is not None and not isinstance(set_by, str):
        return None, "set_by 가 글이 아니다"
    if set_at is not None and (isinstance(set_at, bool) or not isinstance(set_at, (int, float))):
        return None, "set_at 이 수가 아니다"
    if part is None and point is None:
        return None, None
    return {"part": part, "point": point, "set_by": set_by, "set_at": set_at}, None


def item_missing(*, finding_id: str | None = None, target_key: str | None = None, cluster_key: str | None = None) -> AppError:
    """그 과제에 없는 항목의 404 — 남의 것 · 못 읽는 비교의 항목도 같은 답이다(존재를 흘리지 않는다)."""
    if finding_id is not None:
        return AppError("E404", f"그 과제에 finding 이 없습니다 — {finding_id}.", 404)
    return AppError("E404", f"그 과제에 등록부 묶음이 없습니다 — {target_key} · {cluster_key}.", 404)


def item_row(store: Any, project: Mapping[str, Any], *, finding_id: str | None, target_key: str | None,
             cluster_key: str | None) -> dict:
    """그 과제(주인의 행)의 항목 하나 — {kind, finding_id | cluster_key, target_key, subject_key, location, location_problem}(위치는
    `clean_location` 으로 읽은 것 — 꼴이 틀리면 None 과 까닭). 없으면 404(남의 과제와 같은 답)."""
    if finding_id is not None:
        row = store.query_one("SELECT finding_id, target_key, subject_key, location_json, owner_sub, project_id FROM rr_findings"
                              " WHERE finding_id = ?", (finding_id,))
        if row is None or row["project_id"] != project["id"] or row["owner_sub"] != project["owner_sub"]:
            raise item_missing(finding_id=finding_id)
        location, problem = clean_location(row["location_json"])
        return {"kind": "finding", "finding_id": row["finding_id"], "target_key": row["target_key"],
                "subject_key": row["subject_key"] or "", "location": location, "location_problem": problem}
    row = store.query_one(
        "SELECT r.cluster_key AS cluster_key, r.target_key AS target_key, r.subject_key AS subject_key, r.location_json AS location_json"
        " FROM rr_registry r JOIN rr_targets t ON t.target_key = r.target_key WHERE r.target_key = ? AND r.cluster_key = ?"
        " AND t.project_id = ? AND r.owner_sub = ? AND t.owner_sub = ?",
        (target_key, cluster_key, project["id"], project["owner_sub"], project["owner_sub"]))
    if row is None:
        raise item_missing(target_key=target_key, cluster_key=cluster_key)
    location, problem = clean_location(row["location_json"])
    return {"kind": "cluster", "cluster_key": row["cluster_key"], "target_key": row["target_key"],
            "subject_key": row["subject_key"] or "", "location": location, "location_problem": problem}


def item_projects(store: Any, target_key: str) -> list[str]:
    """항목 대상이 읽는 과제 — 현황 대상은 그 과제, 비교 대상은 비교의 두 과제(앞 판 과제 포함). 비교의 앞 판 스냅샷은 다른 과제의 것일 수
    있어 위치 찾기 · 항목 위치 쓰기는 두 과제를 다 읽는 사람만 한다(MCP 비교 문 mcp_scope_owner · 웹 _diff_reader 와 같다 — 반대 검토
    F2-9)."""
    target = store.query_one("SELECT kind, ref_id, project_id FROM rr_targets WHERE target_key = ?", (target_key,))
    if target is None:
        return []
    if target["kind"] != "diff":
        return [target["project_id"]]
    diff = store.query_one("SELECT base_project_id, target_project_id FROM rr_diffs WHERE id = ?", (target["ref_id"],))
    projects = [diff["base_project_id"], diff["target_project_id"]] if diff is not None else []
    return sorted({str(p) for p in [*projects, target["project_id"]] if p})


def find_item_part(store: Any, target_key: str, part: str) -> tuple[str, dict] | None:
    """항목 대상의 스냅샷(새 판 먼저)에서 그 몸체 경로의 MCAD 부품 노드 — (snapshot_id, 노드) 또는 None."""
    for sid in item_snapshots(store, target_key):
        ir = _ir(store, sid)
        node = next((n for n in _parts(ir) if str(n.get("local_key") or "") == part), None) if ir is not None else None
        if node is not None:
            return sid, node
    return None


def item_snapshots(store: Any, target_key: str) -> list[str]:
    """항목 대상의 스냅샷 — 현황 대상은 그 스냅샷, 비교 대상은 새 판 먼저 · 앞 판 다음."""
    target = store.query_one("SELECT kind, ref_id FROM rr_targets WHERE target_key = ?", (target_key,))
    if target is None:
        return []
    if target["kind"] == "snap":
        return [target["ref_id"]]
    diff = store.query_one("SELECT base_snapshot_id, target_snapshot_id FROM rr_diffs WHERE id = ?", (target["ref_id"],))
    return [s for s in ((diff["target_snapshot_id"], diff["base_snapshot_id"]) if diff is not None else ()) if s]


def _mcad_answer(node: Mapping[str, Any], snapshot_id: str, ir: Mapping[str, Any], *, input_: dict, project_id: str,
                 warnings: list[str]) -> dict:
    box = _bbox_of(node)
    if box is None:
        return unknown("bbox_world_absent", input=input_, project_id=project_id, snapshot_id=snapshot_id,
                       body={"path": str(node.get("local_key") or "")})
    extents = _extents(box)
    unit = _unit_warning(ir)
    return located(input_=input_, project_id=project_id, stepforge_project_id=_source_ref(ir, "mcad").get("stepforge_project_id"),
                   point=_center(box), extents=extents, plane_basis="body_bbox — 그 몸체 bbox 의 면내 두 변(x · y — 두 단면은 늘 보드 법선 z 를 품는다)",
                   body=_body_of(node, snapshot_id), feature_long=max(extents.values()), warnings=warnings + ([unit] if unit else []),
                   snapshot_id=snapshot_id)


def _interface_answer(pair: Sequence[Mapping[str, Any]], snapshot_id: str, ir: Mapping[str, Any], *, input_: dict, project_id: str,
                      warnings: list[str]) -> dict:
    """계면(몸체 둘) — 두 bbox 가 겹치면(맞닿으면) 그 칸의 가운데와 면내 두 변, 떨어져 있으면 두 가운데의 가운데와 둘을 함께 품는 칸의 면내 두 변."""
    boxes = [_bbox_of(n) for n in pair]
    if boxes[0] is None or boxes[1] is None:
        return unknown("bbox_world_absent", input=input_, project_id=project_id, snapshot_id=snapshot_id)
    a, b = boxes
    lo = [max(a[i], b[i]) for i in range(3)]
    hi = [min(a[i + 3], b[i + 3]) for i in range(3)]
    if all(lo[i] <= hi[i] + CONTAIN_TOL_MM for i in range(3)):
        region = [min(lo[i], hi[i]) for i in range(3)] + [max(lo[i], hi[i]) for i in range(3)]
        point, extents = _center(region), _extents(region)
        basis = "interface_overlap — 두 몸체 bbox 가 겹친(맞닿은) 칸의 가운데와 그 칸의 면내 두 변"
    else:
        ca, cb = _center(a), _center(b)
        point = {k: (ca[k] + cb[k]) / 2 for k in "xyz"}
        extents = _extents([min(a[i], b[i]) for i in range(3)] + [max(a[i + 3], b[i + 3]) for i in range(3)])
        basis = "interface_gap — 두 몸체 bbox 가 떨어져 있어 두 가운데의 가운데, 축은 둘을 함께 품는 칸의 면내 두 변"
    unit = _unit_warning(ir)
    out = located(input_=input_, project_id=project_id, stepforge_project_id=_source_ref(ir, "mcad").get("stepforge_project_id"),
                  point=point, extents=extents, plane_basis=basis, body=None,
                  body_note="interface — 계면이라 몸체가 둘이다(bodies) — F1 에는 점이나 평면을 넘긴다",
                  feature_long=max(extents.values()) or None, warnings=warnings + ([unit] if unit else []), snapshot_id=snapshot_id)
    out["bodies"] = [_body_of(n, snapshot_id) for n in pair]
    return out


def locate_item(store: Any, project: Mapping[str, Any], item: Mapping[str, Any], *, input_: dict, odb_job_id: str | None,
                stepforge_project_id: str | None, channel_factory: Callable[[], Any]) -> dict:
    """항목 → 위치(적혀 있으면) 또는 주제(스냅샷의 노드). 주제가 ECAD 부품이면 보드 길이다."""
    pid = project["id"]
    snapshots = item_snapshots(store, item["target_key"])
    irs = [(sid, ir) for sid, ir in ((sid, _ir(store, sid)) for sid in snapshots) if ir is not None]
    if item.get("location_problem"):
        return unknown("item_location_invalid", message=f"{UNKNOWN['item_location_invalid']} — {item['location_problem']}", input=input_,
                       project_id=pid)
    location = item.get("location") or {}
    if location:
        part = str(location.get("part") or "") or None
        point = location.get("point") if isinstance(location.get("point"), Mapping) else None
        node, node_sid, node_ir = None, None, None
        if part is not None:
            for sid, ir in irs:
                node = next((n for n in _parts(ir) if str(n.get("local_key") or "") == part), None)
                if node is not None:
                    node_sid, node_ir = sid, ir
                    break
        if point is not None:
            box = _bbox_of(node) if node is not None else None
            extents = _extents(box) if box is not None else {"x": 1.0, "y": 0.0}
            basis = ("item_location — 적힌 점, 축은 적힌 몸체 bbox" if box is not None
                     else "item_location — 적힌 점(대상 크기를 몰라 x 를 긴 축으로 둔다)")
            sf = (_source_ref(node_ir, "mcad").get("stepforge_project_id") if node_ir is not None else None) \
                or next((_source_ref(ir, "mcad").get("stepforge_project_id") for _sid, ir in irs if _source_ref(ir, "mcad")), None) \
                or stepforge_project_id
            note, warnings = None, []
            if part is not None and node is None:
                # 적힌 몸체 경로가 항목의 스냅샷에 없다(들여온 행 · 쓰기 확인 전에 적힌 것) — 몸체로 되싣지 않는다(반대 검토 F2-9). 점은 쓴다.
                note = f"item_part_absent — {UNKNOWN['item_part_absent']} — 몸체로 싣지 않고 적힌 점만 쓴다"
                warnings.append(f"item_part_absent — 항목 위치의 몸체 경로 {part[:200]!r} 가 항목의 스냅샷에 없다")
            return located(input_=input_, project_id=pid, stepforge_project_id=sf,
                           point={"x": point["x"], "y": point["y"], "z": point["z"]}, extents=extents,
                           plane_basis=basis, body=_body_of(node, node_sid) if node is not None else None, body_note=note,
                           feature_long=max(extents.values()) if box is not None else None, warnings=warnings, snapshot_id=node_sid)
        if node is None:
            return unknown("item_part_absent", input=input_, project_id=pid, body={"path": part}, snapshots=snapshots)
        return _mcad_answer(node, node_sid, node_ir, input_=input_, project_id=pid, warnings=["item_location — 적힌 몸체"])
    subject = str(item.get("subject_key") or "")
    if not subject or subject.startswith(("asm:", "dim:")):
        return unknown("subject_not_placeable", input=input_, project_id=pid, subject_key=subject)
    if not irs:
        return unknown("snapshot_missing", input=input_, project_id=pid, subject_key=subject)
    ckeys = subject.split("|")
    for sid, ir in irs:
        nodes = [n for n in ir.get("nodes") or () if isinstance(n, Mapping) and n.get("ckey") in ckeys]
        if not nodes:
            continue
        mcad_parts = [n for n in nodes if n.get("domain") == "mcad" and n.get("kind") == "part"]
        if len(ckeys) == 2:
            # 계면 주제는 두 끝 ckey 를 정렬해 이은 것이다(ir_builder._subject_key — IR 엣지에는 그 칸이 없고 rr_ir_edges 에만 있다). 두 끝이
            # 다 MCAD 몸체인 엣지만 본다(part_of · 브리지는 끝이 몸체 둘이 아니다).
            by_nid = {n.get("nid"): n for n in mcad_parts}
            pairs = [(by_nid[e.get("a")], by_nid[e.get("b")]) for e in ir.get("edges") or ()
                     if isinstance(e, Mapping) and e.get("a") in by_nid and e.get("b") in by_nid
                     and "|".join(sorted((str(by_nid[e["a"]].get("ckey")), str(by_nid[e["b"]].get("ckey"))))) == subject]
            unique = list({tuple(sorted((str(p[0].get("nid")), str(p[1].get("nid"))))): p for p in pairs}.values())
            if len(unique) == 1:
                return _interface_answer(unique[0], sid, ir, input_=input_, project_id=pid, warnings=[])
            if len(unique) > 1:
                return unknown("subject_ambiguous", input=input_, project_id=pid, subject_key=subject, snapshot_id=sid,
                               candidates=[[str(n.get("local_key") or "") for n in p] for p in unique[:10]])
            continue
        if len(mcad_parts) == 1:
            return _mcad_answer(mcad_parts[0], sid, ir, input_=input_, project_id=pid, warnings=[])
        if len(mcad_parts) > 1:
            return unknown("subject_ambiguous", input=input_, project_id=pid, subject_key=subject, snapshot_id=sid,
                           candidates=sorted(str(n.get("local_key") or "") for n in mcad_parts)[:10])
        comps = [n for n in nodes if n.get("domain") == "ecad" and n.get("kind") == "component"]
        if len(comps) == 1:
            refdes = str((comps[0].get("attrs") or {}).get("refdes") or comps[0].get("label") or "")
            board = str(_source_ref(ir, "ecad").get("board_id") or "") or odb_job_id
            cad = str(_source_ref(ir, "mcad").get("stepforge_project_id") or "") or stepforge_project_id
            return locate_on_board(store, project, input_={"kind": "refdes", "refdes": refdes}, odb_job_id=board,
                                   stepforge_project_id=cad, channel_factory=channel_factory,
                                   odb_app=_source_app(ir, "ecad") or ODB_APP_KEY, echo={**input_, "via": {"refdes": refdes}})
        if len(comps) > 1:
            return unknown("subject_ambiguous", input=input_, project_id=pid, subject_key=subject, snapshot_id=sid,
                           candidates=sorted(str(n.get("label") or "") for n in comps)[:10])
    return unknown("subject_nodes_absent", input=input_, project_id=pid, subject_key=subject, snapshots=snapshots)


# ---------------------------------------------------------------- 제안의 보드 몸체 후보
def body_candidates(store: Any, project: Mapping[str, Any], stepforge_project_id: str, size: Sequence[float] | None,
                    thickness: float | None) -> tuple[list[dict], str | None]:
    """ODB 외곽 크기에 면내 두 변이 맞는 CAD 몸체(최근 스냅샷) — 차 작은 것부터. 못 고르면 (빈 목록, 까닭)."""
    if size is None:
        return [], "ODB 외곽 크기를 읽지 못해 몸체 후보를 고르지 않았다"
    found = cad_snapshot(store, project["id"], project["owner_sub"], stepforge_project_id)
    if found is None:
        return [], "이 CAD 과제를 읽은 스냅샷이 과제에 없어 몸체 후보를 고르지 않았다 — board_body_path 를 직접 준다"
    snapshot_id, ir = found["snapshot_id"], found["ir"]
    want = sorted((float(size[0]), float(size[1])), reverse=True)
    out = []
    for node in _parts(ir):
        box = _bbox_of(node)
        if box is None:
            continue
        e = _extents(box)
        if not (e["z"] < e["x"] and e["z"] < e["y"]):
            continue
        got = sorted((e["x"], e["y"]), reverse=True)
        error = max(abs(got[0] - want[0]), abs(got[1] - want[1]))
        if error <= BODY_CANDIDATE_TOL_MM:
            out.append({"path": str(node.get("local_key") or ""), "label": node.get("label"), "error_mm": round(error, bt.DIGITS),
                        "thickness_mm": round(e["z"], bt.DIGITS),
                        "thickness_diff_mm": None if thickness is None else round(e["z"] - float(thickness), bt.DIGITS),
                        "snapshot_id": snapshot_id})
    out.sort(key=lambda c: (c["error_mm"], abs(c["thickness_diff_mm"] or 0.0), c["path"]))
    return out[:CANDIDATES_MAX], None if out else "ODB 외곽 크기에 맞는 몸체가 스냅샷에 없다"
