// P0 플레이스홀더 화면 — 헬스(api/health)·신원(api/me)·어댑터 현황(api/meta/adapters)만 보여준다.
import { useEffect, useState } from "react";
import { api, Adapter, Health, Me } from "./api";

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [me, setMe] = useState<Me | null>(null);
  const [adapters, setAdapters] = useState<Adapter[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.health(), api.me(), api.adapters()])
      .then(([h, m, a]) => {
        setHealth(h);
        setMe(m);
        setAdapters(a);
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  return (
    <main className="container">
      <header>
        <h1>
          HWAX Risk Review <span className="badge">P0 스캐폴드</span>
        </h1>
        <p className="subtitle">
          설계 리스크 심사 앱의 골격만 올라와 있는 상태다. 심사 화면은 P1 이후에 붙는다.
          REST <code>api/health</code> · <code>api/me</code> · MCP <code>mcp</code>(도구 6종. risk_get_snapshot · risk_get_diff ·
          risk_get_registry · risk_claims_for_ref · risk_get_brief · risk_submit_panel_result — P0 는 not_implemented).
        </p>
      </header>

      {error && <p className="error">불러오기 실패. {error}</p>}

      <section>
        <h2>앱 상태</h2>
        {health && me ? (
          <table>
            <tbody>
              <tr>
                <th>ok</th>
                <td>{String(health.ok)}</td>
              </tr>
              <tr>
                <th>app_version</th>
                <td>{health.app_version}</td>
              </tr>
              <tr>
                <th>schema_version</th>
                <td>{health.schema_version}</td>
              </tr>
              <tr>
                <th>신원</th>
                <td>{me.anonymous ? "익명" : `${me.email} (${me.source})`}</td>
              </tr>
              <tr>
                <th>포털 PAT</th>
                <td>{me.portal_pat ? `등록됨 (${me.portal_pat.email})` : "미등록"}</td>
              </tr>
              <tr>
                <th>박스</th>
                <td>
                  <code>{me.box.hostname}</code> · secrets_valid {String(me.box.secrets_valid)}
                </td>
              </tr>
            </tbody>
          </table>
        ) : (
          !error && <p>불러오는 중.</p>
        )}
      </section>

      <section>
        <h2>소스 어댑터</h2>
        <table>
          <thead>
            <tr>
              <th>kind</th>
              <th>app</th>
              <th>status</th>
            </tr>
          </thead>
          <tbody>
            {adapters.map((a) => (
              <tr key={a.kind}>
                <td>{a.kind}</td>
                <td>{a.app ?? "-"}</td>
                <td>{a.status}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </main>
  );
}
