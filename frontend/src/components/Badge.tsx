// 상태 배지 — 라벨은 서버가 준 문자열 그대로 쓰고(§8.2.4 '배지 = 저장 값과 같은 문자열') 색만 여기서 고른다.
import type { ReactNode } from "react";
import type {
  BatchJobState,
  CoverageLevel,
  CoverageStatus,
  EvidenceGrade,
  ExternalSync,
  Judgement,
  PanelStatus,
  RegistryStatus,
  Severity,
  SnapshotJobState,
  SourceStatus,
  Verdict,
} from "../types";

/** 색 축. 판단을 새로 만들지 않고 저장 값 → 색만 대응시킨다. */
export type Tone = "neutral" | "ok" | "warn" | "bad" | "info" | "muted";

export function Badge({
  tone = "neutral",
  title,
  children,
}: {
  tone?: Tone;
  title?: string;
  children: ReactNode;
}) {
  return (
    <span className={`rr-badge rr-badge-${tone}`} title={title}>
      {children}
    </span>
  );
}

const TONES: Record<string, Tone> = {
  // severity
  "경미": "info",
  "중대": "warn",
  "치명": "bad",
  // judgement
  OK: "ok",
  WARNING: "warn",
  FAIL: "bad",
  undetermined: "muted",
  // 소스 카드
  unlinked: "muted",
  linked: "ok",
  unreachable: "bad",
  // 잡(스냅샷·배치)
  queued: "muted",
  running: "info",
  paused: "warn",
  cancelling: "warn",
  cancelled: "muted",
  completed: "ok",
  failed: "bad",
  done: "ok",
  // 커버리지
  pending: "warn",
  assigned: "info",
  done_weak: "warn",
  abstain: "muted",
  skipped: "muted",
  deferred: "muted",
  carried: "warn",
  // 패널
  planned: "muted",
  error: "bad",
  // 등록부
  open: "info",
  verified: "ok",
  dismissed: "muted",
  mitigated: "info",
  superseded: "muted",
  // 완결 레벨
  C0: "muted",
  C1: "info",
  C2: "info",
  "C2(closed)": "ok",
  C3: "ok",
  // verdict
  go: "ok",
  conditional: "warn",
  "no-go": "bad",
  // external_sync
  unavailable: "muted",
  // 근거 등급
  "측정": "ok",
  "문헌·규격": "ok",
  "도구예측": "info",
  "경험칙": "muted",
};

export function toneOf(value: string | null | undefined): Tone {
  if (!value) return "muted";
  return TONES[value] ?? "neutral";
}

/** 어휘를 모르는 값도 받는 범용 배지 — 모르는 값은 중립색으로 그대로 보인다. */
export function StatusBadge({ value, title }: { value: string | null | undefined; title?: string }) {
  if (!value) return <Badge tone="muted">-</Badge>;
  return (
    <Badge tone={toneOf(value)} title={title}>
      {value}
    </Badge>
  );
}

export const SeverityBadge = ({ value }: { value: Severity | string }) => <StatusBadge value={value} />;
export const JudgementBadge = ({ value }: { value: Judgement | string }) => <StatusBadge value={value} />;
export const EvidenceGradeBadge = ({ value }: { value: EvidenceGrade | string }) => <StatusBadge value={value} />;
export const SourceStatusBadge = ({ value }: { value: SourceStatus | string }) => <StatusBadge value={value} />;
export const CoverageStatusBadge = ({ value }: { value: CoverageStatus | string }) => <StatusBadge value={value} />;
export const PanelStatusBadge = ({ value }: { value: PanelStatus | string }) => <StatusBadge value={value} />;
export const RegistryStatusBadge = ({ value }: { value: RegistryStatus | string }) => <StatusBadge value={value} />;
export const LevelBadge = ({ value }: { value: CoverageLevel | string }) => <StatusBadge value={value} />;
export const VerdictBadge = ({ value }: { value: Verdict | string }) => <StatusBadge value={value} />;
export const JobStateBadge = ({ value }: { value: SnapshotJobState | BatchJobState | string }) => (
  <StatusBadge value={value} />
);

/** RA·AIDataHub 반영 상태 두 칸(§5.5.3). */
export function ExternalSyncBadge({ sync }: { sync: ExternalSync | null | undefined }) {
  if (!sync) return null;
  return (
    <span className="rr-badge-group">
      <Badge tone={toneOf(sync.ra)} title="ReportArchive 반영">
        RA {sync.ra}
      </Badge>
      <Badge tone={toneOf(sync.adh)} title="AIDataHub 반영">
        ADH {sync.adh}
      </Badge>
    </span>
  );
}

/** 진행판 상시 배지 — 'C3 미달' 이 숨지 않게 한다(§6.9). */
export function UnseatedBadge({ n }: { n: number }) {
  if (n <= 0) return <Badge tone="ok">전원 착석(C3)</Badge>;
  return (
    <Badge tone="warn" title="비종결 좌석 수. 사용자 요구('전원 한 번씩')의 문자적 충족은 C3 다.">
      미착석 {n}명(C3 미달)
    </Badge>
  );
}
