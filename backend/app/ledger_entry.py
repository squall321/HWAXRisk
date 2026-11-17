# 판정표 원장 MCP 쓰기 본체(RK-01 ~ RK-04) — 게이트웨이 위임으로 확인된 신원만 받고(entry.require_delegate) REST 와 같은 라우트 함수를 그 신원으로 부른다
"""MCP 쓰기 도구는 여기의 함수를 `mcp_server._entry` 로 스레드에서 부른다. 문(구성원 · 편집자 · 남 숨김)은 라우트의 것을 그대로 지난다 — 보기는
403 role_insufficient, 남 · 없는 대상은 404 다. 같은 호출을 두 번 해도 같은 행이다(틀 · 층 · 판 · 묶음은 같은 입력이면 created false)."""
from __future__ import annotations

from typing import Any

from app import entry, identity, ledger_routes


def put_template(ident: identity.Identity, *, target_key: str, kind: str, body: dict) -> dict:
    entry.require_delegate(ident)
    return ledger_routes.put_template(target_key, kind, body, ident=ident)


def put_layer(ident: identity.Identity, *, target_key: str, name: str, order: int, rows: dict,
              source_file: str | None = None) -> dict:
    entry.require_delegate(ident)
    body = entry._body(ledger_routes.LayerBody, name=name, order=order, rows=rows, source_file=source_file)
    return ledger_routes.post_layer(target_key, body, ident=ident)


def build(ident: identity.Identity, *, target_key: str, layers: list[Any], base_version: int | None = None,
          colset_version: int | None = None) -> dict:
    entry.require_delegate(ident)
    body = entry._body(ledger_routes.BuildBody, base_version=base_version, layers=layers, colset_version=colset_version)
    return ledger_routes.post_version(target_key, body, ident=ident)


def build_bundle(ident: identity.Identity, *, target_key: str, template: dict, version: int | None = None,
                 codes: list[str] | None = None, mask: bool = True) -> dict:
    entry.require_delegate(ident)
    body = entry._body(ledger_routes.BundleBody, version=version, codes=codes, template=template, mask=mask)
    return ledger_routes.post_evidence_bundle(target_key, body, ident=ident)


def apply_decision(ident: identity.Identity, *, target_key: str, decision_json: dict | None = None, decision_text: str | None = None,
                   job_id: str | None = None, mapping: dict | None = None, mapping_version: int | None = None,
                   version: int | None = None, layer_name: str | None = None, layer_order: int | None = None) -> dict:
    entry.require_delegate(ident)
    body = entry._body(ledger_routes.DecisionBody, decision_json=decision_json, decision_text=decision_text, job_id=job_id,
                       mapping=mapping, mapping_version=mapping_version, version=version, layer_name=layer_name, layer_order=layer_order)
    return ledger_routes.post_layer_from_decision(target_key, body, ident=ident)


def put_numbers(ident: identity.Identity, *, target_key: str, numbers: list[dict], forbidden: list[dict] | None = None) -> dict:
    entry.require_delegate(ident)
    body = entry._body(ledger_routes.NumbersBody, numbers=numbers, forbidden=forbidden or [])
    return ledger_routes.put_numbers(target_key, body, ident=ident)
