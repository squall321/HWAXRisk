#!/usr/bin/env bash
# HWAX SIF 빌드 hermetic 보정 훅 — 호스트 ~/.local 오염으로 SIF 에서 누락되는 런타임 의존성을
# system python(/usr/local)에 확실히 설치한다(fastapi_react.def 의 opt-in 빌드 훅으로 실행됨, MaterialTwinWeb 과 동일).
#
# 배경: fastapi_react.def 의 `pip install -e ../backend` 가 빌드 중 마운트된 호스트 user-site(~/.local)를
# 보고 거기 있는 패키지를 "설치됨"으로 판단해 이미지에 안 넣는다(대표적으로 httpx). 그 결과 SIF 가
# 호스트 ~/.local 에 의존하는 비-hermetic 상태가 되고, ~/.local 이 드리프트하면 런타임이 깨진다.
# 이 훅은 PYTHONNOUSERSITE=1(=user-site 무시)로 pip 을 재실행해 전체 런타임 클로저를 /usr/local 에
# 박는다. 런타임에서도 manifest launch.env 의 PYTHONNOUSERSITE=1 이 ~/.local 을 무시하게 한다.
set -eux

export PYTHONNOUSERSITE=1  # 빌드 pip 이 호스트 ~/.local 을 무시 → 누락 의존성을 /usr/local 에 설치.
cd /app/backend

# user-site 를 배제한 상태로 재설치 → 누락 런타임 의존성이 system python 에 들어간다.
pip install --no-cache-dir -e .

# 정품 httpx 명시 설치 — mcp 코드는 `import httpx`(정품)를 쓰는데, 빌드 미러가 mcp 의존성을
# httpx2(리패키지)로 매핑해 정품 httpx 가 누락된다. 이름으로 직접 설치해 보정한다.
pip install --no-cache-dir "httpx>=0.27"

# 빌드 시점에 hermetic 클로저를 검증(user-site 무시). 누락되면 빌드를 실패시켜 조기 발견.
python - <<'PY'
import importlib
for m in ("httpx", "mcp.server.fastmcp", "jsonschema", "yaml", "fastapi"):
    importlib.import_module(m)
print("hermetic runtime deps OK (user-site 무시 상태에서 전부 import 성공)")
PY
