// 설정 화면 — 내 신원·포털 PAT 등록/삭제·이 박스 상태·동의 문구(계획 §8.2.4 SettingsPage 행).
import { useState } from "react";
import { isApiError, riskApi } from "../api/risk.api";
import { useAsync } from "../hooks/useAsync";
import { SectionCard } from "../components/SectionCard";
import { KeyValueTable } from "../components/DataTable";
import { ErrorBanner, EmptyBlock, LoadingBlock, NotReadyBlock } from "../components/StateBlocks";
import { Badge } from "../components/Badge";
import { Clock, KeyRound, ShieldAlert, ShieldCheck } from "lucide-react";
import { Chip, Field, Mono } from "../ui/primitives";
import { cn } from "../lib/cn";
import { fmtEpoch } from "../format";
import type { PortalPatSummary } from "../types";
import { PortalMintError, mintPortalPat } from "../api/portalPat";

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

/** `PUT /me/portal-pat` 422 네 가지(§8.2.3) — 서버 code 를 사람이 읽는 문구와 다음 할 일로 바꾼다. */
const PAT_ERRORS: Record<string, { title: string; detail: string }> = {
  pat_invalid: {
    title: "포털이 이 PAT 를 받지 않았습니다.",
    detail: "형식이 포털 PAT(JWT 3분절)가 아니거나 포털 검증 호출이 거부했습니다. 값을 다시 복사하거나 포털에서 새로 발급하세요.",
  },
  pat_email_mismatch: {
    title: "내 계정의 PAT 가 아닙니다.",
    detail: "PAT 안의 email 이 지금 로그인한 계정과 다릅니다. 내 계정으로 로그인한 상태에서 발급한 PAT 를 넣으세요.",
  },
  pat_audience: {
    title: "발급 조건이 맞지 않습니다.",
    detail: "aud 에 mcp-gateway 가 없거나 scope 가 api 가 아닙니다. 발급 화면에서 두 값을 맞춰 다시 발급하세요.",
  },
  pat_expiring: {
    title: "곧 만료되는 PAT 입니다.",
    detail: "만료까지 24시간이 채 남지 않았습니다. ttl 을 365일 이하 범위에서 넉넉히 잡아 다시 발급하세요.",
  },
  // 포털 발급 화면이 scopes 를 ['read','write'] 로 주므로 링크를 그대로 따라간 사용자가 만나는 코드다.
  pat_scope_too_broad: {
    title: "범위가 넓은 PAT 입니다.",
    detail:
      "이 앱은 scopes 가 ['read'] 인 PAT 만 등록합니다. 위의 '포털에서 발급해 등록' 을 쓰면 그 범위로 바로 만들어 줍니다.",
  },
  cred_key_absent: {
    title: "이 박스에 자격 암호키가 없습니다.",
    detail:
      "PAT 를 평문으로 저장하지 않으므로 키가 없으면 등록하지 않습니다. 운영자가 데이터 디렉터리의 cred.key 를 만들어야 합니다.",
  },
  // 설정 문제를 토큰 문제로 읽지 않게 따로 적는다(502).
  portal_unreachable: {
    title: "포털에 닿지 못했습니다 — PAT 문제가 아닙니다.",
    detail:
      "앱이 포털을 부르는 주소(HWAXRISK_PORTAL_BASE)가 실제 포털 오리진을 가리키지 않습니다. 토큰을 다시 발급해도 같은 오류가 납니다 — 운영자가 그 설정을 고쳐야 합니다.",
  },
};

/** 4종은 전용 문구로, 나머지는 공용 배너로 접는다. */
function PatErrorBanner({ error }: { error: unknown }) {
  if (error === null || error === undefined) return null;
  const known = isApiError(error) ? PAT_ERRORS[error.code] : undefined;
  if (!known) return <ErrorBanner error={error} />;
  return (
    <div className="rr-banner rr-banner-error" role="alert">
      <span className="rr-banner-title">{known.title}</span>
      <span className="rr-banner-detail">{known.detail}</span>
    </div>
  );
}

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
            이 자격이 없으면 무인 패널이 돌지 않습니다 — 아래 버튼 한 번이면 포털에서 받아 등록합니다.
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

function PatSection({ summary, onChanged }: { summary: PortalPatSummary | null; onChanged: () => void }) {
  const [pat, setPat] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [result, setResult] = useState<PortalPatSummary | null>(null);

  async function save(value: string | null) {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const next = await riskApi.putPortalPat(value);
      setResult(next);
      setPat("");
      setNotice(next.registered ? "PAT 를 등록했습니다." : "등록된 PAT 를 삭제했습니다.");
      onChanged();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  /**
   * 포털에서 발급받아 그대로 등록한다 — 사람이 값을 손으로 옮기는 단계를 없앤다.
   *
   * 발급은 **브라우저가** 한다. 앱 서버는 포털 `require_csrf`(double-submit)를 만족할 수 없어
   * 사용자를 대신해 발급할 수 없다. 앱 SPA 는 포털과 같은 오리진이라 세션 쿠키와 CSRF 를 그대로 쓴다.
   * 받은 값은 곧바로 서버로 넘기고 화면 상태에 담지 않는다(입력란에도 넣지 않는다).
   */
  async function mintAndSave() {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const minted = await mintPortalPat();
      const next = await riskApi.putPortalPat(minted.token);
      setResult(next);
      setPat("");
      setNotice(`포털에서 발급해 등록했습니다 — jti ${minted.jti}`);
      onChanged();
    } catch (err) {
      // 발급 단계 실패는 문구가 곧 사유다(권한·세션). 등록 단계 실패는 기존 422 표에 걸린다.
      setError(err instanceof PortalMintError ? new Error(err.message) : err);
    } finally {
      setBusy(false);
    }
  }

  const shown = result ?? summary;

  return (
    <>
      <PatErrorBanner error={error} />
      {notice ? (
        <div className="rr-banner rr-banner-info" role="status">
          <span className="rr-banner-title">{notice}</span>
          <span className="rr-banner-detail">PAT 값 자체는 저장 뒤 어디에도 다시 표시되지 않습니다.</span>
        </div>
      ) : null}
      <PatStatus summary={shown} />
      <label className="rr-field">
        <span>포털 PAT</span>
        <input
          className="rr-input"
          type="password"
          autoComplete="off"
          spellCheck={false}
          placeholder="포털에서 발급한 PAT 를 붙여넣습니다."
          value={pat}
          onChange={(e) => setPat(e.target.value)}
        />
      </label>
      <div className="rr-row">
        <button type="button" className="rr-btn rr-btn-primary" onClick={mintAndSave} disabled={busy}>
          {busy ? "처리 중." : "포털에서 발급해 등록"}
        </button>
        <button
          type="button"
          className="rr-btn"
          onClick={() => save(pat.trim())}
          disabled={busy || pat.trim() === ""}
        >
          붙여넣은 값으로 등록
        </button>
        <button type="button" className="rr-btn" onClick={() => save(null)} disabled={busy || !shown?.registered}>
          삭제
        </button>
        <a href="/tokens" target="_blank" rel="noreferrer">
          포털 토큰 화면
        </a>
      </div>
      <p className="rr-muted">
        '포털에서 발급해 등록' 은 이 브라우저의 포털 세션으로 <code>scopes ['read']</code> ·{" "}
        <code>aud mcp-gateway</code> · ttl 90일 PAT 을 만들어 그대로 등록합니다 — 값이 화면에 보이지 않습니다.
        포털이 토큰 발급 권한(<code>feat:api-token</code>)을 요구하면 관리자에게 그 권한을 먼저 받으세요.
      </p>
      <p className="rr-muted">직접 발급할 때의 조건 — aud 에 mcp-gateway 포함 · scope api · ttl 365일 이하.</p>
      <p className="rr-consent">{CONSENT_TEXT}</p>
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
      <p className="rr-muted">
        실제로 어떤 자격이 쓰였는지는 잡 생성 응답의 credential 과 각 패널의 quality.credential 에서 봅니다.
      </p>
      <NotReadyBlock what="러너 큐 상태(대기·동시 실행 수)" />
      <p className="rr-muted">진행 중인 잡은 해당 타깃 화면에서 상태·진행률로 봅니다.</p>
    </>
  );
}

export default function SettingsPage() {
  const me = useAsync((signal) => riskApi.getMe({ signal }), []);
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
              <div className="rr-banner rr-banner-error" role="alert">
                <span className="rr-banner-title">이 박스의 자격이 없습니다.</span>
                <span className="rr-banner-detail">저장된 비밀이 이 호스트에서 풀리지 않습니다.</span>
              </div>
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
                    <span className="rr-muted">서버가 알려 주지 않았습니다.</span>
                  ),
                },
              ]}
            />
            <p className="rr-muted">
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
