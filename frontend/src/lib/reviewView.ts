// 카드 대조 검토의 순수 판정 — 사슬 배지 · 진행판 줄(거르기 · 입력 결손 · 처분 · 잡) · 셀 상태 말 · 처분 사유 검사(포털 m3-frontend-request 1 ~ 3절)
import type {
  CellState,
  ChainStage,
  Coverage,
  DisposeJob,
  CellsDisposed,
  ReopenedExtra,
  ReviewCalls,
  ReviewFilter,
  ReviewJob,
  ReviewJobCreate,
  ReviewNoInput,
  ReviewScope,
} from "../types";

/** 살아 있는 잡 상태(runner.LIVE_JOB_STATES) — 진행판을 5초마다 다시 읽는 동안이다. */
export const LIVE_STATES: ReadonlySet<string> = new Set(["queued", "running", "paused", "cancelling"]);

/** 셀 상태의 사람 말 — 이름은 그대로 두고 말을 붙인다(요청서 2절: na_irrelevant 는 '거름', no_input 은 '입력 결손 — 판정 못 함'). */
export const CELL_STATE_LABEL: Record<CellState, string> = {
  pending: "대기",
  running: "도는 중",
  reviewed: "검토함",
  na_irrelevant: "거름",
  no_input: "입력 결손 — 판정 못 함",
  failed: "실패",
  skipped: "넘김",
};
export const CELL_STATES: readonly CellState[] = [
  "pending",
  "running",
  "reviewed",
  "na_irrelevant",
  "no_input",
  "failed",
  "skipped",
];

export function cellStateLabel(state: string): string {
  return (CELL_STATE_LABEL as Record<string, string>)[state] ?? state;
}

/** 0~1 비율을 '1.2%' 로 — null 은 표본이 없다는 뜻이라 그 말로 적는다(0% 가 아니다). */
export function pct1(value: number | null | undefined, none = "표본 없음"): string {
  if (value === null || value === undefined || Number.isNaN(value)) return none;
  return `${(value * 100).toFixed(1)}%`;
}

// ── 1절 — 사슬 ───────────────────────────────────────────────────────────────

export type StageView = {
  label: string;
  tone: "info" | "warn" | "ok" | "bad" | "muted";
  /** 멈춘 사슬 잡 — 재개 버튼(지금의 resumeJob). */
  resumable: boolean;
  /** 사람에게 남길 한 줄(멈춘 까닭 · PAT 없음 · 재기동 · 비우기). */
  note: string | null;
  /** 내 PAT 를 등록해야 집힌다 — 설정으로 가는 길. */
  needsPat: boolean;
};

/**
 * 사슬 배지(요청서 1절) — '쟁점 패널 중 · 종합 중 · 멈춤 · 끝'. `error` 의 머리가 뜻을 정한다 — `pat_unavailable:` 은 잡을 돌릴 PAT 가
 * 없어 줄에서 집히지 않는다(등록하면 저절로 집힌다), `restart:` 는 앱 재기동이 도는 쟁점 패널을 닫았다(사람이 재개 — 자동 재개는 M4),
 * `draining:` 은 update-all 이 비우는 동안이다.
 */
export function stageView(stage: ChainStage | null | undefined): StageView | null {
  if (!stage) return null;
  const what = stage.mode === "synth" ? "종합" : "쟁점 패널";
  const error = stage.error ?? "";
  const needsPat = error.startsWith("pat_unavailable");
  let note: string | null = null;
  if (needsPat) note = "이 잡을 돌릴 내 포털 PAT 가 없어 줄에서 집히지 않습니다 — PAT 를 등록하면 저절로 집힙니다.";
  else if (error.startsWith("restart:")) note = "앱 재기동이 도는 쟁점 패널을 닫았습니다 — 사람이 재개해야 합니다.";
  else if (error.startsWith("draining:")) note = "update-all 이 비우는 동안입니다 — 끝나면 이어 돕니다.";
  switch (stage.state) {
    case "queued":
    case "running":
      return { label: `${what} 중`, tone: "info", resumable: false, note, needsPat };
    case "paused": {
      const why = stage.hold_code ?? stage.pause_reason;
      return { label: `${what} 멈춤${why ? `(${why})` : ""}`, tone: "warn", resumable: true, note, needsPat };
    }
    case "cancelling":
      return { label: `${what} 취소 중`, tone: "warn", resumable: false, note, needsPat };
    case "completed":
      return { label: `${what} 끝`, tone: "ok", resumable: false, note, needsPat };
    case "failed":
      return { label: `${what} 실패`, tone: "bad", resumable: false, note, needsPat };
    case "cancelled":
      return { label: `${what} 취소됨`, tone: "muted", resumable: false, note, needsPat };
    default:
      return { label: `${what} ${stage.state}`, tone: "muted", resumable: false, note, needsPat };
  }
}

/** `stage.advice` 의 말 — 잡은 멈추지 않는다(계속할지 사람이 정한다). */
export function adviceText(advice: string | null | undefined): string | null {
  if (advice === "issue_yield_low") {
    return "최근 쟁점 패널 다섯이 전부 기각 · 판정 못 함입니다 — 잡은 멈추지 않습니다. 계속할지 사람이 정합니다.";
  }
  return advice ? advice : null;
}

/**
 * M2 시절 잡 뒤의 사슬 시작(요청서 1절) — M2 앱이 세운 검토 잡이 끝난 대상에는 쟁점 · 종합이 저절로 서지 않는다. 사슬도 판도 없고
 * 마지막 검토 잡이 끝났고 대기 셀이 없으면 '쟁점·종합 시작'(검토 잡을 한 번 더 — 셀이 다 닫혀 호출 없이 끝나고 그 끝에서 사슬이 선다).
 */
export function chainStartVisible(coverage: Pick<Coverage, "stage" | "report" | "review" | "flow"> | null): boolean {
  if (!coverage || coverage.flow !== "cells") return false;
  const review = coverage.review;
  return (
    coverage.stage === null &&
    coverage.report === null &&
    review !== null &&
    review.job?.state === "completed" &&
    review.cells.by_state.pending === 0
  );
}

/** 막음이고 확인되지 않은 잔여 수 — 대상 머리의 '완결 확인' 표지. */
export function blockingUnacked(qualifiers: Coverage["qualifiers"]): number {
  return (qualifiers ?? []).filter((q) => q.blocking && !q.acked).length;
}

// ── 2절 — 진행판 줄 ──────────────────────────────────────────────────────────

/**
 * 거르기 줄 — '거름 N셀 · 표본 S · 놓친 걸림 M · 95% 상한 X%'. 배정표 승인 전(approved false)이면 아무 셀도 거르지 않는다는 말,
 * 검토 잡 전(approved null)이면 그 사실을 적는다. 넓힌 영역 · 끔 · 그림자 모드는 따로 한 줄씩이다.
 */
export function filterLines(filter: ReviewFilter): string[] {
  const out: string[] = [];
  if (filter.approved === false) {
    out.push(`배정표 승인 전 — 거르지 않는다(거르기 ${filter.mode}).`);
  } else if (filter.approved === null) {
    out.push(`검토 잡 전 — 거르기 설정이 아직 없다(거르기 ${filter.mode}).`);
  } else {
    out.push(
      `거름 ${filter.filtered}셀 · 표본 ${filter.audited} · 놓친 걸림 ${filter.audit.risk_miss} · 95% 상한 ${pct1(filter.audit.upper95)}` +
        ` (거르기 ${filter.mode})`,
    );
  }
  if (filter.mode === "shadow") {
    out.push(
      `그림자 — 걸렀을 셀 ${filter.shadow.would_filter} · 표본 ${filter.shadow.sampled} · 놓친 걸림 ${filter.shadow.risk_miss}` +
        ` · 95% 상한 ${pct1(filter.shadow.upper95)}`,
    );
  }
  if (filter.audit.pending > 0) out.push(`결과를 기다리는 표본 ${filter.audit.pending}`);
  if (filter.widened.length > 0) out.push(`넓힌 영역 ${filter.widened.join(" · ")}`);
  if (filter.off) out.push("이 대상의 거르기를 껐다(넓힌 영역 셋 이상).");
  return out;
}

/** 입력 결손 줄 — '입력 결손 N명 · M셀(영향 있음 a · 모름 b · 확인할 것 c · 없음 d)'. */
export function noinputLine(noinput: ReviewNoInput): string {
  const o = noinput.by_outcome;
  return (
    `입력 결손 ${noinput.experts}명 · ${noinput.cells}셀(영향 있음 ${o.impact} · 모름 ${o.unknown} · 확인할 것 ${o.request}` +
    ` · 없음 ${o.none})`
  );
}

export function dispositionsLine(d: { retried: number; skipped: number }): string {
  return `사람이 다시 연 셀 ${d.retried} · 넘긴 셀 ${d.skipped}`;
}

/** 잡 단계의 말 — live 는 근거 꾸러미 실호출, 끝난 잡은 그 상태 이름 그대로다. */
export function phaseLabel(phase: string | null | undefined): string {
  switch (phase) {
    case "live":
      return "근거 꾸러미 실호출";
    case "pack":
      return "카드 묶음";
    case "review":
      return "검토";
    case null:
    case undefined:
    case "":
      return "진행판 전";
    default:
      return phase;
  }
}

/** 다시 연 셀 몫 — 셀이 있을 때만 '다시 연 셀 N(추정 M회 · 여유 A회)'. */
export function reopenedLine(extra: ReopenedExtra | null | undefined): string | null {
  if (!extra || extra.cells <= 0) return null;
  const waiting = extra.unconsented.cells > 0
    ? ` · 동의 안 받은 ${extra.unconsented.cells}셀(추정 ${Math.round(extra.unconsented.calls_est)}회)`
    : "";
  return `다시 연 셀 ${extra.cells}(추정 ${Math.round(extra.calls_est)}회 · 여유 ${extra.allowance}회)${waiting}`;
}

/** 초를 '3시간 20분' 꼴로. */
export function fmtDuration(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (h >= 24) return `${Math.floor(h / 24)}일 ${h % 24}시간`;
  if (h > 0) return `${h}시간 ${m}분`;
  if (m > 0) return `${m}분`;
  return `${s}초`;
}

/**
 * 호출 줄 — 'ok N / 추정 E' 와 남은 시간 어림. 추정 E 는 잡을 만들 때의 expected(거르기 없음 가정이라 실제보다 크다)이고, 어림은
 * 남은 호출 × 평균 호출 초 ÷ 지금 도는 호출 수다. 셀 수 없는 것(평균 · 추정이 없다)은 말하지 않는다.
 */
export function callsLine(
  calls: Partial<ReviewCalls> | null | undefined,
  expected: number | null | undefined,
  activeWorkers: number,
): { head: string; eta: string | null; tail: string | null } {
  const ok = calls?.ok;
  if (ok === undefined || ok === null) return { head: "호출 셈 전(진행판을 아직 세지 않았다)", eta: null, tail: null };
  const head = expected ? `호출 ok ${ok} / 추정 ${expected}` : `호출 ok ${ok}`;
  const fails = [
    calls?.infra_fail ? `인프라 실패 ${calls.infra_fail}` : null,
    calls?.content_fail ? `내용 실패 ${calls.content_fail}` : null,
    calls?.wait ? `기다림 ${calls.wait}` : null,
    calls?.aborted ? `끊김 ${calls.aborted}` : null,
  ].filter(Boolean);
  let eta: string | null = null;
  if (expected && calls?.avg_ok_s && expected > ok) {
    const lanes = Math.max(1, activeWorkers);
    eta =
      `남은 시간 어림 ${fmtDuration(((expected - ok) * calls.avg_ok_s) / lanes)}` +
      `(남은 ${expected - ok}회 × 평균 ${calls.avg_ok_s}초 ÷ 도는 호출 ${lanes} — 추정이 거르기 없음 가정이라 실제보다 길다)`;
  }
  return { head, eta, tail: fails.length > 0 ? fails.join(" · ") : null };
}

// ── 3-5 — 보류와 재개 ───────────────────────────────────────────────────────

export type HoldView = {
  /** 다시 연 셀 몫의 보류(보류 코드가 아니라 reopened_extra.hold 로 가른다 — 요청서 3-5). */
  reopenHold: "consent_extra" | "max_calls" | null;
  /** 재개 버튼 — 몫이 consent_extra 면 동의를 받아 consent=true 로, max_calls 면 재개가 풀리지 않아 끈다. */
  resume: "plain" | "consent" | "blocked" | null;
  /** 기다리는 셀 넘기기 버튼(filter state pending)을 앞에 두나. */
  skipWaiting: boolean;
};

/**
 * 멈춘 검토 잡의 버튼(요청서 3-5). 사람이 멈췄거나 자격 보류인 잡도 몫이 넘쳐 있으면 재개에 같은 동의가 든다 — 보류 코드가 아니라
 * `reopened_extra.hold` 로 판단한다. max_calls 는 동의로 풀리지 않아(재개는 409) 재개 대신 넘김 버튼을 앞에 둔다.
 */
export function holdView(job: Pick<ReviewJob, "state" | "progress"> | null | undefined): HoldView {
  const reopenHold = job?.progress?.reopened_extra?.hold ?? null;
  if (!job || job.state !== "paused") return { reopenHold, resume: null, skipWaiting: false };
  if (reopenHold === "max_calls") return { reopenHold, resume: "blocked", skipWaiting: true };
  if (reopenHold === "consent_extra") return { reopenHold, resume: "consent", skipWaiting: true };
  return { reopenHold, resume: "plain", skipWaiting: false };
}

/**
 * 동의 체크가 가리키는 몫 — 잡 · 다시 연 셀 · 동의한 셀 · 동의를 기다리는 셀과 그 추정 호출. 체크는 이 열쇠에 묶인다 — 몫이 바뀌면
 * (기다리는 셀을 넘기고 이어 돌다 더 큰 몫으로 다시 멈추면) 체크가 비어 그 몫에 다시 동의받는다. 몫이 없으면 null.
 */
export function consentAmountKey(jobId: string, extra: ReopenedExtra | null | undefined): string | null {
  if (!extra) return null;
  return [jobId, extra.cells, extra.consented.cells, extra.unconsented.cells, extra.unconsented.calls_est].join(":");
}

// ── 3-3 · 3-4 — 처분 ─────────────────────────────────────────────────────────

/** 처분 · 보류 풀기 사유(routes._human_reason) — 앞뒤 공백을 뗀 4~300자. 300자 초과는 FastAPI 422 라 화면이 먼저 막는다. */
export const REASON_MIN = 4;
export const REASON_MAX = 300;

/** 사유를 보내기 전에 본다 — `required` 가 아니고 비었으면 문제 없음. 문제가 있으면 그 글. */
export function reasonProblem(reason: string, required: boolean): string | null {
  const text = reason.trim();
  if (text === "") return required ? `사유를 ${REASON_MIN}~${REASON_MAX}자로 적으세요.` : null;
  if (text.length < REASON_MIN) return `사유는 ${REASON_MIN}자 이상입니다 — 지금 ${text.length}자.`;
  if (text.length > REASON_MAX) return `사유는 ${REASON_MAX}자까지입니다 — 지금 ${text.length}자.`;
  return null;
}

/**
 * 처분이 잡에 한 일의 한 줄(dispose_cells 의 job). 넘김이 세운 잡은 돌 셀이 없는 마감 잡이다(그 전문가를 다시 마감해 보고서에
 * '넘김 — 사유' 를 싣는다).
 */
export function disposeJobLine(job: DisposeJob, kind: "retry" | "skip" = "retry"): string {
  switch (job.action) {
    case "created":
      if (kind === "skip") return `넘긴 셀만 묶은 마감 잡을 세웠습니다(${job.job_id ?? "?"} — 돌 셀 없이 그 전문가를 다시 마감합니다).`;
      return `그 셀만 묶은 검토 잡을 세웠습니다(${job.job_id ?? "?"}${job.calls_estimate ? ` · 호출 추정 ${job.calls_estimate.expected}회` : ""}).`;
    case "adopted": {
      const hold = job.hold ? ` 그 셀 몫 때문에 잡이 멈췄습니다(${job.hold}) — 진행판에서 동의하거나 기다리는 셀을 넘깁니다.` : "";
      const resumed = job.resumed ? " 몫이 여유 안으로 돌아와 그 잡이 이어 돕니다." : "";
      return `살아 있는 검토 잡(${job.job_id ?? "?"})이 집습니다 — 얹힘 ${job.adopted ?? 0} · 다음 잡 기다림 ${job.waiting ?? 0}.${hold}${resumed}`;
    }
    case "waiting":
      return `살아 있는 검토 잡(${job.job_id ?? "?"})의 범위 밖이라 다음 잡이 집습니다(${job.waiting ?? 0}셀).`;
    default:
      return "잡은 그대로입니다.";
  }
}

/**
 * 넘김의 걸림 셈(요청서 3-4) — '이미 판정된 걸림 N(카드 a · 카드 밖 b · 입력 결손 c)'. 얼린 묶음이 이 박스에 없으면(pack_missing)
 * 0 이 아니라 '모름' 이고 까닭(hits_note)을 그대로 보인다.
 */
export function hitsLine(out: Pick<CellsDisposed, "hits" | "hits_by" | "hits_basis" | "hits_note">): string | null {
  if (out.hits_basis === "pack_missing") return `이미 판정된 걸림 — 모름. ${out.hits_note ?? ""}`.trim();
  if (out.hits === undefined || out.hits === null || !out.hits_by) return null;
  return `이미 판정된 걸림 ${out.hits}(카드 ${out.hits_by.card} · 카드 밖 ${out.hits_by.offcard} · 입력 결손 ${out.hits_by.noinput})`;
}

// ── 3-1 — 검토 잡 본문 ───────────────────────────────────────────────────────

/** 검토 잡 만들기 폼의 값 — 목록 칸은 쉼표로 나눈 글이다(다듬기는 본문을 지을 때 한다). */
export type ReviewJobForm = {
  tiers: string[];
  domains: string[];
  /** 쉼표로 나눈 전문가 키. */
  agents: string;
  /** 쉼표로 나눈 단위 id. */
  unitIds: string;
  memo: string;
  /** 사람이 추정을 보고 체크했을 때만 참이다 — 화면이 미리 체크해 두지 않는다. */
  consent: boolean;
};

function splitList(text: string): string[] {
  return Array.from(new Set(text.split(",").map((s) => s.trim()).filter(Boolean)));
}

/**
 * 검토 잡 본문(routes.JobBody mode reviews) — 범위는 빈 칸을 빼고 싣는다(빠진 칸은 전부 — 빈 목록을 보내면 서버가 422 scope_invalid
 * 다). 범위가 다 비면 scope 를 싣지 않는다(로스터 전원). 동의는 체크했을 때만 `consent: true` 다.
 */
export function reviewJobBody(form: ReviewJobForm): ReviewJobCreate {
  const scope: ReviewScope = {};
  if (form.tiers.length > 0) scope.tiers = [...form.tiers];
  if (form.domains.length > 0) scope.domains = [...form.domains];
  const agents = splitList(form.agents);
  if (agents.length > 0) scope.agents = agents;
  const units = splitList(form.unitIds);
  if (units.length > 0) scope.unit_ids = units;
  const body: ReviewJobCreate = { mode: "reviews" };
  if (Object.keys(scope).length > 0) body.scope = scope;
  if (form.memo.trim() !== "") body.user_memo = form.memo.trim();
  if (form.consent === true) body.consent = true;
  return body;
}
