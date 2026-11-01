// 종합 보고서 — part 탭(본문 · 영역 · 메커니즘 · 부록) · 쪽 넘김 · 판 대조, 머리(제목 · 계기 · 시각 · 서술 정도), '다시 내기'(코드 조립 판) · '요약부터 다시'(종합 잡)(포털 m3-frontend-request 5절)
import { useState } from "react";
import { Link } from "react-router-dom";
import { riskApi } from "../api/risk.api";
import { KeyValueTable } from "./DataTable";
import { ReportPager, isAbsent } from "./ReportPager";
import { ReviewErrorBanner } from "./ReviewErrorBanner";
import { SectionCard } from "./SectionCard";
import { EmptyBlock } from "./StateBlocks";
import { LockNote } from "./LockNote";
import { Banner, Button, Mono } from "../ui/primitives";
import { LIVE_STATES } from "../lib/reviewView";
import { narrativeNote, triggerLabel } from "../lib/reportView";
import { fmtEpoch } from "../format";
import { writeAccess } from "../lib/access";
import type { ChainStage, ProjectRole, ReportAssembled, SynthJobCreated, SynthPart } from "../types";

const PARTS: ReadonlyArray<{ part: SynthPart; label: string }> = [
  { part: "summary", label: "본문" },
  { part: "domains", label: "영역" },
  { part: "mechanisms", label: "메커니즘" },
  { part: "appendix", label: "부록" },
];

/**
 * 앱 사본이 정본이다(RA 투영은 M4). 표 · 수는 코드이고 서술만 LLM 이다. 판은 지금 판만 읽히고(version 은 대조 칸), 확인 · 쟁점 ·
 * 종합이 새 판을 세우면 다음 쪽부터 409 가 나 1쪽부터 다시 받는다.
 */
export function SynthReport({
  targetKey,
  stage,
  onChanged,
  role = null,
}: {
  targetKey: string;
  /** 진행판의 사슬 단계 — 살아 있는 종합 잡이 있으면 '요약부터 다시' 를 끈다(서버는 막지 않고 새 잡을 세운다). */
  stage: ChainStage | null;
  onChanged: () => void;
  /** 대상 과제의 내 역할(진행판 my_role) — 다시 내기 · 요약부터 다시는 편집자 이상이다(OI-2, 모르면 잠그지 않는다). */
  role?: ProjectRole | null;
}) {
  const access = writeAccess(role);
  const [nonce, setNonce] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [assembled, setAssembled] = useState<ReportAssembled | null>(null);
  const [synth, setSynth] = useState<SynthJobCreated | null>(null);
  const synthLive = stage !== null && stage.mode === "synth" && LIVE_STATES.has(stage.state);

  async function assemble() {
    setBusy(true);
    setError(null);
    setSynth(null);
    try {
      const out = await riskApi.assembleReport(targetKey);
      setAssembled(out);
      setNonce((n) => n + 1);
      onChanged();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  async function refresh() {
    setBusy(true);
    setError(null);
    setAssembled(null);
    try {
      setSynth(await riskApi.createSynthJob(targetKey));
      onChanged();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <SectionCard
      title="종합 보고서"
      subtitle="사슬의 단계마다 앱이 판을 세웁니다(앱 사본이 정본). 표 · 수는 코드이고 서술만 LLM 입니다."
      actions={
        <>
          <Button type="button" variant="outline" size="sm" onClick={assemble} disabled={busy || !access.allowed}
                  title={access.reason ?? undefined}>
            다시 내기
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={refresh}
            disabled={busy || synthLive || !access.allowed}
            title={synthLive ? "살아 있는 종합 잡이 있습니다 — 그 잡이 끝난 뒤 다시 냅니다." : access.reason ?? undefined}
          >
            요약부터 다시
          </Button>
        </>
      }
    >
      <LockNote access={access} />
      <ReviewErrorBanner error={error} />
      {synthLive ? (
        <p className="m-0 mb-2 text-sm text-muted-foreground">
          종합 잡 <Mono>{stage?.job_id}</Mono> 이 살아 있어 '요약부터 다시' 를 껐습니다.
        </p>
      ) : null}
      {assembled ? (
        <Banner
          tone="info"
          live="status"
          title={
            assembled.created
              ? `코드 조립 판 v${assembled.version_no} 를 세웠습니다(${assembled.pages_n}쪽).`
              : `직전 판과 내용이 같아 새 판을 만들지 않았습니다 — v${assembled.version_no}.`
          }
          detail={assembled.level_label}
        />
      ) : null}
      {synth ? (
        <Banner
          tone={synth.error ? "warn" : "info"}
          live="status"
          title={synth.created ? `종합 잡 ${synth.job_id} 을 세웠습니다 — 영역 요약 → 과제 종합 → 판.` : `대기 중인 종합 잡 ${synth.job_id} 이 이어 받습니다.`}
          detail={synth.error ?? undefined}
        >
          {synth.error?.startsWith("pat_unavailable") ? (
            <Link to="/settings" className="text-sm underline underline-offset-4">
              설정에서 PAT 등록
            </Link>
          ) : null}
        </Banner>
      ) : null}
      <ReportPager
        key={`${targetKey}#${nonce}`}
        idPrefix="synth-report"
        loadKey={`${targetKey}#${nonce}`}
        parts={PARTS}
        load={(query, signal) => riskApi.getReport(targetKey, query, { signal })}
        absent={(err) =>
          isAbsent(err, "report_absent") ? (
            <EmptyBlock
              title="이 대상에는 종합 보고서 판이 아직 없습니다."
              hint="사슬이 단계마다 판을 세웁니다. 지금 원장으로 바로 만들려면 '다시 내기'(코드 조립 판)를 누릅니다."
            />
          ) : null
        }
        header={(data) => (
          <div className="flex flex-col gap-2">
            <p className="m-0 text-sm font-semibold">{data.title}</p>
            <KeyValueTable
              rows={[
                { label: "완결 표기", hint: "level_label", value: data.level_label },
                { label: "계기", hint: "trigger", value: `${triggerLabel(data.trigger)} (${data.trigger})` },
                { label: "만든 시각", hint: "created_at", value: fmtEpoch(data.created_at) },
                { label: "판", hint: "version · report_uid", value: <span>v{data.version} · <Mono>{data.report_uid}</Mono></span> },
              ]}
            />
            {narrativeNote(data.narrative_state) ? (
              <Banner tone="warn" live="none" title={narrativeNote(data.narrative_state) as string} />
            ) : null}
          </div>
        )}
      />
    </SectionCard>
  );
}
