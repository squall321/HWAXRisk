// 설정 화면 — 내 신원·포털 PAT 등록/삭제·이 박스 상태·동의 문구(계획 §8.2.4 SettingsPage 행).
import { useState } from "react";
import { isApiError, riskApi } from "../api/risk.api";
import { useAsync } from "../hooks/useAsync";
import { SectionCard } from "../components/SectionCard";
import { KeyValueTable } from "../components/DataTable";
import { ErrorBanner, EmptyBlock, LoadingBlock, NotReadyBlock } from "../components/StateBlocks";
import { Badge } from "../components/Badge";
import { fmtEpoch } from "../format";
import type { PortalPatSummary } from "../types";
import { PortalMintError, mintPortalPat } from "../api/portalPat";

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
      <KeyValueTable
        rows={[
          {
            label: "등록 상태",
            value: shown?.registered ? <Badge tone="ok">registered</Badge> : <Badge tone="muted">미등록</Badge>,
          },
          { label: "email", value: shown?.email ?? "-" },
          { label: "groups", value: shown?.groups.length ? shown.groups.join(" · ") : "-" },
          { label: "exp", value: fmtEpoch(shown?.exp ?? null) },
        ]}
      />
      <p className="rr-muted">PAT 값은 저장 뒤 화면에 다시 보이지 않습니다.</p>
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
          <KeyValueTable
            rows={[
              { label: "email", value: me.data.email ?? "-" },
              { label: "display_name", value: me.data.display_name ?? "-" },
              { label: "role", value: me.data.role ?? "-" },
              { label: "organization", value: me.data.organization ?? "-" },
              {
                label: "anonymous",
                value: me.data.anonymous ? <Badge tone="warn">anonymous</Badge> : <Badge tone="ok">인증됨</Badge>,
              },
              { label: "source", value: me.data.source },
            ]}
          />
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
              ]}
            />
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
