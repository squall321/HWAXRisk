# 브리프 E10 의 외부 근거 조회 채널 — 게이트웨이 MCP 호출과 rr_brief_calls 24 h 재사용(plan §5.6.2)
from __future__ import annotations

import gzip
import time
from collections.abc import Mapping, Sequence
from typing import Any

from app import config
from app.common import canonical_json, now_epoch, sha256_hex

# 게이트웨이에서 이 도구를 여는 백엔드(2026-09-04 실측 — VOC 5종 signalforge · 문헌 2종 heax-web_research_mcp).
# 이름은 발견으로 풀지 않는다 — E10 은 probe 없이 돌고 백엔드 키는 호출 인자가 아니라 기록용이다.
# 호출마다 개별 데드라인(plan §5.6.2) — 초과는 그 줄만 빠지고 블록 끝에 조회 불가 한 줄이 남는다.
FIELD_TIMEOUT_S = 5.0

APP_KEY_BY_TOOL: dict[str, str] = {
    "get_top_issues": "signalforge",
    "query_voc": "signalforge",
    "search_scholar": "heax-web_research_mcp",
}


class FieldSource:
    """E10 조회 채널. 같은 `(target_key, tool, args)` 는 24 h 안이면 저장된 원문을 그대로 돌려준다.

    실패는 예외가 아니라 `None` 이다 — 그 줄만 빠지고 브리프 조립은 완주한다(plan §5.6.2).
    호출 원문은 `rr_brief_calls` 에 남아 `voc:`·`paper:` 참조의 해석 원장이 된다.
    """

    def __init__(self, mcp: Any, *, timeout: float | None = None, reuse_s: int | None = None,
                 tool_names: Sequence[str] = ()) -> None:
        self.mcp = mcp
        self.timeout = float(timeout if timeout is not None else 5.0)
        self.reuse_s = int(reuse_s if reuse_s is not None else 24 * 3600)
        # 게이트웨이 실이름들(§2.13.2). E10 은 probe 없이 돌아 이름 접두에 특히 취약하다.
        self.tool_names = tuple(tool_names)

    # ------------------------------------------------ 조회
    def fetch(self, store, target_key: str, owner_sub: str, tool: str,
              args: Mapping[str, Any]) -> Any | None:
        """저장된 원문이 창 안이면 그것을, 아니면 한 번 호출해 저장하고 결과를 돌려준다."""
        args_hash = sha256_hex(canonical_json(dict(args)))
        cached = self._cached(store, target_key, tool, args_hash)
        if cached is not None:
            return cached
        started = time.monotonic()
        try:
            # 데드라인은 클라이언트가 가진다(McpHttpClient.call 은 timeout 인자를 받지 않는다) —
            # from_settings 가 그 값으로 클라이언트를 만든다.
            # 호출은 게이트웨이 실이름으로 나가고 **원장에는 맨이름을 적는다.** 캡처 원장
            # (`rr_snapshot_calls`)과 규칙이 다른 이유는 이 표의 `tool` 이 24 h 재사용 키이자
            # `voc:`·`paper:` 해석 키이기 때문이다 — 실이름을 적으면 게이트웨이가 접두를 붙이는 날
            # 캐시가 통째로 무효가 되고 예전 인용이 dangling 이 된다(읽는 쪽은 맨이름으로 찾는다).
            reply = self.mcp.call(_real_name(tool, self.tool_names), dict(args))
        except Exception as exc:                      # noqa: BLE001 — 채널 오류는 그 줄만 빼는 사유다.
            self._record(store, target_key, owner_sub, tool, args, args_hash, None,
                         ok=False, error=f"{type(exc).__name__}", started=started)
            return None
        ok = bool(reply.get("ok")) if isinstance(reply, Mapping) else False
        result = reply.get("result") if isinstance(reply, Mapping) else None
        self._record(store, target_key, owner_sub, tool, args, args_hash, result,
                     ok=ok, error=None if ok else _error_of(reply), started=started)
        return result if ok else None

    def close(self) -> None:
        """자기 httpx.Client 를 닫는다 — 닫지 않으면 브리프 조립마다 소켓이 샌다(capture_all 과 같은 처리)."""
        closer = getattr(self.mcp, "close", None)
        if callable(closer):
            closer()

    # ------------------------------------------------ 원장
    def _cached(self, store, target_key: str, tool: str, args_hash: str) -> Any | None:
        row = store.query_one(
            "SELECT result_gz, ok, fetched_at FROM rr_brief_calls"
            " WHERE target_key = ? AND tool = ? AND args_hash = ? AND ok = 1"
            " ORDER BY fetched_at DESC LIMIT 1", (target_key, tool, args_hash))
        if row is None or now_epoch() - int(row["fetched_at"] or 0) > self.reuse_s:
            return None
        return _unpack(row["result_gz"])

    def _record(self, store, target_key: str, owner_sub: str, tool: str, args: Mapping[str, Any],
                args_hash: str, result: Any, *, ok: bool, error: str | None, started: float) -> None:
        blob = _pack(result) if ok else None
        raw = canonical_json(result) if ok else ""
        row = (_call_id(target_key, tool, args_hash), target_key, owner_sub, tool,
               APP_KEY_BY_TOOL.get(tool), canonical_json(dict(args)), args_hash, 1 if ok else 0,
               blob, len(raw.encode()) if ok else None, sha256_hex(raw) if ok else None,
               now_epoch(), int((time.monotonic() - started) * 1000), error)
        # 성공은 그 행을 새 원문으로 갱신한다. **실패는 덮어쓰지 않는다** — 행이 하나뿐이라
        # REPLACE 하면 `result_gz` 가 NULL 이 되어, 그 원문으로 해석되던 `voc:`·`paper:` 인용이
        # 전부 dangling 으로 뒤바뀌고 등급이 측정→경험칙으로 떨어진다(§0.2.1 (2)). 실패는 캐시
        # 미스일 뿐이고(`_cached` 는 `ok = 1` 만 본다) 브리프에는 `[조회 불가: <tool>]` 로 이미 드러난다.
        verb = "INSERT OR REPLACE" if ok else "INSERT OR IGNORE"
        store.execute(
            f"{verb} INTO rr_brief_calls(call_id, target_key, owner_sub, tool, app_key, args_json,"
            " args_hash, ok, result_gz, result_bytes, sha256, fetched_at, duration_ms, error)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", row)
        if not ok:
            # 성공 행은 건드리지 않고, 실패 행일 때만 마지막 시도 사실을 갱신한다(원장이 거짓말하지 않게).
            store.execute("UPDATE rr_brief_calls SET fetched_at = ?, duration_ms = ?, error = ?"
                          " WHERE call_id = ? AND ok = 0", (row[11], row[12], error, row[0]))


def from_settings(settings=None, *, portal_pat: str | None = None, http_client: Any = None):
    """읽기 PAT 로 게이트웨이 MCP 채널을 만든다. PAT 가 없으면 None(조회 채널 없음)."""
    from app.ra_client import McpHttpClient      # noqa: PLC0415 — 순환 import 회피.

    cfg = config.settings if settings is None else settings
    token = portal_pat or config.load_secrets(cfg.data_dir).get("HWAXRISK_PORTAL_PAT")
    if not token:
        return None
    from app.adapters.registry import gateway_tool_names  # noqa: PLC0415 — 순환 import 회피.

    return FieldSource(McpHttpClient(getattr(cfg, "gateway_mcp", ""),
                                     headers={"Authorization": f"Bearer {token}"},
                                     client=http_client, timeout=FIELD_TIMEOUT_S),
                       timeout=FIELD_TIMEOUT_S,
                       tool_names=gateway_tool_names(token=token, client=http_client))


def for_target(store, target_key: str, *, settings=None, http_client: Any = None):
    """타깃의 E10 조회 채널 — 자격 (b) 타깃 owner 의 포털 PAT, 없으면 (a) 서비스 PAT(plan §0.1.6).

    서비스 PAT 만 쓰면 남의 시야로 도는 셈이다. 시야 밖 응답은 오류가 아니라 **빈 배열**로 와서
    브리프에는 `[필드·문헌 근거 없음 — VOC 0건]` 으로만 보이고, 그 값이 24 h 재사용된다 —
    없는 리스크가 굳는 경로다. 그래서 러너·로스터와 같은 자격 순서를 쓴다.

    (c) 요청자 자격은 이 경로에 없다 — 브리프를 여는 MCP 경로의 `actor` 는 게이트웨이 신고값이고
    미검증이므로(§6.11) 자격 선택에 쓰면 남의 PAT 를 고르게 된다.
    만료 임박한 PAT 는 쓰지 않는다 — 값이 있기만 하면 쓰면 (a) 폴백이 죽어 게이트웨이 401 로 강등된다
    (`runner.resolve_credential`·`roster.credential` 과 같은 규칙).
    """
    from app import identity  # noqa: PLC0415 — 순환 import 회피.
    from app import runner    # noqa: PLC0415 — 만료 여유 상수만 쓴다.

    row = store.query_one("SELECT owner_sub FROM rr_targets WHERE target_key = ?", (target_key,))
    credential = (store.get_credential(row["owner_sub"]) if row else None) or {}
    portal_pat = identity.credential_pat(credential)
    if int(credential.get("pat_exp") or 0) <= now_epoch() + runner.CREDENTIAL_MARGIN_S:
        portal_pat = None
    return from_settings(settings, portal_pat=portal_pat, http_client=http_client)


# ---------------------------------------------------------------- 작은 도구
def _call_id(target_key: str, tool: str, args_hash: str) -> str:
    """브리프 호출 id — `(타깃, 도구, 인자)` 하나당 한 행이다.

    패널 채번(`<panel_id[:8]>-<seq:03d>`)과 겹치지 않게 `b-` 접두를 쓴다. 시각을 섞지 않는 이유는 둘이다 —
    같은 초에 다시 부르면 UNIQUE 가 터지고, 행이 쌓이면 `voc:` 참조가 어느 행을 가리키는지 모호해진다.
    24 h 창이 지나 다시 부르면 그 행을 새 원문으로 갱신한다.
    """
    return f"b-{sha256_hex(f'{target_key}|{tool}|{args_hash}')[:24]}"


def _real_name(want: str, names: Sequence[str]) -> str:
    """맨이름 → 게이트웨이 실이름. 어댑터와 같은 규칙을 쓴다(§2.13.2)."""
    from app.adapters.base import resolve_tool_name  # noqa: PLC0415 — 순환 import 회피.

    return resolve_tool_name(want, names) if names else want


def _pack(result: Any) -> bytes:
    return gzip.compress(canonical_json(result).encode("utf-8"))


def _unpack(blob: Any) -> Any | None:
    if not blob:
        return None
    import json                                  # noqa: PLC0415 — 해제 경로에서만 쓴다.

    try:
        return json.loads(gzip.decompress(blob).decode("utf-8"))
    except (OSError, ValueError):
        return None


def _error_of(reply: Any) -> str:
    if isinstance(reply, Mapping):
        return str(reply.get("error") or "not_ok")
    return "malformed_reply"
