# 배치 러너 골격(plan §8.2.9) — 데몬 스레드 panel_loop(5 s)·sync_loop(60 s)·nightly_loop(60 s 폴링) 이 P0 에서는 잠만 자고 status() 만 낸다
from __future__ import annotations

import threading
import time

# (스레드명, 폴링 주기 초). 본문은 P3(panel)·P4(sync)·P6(nightly) 에서 채운다.
_LOOPS: tuple[tuple[str, float], ...] = (("panel_loop", 5.0), ("sync_loop", 60.0), ("nightly_loop", 60.0))


class RiskRunner:
    """main.py lifespan 이 start()/stop() 하는 객체. LLM·네트워크 호출 없음(P0)."""

    def __init__(self, store, settings) -> None:
        self.store = store
        self.settings = settings
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._last_tick: dict[str, float | None] = {name: None for name, _ in _LOOPS}

    def _loop(self, name: str, interval: float) -> None:
        while not self._stop.is_set():
            self._last_tick[name] = time.time()
            self._stop.wait(interval)

    def start(self) -> None:
        if self._threads:
            return
        self._stop.clear()
        for name, interval in _LOOPS:
            t = threading.Thread(target=self._loop, args=(name, interval), name=name, daemon=True)
            t.start()
            self._threads.append(t)

    def stop(self) -> None:
        """Event 를 세우고 스레드당 최대 2 s 만 join 한다."""
        self._stop.set()
        for t in self._threads:
            t.join(timeout=2.0)
        self._threads = []

    def status(self) -> dict:
        """{threads: [{name, alive, last_tick}]} — /api/health 에는 싣지 않는다(형식 고정)."""
        alive = {t.name: t.is_alive() for t in self._threads}
        return {
            "threads": [
                {"name": name, "alive": alive.get(name, False), "last_tick": self._last_tick[name]}
                for name, _ in _LOOPS
            ]
        }
