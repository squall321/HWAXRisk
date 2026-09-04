# 결정론 유틸 — canonical_json·sha256_hex·R(반올림 규칙 §2.11)·now_epoch·new_uuid 와 참조 문법(§0.2.1) 파서 make_ref·parse_ref
from __future__ import annotations

import hashlib
import json
import math
import re
import time
import uuid
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Callable

__all__ = [
    "canonical_json",
    "sha256_hex",
    "R",
    "ROUNDING",
    "now_epoch",
    "set_clock",
    "new_uuid",
    "REF_SCHEMES",
    "make_ref",
    "parse_ref",
]


# ---------------------------------------------------------------- 정규 직렬화·해시(plan §2.11.1)
def canonical_json(obj: Any) -> str:
    """키 정렬·구분자 (',', ':')·ensure_ascii=False·NaN 금지의 정규 JSON 문자열.

    같은 입력이면 언제나 같은 바이트가 나와야 하므로 dict 순서를 정렬로 없애고 공백을 빼며,
    NaN·Infinity 는 JSON 이 아니므로 ValueError 로 드러낸다(강등이 아니라 데이터 오류다).
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def sha256_hex(text: str | bytes) -> str:
    """UTF-8 로 인코딩한 텍스트의 sha256 소문자 hex(64자)."""
    data = text if isinstance(text, bytes) else text.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------- 반올림 규칙 R(plan §2.11.1)
# 값은 이미 정규 단위(길이 mm · 응력 MPa · 가속도 G)로 환산돼 있다고 본다. 단위 환산은 어댑터의 몫이다.
# 소수 자릿수로 끊는 kind.
_DECIMALS: dict[str, int] = {
    "length": 3,      # 길이 0.001 mm
    "ratio": 3,       # 비율 0.001
    "alignment": 3,   # 정렬도 0.001
    "fs": 2,          # fs 0.01
    "stress": 1,      # 응력 0.1 MPa
    "acceleration": 1,  # 가속도 0.1 G
}
# 유효자리로 끊는 kind.
_SIGFIGS: dict[str, int] = {
    "area": 4,        # 면적 4 유효자리
    "volume": 4,      # 부피 4 유효자리
}
# 사람이 읽는 규칙표(테스트·문서가 참조한다).
ROUNDING: dict[str, tuple[str, int]] = {
    **{k: ("decimals", v) for k, v in _DECIMALS.items()},
    **{k: ("sigfigs", v) for k, v in _SIGFIGS.items()},
}


def _to_decimal(value: float | int) -> Decimal:
    """float 의 2진 표기 잡음을 repr 로 끊어 Decimal 로 옮긴다(0.1 이 0.1 로 들어간다)."""
    if isinstance(value, int):
        return Decimal(value)
    if not math.isfinite(value):
        raise ValueError(f"R(): 유한하지 않은 값은 반올림할 수 없습니다 — {value!r}.")
    return Decimal(repr(value))


def _unsign_zero(x: float) -> float:
    """-0.0 을 0.0 으로 접는다(canonical_json 이 '-0.0' 과 '0.0' 을 다르게 쓰기 때문)."""
    return 0.0 if x == 0 else x


def R(value: Any, kind: str) -> Any:
    """plan §2.11.1 의 반올림 규칙. 길이 0.001 mm · 면적/부피 4 유효자리 · 비율/정렬도 0.001 · fs 0.01 · 응력 0.1 MPa · 가속도 0.1 G.

    문자열·bool 은 원문 그대로, None 은 None 이다. 숫자가 아닌 다른 타입도 원문 그대로 돌려준다.
    반올림은 ROUND_HALF_UP(사람이 읽는 표기와 같은 방향)이고 같은 입력이면 언제나 같은 값이 나온다.
    kind 를 모르면 ValueError 다(오타를 조용히 통과시키면 ir_hash 가 흔들린다).
    """
    if kind not in ROUNDING:
        raise ValueError(f"R(): 모르는 kind — {kind!r}. 허용 {sorted(ROUNDING)}.")
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        return value
    d = _to_decimal(value)
    if kind in _DECIMALS:
        q = Decimal(1).scaleb(-_DECIMALS[kind])
        return _unsign_zero(float(d.quantize(q, rounding=ROUND_HALF_UP)))
    digits = _SIGFIGS[kind]
    if d == 0:
        return 0.0
    q = Decimal(1).scaleb(d.adjusted() - digits + 1)
    return _unsign_zero(float(d.quantize(q, rounding=ROUND_HALF_UP)))


# ---------------------------------------------------------------- 시계·id
def _default_clock() -> int:
    return int(time.time())


_clock: Callable[[], int] = _default_clock


def now_epoch() -> int:
    """현재 epoch 초(int). 테스트가 set_clock 으로 고정할 수 있다."""
    return int(_clock())


def set_clock(fn: Callable[[], int] | None) -> Callable[[], int]:
    """now_epoch 이 쓰는 시계를 갈아끼운다(None 이면 실제 시계로 복원). 이전 시계를 돌려준다."""
    global _clock
    previous = _clock
    _clock = (lambda: int(time.time())) if fn is None else fn
    return previous


def new_uuid() -> str:
    """앱 DB id 형식 — uuid4 의 hex 32자(plan §0.2.2)."""
    return uuid.uuid4().hex


# ---------------------------------------------------------------- 참조 문법(plan §0.2.1)
# 스킴 이름 → 파싱 결과 dict 의 키(문서 순서). 파서는 대괄호 유무를 모두 받는다.
REF_SCHEMES: tuple[str, ...] = (
    "p", "e", "c", "d", "name", "tool", "card", "narr", "reg", "warn", "gate", "sig", "rule", "req", "rpt", "inc",
)

_HEX12 = re.compile(r"^[0-9a-f]{12}$")
_GATE = re.compile(r"^G(\d+)$")


def parse_ref(text: str) -> dict | None:
    """참조 문자열 하나를 dict 로 푼다. 참조로 읽히지 않으면 None 이다(예외가 아니다).

    산문 표기의 대괄호는 있어도 없어도 받는다. 결과에는 항상 `kind`(스킴)와 `ref`(대괄호 없는 정규 표기)가 있고,
    나머지 키는 스킴마다 다르다 — p·e·c 는 `id`, d 는 `name`, name 은 `a`·`b`, tool 은 `call_id` 또는
    `conv_id`·`idx`, card 는 `record_id`, narr 은 `opinion_id`·`finding_id` 또는 `character_id`,
    reg 는 `target_key`·`cluster_key`, warn 은 `code`·`ref_to`, gate 는 `gate`·`n`, sig 는 `key`,
    rule 은 `rule_id`, rpt 는 `report_id`, inc 는 `object_id` 다.
    존재 검증은 하지 않는다 — 실재하지 않는 참조는 호출자가 dangling 으로 표기한다(§0.2.1 규칙 (2)).
    """
    if not isinstance(text, str):
        return None
    s = text.strip()
    if s.startswith("[") and s.endswith("]"):
        s = s[1:-1].strip()
    if ":" not in s:
        return None
    scheme, rest = s.split(":", 1)
    if scheme not in REF_SCHEMES or not rest:
        return None

    if scheme in ("p", "e", "c"):
        if not _HEX12.match(rest):
            return None
        return {"kind": scheme, "id": rest, "ref": f"{scheme}:{rest}"}
    if scheme == "d":
        return {"kind": "d", "name": rest, "ref": f"d:{rest}"}
    if scheme == "name":
        if "|" not in rest:
            return None
        a, b = rest.split("|", 1)
        if not a or not b:
            return None
        return {"kind": "name", "a": a, "b": b, "ref": f"name:{rest}"}
    if scheme == "tool":
        if rest.startswith("conv:"):
            body = rest[len("conv:"):]
            if "#" not in body:
                return None
            conv_id, idx = body.rsplit("#", 1)
            if not conv_id or not idx.isdigit():
                return None
            return {"kind": "tool", "conv_id": conv_id, "idx": int(idx), "ref": f"tool:conv:{conv_id}#{idx}"}
        return {"kind": "tool", "call_id": rest, "ref": f"tool:{rest}"}
    if scheme == "card":
        return {"kind": "card", "record_id": rest, "ref": f"card:{rest}"}
    if scheme == "narr":
        if "#" in rest:
            opinion_id, finding_id = rest.split("#", 1)
            if not opinion_id or not finding_id:
                return None
            return {"kind": "narr", "opinion_id": opinion_id, "finding_id": finding_id, "ref": f"narr:{rest}"}
        return {"kind": "narr", "character_id": rest, "ref": f"narr:{rest}"}
    if scheme == "reg":
        if "#" not in rest:
            return None
        target_key, cluster_key = rest.rsplit("#", 1)
        if not target_key or not cluster_key:
            return None
        return {"kind": "reg", "target_key": target_key, "cluster_key": cluster_key, "ref": f"reg:{rest}"}
    if scheme == "warn":
        # warnings 항목은 대상 ref 를 못 갖는 경우가 있어 `warn:<code>` 도 받는다(ref_to=None).
        code, ref_to = rest.split("#", 1) if "#" in rest else (rest, None)
        if not code or ref_to == "":
            return None
        return {"kind": "warn", "code": code, "ref_to": ref_to, "ref": f"warn:{rest}"}
    if scheme == "gate":
        m = _GATE.match(rest)
        if not m:
            return None
        return {"kind": "gate", "gate": rest, "n": int(m.group(1)), "ref": f"gate:{rest}"}
    if scheme == "sig":
        return {"kind": "sig", "key": rest, "ref": f"sig:{rest}"}
    if scheme == "rule":
        return {"kind": "rule", "rule_id": rest, "ref": f"rule:{rest}"}
    if scheme == "req":
        # 요구 참조(§0.2.1) — 이름만 담는다. 마지막 줄이 catch-all `inc:` 라 분기를 빠뜨리면
        # `req:` 가 조용히 사고 참조로 읽혀 등급이 곧장 `측정` 으로 튄다.
        if not rest:
            return None
        return {"kind": "req", "name": rest, "ref": f"req:{rest}"}
    if scheme == "rpt":
        return {"kind": "rpt", "report_id": rest, "ref": f"rpt:{rest}"}
    return {"kind": "inc", "object_id": rest, "ref": f"inc:{rest}"}


def make_ref(kind: str, **parts: Any) -> str:
    """참조 문자열을 조립한다(대괄호 없음 — 산문에 넣을 때 호출자가 감싼다).

    받는 인자는 parse_ref 결과의 키와 같다. `name` 은 정렬 무관이므로 두 이름을 정렬해 담는다(같은 계면이면 같은 문자열).
    형식이 어긋나면 ValueError 다.
    """
    def need(key: str) -> str:
        value = parts.get(key)
        if value is None or str(value) == "":
            raise ValueError(f"make_ref({kind!r}): {key} 가 필요합니다.")
        return str(value)

    if kind in ("p", "e", "c"):
        ident = need("id")
        if not _HEX12.match(ident):
            raise ValueError(f"make_ref({kind!r}): id 는 12자리 소문자 hex 여야 합니다 — {ident!r}.")
        ref = f"{kind}:{ident}"
    elif kind == "d":
        ref = f"d:{need('name')}"
    elif kind == "name":
        a, b = sorted([need("a"), need("b")])
        ref = f"name:{a}|{b}"
    elif kind == "tool":
        if "conv_id" in parts:
            ref = f"tool:conv:{need('conv_id')}#{int(parts['idx'])}"
        else:
            ref = f"tool:{need('call_id')}"
    elif kind == "card":
        ref = f"card:{need('record_id')}"
    elif kind == "narr":
        if "character_id" in parts:
            ref = f"narr:{need('character_id')}"
        else:
            ref = f"narr:{need('opinion_id')}#{need('finding_id')}"
    elif kind == "reg":
        ref = f"reg:{need('target_key')}#{need('cluster_key')}"
    elif kind == "warn":
        ref_to = parts.get("ref_to")
        ref = f"warn:{need('code')}" + (f"#{ref_to}" if ref_to else "")
    elif kind == "gate":
        gate = str(parts.get("gate") or f"G{parts.get('n')}")
        if not _GATE.match(gate):
            raise ValueError(f"make_ref('gate'): G<n> 형식이어야 합니다 — {gate!r}.")
        ref = f"gate:{gate}"
    elif kind == "sig":
        ref = f"sig:{need('key')}"
    elif kind == "rule":
        ref = f"rule:{need('rule_id')}"
    elif kind == "rpt":
        ref = f"rpt:{need('report_id')}"
    elif kind == "inc":
        ref = f"inc:{need('object_id')}"
    else:
        raise ValueError(f"make_ref(): 모르는 kind — {kind!r}. 허용 {list(REF_SCHEMES)}.")

    if parse_ref(ref) is None:
        raise ValueError(f"make_ref({kind!r}): 만들어진 참조를 되읽을 수 없습니다 — {ref!r}.")
    return ref
