# 앱이 쓸 수 있는 감사 행위(rr_audit.action)마다 화면 이력 탭에 이름표가 있는지 — 행위는 앱 소스(AST)에서, 이름표는 화면 사전에서 읽는다
"""과제 이력 탭(B34 — frontend ProjectAuditCard 의 ACTION_LABEL)은 아는 행위에만 뜻을 붙이고 모르는 행위는 코드만 보인다. 앱이 새 행위를
쓰기 시작하면서 이름표를 잊으면 화면에 코드만 남는다 — 이 시험이 그것을 막는다(사용자 결정 10-31 · 이력 탭 이름표 후속). 화면 소스를 읽는
것은 test_client_contract 와 같은 꼴이다.

행위 목록은 손으로 적지 않고 앱 소스에서 끌어낸다 — rr_audit 에 쓰는 자리를 AST 로 훑는다.
1. `INSERT INTO rr_audit` 를 싣는 SQL 을 부르는 호출마다 action 칸을 읽는다 — SQL 글자면 그것, 자리표(?)면 매개 튜플의 그 자리 식이다.
   그 식이 감싼 함수의 매개(routes._audit 의 action)면 그 함수를 '쓰는 함수' 로 삼는다.
2. 쓰는 함수를 부르는 곳마다 action 인자를 푼다 — 글자 · 조건식(두 갈래) · 그 함수 안에서 글자로만 정해지는 이름 · f-string(앞 글자마다
   앱의 열거로 펼친다 — FAMILIES).
풀 수 없는 식이나 모르는 f-string 꼴을 만나면 실패한다(새 꼴이면 펼침을 더한다) — 조용히 빠뜨리지 않는다.
"""
from __future__ import annotations

import ast
import re
from collections.abc import Callable
from pathlib import Path

from app import routes

APP = Path(__file__).resolve().parents[1] / "app"
LABELS = Path(__file__).resolve().parents[2] / "frontend" / "src" / "components" / "ProjectAuditCard.tsx"
_INSERT = re.compile(r"INSERT\s+INTO\s+rr_audit\s*\(([^)]*)\)\s*VALUES\s*\(([^)]*)\)", re.S)


def _modules() -> dict[str, ast.Module]:
    return {str(path.relative_to(APP)): ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for path in sorted(APP.rglob("*.py"))}


def _functions(module: ast.Module) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    return [n for n in ast.walk(module) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


def _guard_values(function: str, param: str) -> list[str]:
    """그 함수가 `if <param> not in (<글자>…)` 로 받는 값 — 셀 처분(dispose_cells)의 행위는 그 검사가 정한다."""
    for module in _modules().values():
        for fn in _functions(module):
            if fn.name != function:
                continue
            for node in ast.walk(fn):
                if (isinstance(node, ast.Compare) and isinstance(node.left, ast.Name) and node.left.id == param
                        and isinstance(node.ops[0], ast.NotIn) and isinstance(node.comparators[0], (ast.Tuple, ast.Set))):
                    return [e.value for e in node.comparators[0].elts if isinstance(e, ast.Constant)]
    raise AssertionError(f"{function} 의 {param} 검사를 찾지 못했다 — 셀 처분 행위의 펼침을 다시 본다")


# f-string 행위의 꼴 — 앞 글자 → 그 꼴을 펼치는 앱의 열거. 새 꼴이 생기면 여기에 더한다(모르는 꼴은 실패한다).
FAMILIES: dict[str, Callable[[], list[str]]] = {
    "job.": lambda: list(routes.JOB_ACTIONS),                    # routes._audit_job_control — 잡 제어
    "issue.": lambda: list(routes.ISSUE_ACTIONS),                # routes.put_issue — 쟁점 결정
    "cells.": lambda: _guard_values("dispose_cells", "action"),  # review_runner.dispose_cells — 셀 처분
}


def _resolve(expr: ast.expr, fn: ast.FunctionDef | ast.AsyncFunctionDef, where: str) -> set[str]:
    """action 식 하나가 낼 수 있는 행위 이름 전부."""
    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        return {expr.value}
    if isinstance(expr, ast.IfExp):
        return _resolve(expr.body, fn, where) | _resolve(expr.orelse, fn, where)
    if isinstance(expr, ast.JoinedStr):
        head = expr.values[0]
        prefix = head.value if isinstance(head, ast.Constant) else ""
        assert len(expr.values) == 2 and isinstance(expr.values[1], ast.FormattedValue) and prefix in FAMILIES, (
            f"{where}: 모르는 f-string 행위 꼴 {ast.unparse(expr)!r} — FAMILIES 에 펼침을 더한다")
        return {prefix + value for value in FAMILIES[prefix]()}
    if isinstance(expr, ast.Name):
        values = [node.value for node in ast.walk(fn) if isinstance(node, ast.Assign)
                  and any(isinstance(t, ast.Name) and t.id == expr.id for t in node.targets)]
        assert values, f"{where}: {expr.id} 를 정하는 대입이 없다 — 이 시험이 풀지 못하는 행위 식이다"
        return set().union(*(_resolve(value, fn, where) for value in values))
    raise AssertionError(f"{where}: 풀지 못하는 행위 식 {ast.unparse(expr)!r} — 이 시험에 그 꼴을 더한다")


def _sql(node: ast.expr) -> str | None:
    """호출의 첫 인자가 글자(이어 붙인 글자 포함)면 그 글."""
    try:
        value = ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError):
        return None
    return value if isinstance(value, str) else None


def backend_actions() -> dict[str, set[str]]:
    """앱이 rr_audit 에 쓸 수 있는 행위 이름 → 그것을 쓰는 자리(파일:줄)."""
    modules = _modules()
    found: dict[str, set[str]] = {}
    writers: dict[str, int | None] = {}      # 행위를 매개로 받는 쓰는 함수 이름 → 그 매개의 자리(키워드 전용이면 None)

    def note(names: set[str], where: str) -> None:
        for name in names:
            found.setdefault(name, set()).add(where)

    for rel, module in modules.items():
        for fn in _functions(module):
            for call in (n for n in ast.walk(fn) if isinstance(n, ast.Call) and n.args):
                sql = _sql(call.args[0])
                match = _INSERT.search(sql) if sql else None
                if match is None:
                    continue
                where = f"{rel}:{call.lineno}"
                columns = [c.strip() for c in match.group(1).split(",")]
                values = [v.strip() for v in match.group(2).split(",")]
                slot = values[columns.index("action")]
                if slot != "?":
                    note({slot.strip("'")}, where)
                    continue
                params = call.args[1]
                assert isinstance(params, ast.Tuple), f"{where}: 매개가 튜플 글자가 아니다 — 이 시험이 action 칸을 읽지 못한다"
                expr = params.elts[values[:columns.index("action")].count("?")]
                args = [a.arg for a in (*fn.args.posonlyargs, *fn.args.args)]
                if isinstance(expr, ast.Name) and (expr.id in args or expr.id in [a.arg for a in fn.args.kwonlyargs]):
                    writers[fn.name] = args.index(expr.id) if expr.id in args else None
                    continue
                note(_resolve(expr, fn, where), where)
    assert writers, "행위를 매개로 받는 쓰는 함수(routes._audit)를 찾지 못했다"

    for rel, module in modules.items():
        for fn in _functions(module):
            for call in (n for n in ast.walk(fn) if isinstance(n, ast.Call)):
                callee = call.func.attr if isinstance(call.func, ast.Attribute) else getattr(call.func, "id", None)
                if callee not in writers or fn.name == callee:
                    continue
                where = f"{rel}:{call.lineno}"
                expr = next((k.value for k in call.keywords if k.arg == "action"), None)
                index = writers[callee]
                if expr is None and index is not None and len(call.args) > index:
                    expr = call.args[index]
                assert expr is not None, f"{where}: {callee} 를 action 없이 부른다"
                note(_resolve(expr, fn, where), where)
    return found


def frontend_labels() -> dict[str, str]:
    """화면 이력 탭의 이름표 사전(ACTION_LABEL)의 열쇠와 말."""
    text = LABELS.read_text(encoding="utf-8")
    block = re.search(r"ACTION_LABEL\b[^=]*=\s*\{(.*?)\n\};", text, re.S)
    assert block, f"{LABELS} 에서 ACTION_LABEL 사전을 찾지 못했다 — 이름표가 옮겨 갔으면 이 시험의 자리도 옮긴다"
    return dict(re.findall(r"""^\s*["']([^"']+)["']\s*:\s*["']([^"']*)["']""", block.group(1), re.M))


def test_every_audit_action_the_app_can_write_has_a_label_on_the_history_tab():
    """앱 소스에서 끌어낸 행위마다 이력 탭 이름표가 있다(말이 빈 것도 없다). 없으면 그 행위와 쓰는 자리를 말한다."""
    actions = backend_actions()
    labels = frontend_labels()
    missing = {name: sorted(where) for name, where in sorted(actions.items()) if not labels.get(name, "").strip()}
    assert not missing, f"이력 탭 이름표가 없는 감사 행위 — frontend ProjectAuditCard ACTION_LABEL 에 더한다: {missing}"


def test_the_scan_reaches_every_kind_of_audit_write():
    """훑기가 녹슬어 빈손으로 지나가지 않게 — 쓰는 꼴마다 하나씩 실제로 찾는다(SQL 글자 rekey · 엔진 쪽 멈춤 job.pause, 매개 튜플의
    조건식 ra.*, 쓰는 함수의 글자 · 조건식 · 함수 안 대입 · f-string 셋)."""
    actions = backend_actions()
    assert {"rekey", "job.pause", "ra.retract", "ra.remark", "gate.ack", "recall.approve", "curation.decide",
            "coverage.uncarry", "job.create", "issue.queue", "cells.skip", "coverage.undefer"} <= set(actions)
    assert any(where.startswith("runner.py:") for where in actions["job.pause"])     # 포털 '멈춤'(A24)의 SQL 글자
