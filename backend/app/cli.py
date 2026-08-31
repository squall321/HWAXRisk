# hwax-risk 콘솔 진입점 — uvicorn app.main:app 을 --host/--port/--root-path(env HOST·PORT·ROOT_PATH 기본)로 기동
from __future__ import annotations

import argparse
import sys

from app import config


def main() -> None:
    settings = config.settings
    parser = argparse.ArgumentParser(
        prog="hwax-risk",
        description="HWAX Risk Review 서버 기동 (REST /api + MCP /mcp + /api/health)")
    parser.add_argument("--host", default=settings.host, help="바인드 호스트 (env HOST, 기본 127.0.0.1)")
    parser.add_argument("--port", type=int, default=settings.port, help="포트 (env PORT, 기본 8000)")
    parser.add_argument("--root-path", default=settings.root_path,
                        help="프록시 prefix (env ROOT_PATH, HEAX 는 /apps/hwax_risk 를 준다)")
    args = parser.parse_args()

    import uvicorn

    print(f"[hwax-risk] http://{args.host}:{args.port}{args.root_path} — data_dir={settings.data_dir}",
          file=sys.stderr)
    uvicorn.run("app.main:app", host=args.host, port=args.port, root_path=args.root_path)


if __name__ == "__main__":
    main()
