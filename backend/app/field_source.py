# 브리프 E10 의 외부 근거 조회 채널 — 게이트웨이 MCP 호출과 rr_brief_calls 24 h 재사용(plan §5.6.2)
from __future__ import annotations

import gzip
import time
from collections.abc import Mapping
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

    def __init__(self, mcp: Any, *, timeout: float | None = None, reuse_s: int | None = None) -> None:
        self.mcp = mcp
        self.timeout = float(timeout if timeout is not None else 5.0)
        self.reuse_s = int(reuse_s if reuse_s is not None else 24 * 3600)

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
            reply = self.mcp.call(tool, dict(args))
        except Exception as exc:                      # noqa: BLE001 — 채널 오류는 그 줄만 빼는 사유다.
            self._record(store, target_key, owner_sub, tool, args, args_hash, None,
                         ok=False, error=f"{type(exc).__name__}", started=started)
            return None
        ok = bool(reply.get("ok")) if isinstance(reply, Mapping) else False
        result = reply.get("result") if isinstance(reply, Mapping) else None
        self._record(store, target_key, owner_sub, tool, args, args_hash, result,
                     ok=ok, error=None if ok else _error_of(reply), started=started)
        return result if ok else None

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
        store.execute(
            "INSERT OR REPLACE INTO rr_brief_calls(call_id, target_key, owner_sub, tool, app_key, args_json,"
            " args_hash, ok, result_gz, result_bytes, sha256, fetched_at, duration_ms, error)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (_call_id(target_key, tool, args_hash), target_key, owner_sub, tool,
             APP_KEY_BY_TOOL.get(tool), canonical_json(dict(args)), args_hash, 1 if ok else 0,
             blob, len(raw.encode()) if ok else None, sha256_hex(raw) if ok else None,
             now_epoch(), int((time.monotonic() - started) * 1000), error))


def from_settings(settings=None, *, portal_pat: str | None = None, http_client: Any = None):
    """읽기 PAT 로 게이트웨이 MCP 채널을 만든다. PAT 가 없으면 None(조회 채널 없음)."""
    from app.ra_client import McpHttpClient      # noqa: PLC0415 — 순환 import 회피.

    cfg = config.settings if settings is None else settings
    token = portal_pat or config.load_secrets(cfg.data_dir).get("HWAXRISK_PORTAL_PAT")
    if not token:
        return None
    return FieldSource(McpHttpClient(getattr(cfg, "gateway_mcp", ""),
                                     headers={"Authorization": f"Bearer {token}"},
                                     client=http_client, timeout=FIELD_TIMEOUT_S),
                       timeout=FIELD_TIMEOUT_S)


# ---------------------------------------------------------------- 작은 도구
def _call_id(target_key: str, tool: str, args_hash: str) -> str:
    """브리프 호출 id — `(타깃, 도구, 인자)` 하나당 한 행이다.

    패널 채번(`<panel_id[:8]>-<seq:03d>`)과 겹치지 않게 `b-` 접두를 쓴다. 시각을 섞지 않는 이유는 둘이다 —
    같은 초에 다시 부르면 UNIQUE 가 터지고, 행이 쌓이면 `voc:` 참조가 어느 행을 가리키는지 모호해진다.
    24 h 창이 지나 다시 부르면 그 행을 새 원문으로 갱신한다.
    """
    return f"b-{sha256_hex(f'{target_key}|{tool}|{args_hash}')[:24]}"


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
