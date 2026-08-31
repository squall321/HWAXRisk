// P0 플레이스홀더 화면 — 앱 메타(api/meta)와 어댑터 현황(api/meta/adapters)만 보여준다.
import { useEffect, useState } from "react";
import { api, Adapter, Meta } from "./api";

export default function App() {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [adapters, setAdapters] = useState<Adapter[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.meta(), api.adapters()])
      .then(([m, a]) => {
        setMeta(m);
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
          REST <code>api/meta</code> · MCP <code>mcp</code>(도구 3종. risk_health · risk_get_taxonomy · risk_get_meta).
        </p>
      </header>

      {error && <p className="error">불러오기 실패. {error}</p>}

      <section>
        <h2>앱 메타</h2>
        {meta ? (
          <table>
            <tbody>
              <tr>
                <th>app_id</th>
                <td>{meta.app_id}</td>
              </tr>
              <tr>
                <th>version</th>
                <td>{meta.version}</td>
              </tr>
              <tr>
                <th>schema_version</th>
                <td>{meta.schema_version}</td>
              </tr>
              <tr>
                <th>data_dir</th>
                <td>
                  <code>{meta.data_dir}</code>
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
