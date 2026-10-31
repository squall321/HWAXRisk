// 설정 화면 — 내 신원·포털 PAT 등록/삭제·이 박스 상태·동의 문구(계획 §8.2.4 SettingsPage 행).
import { useId, useState } from "react";
import { riskApi } from "../api/risk.api";
import { useAsync } from "../hooks/useAsync";
import { SectionCard } from "../components/SectionCard";
import { KeyValueTable } from "../components/DataTable";
import { ErrorBanner, EmptyBlock, LoadingBlock, NotReadyBlock } from "../components/StateBlocks";
import { Badge } from "../components/Badge";
import { useAutoPortalPat } from "../components/AutoPortalPat";
import { Clock, KeyRound, ShieldAlert, ShieldCheck } from "lucide-react";
import { Banner, Button, Chip, Field, FormField, Input, Mono, SubPanel } from "../ui/primitives";
import { cn } from "../lib/cn";
import { fmtEpoch } from "../format";
import type { PortalPatAuto, PortalPatDueReason, PortalPatSource, PortalPatSummary } from "../types";
import { MINT_BODY, registerFromPortal } from "../api/portalPat";
import { describePatFailure } from "../api/patErrors";

/** `identity.current` 가 신원을 어디서 읽었나(§8.2.1) — 코드값을 그대로 보이지 않는다. */
const ME_SOURCE: Record<string, string> = {
  cookie: "포털 세션 쿠키",
  bearer: "Authorization 헤더",
  sso: "게이트웨이 위임 단언",
  none: "없음(익명)",
};

/**
 * §8.2.4 동의 문구 — 실제 집행 수준까지만 약속한다.
 * 포털·게이트웨이는 아직 PAT 의 scopes 를 요청 경로에서 강제하지 않으므로(plan §10 #17 ② 결정 대기)
 * '읽기 전용 자격을 맡겼다' 고 읽히게 두지 않는다. 폐기는 포털 토큰 페이지에서 한다.
 */
const CONSENT_TEXT =
  "등록한 PAT 는 내 타깃의 무인 패널이 소스 앱을 읽고 심의 결정문을 내 이름의 포털 대화로 저장하는 데만 쓰입니다. " +
  "다만 포털은 아직 PAT 의 scopes 를 요청 단계에서 강제하지 않으므로 이 토큰 자체의 권한은 발급 시 선택한 범위보다 넓을 수 있습니다 — " +
  "쓰기를 막으려면 포털 토큰 페이지에서 폐기하세요.";

/** 발급 · 등록 실패 — 아는 것(발급 단계 · 등록 거절 code)은 전용 문구로, 나머지는 공용 배너로 접는다(api/patErrors). */
function PatErrorBanner({ error }: { error: unknown }) {
  if (error === null || error === undefined) return null;
  const known = describePatFailure(error);
  if (!known) return <ErrorBanner error={error} />;
  return <Banner title={known.title} detail={known.detail} />;
}

/** `auto.due_reason` 의 말 — 앞의 것이 먼저다(routes.pat_due_reason). */
const DUE_REASON: Record<PortalPatDueReason, string> = {
  absent: "등록된 PAT 가 없습니다",
  revoked: "포털에서 폐기됐습니다",
  undecryptable: "이 박스의 키로 풀리지 않습니다",
  expiring: "곧 끝납니다(갱신 문턱 밑)",
  audience: "청중 step-forge 가 없습니다 — 위임 캡처의 REST 다리가 닫힙니다",
};

/** `auto.last_source` 의 말 — 값은 hint 로 함께 보인다. */
const PAT_SOURCE: Record<PortalPatSource, string> = {
  web: "웹 화면에서 발급(web)",
  "gateway-exchange": "Claude 길 — 게이트웨이 교환(gateway-exchange)",
  manual: "붙여 넣은 PAT(manual)",
};

/**
 * PAT 상태를 **소리 내 말하는** 띠.
 *
 * 예전에는 `등록 상태 / email / groups / exp` 네 줄을 같은 크기로 늘어놓아, 만료된 PAT 과 멀쩡한
 * PAT 이 똑같이 보였다. 이 값이 죽으면 무인 패널이 통째로 멈추므로(그때 잡은 `pat_unavailable` 로
 * 조용히 queued 에 쌓인다) 화면이 먼저 말해야 한다. 서버가 주는데 안 그리던 `revoked_at`·`scopes`·
 * `jti` 도 함께 낸다 — 포털에서 폐기했는데 화면이 'registered' 라고 말하는 일이 없게.
 */
function PatStatus({ summary }: { summary: PortalPatSummary | null }) {
  if (!summary?.registered) {
    return (
      <div className="flex items-start gap-3 rounded-md border border-border bg-muted/40 px-4 py-3">
        <KeyRound className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
        <div className="text-sm">
          <div className="font-medium">등록된 PAT 이 없습니다.</div>
          <p className="mt-0.5 text-muted-foreground">
            이 자격이 없으면 무인 패널이 돌지 않습니다 —{" "}
            {summary?.auto.enabled
              ? "자동 등록이 켜져 있어 앱을 열 때 저절로 받아 등록합니다. 지금 하려면 아래 버튼을 누르세요."
              : "아래 버튼 한 번이면 포털에서 받아 등록합니다."}
          </p>
        </div>
      </div>
    );
  }

  const revoked = Boolean(summary.revoked_at);
  const leftMs = summary.exp ? summary.exp * 1000 - Date.now() : null;
  const expired = leftMs !== null && leftMs <= 0;
  // 러너는 만료 30분 전부터 그 자격을 쓰지 않는다(runner.CREDENTIAL_MARGIN_S) — 그 선을 화면도 쓴다.
  const soon = leftMs !== null && leftMs > 0 && leftMs < 24 * 3600 * 1000;
  const tone = revoked || expired ? "bad" : soon ? "warn" : "ok";
  const Icon = revoked || expired ? ShieldAlert : soon ? Clock : ShieldCheck;
  const headline = revoked
    ? "포털에서 폐기된 PAT 입니다."
    : expired
      ? "만료된 PAT 입니다."
      : soon
        ? "곧 만료됩니다."
        : "쓸 수 있는 PAT 이 등록돼 있습니다.";
  const detail = revoked
    ? "무인 패널이 이 자격으로 돌지 않습니다. 새로 발급해 등록하세요."
    : expired || soon
      ? "러너는 만료 30분 전부터 이 자격을 쓰지 않습니다. 지금 다시 발급하세요."
      : null;

  return (
    <div
      className={cn(
        "flex flex-col gap-3 rounded-md border px-4 py-3",
        tone === "bad"
          ? "border-destructive/30 bg-destructive/10"
          : tone === "warn"
            ? "border-warn/40 bg-warn/10"
            : "border-ok/30 bg-ok/10",
      )}
    >
      <div className="flex items-start gap-3">
        <Icon
          className={cn(
            "mt-0.5 size-4 shrink-0",
            tone === "bad" ? "text-destructive" : tone === "warn" ? "text-warn-foreground dark:text-warn" : "text-ok",
          )}
        />
        <div className="text-sm">
          <div className="font-medium">{headline}</div>
          {detail ? <p className="mt-0.5 text-muted-foreground">{detail}</p> : null}
        </div>
      </div>
      <dl className="grid grid-cols-2 gap-x-6 sm:grid-cols-4">
        <Field label="계정">{summary.email ?? "-"}</Field>
        <Field label="만료" hint="exp">
          {summary.exp ? (
            <span className={cn(expired && "text-destructive")}>
              {fmtEpoch(summary.exp)}
              {leftMs !== null ? (
                <span className="ml-1.5 text-xs text-muted-foreground">
                  {expired ? `${Math.floor(-leftMs / 3600000)}시간 전` : `${Math.floor(leftMs / 3600000)}시간 남음`}
                </span>
              ) : null}
            </span>
          ) : (
            "-"
          )}
        </Field>
        <Field label="범위" hint="scopes">
          {summary.scopes?.length ? summary.scopes.join(" · ") : <span className="text-muted-foreground">-</span>}
        </Field>
        <Field label="토큰 식별자" hint="jti">
          {summary.jti ? <Mono>{summary.jti.slice(0, 12)}</Mono> : <span className="text-muted-foreground">-</span>}
        </Field>
      </dl>
      <p className="text-xs text-muted-foreground">
        PAT 값 자체는 저장 뒤 어디에도 다시 보이지 않습니다. 소속은 {summary.groups.length ? summary.groups.join(" · ") : "없음"}.
      </p>
    </div>
  );
}

/**
 * 자동 등록 — 스위치(`auto.enabled`)와 마지막 등록 · 마지막 자동 실패. 스위치 옆에 멈추는 길(`how_to_stop`)을 그대로 보인다.
 * 글(`last_error` · `how_to_stop`)은 서버가 고른 문장이라 글자 그대로 텍스트로 보인다.
 */
function AutoPanel({
  auto,
  busy,
  running,
  onToggle,
}: {
  auto: PortalPatAuto;
  busy: boolean;
  running: boolean;
  onToggle: (enabled: boolean) => void;
}) {
  const describedBy = useId();
  return (
    <SubPanel title="자동 등록">
      <div className="flex flex-col gap-1.5">
        {/* 스위치의 이름은 짧게 두고(상태는 aria-checked 가 말한다) 설명 · 멈추는 길은 aria-describedby 로 잇는다. */}
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              role="switch"
              aria-checked={auto.enabled}
              aria-describedby={describedBy}
              checked={auto.enabled}
              disabled={busy || running}
              onChange={(e) => onToggle(e.target.checked)}
            />
            <span className="font-medium">자동 등록</span>
          </label>
          <Chip tone={auto.enabled ? "ok" : "muted"} aria-hidden="true">
            {auto.enabled ? "켜짐" : "꺼짐"}
          </Chip>
        </div>
        <div id={describedBy} className="flex flex-col gap-1 text-sm text-muted-foreground">
          <p className="m-0">
            앱을 열 때 PAT 가 없거나 곧 끝나면 이 브라우저가 포털에서 새로 받아 조용히 등록합니다(출처 web). Claude 에서 hwax_risk
            도구를 부를 때는 게이트웨이가 같은 일을 합니다.
          </p>
          {auto.how_to_stop ? <p className="m-0">{auto.how_to_stop}</p> : null}
        </div>
        {running ? (
          <p className="m-0 text-sm text-muted-foreground" role="status">
            지금 자동으로 등록하는 중입니다.
          </p>
        ) : null}
      </div>
      <dl className="m-0 grid gap-x-6 sm:grid-cols-3">
        <Field label="지금 받아야 하나" hint="due · due_reason">
          {auto.due ? (
            <span>
              <Chip tone="warn">필요</Chip> {auto.due_reason ? DUE_REASON[auto.due_reason] ?? auto.due_reason : null}
            </span>
          ) : (
            <Chip tone="ok">아니오</Chip>
          )}
        </Field>
        <Field label="마지막 등록" hint="last_source · last_at">
          {auto.last_source || auto.last_at ? (
            <span>
              {auto.last_source ? PAT_SOURCE[auto.last_source] ?? auto.last_source : "출처 모름"}
              {auto.last_at ? <span className="ml-1.5 text-xs text-muted-foreground">{fmtEpoch(auto.last_at)}</span> : null}
            </span>
          ) : (
            <span className="text-muted-foreground">기록 없음</span>
          )}
        </Field>
        <Field label="마지막 자동 등록 실패" hint="last_error · last_error_kind · last_error_at">
          {auto.last_error ? (
            <span className="flex flex-col gap-0.5">
              <span>
                <Chip tone={auto.last_error_kind === "transient" ? "warn" : "bad"}>
                  {auto.last_error_kind === "transient"
                    ? "일시 — 10분 뒤 다시 바랍니다"
                    : auto.last_error_kind === "final"
                      ? "사람이 고칠 것"
                      : "갈래 모름"}
                </Chip>
                {auto.last_error_at ? (
                  <span className="ml-1.5 text-xs text-muted-foreground">{fmtEpoch(auto.last_error_at)}</span>
                ) : null}
              </span>
              <span className="break-words">{auto.last_error}</span>
            </span>
          ) : (
            <span className="text-muted-foreground">없음</span>
          )}
        </Field>
      </dl>
    </SubPanel>
  );
}

function PatSection({ summary, onChanged }: { summary: PortalPatSummary | null; onChanged: () => void }) {
  const autoPat = useAutoPortalPat();
  const [pat, setPat] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [notice, setNotice] = useState<string | null>(null);
  // 자동 등록이 켜진 채 지우면 다음에 앱을 열 때 다시 등록된다 — 지울 때 자동도 끌지 묻는 자리.
  const [confirmDelete, setConfirmDelete] = useState(false);
  const auto = summary?.auto ?? null;
  const locked = busy || autoPat.running;

  /** 한 동작 — 성공하면 알림, 실패하면 배너. 어느 쪽이든 서버 상태를 다시 읽는다(PUT 의 답은 `GET /me` 와 꼴이 다르다). */
  async function act(run: () => Promise<string>) {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      setNotice(await run());
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
      onChanged();
    }
  }

  /**
   * 포털에서 발급받아 그대로 등록한다 — 사람이 값을 손으로 옮기는 단계를 없앤다. 출처는 web 이다(앱이 받아 온 PAT 라 다음
   * 갱신 때 백엔드가 폐기한다). 발급은 **브라우저가** 한다 — 앱 서버는 포털 `require_csrf`(double-submit)를 만족할 수 없다.
   * 받은 값은 곧바로 서버로 넘기고 화면 상태에 담지 않는다(입력란에도 넣지 않는다).
   */
  const mintAndSave = () =>
    act(async () => {
      const { jti } = await registerFromPortal();
      return `포털에서 발급해 등록했습니다 — jti ${jti}`;
    });

  /** 붙여 넣은 값 — 그 사람의 Claude PAT 일 수 있어 출처를 싣지 않는다(= manual, 백엔드가 폐기하지 않는다). */
  const savePasted = () =>
    act(async () => {
      await riskApi.putPortalPat(pat.trim());
      setPat("");
      return "PAT 를 등록했습니다.";
    });

  /** 지우기 — 자동도 끄면 스위치를 먼저 내린다(그 사이에 다시 등록되지 않게). */
  const remove = (alsoStopAuto: boolean) =>
    act(async () => {
      setConfirmDelete(false);
      if (alsoStopAuto) await riskApi.putPortalPatAuto(false);
      await riskApi.putPortalPat(null);
      return alsoStopAuto ? "자동 등록을 끄고 등록된 PAT 를 지웠습니다." : "등록된 PAT 를 지웠습니다.";
    });

  /** 스위치 — 켜서 지금 받아야 하면(due) 그 자리에서 버튼과 같은 일을 한다. 켠 것은 사람의 손이라 결과를 보인다. */
  const toggleAuto = (enabled: boolean) =>
    act(async () => {
      const next = await riskApi.putPortalPatAuto(enabled);
      if (!enabled) return "자동 등록을 껐습니다 — 이제 PAT 를 지우거나 폐기해도 저절로 다시 만들어지지 않습니다.";
      if (!next.due) return "자동 등록을 켰습니다.";
      const { jti } = await registerFromPortal();
      return `자동 등록을 켜고 포털에서 발급해 등록했습니다 — jti ${jti}`;
    });

  return (
    <>
      <PatErrorBanner error={error} />
      {/* 등록·삭제 성공은 하던 말을 끊을 일이 아니다 — status 로 둔다. */}
      {notice ? (
        <Banner
          tone="info"
          live="status"
          title={notice}
          detail="PAT 값 자체는 저장 뒤 어디에도 다시 표시되지 않습니다."
        />
      ) : null}
      <PatStatus summary={summary} />
      {auto ? <AutoPanel auto={auto} busy={busy} running={autoPat.running} onToggle={toggleAuto} /> : null}
      <FormField label="포털 PAT">
        <Input
          type="password"
          autoComplete="off"
          spellCheck={false}
          placeholder="포털에서 발급한 PAT 를 붙여넣습니다."
          value={pat}
          onChange={(e) => setPat(e.target.value)}
        />
      </FormField>
      <div className="flex flex-wrap items-center gap-2">
        <Button type="button" onClick={mintAndSave} disabled={locked}>
          {busy ? "처리 중." : "포털에서 발급해 등록"}
        </Button>
        <Button type="button" variant="outline" onClick={savePasted} disabled={locked || pat.trim() === ""}>
          붙여넣은 값으로 등록
        </Button>
        <Button
          type="button"
          variant="outline"
          onClick={() => (auto?.enabled ? setConfirmDelete(true) : remove(false))}
          disabled={locked || !summary?.registered}
        >
          삭제
        </Button>
        <a href="/tokens" target="_blank" rel="noreferrer">
          포털 토큰 화면
        </a>
      </div>
      {confirmDelete ? (
        <SubPanel title="등록된 PAT 를 지웁니다.">
          <p className="m-0 text-sm text-muted-foreground">
            자동 등록이 켜져 있어 지워도 다음에 앱을 열 때(또는 Claude 에서 hwax_risk 도구를 부를 때) 다시 등록됩니다. 지운 채
            두려면 자동 등록도 끄세요.
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <Button type="button" variant="destructive" onClick={() => remove(true)} disabled={locked}>
              자동 등록도 끄고 지우기
            </Button>
            <Button type="button" variant="outline" onClick={() => remove(false)} disabled={locked}>
              지우기만
            </Button>
            <Button type="button" variant="ghost" onClick={() => setConfirmDelete(false)}>
              그만두기
            </Button>
          </div>
        </SubPanel>
      ) : null}
      <p className="text-sm text-muted-foreground">
        '포털에서 발급해 등록' 은 이 브라우저의 포털 세션으로 <code>scopes ['read']</code> ·{" "}
        <code>aud {MINT_BODY.audiences.join(" · ")}</code> · ttl {MINT_BODY.ttl_days}일 PAT 을 만들어 그대로 등록합니다 — 값이
        화면에 보이지 않습니다. 포털이 토큰 발급 권한(<code>feat:api-token</code>)을 요구하면 관리자에게 그 권한을 먼저 받으세요.
      </p>
      <p className="text-sm text-muted-foreground">
        직접 발급할 때의 조건 — aud 에 mcp-gateway 포함(위임 캡처의 REST 다리까지 쓰려면 step-forge 도) · scope api · ttl
        365일 이하.
      </p>
      {/* index.css `.rr-consent` 와 같은 값 — 왼쪽 굵은 선 3px · 연한 배경 · 작은 글씨. */}
      <p className="mt-2 rounded-md border-l-[3px] border-border bg-muted/40 p-3 text-sm text-muted-foreground">
        {CONSENT_TEXT}
      </p>
    </>
  );
}

/** 무인 패널 실행 자격 — 자격 선택은 러너가 하고 화면은 서버가 준 사실만 옮긴다. */
function RunnerSection({ pat, secretsValid }: { pat: PortalPatSummary | null; secretsValid: boolean }) {
  return (
    <>
      <KeyValueTable
        rows={[
          {
            label: "내 PAT 등록",
            value: pat?.registered ? <Badge tone="ok">registered</Badge> : <Badge tone="muted">미등록</Badge>,
          },
          { label: "내 PAT exp", value: fmtEpoch(pat?.exp ?? null) },
          {
            label: "서비스 자격",
            value: secretsValid ? <Badge tone="ok">valid</Badge> : <Badge tone="bad">invalid</Badge>,
          },
        ]}
      />
      <p className="text-sm text-muted-foreground">
        실제로 어떤 자격이 쓰였는지는 잡 생성 응답의 credential 과 각 패널의 quality.credential 에서 봅니다.
      </p>
      <NotReadyBlock what="러너 큐 상태(대기·동시 실행 수)" />
      <p className="text-sm text-muted-foreground">진행 중인 잡은 해당 타깃 화면에서 상태·진행률로 봅니다.</p>
    </>
  );
}

export default function SettingsPage() {
  // 앱을 열 때의 자동 등록이 끝나면(version) 다시 읽는다 — PAT 없이 이 화면을 열면 등록된 모습으로 바뀐다.
  const { version: autoVersion } = useAutoPortalPat();
  const me = useAsync((signal) => riskApi.getMe({ signal }), [autoVersion]);
  const health = useAsync((signal) => riskApi.getHealth({ signal }), []);

  return (
    <>
      <SectionCard title="내 신원" subtitle="앱에는 로그인 화면이 없습니다 — 포털에서 로그인한 신원을 그대로 씁니다.">
        <ErrorBanner error={me.error} onRetry={me.reload} />
        {me.loading && !me.data ? <LoadingBlock /> : null}
        {me.data ? (
          /* 라벨은 사람 말로 두고 원시 필드명은 hint 로 접는다 — 화면이 DB 열 이름을 읽어 주는
             자리가 아니다. 다만 필드명을 지우지는 않는다(API·로그와 대조할 때 그 이름이 필요하다). */
          <dl className="grid gap-x-8 gap-y-1 sm:grid-cols-2 lg:grid-cols-3">
            <Field label="계정" hint="email">
              {me.data.email ?? <span className="text-muted-foreground">-</span>}
            </Field>
            <Field label="이름" hint="display_name">
              {me.data.display_name ?? <span className="text-muted-foreground">-</span>}
            </Field>
            <Field label="역할" hint="role">
              {me.data.role ?? <span className="text-muted-foreground">-</span>}
            </Field>
            <Field label="소속" hint="organization">
              {me.data.organization ?? <span className="text-muted-foreground">-</span>}
            </Field>
            <Field label="신원 확인" hint="anonymous">
              {me.data.anonymous ? (
                <Chip tone="warn">확인 안 됨</Chip>
              ) : (
                <Chip tone="ok">확인됨</Chip>
              )}
            </Field>
            <Field label="자격 출처" hint="source">
              {ME_SOURCE[me.data.source] ?? me.data.source}
            </Field>
          </dl>
        ) : null}
      </SectionCard>

      <SectionCard title="포털 PAT" subtitle="무인 패널이 소스 앱을 읽을 때 쓰는 자격입니다.">
        {me.loading && !me.data ? <LoadingBlock /> : null}
        {me.data ? (
          <PatSection summary={me.data.portal_pat} onChanged={me.reload} />
        ) : me.error ? null : (
          <EmptyBlock title="신원을 읽은 뒤에 등록할 수 있습니다." />
        )}
      </SectionCard>

      <SectionCard title="이 박스">
        {me.data ? (
          <>
            {me.data.box.secrets_valid ? null : (
              <Banner
                title="이 박스의 자격이 없습니다."
                detail="저장된 비밀이 이 호스트에서 풀리지 않습니다."
              />
            )}
            <KeyValueTable
              rows={[
                { label: "hostname", value: me.data.box.hostname },
                {
                  label: "secrets_valid",
                  value: me.data.box.secrets_valid ? <Badge tone="ok">valid</Badge> : <Badge tone="bad">invalid</Badge>,
                },
                {
                  label: "cred_key",
                  value: me.data.box.cred_key_present ? (
                    <Badge tone="ok">present</Badge>
                  ) : (
                    <Badge tone="bad">absent</Badge>
                  ),
                },
                {
                  // 이 값이 틀리면 PAT 등록·패널 실행이 전부 실패한다 — 안 보이면 사람이 토큰을 의심한다.
                  label: "portal_base",
                  value: me.data.box.portal_base ? (
                    <code>{me.data.box.portal_base}</code>
                  ) : (
                    <span className="text-sm text-muted-foreground">서버가 알려 주지 않았습니다.</span>
                  ),
                },
              ]}
            />
            <p className="text-sm text-muted-foreground">
              portal_base 는 앱이 포털을 부르는 주소입니다. 이 값이 실제 포털 오리진(nginx)이 아니면 PAT 등록과
              무인 패널이 모두 실패하고, 그 실패는 토큰 탓처럼 보입니다.
            </p>
          </>
        ) : null}
        <ErrorBanner error={health.error} onRetry={health.reload} />
        {health.loading && !health.data ? <LoadingBlock /> : null}
        {health.data ? (
          <KeyValueTable
            rows={[
              { label: "ok", value: health.data.ok ? <Badge tone="ok">ok</Badge> : <Badge tone="bad">not ok</Badge> },
              { label: "app_version", value: health.data.app_version },
              { label: "schema_version", value: String(health.data.schema_version) },
            ]}
          />
        ) : null}
      </SectionCard>

      <SectionCard title="러너" subtitle="무인 패널을 실행하는 자격과 상태입니다.">
        {me.data ? (
          <RunnerSection pat={me.data.portal_pat} secretsValid={me.data.box.secrets_valid} />
        ) : (
          <NotReadyBlock what="러너 상태" />
        )}
      </SectionCard>
    </>
  );
}
