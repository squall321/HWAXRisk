// 백엔드 REST 호출 — 모든 fetch 는 상대경로('api/…')라 /apps/hwax_risk/ 서브패스 아래서도 그대로 풀린다.
export type Meta = {
  app_id: string;
  version: string;
  schema_version: number;
  data_dir: string;
  root_path: string;
};

export type Adapter = {
  kind: string;
  app: string | null;
  status: string;
};

async function request<T>(path: string): Promise<T> {
  const res = await fetch(path);
  if (!res.ok) {
    throw new Error(`${res.status} ${res.statusText}`);
  }
  return (await res.json()) as T;
}

export const api = {
  meta: () => request<Meta>("api/meta"),
  adapters: () => request<Adapter[]>("api/meta/adapters"),
};
