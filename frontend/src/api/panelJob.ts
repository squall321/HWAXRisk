// 패널 잡(Tier A · B · C) 만들기의 본문 · 시작 가능 여부 · 거절 문구 — GLM 잡의 본문은 판단 LLM 칸이 생기기 전과 바이트로 같다.
import { isApiError } from "./risk.api";
import type { TargetJobCreate, Tier } from "../types";

/** 판단 LLM — glm 은 이 박스의 LLM(기본), claude 는 잡을 만든 사람의 Claude Code 워크플로(hwax-risk-claude)다. */
export type JudgeLlm = "glm" | "claude";

/** 잡 주인이 Claude Code 에서 돌리는 워크플로(백엔드 runner.EXTERNAL_WORKFLOW 와 같은 이름). */
export const EXTERNAL_WORKFLOW = "hwax-risk-claude";

/**
 * 반출 경고 — 검토 잡의 경고(백엔드 review_runner.EGRESS_WARNING)에 패널 잡이 내보내는 것(그 패널의 브리프 · 좌석 조회 결과)을
 * 붙인 뜻이다(포털 docs/claude-delib-parity/frontend-request.md 2절).
 */
export const PANEL_EGRESS_WARNING =
  "판단 LLM 을 Claude 로 고르면 이 잡이 돌리는 패널마다 그 패널의 브리프(설계 변경 · 근거 · 메모 — 선례처럼 다른 사람의 검토 결과도" +
  " 든다)와 좌석이 조회한 결과가 Claude(외부)로 나갑니다. 판단은 내 Claude Code 의 워크플로가 하고, 잡은 동의한 내 포털 PAT 로만 돕니다.";

/** 패널 잡 만들기 폼의 값 — 입력란 그대로(다듬기는 본문을 지을 때 한다). */
export type PanelJobForm = {
  tier: Tier;
  concurrency: number;
  /** 쉼표로 나눈 수정자. */
  modifiers: string;
  memo: string;
  /** Tier C 명시 승인 체크. */
  tierConsent: boolean;
  llm: JudgeLlm;
  /** 반출 동의 체크 — 사람이 경고를 보고 체크했을 때만 참이다. 화면이 미리 체크해 두지 않는다. */
  externalConsent: boolean;
};

/**
 * 본문 — 앞의 다섯 칸은 판단 LLM 선택이 생기기 전의 본문과 같은 순서 · 같은 값이다(JSON 으로 바이트가 같다). Claude 일 때만
 * `llm` 을 덧붙이고, 반출 동의를 체크했을 때만 `consent_external: true` 를 덧붙인다. GLM 은 `llm` 을 싣지 않는다(없음 = glm).
 */
export function panelJobBody(form: PanelJobForm): TargetJobCreate {
  const body: TargetJobCreate = {
    tier: form.tier,
    concurrency: form.concurrency,
    modifiers:
      form.modifiers.trim() === ""
        ? undefined
        : form.modifiers
            .split(",")
            .map((s) => s.trim())
            .filter(Boolean),
    user_memo: form.memo.trim() === "" ? undefined : form.memo.trim(),
    consent: form.tier === "C" ? form.tierConsent : undefined,
  };
  if (form.llm === "claude") {
    body.llm = "claude";
    if (form.externalConsent === true) body.consent_external = true;
  }
  return body;
}

/** 시작 버튼을 열어도 되나 — Tier C 는 명시 승인, Claude 는 반출 동의가 체크돼 있어야 한다. */
export function panelJobReady(form: PanelJobForm): boolean {
  if (form.tier === "C" && !form.tierConsent) return false;
  if (form.llm === "claude" && !form.externalConsent) return false;
  return true;
}

/** 거절의 갈래 — 화면이 덧붙일 다음 걸음. */
export type JobErrorNext = "settings" | "use_glm" | null;

/**
 * 패널 잡 만들기의 거절(runner.create_job · panel_job_gate · review_runner.check_llm_choice · require_external_llm)을 code 로 가른다.
 * 서버 글(`message`)은 고칠 곳까지 말하므로 화면은 제목과 다음 걸음만 고르고 글은 그대로 보인다. 모르는 code 는 null —
 * 공용 배너(describeError)가 말한다.
 */
export function describeJobError(err: unknown): { title: string; next: JobErrorNext } | null {
  if (!isApiError(err)) return null;
  switch (err.code) {
    case "consent_external_required":
      return { title: "Claude 로 고르려면 반출 동의가 필요합니다.", next: null };
    case "pat_unavailable":
      return { title: "내 포털 PAT 가 없어 잡을 시작하지 못했습니다.", next: "settings" };
    case "external_llm_unavailable":
      return { title: "이 박스는 Claude 길을 열지 않았습니다.", next: "use_glm" };
    case "flow_mismatch":
      return { title: "이 대상은 카드 대조 방식이라 Tier 패널 잡을 세우지 않습니다.", next: null };
    case "review_job_running":
      return { title: "이 대상에 살아 있는 카드 대조 검토 잡이 있습니다.", next: null };
    default:
      return null;
  }
}
