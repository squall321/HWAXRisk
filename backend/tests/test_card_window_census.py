# 카드 창 측정 스크립트(backend/scripts/card_window_census.py) — 가짜 AIDataHub 를 루프백에 띄우고 실제 엔진 식으로 센 값을 본다
"""B32(포털 docs/leftovers-1017/triage-1031.md · risk-200k 체크리스트 7줄).

스크립트는 하위 프로세스로 돌린다 — 엔진 모듈(형제 리포 HWAXAgentServer 의 card_review)을 그 프로세스만 들이므로 이 시험 세션의
sys.path · sys.modules 가 엔진 이름으로 섞이지 않는다. AIDataHub 는 이 시험이 띄운 루프백 서버라 dev 의 실 서비스(8001)를 부르지 않는다.
엔진 리포가 곁에 없으면(SIF 빌드) 건너뛴다 — 곁에 있는데 건너뛰면 건너뜀 예산이 붉힌다(tests/skip_budget.py SIBLING_ONLY).

합성 명단 — alpha 는 지식카드 셋(하나는 faq 라 배경)과 14만 자 논문 하나, beta 는 13,000자 지식카드 둘(합이 20만 입력 결손 몫
24,648자를 넘는다), gamma 는 기록 0건, unrender 는 절 없는 카드 하나, ghost 는 명단에만 있고 기록 경로가 404 다.
"""
from __future__ import annotations

import json
import os
import random
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote

import pytest

from tests.conftest import BACKEND_DIR, REPO_ROOT

SCRIPT = BACKEND_DIR / "scripts" / "card_window_census.py"
ENGINE = REPO_ROOT.parent / "HWAXAgentServer"
CARD = "expert_knowledge_card"
API_KEY = "fake-aidh-key-not-real"           # 명백한 가짜 — 실 키가 아니다


def _record(rid: str, doc_type: str, chars: int, *, ctype: str | None = "design-rule", sections: bool = True) -> dict:
    content: dict = {"sections": [{"section_id": "1", "title": "본문", "content_text": "a" * chars}] if sections else []}
    if doc_type == CARD:
        content["card"] = {"card_id": rid, "type": ctype}
    return {"id": rid, "doc_type": doc_type, "title": f"{rid} 제목", "tags": [f"type:{ctype}"] if ctype else [],
            "content": content}


PAPER_CHARS = 140_000
RECORDS = {
    "syn-alpha": [_record("K1", CARD, 1_000), _record("K2", CARD, 1_200), _record("K3", CARD, 800, ctype="faq"),
                  _record("P1", "paper", PAPER_CHARS, ctype=None)],
    "syn-beta": [_record("K4", CARD, 13_000), _record("K5", CARD, 13_000)],
    "syn-gamma": [],
    "syn-unrender": [_record("K6", CARD, 10, sections=False)],
}
LISTED = sorted(list(RECORDS) + ["syn-ghost"])


class _Hub(BaseHTTPRequestHandler):
    seen: list = []
    require_key = False

    def _send(self, status: int, body) -> None:
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):  # noqa: N802 — http.server 의 이름이다.
        type(self).seen.append(("GET", self.path, self.headers.get("X-API-Key")))
        if type(self).require_key and self.headers.get("X-API-Key") != API_KEY:
            return self._send(401, {"detail": "missing X-API-Key header"})
        if self.path == "/api/agents":
            return self._send(200, [{"agent_type": key, "name": key} for key in LISTED])
        parts = self.path.split("/")
        if len(parts) == 5 and parts[1:3] == ["api", "agents"] and parts[4] == "records":
            key = unquote(parts[3])
            if key in RECORDS:
                return self._send(200, RECORDS[key])
        return self._send(404, {"detail": "agent not found"})

    def _refuse(self):
        type(self).seen.append((self.command, self.path, None))
        self._send(405, {"detail": "read only"})

    do_POST = do_PUT = do_PATCH = do_DELETE = _refuse

    def log_message(self, *_args):
        pass


@pytest.fixture
def hub():
    if not (ENGINE / "card_review.py").is_file():
        pytest.skip(f"엔진 리포가 곁에 없다(../HWAXAgentServer) — {ENGINE}")
    _Hub.seen, _Hub.require_key = [], False
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Hub)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def _run(base: str, *args: str, key: str | None = None, tmp_path=None) -> tuple[int, dict | None, str, str]:
    env = {k: v for k, v in os.environ.items() if k not in ("AIDH_API_KEY", "HWAXRISK_AIDH_API_KEY", "HWAXRISK_AIDH_BASE")}
    if key:
        env["AIDH_API_KEY"] = key
    out = tmp_path / "census.json"
    proc = subprocess.run([sys.executable, str(SCRIPT), "--base", base, "--engine", str(ENGINE), "--out", str(out), *args],
                          capture_output=True, text=True, timeout=300, env=env, check=False)
    body = json.loads(out.read_text(encoding="utf-8")) if proc.returncode == 0 else None
    return proc.returncode, body, proc.stdout, proc.stderr


def test_census_counts_over_slot_cards_input_deficit_and_calls_for_both_views(hub, tmp_path):
    rc, out, _stdout, stderr = _run(hub, "--per-expert", tmp_path=tmp_path)
    assert rc == 0, stderr
    assert out["roster"] == {"source": "/api/agents", "listed": 5, "selected": 5, "measured": 4, "mode": "all",
                             "sample": None, "seed": None, "include": []}
    assert out["failed"] == [{"agent": "syn-ghost", "why": "404 — 명단에는 있는데 기록 경로가 그 전문가를 모른다"}]
    assert out["engine"]["norm_rev"] and out["engine"]["api_rev"]

    records = out["views"]["records"]
    assert (records["experts"], records["experts_with_cards"]) == (4, 2)
    assert (records["cards_listed"], records["cards_rendered"], records["unrenderable"]) == (7, 6, 1)
    assert records["doc_types"] == {CARD: 6, "paper": 1}
    big, one_m = records["windows"]["200k"], records["windows"]["1M"]
    # 창 값은 W-D2 와 같은 식이다 — 20만은 Claude 길 기본(200,000 · 32,000), 1M 은 1,048,576 · 출력 상한 없음.
    assert (big["ctx_tokens"], big["max_tokens"], one_m["ctx_tokens"], one_m["max_tokens"]) == (200_000, 32_000, 1_048_576, 0)
    assert big["card_room"] == min(big["verdict_slot"], big["sweep_slot"]) < PAPER_CHARS < one_m["card_room"]
    # 한 장 자리를 넘는 것은 20만의 논문 하나다 — 조각 수 어림은 그 카드의 글자를 자리로 나눈 올림이다.
    assert (big["over_slot_cards"], big["over_slot_doc_types"], big["experts_with_over_slot"]) == (1, {"paper": 1}, 1)
    assert big["over_slot_experts"][0]["agent"] == "syn-alpha"
    paper = next(e for e in out["experts"] if e["agent"] == "syn-alpha")["views"]["records"]["card_chars_max"]
    assert big["chunks"] == -(-paper // big["card_room"]) == 2 and big["oversize_cards"] == 0
    assert (one_m["over_slot_cards"], one_m["chunks"]) == (0, 0)
    # 입력 결손 몫 — 20만에서는 alpha(논문 포함)와 beta(26,000자 남짓), 1M 에서는 alpha 만 넘는다.
    assert big["noinput_card_budget"] < 26_000 < one_m["noinput_card_budget"] < PAPER_CHARS
    assert (big["experts_noinput_over"], one_m["experts_noinput_over"]) == (2, 1)
    # 셀당 판정 호출 — 배경(faq)은 판정 묶음에 들지 않고 조각 묶음은 조각 수만큼 센다.
    # alpha 20만: [K1 K2] + 논문 조각 2 = 3 · 1M: [K1 K2] + [논문] = 2 / beta 20만: 13,000자 둘이 판정 몫을 넘어 2 · 1M: 1.
    assert big["verdict_calls_per_cell"] == {"n": 2, "median": 2.5, "max": 3, "total": 5}
    assert one_m["verdict_calls_per_cell"] == {"n": 2, "median": 1.5, "max": 2, "total": 3}
    assert big["vs_1M"]["verdict_calls_ratio_per_expert"] == {"median": 1.75, "max": 2.0}
    assert (big["sweep_calls"]["total"], one_m["sweep_calls"]["total"], big["vs_1M"]["sweep_calls_ratio_total"]) == (4, 2, 2.0)

    # 엔진의 팩이 싣는 지식카드만 보면 논문이 빠진다 — 20만에서도 한 장 자리를 넘는 카드가 없다.
    cards = out["views"]["knowledge_cards"]
    assert (cards["cards_listed"], cards["cards_rendered"], cards["doc_types"]) == (6, 5, {CARD: 6})
    assert cards["windows"]["200k"]["over_slot_cards"] == 0 and cards["windows"]["200k"]["chunks"] == 0
    assert cards["windows"]["200k"]["experts_noinput_over"] == 1          # beta 뿐
    assert cards["windows"]["1M"]["experts_noinput_over"] == 0


def test_census_reads_only_and_never_prints_the_key(hub, tmp_path):
    _Hub.require_key = True
    rc, out, stdout, stderr = _run(hub, key=API_KEY, tmp_path=tmp_path)
    assert rc == 0, stderr
    assert {method for method, _path, _key in _Hub.seen} == {"GET"}
    assert {path for _m, path, _k in _Hub.seen} == {"/api/agents"} | {f"/api/agents/{k}/records" for k in LISTED}
    assert {key for _m, _p, key in _Hub.seen} == {API_KEY}
    assert API_KEY not in stdout + stderr + json.dumps(out, ensure_ascii=False)


def test_census_without_the_key_on_a_locked_hub_says_what_to_set(hub, tmp_path):
    _Hub.require_key = True
    rc, out, _stdout, stderr = _run(hub, tmp_path=tmp_path)
    assert rc == 2 and out is None
    assert "HTTP 401" in stderr and "AIDH_API_KEY" in stderr


def test_census_cannot_measure_an_unreachable_hub(tmp_path):
    if not (ENGINE / "card_review.py").is_file():
        pytest.skip(f"엔진 리포가 곁에 없다(../HWAXAgentServer) — {ENGINE}")
    import socket

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        dead = f"http://127.0.0.1:{sock.getsockname()[1]}"
    rc, out, _stdout, stderr = _run(dead, tmp_path=tmp_path)
    assert rc == 2 and out is None and "닿지 않는다" in stderr


def test_census_refuses_an_engine_older_than_the_card_room(hub, tmp_path):
    """한 장 자리(card_room) · 조각 계획은 risk-200k W1 뒤에 생겼다 — 그 전 판의 엔진이면 셈의 뜻이 달라 재지 않는다."""
    old = tmp_path / "old-engine"
    old.mkdir()
    (old / "card_review.py").write_text("API_REV = 'cr-1'\nNORM_REV = 'cr-n1'\nLIMITS_FORMULA_REV = 'cr-l2'\nFEATURES = ()\n"
                                        "def normalize_card(rec):\n    return None\n", encoding="utf-8")
    (old / "external_llm.py").write_text("CTX_DEFAULT = 200000\nMAX_TOKENS_DEFAULT = 32000\n", encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k not in ("AIDH_API_KEY", "HWAXRISK_AIDH_API_KEY")}
    proc = subprocess.run([sys.executable, str(SCRIPT), "--base", hub, "--engine", str(old)], capture_output=True,
                          text=True, timeout=120, env=env, check=False)
    assert proc.returncode == 2 and "엔진이 이 측정보다 낡았다" in proc.stderr and "card_room" in proc.stderr
    assert _Hub.seen == []                     # 엔진을 확인하기 전에는 AIDataHub 를 부르지 않는다


def test_census_sample_is_a_seeded_draw_from_the_sorted_roster_plus_named_experts(hub, tmp_path):
    rc, out, _stdout, stderr = _run(hub, "--sample", "2", "--seed", "7", "--include", "syn-gamma", "--per-expert",
                                    tmp_path=tmp_path)
    assert rc == 0, stderr
    want = random.Random(7).sample(LISTED, 2)
    want += [] if "syn-gamma" in want else ["syn-gamma"]
    assert out["roster"]["mode"] == "sample" and out["roster"]["selected"] == len(want)
    measured = [e["agent"] for e in out["experts"]] + [f["agent"] for f in out["failed"]]
    assert sorted(measured) == sorted(want)
