# MCP 응답 풀기 — text 블록이 여럿이면 전부 읽는다(목록의 둘째 항목부터 말없이 버리지 않는다, 절단 전수 조사 X1)
from __future__ import annotations

import json

from app.ra_client import McpHttpClient


def test_every_text_block_is_read():
    rows = [{"key": "mech-a", "score": 0.9}, {"key": "rel-b", "score": 0.7}]
    many = {"content": [{"type": "text", "text": json.dumps(r)} for r in rows]}
    assert McpHttpClient._unwrap(many) == rows
    plain = {"content": [{"type": "text", "text": "첫 줄"}, {"type": "text", "text": "둘째 줄"}]}
    assert McpHttpClient._unwrap(plain) == "첫 줄\n둘째 줄"


def test_single_block_and_structured_content_answer_as_before():
    assert McpHttpClient._unwrap({"content": [{"type": "text", "text": '{"a": 1}'}]}) == {"a": 1}
    assert McpHttpClient._unwrap({"content": [{"type": "text", "text": "글"}]}) == "글"
    assert McpHttpClient._unwrap({"structuredContent": {"x": 1}, "content": []}) == {"x": 1}
    assert McpHttpClient._unwrap({"content": []}) == {"content": []}
