# 런타임 JSON 자산 로더 — docs/*.v1.json(taxonomy·character-vocab·seat-contract·rules-seed·adjacency·character-seed-rules)
from __future__ import annotations

import json
from functools import lru_cache

from app.config import BASE_DIR
from app.errors import AppError

DOCS_DIR = BASE_DIR / "docs"
ASSET_VERSION = "v1"

# /meta/vocab 이 이름·버전을 나열하는 어휘 자산(taxonomy 는 /meta/taxonomy 로 따로 낸다).
VOCAB_ASSETS: tuple[str, ...] = (
    "character-vocab",
    "seat-contract",
    "rules-seed",
    "adjacency",
    "character-seed-rules",
)


def asset_path(name: str):
    """docs/<name>.v1.json 경로."""
    return DOCS_DIR / f"{name}.{ASSET_VERSION}.json"


@lru_cache(maxsize=None)
def load_json(name: str) -> dict:
    """docs/<name>.v1.json 을 읽어 dict 로 돌려준다(프로세스 캐시). 없거나 깨지면 E300."""
    path = asset_path(name)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise AppError("E300", f"자산 파일이 없습니다: {path}", http_status=503) from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise AppError("E300", f"자산 파일을 읽을 수 없습니다: {path} — {exc}") from exc


def load_taxonomy() -> dict:
    """리스크 택소노미 v1(docs/taxonomy.v1.json)."""
    return load_json("taxonomy")


def version_of(doc: dict) -> str | None:
    """자산 dict 의 버전 문자열 — 'version' 또는 '*_version' 키 중 첫 값."""
    if "version" in doc:
        return str(doc["version"])
    for key, value in doc.items():
        if key.endswith("_version"):
            return str(value)
    return None


def vocab_index() -> list[dict]:
    """어휘 자산 5종의 {name, file, present, version} 목록(/meta/vocab 용). 파일이 없어도 오류 없이 present=false."""
    out = []
    for name in VOCAB_ASSETS:
        path = asset_path(name)
        item = {"name": name, "file": path.name, "present": path.exists(), "version": None}
        if item["present"]:
            try:
                item["version"] = version_of(load_json(name))
            except AppError as exc:
                item["error"] = exc.message
        out.append(item)
    return out
