# 가짜 쟁점 패널 엔진(재설계 M3 S3-7 시험) — 러너가 보낸 delib_opts 를 받아, 질문의 쟁점 닻에 맞춘 결정문(risk_spec)을 대본대로 돌려준다
"""`tests/rr/legacy_build.LegacyEngine` 과 같은 모양({decision_text, turns, events, conv_id, …})을 낸다. 결정문의 원자는 닻 클러스터의
주체·변경 종류(원장의 diff 이벤트에서 그대로 — 인용 줄도 이벤트의 cid·text)를 쓰므로, 정규화가 같은 cluster_key 를 낸다.

대본(`script`) — 쟁점 id 또는 '*' → 결과 하나:
  {"severity": "치명"|"중대"|"경미", "judgement": "FAIL"|"WARNING"|"OK"|"undetermined",
   "direction": "risk"|"improvement", "status": "open"|"rejected_in_panel", "detail": None(닻 그대로)|"<다른 세부>",
   "subject": None(닻 그대로)|"other" — 다른 이벤트의 주체(닻에 붙지 않는 원자)}
  "unparseable" — 결정문에 JSON 이 없다(파싱 실패)
  예외 인스턴스 — 그대로 올린다(러너 실패 표 시험)
`drain` 이 참이면 `drain_state()` 가 비우는 중이라 답한다. `calls` 는 받은 delib_opts 전부다.
"""
from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from app import issues
from tests.rr import legacy_build

_ISSUE_RE = re.compile(r"\[쟁점 (iss-[0-9a-f]{12})")
DEFAULT = {"severity": "중대", "judgement": "WARNING", "direction": "risk", "status": "open", "detail": None,
           "subject": None}


class IssuePanelEngine:
    def __init__(self, store, script: Mapping[str, Any] | None = None) -> None:
        self.store = store
        self.script: dict[str, Any] = dict(script or {})
        self.calls: list[dict] = []
        self.drain = False

    def health(self) -> dict:
        return {"model": "issue-fake-model", "provider": "fake", "engine_rev": "issue-fake"}

    def drain_state(self) -> dict:
        return {"on": bool(self.drain), "scope": "panels" if self.drain else None}

    def run(self, delib_opts, *, owner_sub=None):
        self.calls.append(dict(delib_opts))
        keys = [p["key"] for p in delib_opts["personas"]]
        found = _ISSUE_RE.search(str(delib_opts.get("question") or ""))
        issue_id = found.group(1) if found else None
        plan = self.script.get(issue_id, self.script.get("*", DEFAULT)) if issue_id else "unparseable"
        if isinstance(plan, BaseException):
            raise plan
        if plan == "unparseable":
            decision = "[검증 대상 — 결론 아님] 좌석들은 이 쟁점을 따졌으나 결정문 JSON 을 내지 않았다."
        else:
            decision = legacy_build.decision_text(self.spec(issue_id, {**DEFAULT, **dict(plan)}, keys))
        return {"decision_text": decision,
                "turns": [{"round": r, "persona": k, "say": f"{k} 라운드 {r} 발언"} for r in (1, 2, 3) for k in keys],
                "events": legacy_build.seat_events(keys), "conv_id": f"conv-{issue_id}", "report_id": None,
                "call_path": "portal"}

    # ------------------------------------------------------------ 결정문
    def spec(self, issue_id: str, plan: Mapping[str, Any], seats: list[str]) -> dict:
        target_key = self.store.query_one("SELECT target_key FROM rr_issues WHERE issue_id = ?", (issue_id,))["target_key"]
        (issue,) = [i for i in issues.issue_rows(self.store, target_key) if i["issue_id"] == issue_id]
        anchor = issues.anchor_row(self.store, target_key, issue["anchor_cluster_key"])
        target = self.store.query_one("SELECT ref_id, project_id, ir_hash FROM rr_targets WHERE target_key = ?",
                                      (target_key,))
        diff = self.store.query_one("SELECT base_snapshot_id, target_snapshot_id, diff_json FROM rr_diffs WHERE id = ?",
                                    (target["ref_id"],))
        events = json.loads(diff["diff_json"])["semantic"]["events"]
        rep = json.loads(self.store.query_one("SELECT finding_json FROM rr_findings WHERE finding_id = ?",
                                              (anchor["merged"]["claim_finding_id"],))["finding_json"])
        cited = {c["ref"] for c in rep.get("cites") or () if str(c.get("ref", "")).startswith("c:")}
        event = next((e for e in events if e.get("cid") in cited), None)
        if event is None:
            # 닻의 인용 줄이 diff 이벤트가 아니다(묶음 밖 원자료 줄) — 대표 원자의 주체·변경 종류·인용을 그대로 쓴다.
            line = next(c for c in rep["cites"] if str(c.get("ref", "")).startswith("c:"))
            event = {"cid": line["ref"], "text": line.get("quote") or "", "change_kind": rep["change_kind"],
                     "subject": {"ckeys": list((rep.get("subject") or {}).get("ckeys") or ())}}
        if plan.get("subject") == "other":
            event = next(e for e in events if e.get("cid") not in cited and e["subject"]["ckeys"] != event["subject"]["ckeys"])
        seat = seats[0]
        finding = {
            "id": "F1", "direction": plan["direction"], "domain": seat.split("-", 1)[0],
            "mechanism": anchor["mechanism"], "mechanism_detail": plan.get("detail") or anchor["mechanism_detail"],
            "change_kind": event["change_kind"], "subject": {"ckeys": list(event["subject"]["ckeys"]), "names": []},
            "trigger_condition": "none", "severity": plan["severity"], "judgement": plan["judgement"],
            "detectability": {"level": "sim-detectable", "tool": "report_part_risk"},
            "evidence_grade": "도구예측", "precedent": "none",
            "cites": [{"ref": event["cid"], "quote": event["text"]}], "tool_calls": [],
            "claim": "쟁점 패널이 닻 클러스터를 다시 본 결과다.", "warrant": "변경 줄이 그 메커니즘의 조건을 바꾼다.",
            "resolving_check": {"kind": "sim", "ref": "낙하 해석 재실행"}, "owner_domain": seat.split("-", 1)[0],
            "raised_by": [seat], "contested_by": (["delib-baseline-defender"] if plan["status"] == "rejected_in_panel"
                                                 else []),
            "contest_note": "패널이 이 주장을 기각했다." if plan["status"] == "rejected_in_panel" else "",
            "status": plan["status"],
        }
        facets = ("intent", "constraint", "anomaly", "lineage", "vulnerability", "strength", "tradeoff", "unknown")
        return {
            "schema": "risk_spec", "version": "1.0", "taxonomy_version": "1.0",
            "scope": {"kind": "diff", "target_key": target_key, "project_refs": [target["project_id"]],
                      "ir_refs": [diff["base_snapshot_id"], diff["target_snapshot_id"]], "diff_ref": target["ref_id"],
                      "ir_hash": target["ir_hash"]},
            "findings": [finding] if plan["direction"] == "risk" else [],
            "gains": [finding] if plan["direction"] == "improvement" else [],
            "cross_domain": [], "open_items": [],
            # 성격 진술 하나 — 쟁점 패널은 이것을 앉히지 않는다(rr_character 무접촉, WP4 3.7).
            "character": {"one_liner": "쟁점 하나의 재심.",
                          "facets": [{"facet": f, "statements": ([{"id": "s1", "text": "두께를 늘리는 개정이 잦다.",
                                                                    "tags": [], "cites": [], "by": [seat]}]
                                                                  if f == "lineage" else []),
                                      "na_reason": "" if f == "lineage" else "좌석 미기재"} for f in facets]},
            "coverage": {"seats": [{"key": k, "domain": k.split("-", 1)[0], "origin": "primary"} for k in seats],
                         "domains_seated": sorted({k.split("-", 1)[0] for k in seats}), "domains_missing": []},
            "verdict": "undetermined", "verdict_conditions": [],
            "evidence_profile": {"tool": 1, "card": 0, "precedent": {"verified": 0, "dismissed": 0},
                                 "heuristic": 0, "measured": 0},
        }
