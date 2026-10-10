# 씨앗 출처 래칫(WP5b C4 가드 B) — 시험 파일이 원장 행을 손으로 INSERT 하는 수가 늘지 않게 막는다(0 을 요구하지 않는다)
"""손으로 쓴 원장 행은 소비자 코드를 보고 쓴 모양이라 소비자와 같이 틀린다(2.3절 실례 여섯). 새 시험은 생산자 경로
(`tests/factories.py`)로 입력을 만든다. 생산자가 만들 수 없는 '망가진 행' 만 `factories.seed_raw(…, reason=…)` 로 심는다.

이미 있는 손 INSERT 를 지우라고 하지는 않는다 — 늘지 않게만 막는다(포털 리포의 내부 IP 가드와 같은 방식). 줄이면 아래
기준선을 같이 내린다.
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Iterable

from tests.conftest import BACKEND_DIR

# HWAXRisk 7248651 의 tests/ 실측값. 줄이는 방향으로만 고친다 — 늘리려면 먼저 왜 생산자 경로로 못 만드는지 적어라.
BASELINE = {"rr_diffs": 8, "rr_diff_events": 4, "rr_states": 9, "rr_snapshots": 16, "rr_panels": 15}
_INSERT = re.compile(r"INSERT\s+(?:OR\s+\w+\s+)?INTO\s+(rr_diffs|rr_diff_events|rr_states|rr_snapshots|rr_panels)\b",
                     re.IGNORECASE)


def count_inserts(paths: Iterable[Path]) -> tuple[Counter, dict[str, Counter]]:
    """(표마다 합계, 파일마다 표별 수)."""
    total: Counter = Counter()
    by_file: dict[str, Counter] = {}
    for path in paths:
        hits = Counter(t.lower() for t in _INSERT.findall(path.read_text(encoding="utf-8")))
        if hits:
            total.update(hits)
            by_file[path.as_posix()] = hits
    return total, by_file


def _test_sources() -> list[Path]:
    return [p for p in sorted((BACKEND_DIR / "tests").rglob("*.py")) if p.name != Path(__file__).name]


def test_hand_written_ledger_rows_do_not_grow():
    total, by_file = count_inserts(_test_sources())
    grown = {table: f"{BASELINE[table]} → {total[table]}" for table in BASELINE if total[table] > BASELINE[table]}
    assert grown == {}, (
        f"시험 파일의 손 INSERT 가 늘었다 — {grown}. 새 시험은 tests/factories.py 의 생산자 경로로 입력을 만든다"
        f"(망가진 행이면 factories.seed_raw 에 사유를 적는다). 파일별: "
        + "; ".join(f"{Path(f).name} {dict(c)}" for f, c in by_file.items() if set(c) & set(grown)))


def test_the_ratchet_actually_counts(tmp_path):
    """0건을 훑고 통과하는 가드는 아무것도 지키지 않는다 — 심은 문장을 세고, 세지 말아야 할 것은 세지 않는다."""
    planted = tmp_path / "test_planted.py"
    planted.write_text(
        'store.execute("INSERT INTO rr_diffs(id, diff_json) VALUES (?, ?)", row)\n'
        'conn.execute("INSERT OR IGNORE INTO rr_panels(id) VALUES (?)")\n'
        'conn.execute("insert into rr_states (snapshot_id) values (?)")\n'
        'conn.execute("INSERT INTO rr_projects(id) VALUES (?)")\n'
        'conn.execute("INSERT INTO rr_diffs_archive(id) VALUES (?)")\n', encoding="utf-8")
    total, _ = count_inserts([planted])
    assert total == Counter({"rr_diffs": 1, "rr_panels": 1, "rr_states": 1})
    real, _ = count_inserts(_test_sources())
    assert sum(real.values()) >= 40, "기준선의 표를 거의 못 셌다 — 가드가 죽었다"
