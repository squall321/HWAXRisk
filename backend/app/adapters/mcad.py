# StepForge → rr_ir(mcad) 어댑터 — 정상은 heax REST(tree.json·graph.json·parts) 가 정본이고, 서비스 PAT 가 없으면 게이트웨이 MCP 만으로 모아 mcp_degraded 로 강등한다(plan §2.5.1·§2.13.3)
from __future__ import annotations

import json
from typing import Any, Mapping, Sequence

from app.adapters import base
from app.adapters.base import AdapterResult, CallRecorder, Principal, Probe, SourceAdapter
from app.common import canonical_json, now_epoch, sha256_hex
from app.errors import AppError

ADAPTER_VERSION = "1.0"
KIND = "mcad"

# 게이트웨이에 이 5종이 다 보여야 mcad 를 그 백엔드에 바인딩한다(plan §2.13.2).
# part_mesh_map 은 캡처가 한 번도 부르지 않으므로 게이트에서 뺀다 — dyna 브리지를 만들 때 다시 넣는다(recon §4 5항).
REQUIRED_TOOLS: tuple[str, ...] = (
    "list_parts", "list_interfaces", "interface_graph", "project_tree", "job_status",
)
# 계면 kind 4종. MCP 폴백에서는 list_interfaces 를 kind 별로 부른다(소스 MAX_ROWS 500/호출).
IFACE_KINDS: tuple[str, ...] = ("tied", "touching", "clearance", "interference")
MCP_IFACE_LIMIT = 500
# REST /interfaces 는 한 번에 5000행까지 준다 — 살아 있으면 MCP 4회를 이 1회로 대체한다(recon §4 1항).
REST_IFACE_LIMIT = 5000
# tol_config 를 못 읽었을 때 detect 잡 params 에서 읽는 4키(plan §2.2 tol_known_keys).
JOB_TOL_KEYS: tuple[str, ...] = ("tied_gap", "clearance_gap", "tied_area", "tied_width")
# tree.json 노드 kind → IR 노드 kind. 소스 어휘는 core/model.py 의 5종뿐이고(step-file·assembly·instance +
# project-root·file-group), project-root·file-group 은 노드로 만들지 않는다(plan §2.3).
NODE_KIND_MAP: dict[str, str] = {"step-file": "file", "assembly": "assembly", "instance": "part"}


# ---------------------------------------------------------------- 타입 정규화(recon §4 9항 · plan §2.13.1)
def _as_bool(value: Any, *, tool: str = "", field: str = "", warnings: list | None = None) -> bool:
    """cross_file·has_geometry 가 소스에 따라 int 로도 bool 로도 온다 — IR 로 올릴 때 bool 로 통일한다.

    규칙은 `bool(int(v))` 다. 정의 밖 값(문자열·소수·None)은 무언의 캐스팅 대신 `type_unexpected`
    경고 1건으로 남긴다 — 조용한 캐스팅이 `null≠0` 원칙을 깨기 때문이다(plan §2.13.1 표).
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return bool(value)
    if value is not None and warnings is not None:
        warnings.append({"severity": "WARNING", "code": "type_unexpected",
                         "message": f"{field or 'value'}={value!r}", "ref": tool or None,
                         "source_kind": "mcad"})
    return bool(value)


def _as_float(value: Any) -> float | None:
    """수치 결측은 null 이지 0 이 아니다(plan §2.1 4)."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_vec(value: Any, size: int) -> list[float] | None:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) != size:
        return None
    out = [_as_float(v) for v in value]
    return None if any(v is None for v in out) else [float(v) for v in out]  # type: ignore[arg-type]


def _norm_counts(raw: Any) -> dict[str, int]:
    """list_interfaces 는 0 인 kind 키를 생략하고 interface_graph 는 4키 고정이다 — 4키 고정으로 통일한다."""
    src = raw if isinstance(raw, Mapping) else {}
    return {k: int(src.get(k) or 0) for k in IFACE_KINDS}


def _norm_orphans(raw: Any) -> tuple[list[str], int]:
    """orphans 는 fmt 에 따라 배열이거나 개수다 — (목록, 개수) 로 통일한다(목록을 모르면 빈 목록)."""
    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
        items = [str(x) for x in raw]
        return items, len(items)
    try:
        return [], int(raw)
    except (TypeError, ValueError):
        return [], 0


# ---------------------------------------------------------------- 좌표 변환(plan §2.13.3)
def _apply(transform: Sequence[Sequence[float]] | None, point: Sequence[float]) -> list[float]:
    """4x4 row-major 변환을 점 하나에 적용한다. transform 이 없으면 원점 그대로."""
    if transform is None:
        return [float(p) for p in point]
    x, y, z = (float(p) for p in point)
    out = []
    for row in list(transform)[:3]:
        r = [float(v) for v in row]
        out.append(r[0] * x + r[1] * y + r[2] * z + (r[3] if len(r) > 3 else 0.0))
    return out


def _world_bbox(bbox_def: Sequence[float] | None,
                transform: Sequence[Sequence[float]] | None) -> list[float] | None:
    """정의 좌표계 bbox 8꼭짓점을 변환해 축정렬 min/max 를 다시 취한다. transform 이 없으면 null."""
    if bbox_def is None or transform is None:
        return None
    x0, y0, z0, x1, y1, z1 = (float(v) for v in bbox_def)
    corners = [
        _apply(transform, (x, y, z))
        for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)
    ]
    return [
        min(c[0] for c in corners), min(c[1] for c in corners), min(c[2] for c in corners),
        max(c[0] for c in corners), max(c[1] for c in corners), max(c[2] for c in corners),
    ]


def _normalize_transform(raw: Any) -> list[list[float]] | None:
    """4x4 row-major 를 4행 리스트로 편다. 16개 평탄 배열도 받는다. 모양이 아니면 None."""
    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
        rows = list(raw)
        if len(rows) == 16 and all(isinstance(v, (int, float)) for v in rows):
            return [[float(v) for v in rows[i * 4:i * 4 + 4]] for i in range(4)]
        if len(rows) == 4 and all(isinstance(r, Sequence) and len(list(r)) == 4 for r in rows):
            return [[float(v) for v in list(r)] for r in rows]
    return None


# ---------------------------------------------------------------- 경로·키
def _strip_project(path: str, project_name: str | None) -> str:
    """tree path 는 `/{project}/…` 로 시작한다 — 접두를 떼야 canon_key 가 프로젝트 이름에 흔들리지 않는다."""
    text = str(path or "")
    if project_name and text.startswith(f"/{project_name}/"):
        return text[len(project_name) + 1:]
    if project_name and text == f"/{project_name}":
        return "/"
    return text


def _canon_key(path: str, project_name: str | None) -> str:
    return "mcad:" + _strip_project(path, project_name)


class McadAdapter(SourceAdapter):
    """StepForge 프로젝트 1건을 mcad 소스 하나로 읽는다. 소스 앱에 쓰기는 하지 않는다."""

    kind = KIND
    version = ADAPTER_VERSION
    required_tools = REQUIRED_TOOLS

    def __init__(self, app_key: str | None = None) -> None:
        self.app_key = app_key

    # -- 발견 ---------------------------------------------------------------
    def discover(self, registry: Any) -> Probe:
        return registry.probe(KIND, self.app_key)

    # -- 캡처 ---------------------------------------------------------------
    def capture(self, ref: Mapping[str, Any], principal: Principal | None,
                recorder: CallRecorder) -> AdapterResult:
        """plan §2.11.3 2단계. ref = {stepforge_project_id, project_name?, app_slug?, detect_job_id?}."""
        project_id = str(ref.get("stepforge_project_id") or ref.get("project_id") or "").strip()
        if not project_id:
            raise AppError("E100", "mcad ref 에 stepforge_project_id 가 없습니다.", http_status=422)
        app_key = self.app_key or ref.get("app_key")
        slug = str(ref.get("app_slug") or (app_key or "heax-step_forge").split("heax-", 1)[-1])
        captured_at = now_epoch()
        degraded: set[str] = set()
        warnings: list[dict] = []

        def mcp(tool: str, args: Mapping[str, Any]) -> dict:
            return recorder.call("mcp", tool, args, source_kind=KIND, app_key=app_key)

        def rest(path: str, params: Mapping[str, Any] | None = None) -> dict:
            return recorder.call("rest", f"/apps/{slug}/api{path}", params, source_kind=KIND, app_key=app_key)

        # ① detect 잡 상태 — done 이 아니면 캡처를 중단한다(자동 재실행 금지, plan §2.5.1).
        detect_job_id = ref.get("detect_job_id") or None
        job_params: dict = {}
        detect_finished_at = None
        if detect_job_id:
            reply = mcp("job_status", {"job_id": detect_job_id})
            if not reply["ok"]:
                degraded.add("detect_absent")
                warnings.append(_warn("detect_status_unreadable",
                                      f"detect 잡 상태를 읽지 못했다 — {reply['error']}", str(detect_job_id)))
            else:
                job = reply["result"] if isinstance(reply["result"], Mapping) else {}
                status = str(job.get("status") or "")
                if status and status != "done":
                    raise AppError("detect_not_done",
                                   f"검출 잡이 done 이 아닙니다 — status={status}. 소스 앱에서 검출을 마친 뒤 다시 캡처하세요.",
                                   http_status=409)
                job_params = dict(job.get("params") or {})
                detect_finished_at = job.get("finished_at")
        else:
            degraded.add("detect_absent")

        # ② 정본 채널(REST). tree.json 만이 world_transform·노드 id·unit_system·shape_defs 를 준다.
        tree: dict | None = None
        graph: dict | None = None
        parts_rest: list[dict] = []
        tol_config: dict | None = None
        if recorder.rest_available:
            detail = rest(f"/projects/{project_id}")
            if detail["ok"] and isinstance(detail["result"], Mapping):
                # 응답은 {project, files, counts} 봉투이고 tol_config 는 TEXT 컬럼(JSON 문자열)이다(recon 실측).
                body = detail["result"]
                inner = body.get("project")
                raw_tol = (inner if isinstance(inner, Mapping) else body).get("tol_config")
                if isinstance(raw_tol, str):
                    try:
                        raw_tol = json.loads(raw_tol)
                    except ValueError:
                        raw_tol = None
                        degraded.add("tol_config_unknown")
                        warnings.append(_warn("tol_config_unparsable",
                                              "프로젝트 tol_config 를 JSON 으로 풀지 못했다.", project_id))
                tol_config = dict(raw_tol) if isinstance(raw_tol, Mapping) else None
            reply = rest(f"/projects/{project_id}/tree")
            if reply["ok"] and isinstance(reply["result"], Mapping):
                tree = dict(reply["result"])
                tree_call = reply["call_id"]
            reply = rest(f"/projects/{project_id}/artifacts/graph/")
            if reply["ok"] and isinstance(reply["result"], Mapping):
                graph = dict(reply["result"])
            reply = rest(f"/projects/{project_id}/parts")
            if reply["ok"]:
                parts_rest = _rows(reply["result"], "parts")

        # ③ 폴백(MCP). 노드 3키뿐이라 depth·seq·shape_def_id·auto_named·color·world_transform 이 소실된다.
        mcp_tree: dict | None = None
        parts_mcp: list[dict] = []
        if tree is None:
            # MCP 노드는 {name, kind, path} 3키뿐이라 depth·seq·auto_named 가 통째로 소실된다(recon §4 3항).
            degraded.update({"mcp_degraded", "no_node_id", "no_world_transform",
                             "no_depth_seq", "no_auto_named_flag"})
            reply = mcp("project_tree", {"project_id": project_id})
            tree_call = reply["call_id"]
            if not reply["ok"]:
                raise AppError("source_unreachable",
                               f"StepForge 프로젝트 트리를 읽지 못했습니다 — {reply['error']}.", http_status=409)
            mcp_tree = dict(reply["result"]) if isinstance(reply["result"], Mapping) else {}
            if not isinstance(mcp_tree.get("nodes"), list):
                # 노드 500 초과면 소스가 nodes 키 자체를 빼고 summary·note 만 준다(recon §2.2).
                degraded.add("tree_truncated")
                warnings.append(_warn("tree_truncated", str(mcp_tree.get("note") or "노드 요약만 수신했다."), None))
            reply = mcp("list_parts", {"project_id": project_id, "limit": MCP_IFACE_LIMIT})
            parts_mcp = _rows(reply["result"], "parts") if reply["ok"] else []
            parts_call = reply["call_id"]
            # 소스가 limit 를 500 으로 클램프하고 truncated 플래그를 주지 않는다 — 요약의 리프 수와 비교한다(recon §2.2).
            summary_mcp = mcp_tree.get("summary") if isinstance(mcp_tree.get("summary"), Mapping) else {}
            leaf_expected = summary_mcp.get("leaf_instances")
            if isinstance(leaf_expected, int) and not isinstance(leaf_expected, bool) \
                    and leaf_expected > len(parts_mcp):
                degraded.add("parts_truncated")
        else:
            parts_call = tree_call

        project_name = str((tree or mcp_tree or {}).get("project") or ref.get("project_name") or "") or None
        unit_system = (tree or {}).get("unit_system")

        # ④ 노드
        if tree is not None:
            nodes, id_to_canon = _nodes_from_tree(tree, project_name=project_name, app_key=app_key,
                                                  call_id=tree_call, captured_at=captured_at, warnings=warnings)
            for row in parts_rest:
                node_id, path = row.get("id"), row.get("path")
                if node_id is not None and path:
                    id_to_canon[str(node_id)] = _canon_key(str(path), project_name)
        else:
            nodes, id_to_canon = _nodes_from_mcp(mcp_tree or {}, parts_mcp, project_name=project_name,
                                                 app_key=app_key, tree_call=tree_call, parts_call=parts_call,
                                                 captured_at=captured_at)

        leaves = [n for n in nodes if n["kind"] == "part"]
        if leaves and all(n["attrs"].get("volume") is None for n in leaves):
            degraded.add("volume_null_pre_d168")
        if leaves and all(n["attrs"].get("bbox_world") is None for n in leaves):
            degraded.add("no_world_transform")

        # ⑤ 계면 — REST 가 살아 있으면 1회로 읽고(정본), 아니면 MCP 로 kind 4종을 각각 부른다(recon §4 1항).
        iface_rows: list[dict] = []
        iface_call_by_kind: dict[str, str] = {}
        iface_call_rest: str | None = None
        rest_counts: dict[str, int] | None = None
        if recorder.rest_available:
            reply = rest(f"/projects/{project_id}/interfaces", {"limit": REST_IFACE_LIMIT})
            if reply["ok"]:
                iface_call_rest = reply["call_id"]
                iface_rows = _rows(reply["result"], "interfaces")
                if isinstance(reply["result"], Mapping) and isinstance(reply["result"].get("counts"), Mapping):
                    rest_counts = _norm_counts(reply["result"]["counts"])
            else:
                warnings.append(_warn("interfaces_unreadable",
                                      f"REST 계면 표를 읽지 못했다 — {reply['error']}", None))
        if iface_call_rest is None:
            for kind in IFACE_KINDS:
                reply = mcp("list_interfaces", {"project_id": project_id, "kind": kind, "limit": MCP_IFACE_LIMIT})
                if not reply["ok"]:
                    warnings.append(_warn("interfaces_unreadable", f"{kind} 계면을 읽지 못했다 — {reply['error']}", None))
                    continue
                iface_call_by_kind[kind] = reply["call_id"]
                for row in _rows(reply["result"], "interfaces"):
                    if str(row.get("kind") or kind) == kind:
                        iface_rows.append(dict(row))
        if iface_call_rest is None and not iface_call_by_kind:
            # 어느 채널로도 계면을 못 읽었다 — 경고만 남기면 counts.edges.* 0 이 '위반 없음' 으로 읽힌다.
            degraded.add("interfaces_unreadable")

        reply = mcp("interface_graph", {"project_id": project_id, "fmt": "json"})
        igraph = reply["result"] if (reply["ok"] and isinstance(reply["result"], Mapping)) else {}
        graph_counts = _norm_counts(igraph.get("counts"))
        _, orphan_n = _norm_orphans(igraph.get("orphans"))
        if rest_counts is not None:
            graph_counts = rest_counts
        if graph is not None:
            # REST graph.json 이 정본이다 — 0 도 정답이므로 진리값 폴백을 쓰지 않는다.
            _, orphan_n = _norm_orphans(graph.get("orphans"))
            if isinstance(graph.get("counts"), Mapping):
                graph_counts = _norm_counts(graph["counts"])
        # 소스가 truncated 플래그를 주지 않으므로 counts 합과 수신 행 수로 판정한다(recon §4 4항).
        if sum(graph_counts.values()) > len(iface_rows):
            degraded.add("interfaces_truncated")

        tol_hash, tol_keys = _tol_hash(tol_config, job_params)
        if tol_hash is None:
            degraded.add("tol_config_unknown")

        edges, iface_warnings = _edges_from_interfaces(
            iface_rows, nodes=nodes, id_to_canon=id_to_canon, app_key=app_key,
            call_by_kind=iface_call_by_kind, tol_hash=tol_hash, rest_call=iface_call_rest,
        )
        warnings.extend(iface_warnings)
        edges.extend(_part_of_edges(nodes))

        # ⑥ 소스 원문 warnings 를 축어로 보존한다(plan §2.5.1 13코드).
        for w in _rows((tree or {}), "warnings"):
            warnings.append({"severity": str(w.get("severity") or "WARNING"), "code": str(w.get("code") or "unknown"),
                             "message": str(w.get("message") or ""), "ref": w.get("ref"), "source_kind": KIND})

        scope = job_params.get("scope") or ((graph or {}).get("scope") if graph else None)
        step_files = _step_files(tree)
        app_version = base.probe_app_version(recorder, KIND, app_key=app_key)
        if not app_version.get("version"):
            degraded.add("app_version_unknown")
        source = {
            "kind": KIND,
            "app_key": app_key,
            "adapter_version": ADAPTER_VERSION,
            "channel": "rest+mcp" if tree is not None else "mcp",
            "ref": {
                "stepforge_project_id": project_id,
                "project_name": project_name,
                "unit_system": unit_system,
                "detect_job_id": detect_job_id,
                "detect_finished_at": detect_finished_at,
                "step_files": step_files,
            },
            "source_hash": sha256_hex(canonical_json({
                "step_sha256": sorted(f["sha256"] for f in step_files if f.get("sha256")),
                "tol_config_hash": tol_hash,
                "detect_job_id": detect_job_id,
            })),
            "tol_config_hash": tol_hash,
            "tol_known_keys": tol_keys,
            "scope": dict(scope) if isinstance(scope, Mapping) else None,
            "stats": _stats(tree, mcp_tree, nodes, len(iface_rows), orphan_n, graph_counts),
            # 소스 앱 버전은 ir_hash 입력이 아니다 — 쌍의 comparability.app_version_parity 가 이 값을 본다(§2.2).
            "app_version": app_version,
            "degraded": sorted(degraded),
            "captured_at": captured_at,
        }
        return {
            "source": source,
            "nodes": nodes,
            "edges": edges,
            "warnings": warnings,
            "degraded": sorted(degraded),
            "call_ids": recorder.call_ids(KIND),
            "missing": {
                "world_transform_absent": bool(leaves) and all(n["attrs"].get("bbox_world") is None for n in leaves),
                "volume_null": bool(leaves) and all(n["attrs"].get("volume") is None for n in leaves),
            },
        }


# ---------------------------------------------------------------- 조립 도우미
def _warn(code: str, message: str, ref: str | None) -> dict:
    return {"severity": "WARNING", "code": code, "message": message, "ref": ref, "source_kind": KIND}


def _rows(payload: Any, key: str) -> list[dict]:
    """`{key: [...]}` 도 `[...]` 도 받는다(소스·채널에 따라 봉투가 다르다)."""
    if isinstance(payload, Mapping):
        payload = payload.get(key)
    if not isinstance(payload, Sequence) or isinstance(payload, (str, bytes)):
        return []
    return [dict(r) for r in payload if isinstance(r, Mapping)]


def _step_files(tree: Mapping[str, Any] | None) -> list[dict]:
    out = []
    for f in _rows(tree or {}, "files"):
        out.append({"relpath": f.get("relpath"), "sha256": f.get("sha256"),
                    "header_unit": f.get("header_unit"), "schema_ap": f.get("schema_ap")})
    return out


def _tol_hash(tol_config: Mapping[str, Any] | None,
              job_params: Mapping[str, Any]) -> tuple[str | None, list[str]]:
    """tol_config(REST) 위에 detect 잡 params 4키를 덮어쓴 뒤 키 정렬 JSON 의 sha256(plan §2.2).

    둘 다 못 읽으면 (None, []) 이고 호출자가 `tol_config_unknown` 을 세운다.
    """
    merged: dict[str, Any] = {}
    if isinstance(tol_config, Mapping):
        merged.update({str(k): v for k, v in tol_config.items()})
    for key in JOB_TOL_KEYS:
        if job_params.get(key) is not None:
            merged[key] = job_params[key]
    if not merged:
        return None, []
    return sha256_hex(canonical_json(merged)), sorted(merged)


def _shape_attrs(defn: Mapping[str, Any], *, depth: int | None, transform: Any,
                 color: Any, step_file: Any, shape_def_id: Any) -> dict:
    """shape_def 하나를 mcad part attrs 로 편다(plan §2.3). world 계열은 transform 이 있을 때만 산다."""
    bbox_def = _as_vec(defn.get("bbox"), 6)
    size_def = None if bbox_def is None else [bbox_def[3] - bbox_def[0], bbox_def[4] - bbox_def[1],
                                              bbox_def[5] - bbox_def[2]]
    centroid_def = _as_vec(defn.get("centroid"), 3)
    matrix = _normalize_transform(transform)
    return {
        "shape_kind": defn.get("kind"),
        "bbox_def": bbox_def,
        "size_def": size_def,
        "size_sorted": None if size_def is None else sorted(size_def, reverse=True),
        "bbox_world": _world_bbox(bbox_def, matrix),
        "centroid_def": centroid_def,
        "centroid_world": None if (centroid_def is None or matrix is None) else _apply(matrix, centroid_def),
        "volume": _as_float(defn.get("volume")),
        "area": _as_float(defn.get("area")),
        "min_dim": None if size_def is None else min(size_def),
        "material": defn.get("material"),
        "density": _as_float(defn.get("density")),
        "density_unit": defn.get("density_unit"),
        "color": color if color is not None else defn.get("color"),
        "instance_count": defn.get("instance_count"),
        "has_geometry": _as_bool(defn.get("has_geometry")),
        "depth": depth,
        "solid_count": defn.get("solid_count"),
        "construction_only": defn.get("construction_only"),
        "shape_def_id": shape_def_id,
        "step_file": step_file if step_file is not None else defn.get("step_file"),
    }


def _flags(attrs: Mapping[str, Any], *, auto_named: bool) -> list[str]:
    flags = set()
    if auto_named:
        flags.add("auto_named")
    if not attrs.get("has_geometry"):
        flags.add("missing_geometry")
    if attrs.get("construction_only"):
        flags.add("construction_only")
    try:
        if int(attrs.get("solid_count") or 0) > 1:
            flags.add("multi_solid")
    except (TypeError, ValueError):
        pass
    if attrs.get("volume") is None:
        flags.add("volume_null")
    return sorted(flags)


def _provenance(app_key: str | None, tool: str, call_id: str, captured_at: int,
                node_id: Any = None) -> dict:
    prov = {"adapter": KIND, "app_key": app_key, "tool": tool, "call_id": call_id, "captured_at": captured_at}
    if node_id is not None:
        prov["node_id_at_capture"] = str(node_id)
    return prov


def _nodes_from_tree(tree: Mapping[str, Any], *, project_name: str | None, app_key: str | None,
                     call_id: str, captured_at: int, warnings: list[dict]) -> tuple[list[dict], dict[str, str]]:
    """REST tree.json → 노드. shape_def 없는 instance 는 노드로 만들지 않고 missing_geometry 로 남긴다."""
    shape_defs = tree.get("shape_defs") if isinstance(tree.get("shape_defs"), Mapping) else {}
    by_id: dict[str, dict] = {}
    for raw in _rows(tree, "nodes"):
        if raw.get("id") is not None:
            by_id[str(raw["id"])] = raw
    nodes: list[dict] = []
    id_to_canon: dict[str, str] = {}
    for raw in _rows(tree, "nodes"):
        kind = NODE_KIND_MAP.get(str(raw.get("kind") or ""))
        if kind is None:
            continue
        path = str(raw.get("path") or "")
        canon_key = _canon_key(path, project_name)
        if raw.get("id") is not None:
            id_to_canon[str(raw["id"])] = canon_key
        parent = by_id.get(str(raw.get("parent_id")))
        parent_canon = None
        if parent is not None and NODE_KIND_MAP.get(str(parent.get("kind") or "")) is not None:
            parent_canon = _canon_key(str(parent.get("path") or ""), project_name)
        depth = raw.get("depth")
        if kind == "part":
            defn = shape_defs.get(str(raw.get("shape_def_id"))) if raw.get("shape_def_id") is not None else None
            if not isinstance(defn, Mapping):
                warnings.append(_warn("missing_geometry", "shape_def 가 없는 인스턴스라 노드로 만들지 않았다.", path))
                continue
            attrs = _shape_attrs(defn, depth=depth, transform=raw.get("world_transform"), color=raw.get("color"),
                                 step_file=raw.get("step_file"), shape_def_id=raw.get("shape_def_id"))
            flags = _flags(attrs, auto_named=bool(raw.get("auto_named")))
        else:
            attrs = {"depth": depth, "relpath": raw.get("relpath") or raw.get("name")}
            if raw.get("sha256"):
                attrs["sha256"] = raw["sha256"]
            flags = ["auto_named"] if raw.get("auto_named") else []
        nodes.append({
            "canon_key": canon_key,
            "domain": KIND,
            "kind": kind,
            "label": str(raw.get("name") or ""),
            "local_key": path,
            "parent_canon_key": parent_canon,
            "status_flags": flags,
            "attrs": attrs,
            "provenance": _provenance(app_key, "REST /tree", call_id, captured_at, raw.get("id")),
        })
    return nodes, id_to_canon


def _nodes_from_mcp(tree: Mapping[str, Any], parts: Sequence[Mapping[str, Any]], *,
                    project_name: str | None, app_key: str | None, tree_call: str, parts_call: str,
                    captured_at: int) -> tuple[list[dict], dict[str, str]]:
    """MCP 폴백 — project_tree 노드는 {name, kind, path} 3키뿐이고 list_parts 가 파트 attrs 를 채운다."""
    parts_by_path = {str(p.get("path") or ""): dict(p) for p in parts}
    nodes: list[dict] = []
    seen: set[str] = set()
    for raw in _rows(tree, "nodes"):
        kind = NODE_KIND_MAP.get(str(raw.get("kind") or ""))
        if kind is None:
            continue
        path = str(raw.get("path") or "")
        canon_key = _canon_key(path, project_name)
        if canon_key in seen:
            continue
        seen.add(canon_key)
        parent_path = path.rsplit("/", 1)[0]
        if kind == "part":
            row = parts_by_path.get(path)
            if row is None:
                continue
            attrs = _part_attrs_from_row(row)
            flags = _flags(attrs, auto_named=False)
            prov = _provenance(app_key, "list_parts", parts_call, captured_at)
        else:
            attrs = {"depth": path.count("/"), "relpath": raw.get("name")}
            flags = []
            prov = _provenance(app_key, "project_tree", tree_call, captured_at)
        nodes.append({
            "canon_key": canon_key, "domain": KIND, "kind": kind, "label": str(raw.get("name") or ""),
            "local_key": path, "parent_canon_key": _canon_key(parent_path, project_name) if parent_path else None,
            "status_flags": flags, "attrs": attrs, "provenance": prov,
        })
    # project_tree 가 노드를 주지 못한 경우(500 초과 절단)에도 list_parts 만으로 리프는 세운다.
    for path, row in parts_by_path.items():
        canon_key = _canon_key(path, project_name)
        if canon_key in seen:
            continue
        seen.add(canon_key)
        attrs = _part_attrs_from_row(row)
        parent_path = path.rsplit("/", 1)[0]
        nodes.append({
            "canon_key": canon_key, "domain": KIND, "kind": "part", "label": str(row.get("name") or ""),
            "local_key": path, "parent_canon_key": _canon_key(parent_path, project_name) if parent_path else None,
            "status_flags": _flags(attrs, auto_named=False), "attrs": attrs,
            "provenance": _provenance(app_key, "list_parts", parts_call, captured_at),
        })
    return nodes, {}


def _part_attrs_from_row(row: Mapping[str, Any]) -> dict:
    """MCP list_parts 행 → part attrs. bbox 는 shape_def 로컬이라 world 계열은 전부 null 이다."""
    defn = {
        "kind": row.get("kind"), "bbox": row.get("bbox"), "volume": row.get("volume"), "area": row.get("area"),
        "centroid": row.get("centroid"), "material": row.get("material"), "density": row.get("density"),
        "density_unit": row.get("density_unit"), "instance_count": row.get("instance_count"),
        "has_geometry": row.get("has_geometry"), "solid_count": None, "construction_only": None,
        "step_file": row.get("step_file"),
    }
    return _shape_attrs(defn, depth=str(row.get("path") or "").count("/"), transform=None,
                        color=row.get("color"), step_file=row.get("step_file"), shape_def_id=None)


def _edges_from_interfaces(rows: Sequence[Mapping[str, Any]], *, nodes: Sequence[Mapping[str, Any]],
                           id_to_canon: Mapping[str, str], app_key: str | None,
                           call_by_kind: Mapping[str, str], tol_hash: str | None,
                           rest_call: str | None = None) -> tuple[list[dict], list[dict]]:
    """계면 행 → iface 엣지. 끝점 n{seq} 는 REST 표로 풀고, 표가 없으면 이름으로만 시도한다."""
    by_label: dict[str, list[str]] = {}
    for node in nodes:
        if node["kind"] == "part":
            by_label.setdefault(str(node["label"]), []).append(node["canon_key"])
    edges: list[dict] = []
    warnings: list[dict] = []
    for row in rows:
        kind = str(row.get("kind") or "")
        a, a_note = _endpoint(row.get("node_a"), row.get("name_a"), id_to_canon, by_label)
        b, b_note = _endpoint(row.get("node_b"), row.get("name_b"), id_to_canon, by_label)
        if a is None or b is None:
            warnings.append(_warn("ambiguous_edge_endpoint",
                                  f"계면 끝점을 노드로 풀지 못해 제외했다 — {a_note or ''} {b_note or ''}".strip(),
                                  f"{row.get('name_a')}~{row.get('name_b')}"))
            continue
        penetration_volume = _as_float(row.get("penetration_volume"))
        edges.append({
            "kind": kind,
            "domain": KIND,
            "status": str(row.get("status") or "auto"),
            "a": a,
            "b": b,
            "attrs": {
                "min_gap": _as_float(row.get("min_gap")),
                "contact_area_est": _as_float(row.get("contact_area_est")),
                "band_width": _as_float(row.get("band_width")),
                "normal_align": None,
                "penetration_depth": _as_float(row.get("penetration_depth")),
                # 부울 경로(penetration_volume 산출)가 아니면 깊이는 하한값이다(plan §2.4).
                "penetration_depth_is_lower_bound": penetration_volume is None,
                "penetration_volume": penetration_volume,
                "cross_file": _as_bool(row.get("cross_file"), tool="list_interfaces",
                                       field="cross_file", warnings=warnings),
                "face_pairs_count": None,
                "note": row.get("note"),
                "tol_config_hash": tol_hash,
            },
            "provenance": {
                "adapter": KIND, "app_key": app_key,
                "tool": "REST /interfaces" if rest_call is not None else "list_interfaces",
                "call_id": rest_call if rest_call is not None else call_by_kind.get(kind),
                "detected_at": None, "params_hash": tol_hash,
                # REST 판만 행 id 를 준다 — 확정·별칭 원장이 소스 행으로 되짚을 때 쓴다.
                "iface_row_id_at_capture": None if row.get("id") is None else str(row.get("id")),
            },
        })
    return edges, warnings


def _endpoint(node_id: Any, name: Any, id_to_canon: Mapping[str, str],
              by_label: Mapping[str, list[str]]) -> tuple[str | None, str | None]:
    if node_id is not None and str(node_id) in id_to_canon:
        return id_to_canon[str(node_id)], None
    candidates = by_label.get(str(name or ""), [])
    if len(candidates) == 1:
        return candidates[0], None
    if len(candidates) > 1:
        return None, f"동명 파트 {name!r} 가 {len(candidates)}건"
    return None, f"끝점 {node_id!r}({name!r}) 을 알 수 없음"


def _part_of_edges(nodes: Sequence[Mapping[str, Any]]) -> list[dict]:
    """하이라키 엣지(part_of). 방향은 부모 → 자식이다(plan §2.4)."""
    known = {n["canon_key"] for n in nodes}
    out = []
    for node in nodes:
        parent = node.get("parent_canon_key")
        if parent and parent in known:
            out.append({"kind": "part_of", "domain": KIND, "status": "auto",
                        "a": parent, "b": node["canon_key"], "attrs": {"depth_delta": 1}})
    return out


def _stats(tree: Mapping[str, Any] | None, mcp_tree: Mapping[str, Any] | None,
           nodes: Sequence[Mapping[str, Any]], interfaces: int, orphans: int,
           counts: Mapping[str, int]) -> dict:
    """봉투 stats — 카운트만 담고 ir_hash 에서 빠진다(plan §2.2)."""
    summary = ((tree or {}).get("summary") if isinstance((tree or {}).get("summary"), Mapping)
               else (mcp_tree or {}).get("summary"))
    summary = summary if isinstance(summary, Mapping) else {}
    return {
        "files": summary.get("files", len(_rows(tree or {}, "files"))),
        "nodes": summary.get("nodes", len(nodes)),
        "leaf_instances": summary.get("leaf_instances", sum(1 for n in nodes if n["kind"] == "part")),
        "assemblies": summary.get("assemblies", sum(1 for n in nodes if n["kind"] == "assembly")),
        "max_depth": summary.get("max_depth"),
        "auto_named_nodes": summary.get("auto_named_nodes",
                                        sum(1 for n in nodes if "auto_named" in n["status_flags"])),
        "interfaces": interfaces,
        "orphans": orphans,
        "interface_counts": dict(counts),
    }
