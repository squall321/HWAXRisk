# 비율의 정확 이항 상한 — 검토 품질 수치(review_quality)가 쓰는 binom_upper 하나(M3 의 WP4 표본 재검토가 이 파일을 넓힌다)
"""비율 k/n 의 단측 95% 상한(Clopper–Pearson) 하나만 둔다. 상한 함수를 둘 두지 않는다(WP5b 3.7.1).

상한 p_u 는 '참 비율이 p_u 이면 k 이하가 나올 확률이 α' 인 값이다 — P(X ≤ k; n, p_u) = α. 그 확률은 정칙 불완전 베타로
1 − I_{p_u}(k + 1, n − k) 와 같으므로 I_p(k + 1, n − k) = 1 − α 를 이분법으로 푼다. 불완전 베타는 연분수(Lentz)로 센다 — n 이
수만이어도 빠르고 표준 라이브러리만 쓴다(앱에 scipy 가 없다).
"""
from __future__ import annotations

import math

ALPHA = 0.05                 # 단측 95%
_BISECT_STEPS = 80           # [0, 1] 을 2^-80 까지 — 소수 여섯째 자리보다 훨씬 곱다
_CF_EPS = 1e-15
_CF_TINY = 1e-300
_CF_MAX_ITER = 100_000


def _betacf(a: float, b: float, x: float) -> float:
    """정칙 불완전 베타의 연분수 부분(Numerical Recipes betacf — 수정 Lentz)."""
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > _CF_TINY else _CF_TINY)
    h = d
    for m in range(1, _CF_MAX_ITER + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > _CF_TINY else _CF_TINY)
        c = 1.0 + aa / c
        c = c if abs(c) > _CF_TINY else _CF_TINY
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > _CF_TINY else _CF_TINY)
        c = 1.0 + aa / c
        c = c if abs(c) > _CF_TINY else _CF_TINY
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < _CF_EPS:
            return h
    raise ArithmeticError(f"불완전 베타 연분수가 {_CF_MAX_ITER}번 안에 모이지 않았다(a={a}, b={b}, x={x})")


def betainc(a: float, b: float, x: float) -> float:
    """정칙 불완전 베타 I_x(a, b) — a, b > 0, 0 ≤ x ≤ 1."""
    if a <= 0 or b <= 0:
        raise ValueError(f"betainc 의 a·b 는 양수다 — a={a}, b={b}")
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    front = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x))
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def binom_upper(k: int, n: int, *, alpha: float = ALPHA) -> float | None:
    """k/n 의 정확 이항 단측 (1 − α) 상한. n 이 0 이면 None(표본이 없다 — 0 으로 적지 않는다), k == n 이면 1.0.

    k = 0 이면 닫힌 꼴 1 − α^(1/n) 과 같다(0/59 → 0.0495). 정수가 아니거나 0 ≤ k ≤ n 밖이면 ValueError 다."""
    if isinstance(k, bool) or isinstance(n, bool) or not isinstance(k, int) or not isinstance(n, int):
        raise ValueError(f"binom_upper 의 k·n 은 정수다 — k={k!r}, n={n!r}")
    if n < 0 or k < 0 or k > n:
        raise ValueError(f"binom_upper 는 0 ≤ k ≤ n 이다 — k={k}, n={n}")
    if not 0.0 < alpha < 1.0:
        raise ValueError(f"alpha 는 (0, 1) 안이다 — {alpha}")
    if n == 0:
        return None
    if k == n:
        return 1.0
    if k == 0:
        return 1.0 - alpha ** (1.0 / n)
    target = 1.0 - alpha
    lo, hi = k / n, 1.0                      # 상한은 점추정 위에 있다
    for _ in range(_BISECT_STEPS):
        mid = (lo + hi) / 2.0
        if betainc(k + 1, n - k, mid) < target:
            lo = mid
        else:
            hi = mid
    return hi
