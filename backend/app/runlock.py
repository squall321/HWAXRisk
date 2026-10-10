# 데이터 디렉터리 러너 잠금(WP5a R2) — runner.lock 을 flock 으로 쥔 프로세스 하나만 러너 루프와 재기동 복구를 돈다
"""HEAXHub 는 앱의 헬스가 2초 안에 안 오면 같은 인스턴스 안에 서버를 하나 더 띄운다(같은 데이터 디렉터리, 같은 포트).
둘째가 재기동 복구를 돌리면 첫째가 돌리는 패널을 error('restart') 로 닫고 좌석을 되돌려 같은 좌석이 두 번 돈다.

- 잠금은 fcntl.flock(LOCK_EX | LOCK_NB) 이다 — 기다리지 않는다. 쥔 프로세스가 죽으면 커널이 푼다.
- 잠금 파일은 지우지 않는다. 지우면 지워진 inode 를 쥔 첫째 옆에서 셋째가 새 파일로 잠금을 얻어 러너가 둘이 된다(반대 검토 P-12).
- 주인 정보(pid·boot_id·시각·호스트)는 잠금을 얻은 뒤에만 적는다 — 못 쥔 쪽이 덮어쓰면 holder() 가 죽은 pid 를 말한다.
  사람이 읽는 용이다(박스 사이로 파일이 건너가도 잠금은 fd 라 무해하다 — 글은 믿지 않는다, X2-07).
"""
from __future__ import annotations

import fcntl
import json
import os
import socket
import time
import uuid
from pathlib import Path

LOCK_FILENAME = "runner.lock"
# 못 쥔 러너가 다시 잡아 보는 간격(초). 운영에서는 같은 포트의 둘째가 포트를 못 묶어 곧 죽으므로 거의 돌지 않는다 —
# 다른 포트로 뜬 둘째(손으로 띄운 것 등)가 첫째가 죽은 뒤 이어받는 길이다. 시험은 환경변수로 줄인다.
RETRY_S = float(os.environ.get("HWAXRISK_RUNNER_LOCK_RETRY_S") or 60)


class RunnerLock:
    """데이터 디렉터리의 runner.lock 을 쥔다. 한 인스턴스 = 한 번의 기동(boot_id)."""

    def __init__(self, data_dir: Path | str) -> None:
        self.path = Path(data_dir) / LOCK_FILENAME
        self.boot_id = uuid.uuid4().hex
        self._fd: int | None = None

    def acquire(self) -> bool:
        """잡아 본다(기다리지 않는다). 이미 쥐었으면 True. 못 쥐면 False 이고 파일을 건드리지 않는다."""
        if self._fd is not None:
            return True
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            return False
        body = json.dumps({"pid": os.getpid(), "boot_id": self.boot_id, "acquired_at": int(time.time()),
                           "hostname": socket.gethostname()}, ensure_ascii=False).encode("utf-8")
        os.ftruncate(fd, 0)
        os.pwrite(fd, body, 0)
        self._fd = fd
        return True

    def held(self) -> bool:
        return self._fd is not None

    def holder(self) -> dict | None:
        """파일에 적힌 주인(읽지 못하면 None) — 사람이 읽는 용이다."""
        try:
            value = json.loads(self.path.read_text(encoding="utf-8") or "null")
        except (OSError, ValueError):
            return None
        return value if isinstance(value, dict) else None

    def release(self) -> None:
        """쥐었으면 놓는다(fd 를 닫으면 풀린다). 못 쥔 인스턴스는 아무것도 하지 않는다. 파일은 지우지 않는다."""
        if self._fd is None:
            return
        fd, self._fd = self._fd, None
        os.close(fd)
