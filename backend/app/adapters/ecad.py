# ODB 허브 → rr_ir(ecad) 1단계 어댑터 — 게이트웨이 백엔드 odb-hub 의 지금 도구를 원래 이름으로 찾아 보드 · 적층 · 분류된 부품을 싣고, 좌표 · 넷은 2단계라 표지로 남긴다(포털 docs/design-risk-review/ecad-1031 부록 A)
"""ODB 허브 1단계(요청서 ER-01 ~ ER-05, 사용자 결정 D-1 = 가).

계약 4도구(`odb_get_board` 등)는 어디에도 없다 — 허브는 게이트웨이 백엔드 `odb-hub` 로 도구 39개를 낸다. 이 어댑터는 그
가운데 여섯을 원래 이름으로 찾아(`base.backend_tool_name` — 이름이 겹치면 `odbhub_` 접두) 보드 1장을 이렇게 읽는다.

- `find_job` 1 — 보드가 있는지 · 이름(project · model · board_type · revision). 이것이 필수 호출이다.
- `get_board_layers` 1 · `check_job_stackup` 1 — 적층(5종으로 거른 layer 노드) · 두께 · 판정 · 표준 적층의 재료.
- `get_volume_result` 1 — 외곽 폭 · 높이 · 면적 · 배치 수 · 면마다 큰 부품 10개의 높이.
- `get_odb_download` 1 — 원본 sha256(source_hash).
- `list_parts` 100행씩 — 분류된 부품(component 노드, 좌표 · 넷 없이).

보드 1장은 소스 1건이면서 board 노드 1건이다(요청서 ER-03 · 4절) — ir_hash 는 노드 · 엣지만 보므로 보드의 정체(job_id ·
판 · 원본 해시)가 노드에 없으면 배치 · 배선만 바꾼 판으로 바꿔 붙였을 때 앞 판의 스냅샷이 재사용으로 돌아온다.

못 채우는 칸은 지어내지 않고 `degraded` 표지로 남긴다(ER-04). 단위는 허브가 mm 로 맞춰 준다(층 두께만 µm 로 오고 여기서 mm 로
바꾼다 — rr_ir 의 길이 단위는 mm 다).
"""
from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

from app.adapters.base import AdapterResult, CallRecorder, Principal, Probe, SourceAdapter, backend_tool_name
from app.common import now_epoch
from app.errors import AppError

KIND = "ecad"
# 1단계 매핑(요청서 부록 A)의 세대. 2단계(좌표 · 넷)가 붙으면 올린다 — 같은 보드라도 실리는 칸이 달라진다.
ADAPTER_VERSION = "1.0"
# 보드를 싣지 못한 소스의 세대 — 스텁 시절과 같은 값이다. 노드를 하나도 만들지 않은 소스에는 매핑표가 없고, 값을 바꾸면 스텁
# 시절 스냅샷과의 모든 비교에 parser_differs 가 붙는다(diff.comparability 의 adapter_parity 는 공통 kind 전부를 본다).
ABSENT_VERSION = "0.0-stub"
# 게이트웨이 백엔드 키(HWAXMcpGateway provision-config 의 `odb-hub`) — 소스 카드의 app_key 가 비면 이것이다.
DEFAULT_APP_KEY = "odb-hub"
# 1단계에 필요한 원래 이름 — 하나라도 그 백엔드에 없으면 캡처하지 않는다(발견 status 도 unavailable).
REQUIRED_TOOLS: tuple[str, ...] = (
    "find_job", "get_board_layers", "check_job_stackup", "get_volume_result", "get_odb_download", "list_parts",
)
# odb-hub 의 job_id 는 16자리 16진이다(원본 sha256 앞 16자리 — 부록 A).
JOB_ID_RE = re.compile(r"^[0-9a-fA-F]{16}$")
# list_parts 는 page_size 를 얼마로 줘도 100 으로 줄인다(부록 B — 5000 이 100 으로 왔다).
PARTS_PAGE_SIZE = 100
# 컴포넌트 총 상한(계약 §2.5.3) — 넘으면 앞의 것만 싣고 components_truncated 다.
MAX_COMPONENTS = 2000
# board 노드 — 보드 1장에 1건이다. label 은 판이 바뀌어도 같은 값이라 쌍 비교가 두 판의 보드를 이름으로 맞춘다(same-as 5단계).
# local_key 는 job_id 다 — ecad↔mcad 이름 대응은 refdes · local_key 토큰이 상대 이름과 겹쳐야 하므로 'PCB' 라는 mcad 부품과
# 저절로 묶이지 않는다.
BOARD_CANON_KEY = "ecad:board"
BOARD_LABEL = "board"
# find_job 은 10개까지 준다(부록 A) — 찾기 답도 이 수를 넘기지 않는다.
SEARCH_MAX = 10
# get_board_layers.layers[].type → layer 노드 type(§2.3 의 5종). 나머지(부품 · 페이스트 · 드릴 · 문서 층)는 뺀다.
LAYER_TYPES: dict[str, str] = {
    "SIGNAL": "signal", "POWER_GROUND": "plane", "DIELECTRIC": "dielectric",
    "SOLDER_MASK": "soldermask", "SILK_SCREEN": "silkscreen",
}
COPPER_TYPES: tuple[str, ...] = ("SIGNAL", "POWER_GROUND")
# 보드 층 type → 표준 적층(check_job_stackup.layers[].kind) 구분. 실크 층은 표준 적층에 없다.
STACKUP_KIND: dict[str, str] = {
    "SOLDER_MASK": "solderresist", "SIGNAL": "signal", "POWER_GROUND": "signal", "DIELECTRIC": "dielectric",
}
# 응답 계약(§2.13.1) — 맨이름 키이고 이 어댑터의 호출에만 쓴다(StepForge `list_parts` 의 계약과 섞이지 않는다).
# find_job 은 봉투 열쇠가 부록 A 에 없어 계약을 두지 않는다(`job_rows` 가 알려진 꼴만 읽고, 못 읽으면 드리프트로 적는다).
RESPONSE_CONTRACT: dict[str, dict[str, str]] = {
    "get_board_layers": {"/layers": "array"},
    "check_job_stackup": {"/verdict": "string"},
    "get_volume_result": {"/board": "object"},
    "get_odb_download": {"/sha256": "string"},
    "list_parts": {"/rows": "array", "/total": "number"},
}
# 찾기 후보에 옮기는 잡 칸 — 사람이 같은 모델의 다른 판을 가를 수 있게 올린 시각 · 파일 이름까지 싣는다.
CANDIDATE_KEYS: tuple[str, ...] = (
    "job_id", "project", "model", "board_type", "revision", "original_filename", "uploaded_at",
)
# find_job 응답에서 후보 목록을 찾는 열쇠(앞의 것이 먼저) — list_jobs 는 `jobs` 다(허브 레퍼런스 4.2).
JOB_LIST_KEYS: tuple[str, ...] = ("jobs", "matches", "results", "items")


# ---------------------------------------------------------------- 값 다듬기
def _s(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _num(value: Any) -> float | None:
    """수치 결측은 null 이지 0 이 아니다(plan §2.1 4)."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    number = _num(value)
    return int(number) if number is not None and number.is_integer() else None


def _rows(payload: Any, key: str) -> list[dict]:
    rows = payload.get(key) if isinstance(payload, Mapping) else None
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        return []
    return [dict(r) for r in rows if isinstance(r, Mapping)]


def body_error(payload: Any) -> str | None:
    """허브의 봉투형 오류 — 200 응답 안의 `{"error": …, "hint": …}`(예외가 아니다, 허브 레퍼런스 3절). 아니면 None."""
    if not isinstance(payload, Mapping) or not payload.get("error"):
        return None
    hint = _s(payload.get("hint"))
    return _s(payload["error"]) + (f" — {hint}" if hint else "")


def board_name(job: Mapping[str, Any]) -> str | None:
    """보드 이름 — project · model · board_type · revision 을 엮는다(부록 A). job_name · step_name 은 쓰지 않는다(최근 100건 가운데
    37건 · 58건이 같은 기본값이다). 넷이 다 비면 지어내지 않고 None 이다."""
    parts = [_s(job.get(key)) for key in ("project", "model", "board_type", "revision")]
    return " / ".join(p for p in parts if p) or None


def job_rows(payload: Any) -> list[dict] | None:
    """find_job 응답의 잡 행. 봉투 열쇠가 부록 A 에 없어 알려진 꼴(`JOB_LIST_KEYS` · 맨 목록 · 잡 하나)만 읽는다 — 못 읽으면 None."""
    if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes)):
        return [dict(r) for r in payload if isinstance(r, Mapping)]
    if not isinstance(payload, Mapping):
        return None
    for key in JOB_LIST_KEYS:
        rows = payload.get(key)
        if isinstance(rows, Sequence) and not isinstance(rows, (str, bytes)):
            return [dict(r) for r in rows if isinstance(r, Mapping)]
    if _s(payload.get("job_id")):
        return [dict(payload)]
    return None


def candidate_of(row: Mapping[str, Any]) -> dict:
    """찾기 후보 한 줄 — 허브 칸을 그대로 옮기고 이름만 엮는다."""
    out = {key: row.get(key) for key in CANDIDATE_KEYS}
    out["job_id"] = _s(row.get("job_id")) or None
    out["name"] = board_name(row)
    return out


# ---------------------------------------------------------------- 보드 찾기(ER-01 — 사람이 고른다)
def pat_absent_error(app_key: str | None = None) -> AppError:
    """그 사람의 포털 PAT 가 없어(없음 · 폐기 · 풀리지 않음 · 곧 끝남) ODB 허브를 부르지 않는다 — 409 `ecad_pat_absent`.

    ECAD 보드의 찾기 · 붙이기 확인 · 캡처는 그 사람의 PAT 로만 부른다(사용자 결정 10-31). 박스 읽기 PAT 로 내려가지 않는다 — odb-hub 는
    사람별 격리가 없고 게이트웨이 plat:odbhub 로만 막혀, 내려가면 그 문을 서비스 계정으로 지난다."""
    return AppError("ecad_pat_absent",
                    "그 사람의 포털 PAT 가 없거나 곧 끝나 ODB 허브를 부르지 않습니다 — ECAD 보드는 그 사람의 PAT 로만 찾고 읽습니다(박스"
                    " 읽기 PAT 로 내려가지 않습니다). 웹 설정 화면에서 포털 PAT 를 등록하거나 Claude 에서 hwax_risk 도구를 다시 불러 자동"
                    " 등록한 뒤 다시 합니다.", 409, detail={"app_key": app_key or DEFAULT_APP_KEY, "fix": "portal_pat"})


def search_boards(channel: Any, tool_map: Mapping[str, str], query: str, *,
                  app_key: str | None = None) -> dict:
    """find_job 한 번을 감싼다 — 후보(최대 `SEARCH_MAX`)와 `truncated` 를 돌려줄 뿐 고르지 않는다(모델 이름만으로 정하지 않는다).

    같은 모델의 다른 판이 함께 나올 수 있어 고르는 것은 사람이다. 허브의 봉투형 오류(찾는 것이 없다 따위)는 실패가 아니라 빈
    후보와 그 글(`hub_message`)이다. 자격 · 도구 · 호출 실패는 까닭을 말하는 409 다. `channel` 은 그 사람의 PAT 로 연 채널이어야 한다
    (routes 가 PAT 를 먼저 본다) — 없으면 `pat_absent_error` 다.
    """
    query = _s(query)
    if not query:
        raise AppError("E100", "찾을 말(query)이 비었습니다 — 과제 · 모델 · 파일 이름이나 job_id 를 줍니다.", 422)
    backend = app_key or DEFAULT_APP_KEY
    if channel is None:
        raise pat_absent_error(backend)
    if not tool_map:
        # 지도를 못 읽은 것과 그 백엔드에 도구가 없는 것은 고칠 곳이 다르다 — 앞은 게이트웨이, 뒤는 ODB 허브 등록이다.
        raise AppError("ecad_gateway_unreadable",
                       "게이트웨이 도구 지도(/tools-map)를 읽지 못해 ODB 허브를 찾지 못합니다 — 게이트웨이가 살아 있는지 본 뒤 다시"
                       " 찾습니다.", 409, detail={"app_key": backend})
    tool = backend_tool_name("find_job", backend, tool_map)
    if tool is None:
        raise AppError("ecad_unavailable",
                       f"게이트웨이에 {backend} 의 find_job 이 없습니다 — ODB 허브가 게이트웨이에 붙어 있는지 운영자가 봅니다.", 409,
                       detail={"app_key": backend, "tools_missing": ["find_job"]})
    reply = channel.call(tool, {"query": query})
    if not reply.get("ok"):
        raise AppError("ecad_unreachable", f"ODB 허브 {tool} 호출이 실패했습니다 — {reply.get('error')}.", 409,
                       detail={"app_key": backend, "tool": tool})
    payload = reply.get("result")
    head = {"query": query, "app_key": backend, "tool": tool}
    message = body_error(payload)
    if message is not None:
        return {**head, "candidates": [], "truncated": False, "hub_message": message}
    rows = job_rows(payload)
    if rows is None:
        raise AppError("ecad_schema_drift", f"ODB 허브 {tool} 응답에서 잡 목록을 읽지 못했습니다(알려진 열쇠 "
                       f"{'·'.join(JOB_LIST_KEYS)} 가 없다).", 409, detail={"app_key": backend, "tool": tool})
    candidates = [candidate_of(r) for r in rows if _s(r.get("job_id"))]
    truncated = bool(isinstance(payload, Mapping) and payload.get("truncated")) or len(candidates) > SEARCH_MAX
    return {**head, "candidates": candidates[:SEARCH_MAX], "truncated": truncated}


# ---------------------------------------------------------------- 적층
def _stackup_materials(rows: Sequence[Mapping[str, Any]], stackup: Mapping[str, Any] | None) -> list[str | None] | None:
    """5종 층 행마다의 재료 — 판정이 standard 이고 표준 적층의 층 구분이 보드 층(실크 제외)과 하나하나 맞을 때만이다.

    재료는 보드 ODB 가 아니라 맞춘 표준 적층에서 온다(부록 A). 수나 구분이 하나라도 어긋나면 자리를 짐작하지 않고 None 이다.
    """
    if not isinstance(stackup, Mapping) or _s(stackup.get("verdict")) != "standard":
        return None
    standard = _rows(stackup, "layers")
    board = [r for r in rows if _s(r.get("type")).upper() != "SILK_SCREEN"]
    if not standard or len(standard) != len(board):
        return None
    for mine, theirs in zip(board, standard):
        if STACKUP_KIND.get(_s(mine.get("type")).upper()) != _s(theirs.get("kind")).lower():
            return None
    materials = iter(_s(r.get("material")) or None for r in standard)
    return [None if _s(r.get("type")).upper() == "SILK_SCREEN" else next(materials) for r in rows]


def _layer_nodes(layers: Mapping[str, Any] | None, stackup: Mapping[str, Any] | None, *, app_key: str,
                 tool: str, call_id: str | None, captured_at: int) -> tuple[list[dict], list[str | None] | None]:
    """get_board_layers.layers[] 를 5종으로 걸러 위에서 아래 순서로 번호(1부터)를 매긴다(부록 A idx)."""
    rows = [r for r in _rows(layers, "layers") if _s(r.get("type")).upper() in LAYER_TYPES]
    materials = _stackup_materials(rows, stackup)
    nodes = []
    for idx, row in enumerate(rows, start=1):
        name = _s(row.get("name")) or f"#{idx}"
        thickness_um = _num(row.get("thickness_um"))
        nodes.append({
            "canon_key": f"ecad:layer:{idx}", "domain": KIND, "kind": "layer", "label": name, "local_key": name,
            "group": None, "status_flags": [],
            "attrs": {
                "idx": idx, "name": name, "type": LAYER_TYPES[_s(row.get("type")).upper()],
                # µm 로 온다(실크 층은 null) — rr_ir 길이 단위 mm 로 옮긴다.
                "thickness": None if thickness_um is None else round(thickness_um / 1000.0, 6),
                "material": materials[idx - 1] if materials is not None else None,
                # 무게 칸은 없다 — 바깥층 두께는 도금을 포함해 원판 동박 무게가 아니다(부록 A).
                "copper_weight": None,
            },
            "provenance": {"adapter": KIND, "app_key": app_key, "tool": tool, "call_id": call_id,
                           "captured_at": captured_at},
        })
    return nodes, materials


# ---------------------------------------------------------------- 결과 조립
def _warn(code: str, message: str, ref: str | None = None, severity: str = "WARNING") -> dict:
    return {"severity": severity, "code": code, "message": message, "ref": ref, "source_kind": KIND}


def absent_result(captured_at: int, *, message: str = "과제에 ECAD 보드가 붙지 않아 ecad 소스를 싣지 않았다.",
                  code: str = "ecad_absent", severity: str = "INFO", board_id: str | None = None,
                  app_key: str | None = None, failed: bool = False, call_ids: Sequence[str] = ()) -> AdapterResult:
    """노드를 하나도 만들지 않은 ecad 소스. 보드가 없으면 스텁 시절과 같은 봉투이고, 붙었는데 못 읽었으면 그 까닭이 경고로 남는다.

    `ecad_capture_failed`(failed)는 필수 호출 find_job 을 불렀는데 실패했거나 그 job_id 가 없을 때만이다(§2.11.3 표). 호출 없이
    끝난 것(자격 · 도구 지도 · 도구 없음)은 dyna 의 자격 없음(`dyna_pat_absent`)과 같은 결측 + 경고다. 어느 쪽이든 쌍 비교는
    ECAD 항목에만 효과를 준다(diff.comparability 의 `ecad`)."""
    missing = {"ecad_absent": True}
    if failed:
        missing["ecad_capture_failed"] = True
    return {
        "source": {"kind": KIND, "app_key": app_key, "adapter_version": ABSENT_VERSION,
                   "channel": "mcp" if call_ids else None, "ref": {"board_id": board_id} if board_id else {},
                   "source_hash": None, "degraded": ["ecad_absent"], "captured_at": captured_at},
        "nodes": [], "edges": [],
        "warnings": [_warn(code, message, board_id, severity)],
        "degraded": ["ecad_absent"], "call_ids": list(call_ids), "missing": missing,
    }


class EcadAdapter(SourceAdapter):
    """ODB 허브 보드 1장을 ecad 소스 하나로 읽는다(1단계). 허브에 쓰기는 하지 않는다 — 부르는 도구는 전부 읽기다. 그 사람의 포털 PAT
    채널로만 부른다(사용자 결정 10-31 — 박스 읽기 PAT 의 채널로는 부르지 않는다)."""

    kind = KIND
    version = ADAPTER_VERSION
    required_tools = REQUIRED_TOOLS

    def __init__(self, app_key: str | None = None) -> None:
        self.app_key = app_key

    def discover(self, registry: Any) -> Probe:
        return registry.probe(KIND, self.app_key)

    def capture(self, ref: Mapping[str, Any], principal: Principal | None,
                recorder: CallRecorder | None) -> AdapterResult:
        """ref = {odb_job_id} — 소스 카드는 `PUT /api/projects/{id}/ecad-board` 가 find_job 으로 확인한 뒤에만 적는다.

        recorder 의 게이트웨이 MCP 채널은 캡처의 다른 kind 와 같은 것이다 — mcad · dyna 는 그 사람의 PAT 가 없으면 박스 읽기 PAT 로
        내려가지만 ECAD 는 내려가지 않는다. `principal.mcp_credential` 이 user(그 사람의 PAT)가 아니면 부르지 않고 결측 + 경고
        `ecad_pat_absent` 다(odb-hub 는 사람별 격리가 없고 게이트웨이 plat:odbhub 로만 막힌다)."""
        captured_at = now_epoch()
        job_id = _s((ref or {}).get("odb_job_id"))
        if not job_id:
            return absent_result(captured_at)
        app_key = self.app_key or DEFAULT_APP_KEY
        # 아래 셋은 호출 없이 끝난다 — 보드를 읽으러 가지도 못했으니 결측 + 경고이고 capture_failed 가 아니다(absent_result).
        if recorder is None or not getattr(recorder, "mcp_available", False) \
                or getattr(principal, "mcp_credential", None) != "user":
            return absent_result(captured_at, code="ecad_pat_absent", severity="WARNING", board_id=job_id, app_key=app_key,
                                 message="그 사람의 포털 PAT 가 없거나 곧 끝나 붙은 ECAD 보드를 읽지 않았다 — ECAD 는 그 사람의 PAT"
                                         " 로만 읽는다(박스 읽기 PAT 로 내려가지 않는다).")
        # 이름은 게이트웨이 도구 지도(`/tools-map` 의 map)에서 그 백엔드 것으로만 찾는다 — 지도가 없으면 부르지 않는다
        # (맨이름 `list_parts` 는 다른 앱의 도구일 수 있다). 빈 지도는 게이트웨이를 못 읽은 것이다(도구가 없는 것과 고칠 곳이 다르다).
        tool_map = getattr(recorder, "tool_map", None) or {}
        if not tool_map:
            return absent_result(captured_at, code="ecad_gateway_unreadable", severity="WARNING", board_id=job_id,
                                 app_key=app_key, message="게이트웨이 도구 지도(/tools-map)를 읽지 못해 붙은 ECAD 보드를 읽지"
                                                          " 않았다 — 게이트웨이가 살아 있는지 본다.")
        names = {want: backend_tool_name(want, app_key, tool_map) for want in REQUIRED_TOOLS}
        missing_tools = [want for want, name in names.items() if name is None]
        if missing_tools:
            return absent_result(captured_at, code="ecad_tools_missing", severity="WARNING", board_id=job_id,
                                 app_key=app_key, message=f"게이트웨이에 {app_key} 의 {'·'.join(missing_tools)} 가 없어 붙은"
                                                          " ECAD 보드를 읽지 않았다.")
        return _capture(job_id, app_key, names, recorder, captured_at)


def _capture(job_id: str, app_key: str, names: Mapping[str, str], recorder: CallRecorder,
             captured_at: int) -> AdapterResult:
    warnings: list[dict] = []
    degraded: set[str] = set()

    def call(want: str, args: Mapping[str, Any]) -> dict:
        return recorder.call("mcp", want, args, source_kind=KIND, app_key=app_key, response_contract=RESPONSE_CONTRACT)

    def optional(want: str, reply: dict) -> Mapping[str, Any] | None:
        """선택 호출의 답 — 호출 실패는 capture_partial(§2.11.3 표), 허브의 봉투형 오류는 그 칸이 허브에 없다는 뜻이라 경고만,
        계약 위반은 schema_drift 다(값을 None 으로 흡수하지 않고 드러낸다)."""
        tool = names[want]
        if not reply["ok"]:
            degraded.add("capture_partial")
            warnings.append(_warn("capture_call_failed", f"{tool} 을 읽지 못했다 — {reply['error']}", reply["call_id"]))
            return None
        body = reply["result"]
        message = body_error(body)
        if message is not None:
            warnings.append(_warn("odb_error_body", f"{tool} 이 값을 주지 않았다 — {message}", reply["call_id"]))
            return None
        if not isinstance(body, Mapping):
            degraded.add("schema_drift")
            warnings.append(_warn("source_schema_drift", f"{tool} 응답이 객체가 아니다.", reply["call_id"]))
            return None
        if reply.get("contract_ok") is False:
            degraded.add("schema_drift")
            warnings.append(_warn("source_schema_drift", f"{tool} 응답에 {', '.join(reply['contract_missing'] or ['?'])}"
                                  " 가 없거나 꼴이 다르다.", reply["call_id"]))
        return body

    # ① find_job — 필수 호출. 못 읽거나 그 job_id 가 없으면 ecad 를 통째로 버린다(§2.11.3 표 '필수 호출 실패').
    found = call("find_job", {"query": job_id})
    if not found["ok"]:
        return absent_result(captured_at, code="capture_call_failed", severity="WARNING", board_id=job_id,
                             app_key=app_key, failed=True, message=f"{names['find_job']} 을 읽지 못했다 — {found['error']}",
                             call_ids=recorder.call_ids(KIND))
    rows = job_rows(found["result"]) if body_error(found["result"]) is None else []
    if rows is None:
        return absent_result(captured_at, code="source_schema_drift", severity="WARNING", board_id=job_id,
                             app_key=app_key, failed=True,
                             message=f"{names['find_job']} 응답에서 잡 목록을 읽지 못했다(알려진 열쇠 "
                                     f"{'·'.join(JOB_LIST_KEYS)} 가 없다).", call_ids=recorder.call_ids(KIND))
    # 후보 가운데 그 job_id 와 같은 행만 쓴다 — 첫 후보나 모델 이름이 같은 행으로 대신하지 않는다(ER-01).
    job = next((r for r in rows if _s(r.get("job_id")).lower() == job_id.lower()), None)
    if job is None:
        hub = body_error(found["result"])
        return absent_result(captured_at, code="ecad_board_not_found", severity="WARNING", board_id=job_id,
                             app_key=app_key, failed=True,
                             message=f"{names['find_job']} 이 붙은 보드 {job_id} 를 찾지 못했다"
                                     + (f" — {hub}" if hub else "") + ".", call_ids=recorder.call_ids(KIND))
    jid = _s(job.get("job_id"))
    name = board_name(job)

    # ②③ 적층 — 층 구성 · 두께(get_board_layers)와 표준 적층 판정 · 재료(check_job_stackup).
    layers_reply = call("get_board_layers", {"job_id": jid})
    layers = optional("get_board_layers", layers_reply)
    stackup = optional("check_job_stackup", call("check_job_stackup", {"job_id": jid}))
    # ④ 외곽 · 배치 수 · 큰 부품 높이.
    volume = optional("get_volume_result", call("get_volume_result", {"job_id": jid}))
    # ⑤ 원본 해시.
    download = optional("get_odb_download", call("get_odb_download", {"job_id": jid}))

    layer_nodes, materials = _layer_nodes(layers, stackup, app_key=app_key, tool=names["get_board_layers"],
                                          call_id=layers_reply["call_id"], captured_at=captured_at)

    # ⑥ 분류된 부품 — 100행씩. 인자는 기본값이라도 다 싣는다(허브 레퍼런스 1절 — 빠진 선택 인자를 거부한 적이 있다).
    parts, parts_read, total, pages = _read_parts(jid, call, optional, names, warnings, degraded)
    heights = _heights(volume)
    component_nodes = []
    for row, call_id in parts:
        refdes = _s(row.get("refdes"))
        side = _s(row.get("side")).lower()
        attrs: dict[str, Any] = {
            "refdes": refdes, "part_number": _s(row.get("part_name")) or None,
            "footprint": _s(row.get("pkg_name")) or None, "side": side,
            # 좌표 · 회전 · 넷은 부품마다 get_part_detail 을 불러야 해 2단계다(ER-06) — 0 이 아니라 null 이다.
            "x": None, "y": None, "rot": None, "pin_count": _int(row.get("pin_count")), "nets": None,
            # 높이는 get_volume_result 의 면마다 큰 부품 10개뿐이다(부록 A). 값(용량 · 저항)은 어느 도구에도 없다.
            "height": heights.get(refdes), "value": None,
        }
        if side not in ("top", "bottom"):
            attrs.pop("side")
            warnings.append(_warn("type_unexpected", f"side={row.get('side')!r}", refdes))
        component_nodes.append({
            "canon_key": f"ecad:{refdes}", "domain": KIND, "kind": "component", "label": refdes, "local_key": refdes,
            "group": side if side in ("top", "bottom") else None, "status_flags": [], "attrs": attrs,
            "provenance": {"adapter": KIND, "app_key": app_key, "tool": names["list_parts"], "call_id": call_id,
                           "captured_at": captured_at},
        })

    placed = _placed(volume)
    board = (volume or {}).get("board") if isinstance((volume or {}).get("board"), Mapping) else {}
    outline = {"x_mm": _num(board.get("x_mm")), "y_mm": _num(board.get("y_mm")),
               "area_mm2": _num(board.get("outline_area_mm2"))} if board else None
    thickness = _num((layers or {}).get("total_thickness_mm"))
    stackup_total = _stackup_total(layer_nodes)
    if thickness is not None and stackup_total is not None and abs(thickness - stackup_total) > 0.001:
        warnings.append(_warn("stackup_total_mismatch", f"5종 층 두께 합 {stackup_total} mm 가 보드 두께 {thickness} mm 와"
                              " 다르다.", jid))
    sha256, size_bytes = _download(download, jid, warnings)

    # ER-04 표지 — 1단계에서 늘 비는 칸과 이번 보드에서 빈 칸.
    degraded.update({"ecad_nets_deferred", "odb_version_absent", "outline_origin_unknown"})
    # 노드 가족이 통째로 빠졌다 — 허브의 봉투형 오류(분석을 돌리지 않은 보드)는 경고만 남기므로 표지가 없으면 빈 가족이 '보드에
    # 그것이 없다' 로 읽힌다. 그 수(stats.layer_rows · n_components)는 미측정(null)이다.
    if not layer_nodes:
        degraded.add("layers_unavailable")
    if not parts_read:
        degraded.add("components_unavailable")
    if component_nodes:
        degraded.update({"component_xy_deferred", "component_value_absent"})
        if any(n["attrs"]["height"] is None for n in component_nodes):
            degraded.add("component_height_partial")
    if parts_read and (placed is None or total is None or placed != total):
        # list_parts 는 분류된 부품만 낸다(저항 · 테스트 포인트 등 category Unknown 은 빠진다 — OH-02). 배치 수와 같다고
        # 확인되지 않으면 빠졌다고 적는다.
        degraded.add("components_unclassified_omitted")
    if placed is not None and total is not None and placed < total:
        # 배치 수는 분류된 부품을 포함하므로 그보다 작을 수 없다 — 그 칸이 배치 수가 아니다(부록 A 는 count, OH-02 는 counted).
        warnings.append(_warn("placed_below_classified", f"get_volume_result 의 면별 배치 수 합 {placed} 이 분류된 부품 수"
                              f" {total} 보다 작다 — 그 칸이 배치 수가 아닐 수 있다(cae00 에서 칸 이름을 확인한다).", jid))
    copper = [n for n in layer_nodes if n["attrs"]["type"] in ("signal", "plane")]
    if copper:
        degraded.add("copper_weight_absent")
        if not any(n["attrs"]["type"] == "plane" for n in copper):
            degraded.add("plane_type_unknown")          # 동박층이 다 SIGNAL 이다 — plane 이 없다는 뜻이 아니다
    if layer_nodes and (materials is None
                        or any(n["attrs"]["material"] is None for n in layer_nodes if n["attrs"]["type"] != "silkscreen")):
        degraded.add("stackup_material_unmatched")

    verdict = _s((stackup or {}).get("verdict")) or _s((layers or {}).get("stackup_verdict")) or None
    stackup_id = _s((stackup or {}).get("chosen_id")) or None
    # 동박층 수 — get_board_layers.layer_count 는 부품 · 실크 · 페이스트 · 드릴 · 문서 층까지 센다(부록 A).
    layer_count = _int((layers or {}).get("signal_layer_count")) or _int((stackup or {}).get("layer_count"))
    stats = {
        "units": "mm",
        "board": {key: job.get(key) for key in ("project", "model", "board_type", "revision")},
        "thickness_mm": thickness,
        "thickness_source": (layers or {}).get("thickness_source"),
        "stackup_verdict": verdict,
        "stackup_id": stackup_id,
        "stackup_total_mm": stackup_total,
        "layer_count": layer_count,
        "layer_rows": len(layer_nodes) if layers is not None else None,
        "layer_rows_all": len(_rows(layers, "layers")) if layers is not None else None,
        "outline": outline,
        "outline_bbox": None,
        # n_components 는 list_parts.total(분류된 부품 = component 노드의 원천)이다. 배치 수(분류 안 된 부품 포함)는 따로 싣는다.
        "n_components": total,
        "n_components_basis": "classified",
        "n_components_placed": placed,
        "n_nets": None,
        "odb_version": None,
        "source_size_bytes": size_bytes,
        "list_parts_pages": pages,
    }
    # board 노드 — 계약 odb_get_board 의 칸(board_id · name · units · outline_bbox · thickness · layer_count · n_components ·
    # n_nets · odb_version · source_hash)과 판정 · 적층 합 · 외곽 폭 · 높이 · 배치 수. 노드라 ir_hash 에 든다 — 보드를 다른 판으로
    # 바꿔 붙이면 1단계 칸(층 · 분류된 부품)이 같아도 새 스냅샷이다. 두께 · 적층 합은 rr_ir 길이 단위 mm 다.
    board_node = {
        "canon_key": BOARD_CANON_KEY, "domain": KIND, "kind": "board", "label": BOARD_LABEL, "local_key": jid,
        "group": None, "status_flags": [],
        "attrs": {
            "board_id": jid, "name": name, "revision": _s(job.get("revision")) or None, "units": "mm",
            "outline_bbox": None, "outline": outline, "thickness": thickness, "stackup_verdict": verdict,
            "stackup_id": stackup_id, "ecad_stackup_total": stackup_total, "layer_count": layer_count,
            "n_components": total, "n_components_placed": placed, "n_nets": None, "odb_version": None,
            "source_hash": sha256,
        },
        "provenance": {"adapter": KIND, "app_key": app_key, "tool": names["find_job"], "call_id": found["call_id"],
                       "captured_at": captured_at},
    }
    source = {
        "kind": KIND, "app_key": app_key, "adapter_version": ADAPTER_VERSION, "channel": "mcp",
        "ref": {"board_id": jid, "name": name}, "source_hash": sha256, "stats": stats,
        "degraded": sorted(degraded), "captured_at": captured_at,
    }
    return {"source": source, "nodes": [board_node] + layer_nodes + component_nodes, "edges": [], "warnings": warnings,
            "degraded": sorted(degraded), "call_ids": recorder.call_ids(KIND), "missing": {"ecad_absent": False}}


def _page_cap(total: int | None) -> int:
    """list_parts 를 부를 쪽 수의 상한 — 실을 수 있는 만큼(total, 모르면 상한 MAX_COMPONENTS)을 100행씩 읽고 한 쪽 여유.
    쪽마다 새 행이 하나씩만 오는 허브가 캡처 예산을 넘겨 수천 번 불리지 않게 한다."""
    want = MAX_COMPONENTS if total is None else min(max(total, 0), MAX_COMPONENTS)
    return -(-want // PARTS_PAGE_SIZE) + 1


def _read_parts(jid: str, call, optional, names: Mapping[str, str], warnings: list[dict],
                degraded: set[str]) -> tuple[list[tuple[dict, str]], bool, int | None, int]:
    """list_parts 를 끝까지 읽는다 — ([(행, call_id)], 첫 쪽을 읽었나, total, 부른 쪽 수). refdes 가 겹치는 행은 앞의 것만 싣는다
    (canon_key 가 `ecad:<refdes>` 라 겹치면 IR 이 서지 않는다).

    다 받았는지는 **서로 다른** 행 수(겹친 refdes 는 한 번, 빈 refdes 는 행마다)로 total 과 견준다 — 쪽 순서가 흔들리는 허브
    (sort 기본값의 offset 쪽 넘김)는 어떤 행을 두 번 주고 어떤 행은 한 번도 주지 않아, 받은 행 수로 세면 빠진 행이 보이지 않는다.
    """
    out: list[tuple[dict, str]] = []
    seen: set[str] = set()
    total: int | None = None
    received = duplicates = blank = reserved = 0
    page = 0
    cap = _page_cap(None)
    first_ok = False
    while True:
        if page >= cap:
            degraded.add("capture_partial")
            warnings.append(_warn("odb_paging_capped", f"{names['list_parts']} 를 {page}쪽에서 멈췄다 — total {total} 의"
                                  f" 쪽 상한 {cap} 에 닿았다(서로 다른 행 {len(seen) + blank} · 받은 행 {received}).", jid))
            break
        page += 1
        reply = call("list_parts", {"job_id": jid, "category": "", "side": "", "sort": "", "page": page,
                                    "page_size": PARTS_PAGE_SIZE})
        body = optional("list_parts", reply)
        if body is None:
            break
        if page == 1:
            first_ok = True
            total = _int(body.get("total"))
            cap = _page_cap(total)
        rows = _rows(body, "rows")
        received += len(rows)
        before = len(seen) + blank
        for row in rows:
            refdes = _s(row.get("refdes"))
            if not refdes:
                blank += 1
                continue
            if refdes in seen:
                duplicates += 1
                continue
            seen.add(refdes)
            if refdes == BOARD_LABEL or refdes.startswith(("layer:", "net:")):
                reserved += 1          # board · layer · net 노드의 canon_key(`ecad:board` · `ecad:layer:…` · `ecad:net:…`)와 겹친다
                continue
            out.append((row, reply["call_id"]))
        has_more = body.get("has_more")
        more = has_more if isinstance(has_more, bool) else (total is not None and received < total)
        if len(out) >= MAX_COMPONENTS:
            if more or (total is not None and total > MAX_COMPONENTS):
                degraded.add("components_truncated")
                warnings.append(_warn("components_truncated", f"부품이 {total} 개라 앞의 {MAX_COMPONENTS} 개만 실었다.", jid))
            out = out[:MAX_COMPONENTS]
            break
        if not more:
            break
        if len(seen) + blank == before:
            # 다음 쪽이 있다는데 새 행이 없다 — 허브가 page 를 듣지 않는 것이다. 같은 쪽을 끝없이 부르지 않는다.
            degraded.add("capture_partial")
            warnings.append(_warn("odb_paging_stalled", f"{names['list_parts']} {page}쪽에 새 행이 없어 멈췄다"
                                  f"(받은 {received} · total {total}).", reply["call_id"]))
            break
    distinct = len(seen) + blank
    if duplicates:
        warnings.append(_warn("duplicate_refdes", f"refdes 가 겹친 행 {duplicates}개는 앞의 것만 실었다 — 허브의 쪽 순서가"
                              " 흔들렸거나 같은 refdes 가 두 번 있다.", jid))
    if blank:
        warnings.append(_warn("refdes_missing", f"refdes 가 빈 행 {blank}개는 싣지 않았다.", jid))
    if reserved:
        warnings.append(_warn("refdes_reserved", f"refdes 가 board · layer: · net: 꼴인 행 {reserved}개는 보드 · 층 · 넷 노드의"
                              " 열쇠와 겹쳐 싣지 않았다.", jid))
    if first_ok and total is not None and distinct < min(total, MAX_COMPONENTS) and "capture_partial" not in degraded \
            and "components_truncated" not in degraded:
        degraded.add("capture_partial")
        warnings.append(_warn("components_incomplete", f"부품 total {total} 가운데 서로 다른 행 {distinct}개만 받았다(받은 행"
                              f" {received} · refdes 가 겹친 행 {duplicates}).", jid))
    return out, first_ok, total, page


def _heights(volume: Mapping[str, Any] | None) -> dict[str, float]:
    """get_volume_result 의 면마다 큰 부품(largest_items) refdes → 평균 높이(mm)."""
    out: dict[str, float] = {}
    for side in ("top", "bottom"):
        block = (volume or {}).get(side)
        for item in _rows(block, "largest_items"):
            height = _num(item.get("height_mean_mm"))
            refdes = _s(item.get("refdes"))
            if refdes and height is not None:
                out.setdefault(refdes, height)
    return out


def _placed(volume: Mapping[str, Any] | None) -> int | None:
    """실제 배치 수(분류 안 된 부품 포함) — get_volume_result 의 top · bottom count 합(부록 A). 요청서 OH-02 는 같은 값을 counted
    라 적었다 — count 가 없을 때만 그것을 본다(cae00 에서 칸 이름을 확인한다). 한쪽이라도 없으면 None 이다."""
    counts = []
    for side in ("top", "bottom"):
        block = (volume or {}).get(side)
        value = None
        if isinstance(block, Mapping):
            value = _int(block.get("count"))
            if value is None:
                value = _int(block.get("counted"))
        counts.append(value)
    return None if any(c is None for c in counts) else sum(counts)


def _stackup_total(layer_nodes: Sequence[Mapping[str, Any]]) -> float | None:
    """5종 층 두께 합(mm) — 실크 층(두께 null)은 빼고, 다른 층에 하나라도 두께가 없으면 합을 짓지 않는다."""
    values = [n["attrs"]["thickness"] for n in layer_nodes if n["attrs"]["type"] != "silkscreen"]
    if not values or any(v is None for v in values):
        return None
    return round(sum(values), 6)


def _download(download: Mapping[str, Any] | None, jid: str, warnings: list[dict]) -> tuple[str | None, int | None]:
    """원본 sha256 · 크기. 64자리 16진이 아니면 해시로 쓰지 않는다. job_id 는 sha256 앞 16자리였다(부록 A) — 다르면 알린다."""
    if download is None:
        return None, None
    sha = _s(download.get("sha256")).lower()
    if not re.fullmatch(r"[0-9a-f]{64}", sha):
        warnings.append(_warn("source_hash_invalid", f"get_odb_download.sha256 이 64자리 16진이 아니다 — {sha[:20]!r}.", jid))
        sha = ""
    elif not sha.startswith(jid.lower()):
        warnings.append(_warn("source_hash_job_mismatch", "원본 sha256 앞 16자리가 job_id 와 다르다.", jid, "INFO"))
    return sha or None, _int(download.get("size_bytes"))
