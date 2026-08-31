# DynaForge → rr_ir(dyna·dyna_result) 어댑터 — 러너 자격(사용자 포털 PAT)이 없으면 호출 없이 dyna_absent 로 강등하고, 있으면 게이트웨이 MCP 로 modelmeta·리포트를 읽는다(plan §2.5.2·§2.13.4)
from __future__ import annotations

from typing import Any, Mapping, Sequence

from app.adapters.base import AdapterResult, CallRecorder, Principal, Probe, SourceAdapter
from app.common import canonical_json, now_epoch, sha256_hex

ADAPTER_VERSION = "1.0"
KIND = "dyna"
RESULT_KIND = "dyna_result"

# DynaAdapter 가 실제로 부르는 도구만 발견 게이트로 쓴다 — 리포트 도구는 dyna_result 의 게이트다(recon §4).
REQUIRED_TOOLS: tuple[str, ...] = (
    "inspect_file", "download_result", "corpus_summary", "material_usage", "section_contact_usage",
)
# 한 스냅샷에 실을 수 있는 리포트 상한(plan §2.13.4).
MAX_REPORTS = 3
# sim_params_hash 입력 키 순서(plan §2.5.2). 없는 키는 null 로 직렬화한다.
SIM_PARAM_KEYS: tuple[str, ...] = ("kind", "unit_system", "drop_height", "impactor_mass",
                                   "impactor_velocity", "yield_stress")


def group_of(title: str) -> str:
    """리포트 파서 `_group_of` 규칙을 K파일 title 에 그대로 재적용한다 — `\\` 또는 `/` 앞이 group, 없으면 Other."""
    text = str(title or "")
    for sep in ("\\", "/"):
        if sep in text:
            return text.split(sep, 1)[0]
    return "Other"


def _as_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _rows(payload: Any, key: str | None = None) -> list[dict]:
    if isinstance(payload, Mapping) and key is not None:
        payload = payload.get(key)
    if not isinstance(payload, Sequence) or isinstance(payload, (str, bytes)):
        return []
    return [dict(r) for r in payload if isinstance(r, Mapping)]


def _canon(sha256: str, suffix: str) -> str:
    return f"dyna:{str(sha256)[:8]}:{suffix}"


class DynaAdapter(SourceAdapter):
    """K파일 1건을 dyna 소스로 읽는다. 자격이 없으면 소스 호출을 한 번도 하지 않는다."""

    kind = KIND
    version = ADAPTER_VERSION
    required_tools = REQUIRED_TOOLS

    def __init__(self, app_key: str | None = None) -> None:
        self.app_key = app_key

    def discover(self, registry: Any) -> Probe:
        return registry.probe(KIND, self.app_key)

    def capture(self, ref: Mapping[str, Any], principal: Principal | None,
                recorder: CallRecorder) -> AdapterResult:
        """ref = {session_id, file_id, filename?, sha256?, detect_result_file_id?}."""
        app_key = self.app_key or ref.get("app_key")
        captured_at = now_epoch()
        session_id = ref.get("session_id")
        file_id = ref.get("file_id")
        # 러너 자격 (b) — 사용자 포털 PAT 가 없으면 서비스 시야에는 세션이 0건이라 부르지 않는다(plan §2.13.4).
        if principal is None or not principal.portal_pat or not recorder.mcp_available:
            return _absent(app_key, captured_at, "dyna_pat_absent",
                           "요청자의 포털 PAT 가 없어 DynaForge 세션을 열지 않았다(대리 발급 경로는 없다).")
        if not session_id or not file_id:
            return _absent(app_key, captured_at, "dyna_ref_incomplete",
                           "dyna 소스 ref 에 session_id·file_id 가 없어 캡처하지 않았다.")

        reply = recorder.call("mcp", "inspect_file", {"session_id": session_id, "file_id": file_id},
                              source_kind=KIND, app_key=app_key)
        if not reply["ok"]:
            return _absent(app_key, captured_at, "dyna_unreachable",
                           f"inspect_file 을 읽지 못했다 — {reply['error']}")
        payload = reply["result"] if isinstance(reply["result"], Mapping) else {}
        meta = payload.get("meta") if isinstance(payload.get("meta"), Mapping) else payload
        call_id = reply["call_id"]

        warnings: list[dict] = []
        degraded: set[str] = {"no_secid"}  # modelmeta 는 secid 를 내지 않는다(plan §2.5.2).
        if meta.get("valid") is False:
            return _absent(app_key, captured_at, "kfile_invalid", "inspect_file 이 valid=false 를 냈다.")
        if meta.get("truncated_scan"):
            degraded.add("truncated_scan")

        sha256 = str(ref.get("sha256") or meta.get("sha256") or "")
        modelmeta = meta.get("modelmeta") if isinstance(meta.get("modelmeta"), Mapping) else {}
        connectivity = modelmeta.get("connectivity") if isinstance(modelmeta.get("connectivity"), Mapping) else {}
        if connectivity.get("edges_truncated"):
            degraded.add("edges_truncated")
        unresolved = int(connectivity.get("unresolved_sides") or 0)
        if unresolved:
            warnings.append(_warn("contact_side_unresolved", f"환원되지 않은 접촉 측면 {unresolved}건.", None))

        nodes = _pid_nodes(modelmeta, sha256=sha256, app_key=app_key, call_id=call_id, captured_at=captured_at)
        edges = _contact_edges(connectivity, sha256=sha256, app_key=app_key, call_id=call_id)
        contact_nodes, scope_edges = _single_surface(connectivity, sha256=sha256, app_key=app_key, call_id=call_id)
        nodes.extend(contact_nodes)
        edges.extend(scope_edges)
        # detect=true 산출은 사용자가 실행한 결과 파일을 지정했을 때만 읽는다(어댑터가 run_operation 을 부르지 않는다).
        detect_file_id = ref.get("detect_result_file_id")
        if detect_file_id:
            detect = recorder.call("mcp", "download_result", {"session_id": session_id, "file_id": detect_file_id},
                                   source_kind=KIND, app_key=app_key)
            if detect["ok"]:
                edges.extend(_geometric_edges(detect["result"], sha256=sha256, app_key=app_key,
                                              call_id=detect["call_id"]))
            else:
                degraded.add("detect_absent")
                warnings.append(_warn("detect_result_unreadable", f"detect 결과 파일을 읽지 못했다 — {detect['error']}", None))
        else:
            degraded.add("detect_absent")

        context = _corpus_context(recorder, app_key=app_key, captured_at=captured_at)
        source = {
            "kind": KIND, "app_key": app_key, "adapter_version": ADAPTER_VERSION, "channel": "mcp",
            "ref": {"session_id": session_id, "file_id": file_id, "filename": ref.get("filename") or meta.get("filename"),
                    "sha256": sha256 or None, "origin_job_id": ref.get("origin_job_id"),
                    "modelmeta_detect": bool(detect_file_id), "detect_result_file_id": detect_file_id,
                    "includes": list(meta.get("includes") or [])},
            "source_hash": sha256 or None,
            "stats": _stats(meta, connectivity, nodes),
            "conventions": dict(modelmeta.get("conventions") or {}),
            "context": context,
            "degraded": sorted(degraded), "captured_at": captured_at,
        }
        return {"source": source, "nodes": nodes, "edges": edges, "warnings": warnings,
                "degraded": sorted(degraded), "call_ids": recorder.call_ids(KIND),
                "missing": {"dyna_absent": False}}


class DynaResultAdapter(SourceAdapter):
    """리포트 ≤3건을 dyna_result 소스(결과층)로 읽는다. 노드는 만들지 않고 dyna 노드에 오버레이한다."""

    kind = RESULT_KIND
    version = ADAPTER_VERSION
    required_tools = ("report_summary", "report_part_risk", "report_findings", "report_worst_cases")

    def __init__(self, app_key: str | None = None) -> None:
        self.app_key = app_key

    def discover(self, registry: Any) -> Probe:
        return registry.probe(KIND, self.app_key)

    def capture(self, ref: Mapping[str, Any], principal: Principal | None,
                recorder: CallRecorder) -> AdapterResult:
        """ref = {report_ids[], session_id?, dyna_source_hash?, pid_to_nid?{pid: nid}}."""
        app_key = self.app_key or ref.get("app_key")
        captured_at = now_epoch()
        report_ids = [str(r) for r in (ref.get("report_ids") or [])][:MAX_REPORTS]
        if principal is None or not principal.portal_pat or not recorder.mcp_available or not report_ids:
            return _absent(app_key, captured_at, "dyna_result_absent",
                           "리포트 지정 또는 러너 자격이 없어 결과층을 싣지 않았다.", kind=RESULT_KIND)

        warnings: list[dict] = []
        summaries: list[dict] = []
        for report_id in report_ids:
            reply = recorder.call("mcp", "report_summary", {"report_id": report_id},
                                  source_kind=RESULT_KIND, app_key=app_key)
            if not reply["ok"]:
                warnings.append(_warn("report_unreadable", f"리포트를 읽지 못했다 — {reply['error']}", report_id))
                continue
            summaries.append(dict(reply["result"] or {}))
        if not summaries:
            return _absent(app_key, captured_at, "dyna_result_absent", "지정한 리포트를 하나도 읽지 못했다.",
                           kind=RESULT_KIND)

        kinds = {str(s.get("kind") or "") for s in summaries}
        source = {
            "kind": RESULT_KIND, "app_key": app_key, "adapter_version": ADAPTER_VERSION, "channel": "mcp",
            "ref": {"report_ids": report_ids, "report_kind": sorted(kinds)[0] if len(kinds) == 1 else None,
                    "session_id": ref.get("session_id")},
            "source_hash": sha256_hex(canonical_json(sorted(report_ids))),
            "degraded": [], "captured_at": captured_at,
        }
        if len(kinds) > 1:
            # kind 가 섞이면 결과층을 만들지 않는다(plan §2.2 result_kind_mismatch).
            warnings.append(_warn("result_kind_mismatch", f"리포트 kind 가 섞였다 — {sorted(kinds)}", None))
            return {"source": source, "nodes": [], "edges": [], "warnings": warnings, "degraded": [],
                    "call_ids": recorder.call_ids(RESULT_KIND), "results": None,
                    "missing": {"result_kind_mismatch": True}}

        pid_to_nid = {str(k): v for k, v in (ref.get("pid_to_nid") or {}).items()}
        first = summaries[0]
        results: dict = {
            "report_ids": report_ids,
            "kind": sorted(kinds)[0],
            "summary": first.get("summary"),
            "sim_params_hash": _sim_params_hash(first),
            "parts_map": pid_to_nid,
            "part_risk": [],
            "findings": [],
            "worst_cases": [],
            "energy_edges": [],
        }
        report_id = report_ids[0]
        risk = recorder.call("mcp", "report_part_risk", {"report_id": report_id},
                             source_kind=RESULT_KIND, app_key=app_key)
        if risk["ok"]:
            for row in _rows(risk["result"], "parts"):
                pid = str(row.get("part_id"))
                results["part_risk"].append({
                    "nid": pid_to_nid.get(pid), "pid": pid,
                    "worst_stress": row.get("worst_stress"), "worst_g": row.get("worst_g"),
                    "worst_disp": row.get("worst_disp"), "min_safety_factor": row.get("min_safety_factor"),
                })
        findings = recorder.call("mcp", "report_findings", {"report_id": report_id},
                                 source_kind=RESULT_KIND, app_key=app_key)
        if findings["ok"]:
            results["findings"] = _rows(findings["result"], "findings") or _rows(findings["result"])
        worst = recorder.call("mcp", "report_worst_cases", {"report_id": report_id, "metric": "max_stress",
                                                            "limit": 5}, source_kind=RESULT_KIND, app_key=app_key)
        if worst["ok"]:
            results["worst_cases"] = [
                {"case_key": r.get("case_key"), "identity": r.get("identity"), "max_stress": r.get("max_stress"),
                 "max_g": r.get("max_g"), "max_disp": r.get("max_disp"),
                 "min_safety_factor": r.get("min_safety_factor")}
                for r in (_rows(worst["result"], "cases") or _rows(worst["result"]))[:5]
            ]
        energy = recorder.call("mcp", "report_energy_flow", {"report_id": report_id},
                               source_kind=RESULT_KIND, app_key=app_key)
        if energy["ok"] and isinstance(energy["result"], Mapping):
            # src/dst 가 pid 임을 픽스처로 확정하기 전에는 load_path 엣지를 만들지 않고 원문만 둔다(plan §2.13.4).
            results["energy_edges"] = _rows(energy["result"].get("energy_flow") or energy["result"], "edges")

        binding = ref.get("dyna_source_hash")
        if binding:
            source["binding"] = {"bound_to_dyna_source_hash": str(binding),
                                 "method": str(ref.get("binding_method") or "user_declared")}
        return {"source": source, "nodes": [], "edges": [], "warnings": warnings, "degraded": [],
                "call_ids": recorder.call_ids(RESULT_KIND), "results": results,
                "missing": {"dyna_result_absent": False}}


# ---------------------------------------------------------------- 조립 도우미
def _warn(code: str, message: str, ref: str | None, kind: str = KIND) -> dict:
    return {"severity": "WARNING", "code": code, "message": message, "ref": ref, "source_kind": kind}


def _absent(app_key: str | None, captured_at: int, code: str, message: str, kind: str = KIND) -> AdapterResult:
    """호출하지 않았거나 못 읽은 경우 — 노드 0건의 소스와 결측 플래그를 세운다(예외로 삼키지 않는다)."""
    missing = {"dyna_absent": True} if kind == KIND else {"dyna_result_absent": True}
    return {
        "source": {"kind": kind, "app_key": app_key, "adapter_version": ADAPTER_VERSION, "channel": None,
                   "ref": {}, "source_hash": None, "degraded": [], "captured_at": captured_at},
        "nodes": [], "edges": [], "warnings": [_warn(code, message, None, kind)],
        "degraded": [], "call_ids": [], "missing": missing,
        **({"results": None} if kind == RESULT_KIND else {}),
    }


def _pid_nodes(modelmeta: Mapping[str, Any], *, sha256: str, app_key: str | None, call_id: str,
               captured_at: int) -> list[dict]:
    nodes = []
    for part in _rows(modelmeta, "parts"):
        title = str(part.get("title") or "")
        elem_class = str(part.get("elem_class") or "")
        volume = _as_float(part.get("volume"))
        flags: list[str] = []
        # shell 파트의 volume 0 은 미측정이지 0 이 아니다(plan §2.5.2 null≠0).
        if elem_class == "shell" and volume == 0:
            volume = None
            flags.append("shell_volume_zero")
        size = part.get("size")
        nodes.append({
            "canon_key": _canon(sha256, str(part.get("pid"))),
            "domain": KIND, "kind": "pid", "label": title, "local_key": str(part.get("pid")),
            "group": group_of(title), "status_flags": flags,
            "attrs": {
                "title": title, "elem_class": elem_class or None, "n_elems": part.get("n_elems"),
                "bbox_min": part.get("bbox_min"), "bbox_max": part.get("bbox_max"), "size": size,
                "size_sorted": sorted((float(v) for v in size), reverse=True) if isinstance(size, Sequence)
                and not isinstance(size, (str, bytes)) else None,
                "area_ext": _as_float(part.get("area_ext")), "volume": volume, "proj": part.get("proj"),
                "material": dict(part.get("material") or {}), "secid": None,
                "section_hint": part.get("section_hint"), "bridge": None,
            },
            "provenance": {"adapter": KIND, "app_key": app_key, "tool": "inspect_file", "call_id": call_id,
                           "captured_at": captured_at},
        })
    return nodes


def _contact_edges(connectivity: Mapping[str, Any], *, sha256: str, app_key: str | None,
                   call_id: str) -> list[dict]:
    edges = []
    for row in _rows(connectivity, "contact_edges"):
        edges.append({
            "kind": "contact", "domain": KIND, "status": "auto",
            "a": _canon(sha256, str(row.get("a"))), "b": _canon(sha256, str(row.get("b"))),
            "attrs": {"contact_index": row.get("contact"), "contact_type": row.get("type"),
                      "title": row.get("title"), "fs": _as_float(row.get("fs"))},
            "provenance": {"adapter": KIND, "app_key": app_key, "tool": "inspect_file", "call_id": call_id},
        })
    return edges


def _single_surface(connectivity: Mapping[str, Any], *, sha256: str, app_key: str | None,
                    call_id: str) -> tuple[list[dict], list[dict]]:
    """single_surface 접촉은 가상 노드(contact_set) + scope 하이퍼엣지로 편다(plan §2.5.2)."""
    nodes, edges = [], []
    for row in _rows(connectivity, "single_surface"):
        index = row.get("contact")
        canon = _canon(sha256, f"contact:{index}")
        members = [_canon(sha256, str(pid)) for pid in (row.get("pids") or [])]
        nodes.append({
            "canon_key": canon, "domain": KIND, "kind": "contact_set", "label": str(row.get("title") or ""),
            "local_key": str(index), "status_flags": [],
            "attrs": {"contact_index": index, "contact_type": row.get("type"), "title": row.get("title"),
                      "n_members": len(members)},
            "provenance": {"adapter": KIND, "app_key": app_key, "tool": "inspect_file", "call_id": call_id},
        })
        edges.append({
            "kind": "scope", "domain": KIND, "status": "auto", "a": canon, "b": None, "members": members,
            "attrs": {"contact_index": index, "contact_type": row.get("type"), "title": row.get("title")},
            "provenance": {"adapter": KIND, "app_key": app_key, "tool": "inspect_file", "call_id": call_id},
        })
    return nodes, edges


def _geometric_edges(payload: Any, *, sha256: str, app_key: str | None, call_id: str) -> list[dict]:
    body = payload if isinstance(payload, Mapping) else {}
    connectivity = body.get("connectivity") if isinstance(body.get("connectivity"), Mapping) else body
    edges = []
    for row in _rows(connectivity, "geometric_edges"):
        edges.append({
            "kind": "geometric", "domain": KIND, "status": "auto",
            "a": _canon(sha256, str(row.get("a"))), "b": _canon(sha256, str(row.get("b"))),
            "attrs": {"gap_min": _as_float(row.get("gap_min")), "gap_avg": _as_float(row.get("gap_avg")),
                      "pairs": row.get("pairs")},
            "provenance": {"adapter": KIND, "app_key": app_key, "tool": "download_result", "call_id": call_id},
        })
    return edges


def _corpus_context(recorder: CallRecorder, *, app_key: str | None, captured_at: int) -> dict:
    """전사 집계 3종 — 파일·세션·소유자 무관 조직 분포이고 ir_hash 에서 빠진다(plan §2.5.2)."""
    usage: dict[str, Any] = {"fetched_at": captured_at}
    for tool, key in (("material_usage", "materials"), ("section_contact_usage", "sections"),
                      ("corpus_summary", "corpus")):
        reply = recorder.call("mcp", tool, {}, source_kind=KIND, app_key=app_key)
        usage[key] = reply["result"] if reply["ok"] else None
    return {"corpus_usage": usage}


def _stats(meta: Mapping[str, Any], connectivity: Mapping[str, Any],
           nodes: Sequence[Mapping[str, Any]]) -> dict:
    return {
        "nodes": meta.get("nodes"), "elements": meta.get("elements"),
        "parts": meta.get("parts", sum(1 for n in nodes if n["kind"] == "pid")),
        "bbox_min": meta.get("bbox_min"), "bbox_max": meta.get("bbox_max"), "size": meta.get("size"),
        "keyword_counts": dict(meta.get("keyword_counts") or {}),
        "contacts_total": connectivity.get("contacts_total"),
        "unresolved_sides": connectivity.get("unresolved_sides"),
        "edges_truncated": bool(connectivity.get("edges_truncated")),
        "truncated_scan": bool(meta.get("truncated_scan")),
    }


def _sim_params_hash(summary: Mapping[str, Any]) -> str:
    """kind·unit_system·drop_height·impactor.mass·impactor.velocity·yield_stress 를 null 포함 정렬 직렬화한다."""
    params = summary.get("sim_params") if isinstance(summary.get("sim_params"), Mapping) else {}
    impactor = params.get("impactor") if isinstance(params.get("impactor"), Mapping) else {}
    values = {
        "kind": summary.get("kind"), "unit_system": params.get("unit_system"),
        "drop_height": params.get("drop_height"), "impactor_mass": impactor.get("mass"),
        "impactor_velocity": impactor.get("velocity"), "yield_stress": params.get("yield_stress"),
    }
    return sha256_hex(canonical_json({k: values.get(k) for k in SIM_PARAM_KEYS}))
