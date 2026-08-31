// 백엔드 REST 호출 — 모든 fetch 는 상대경로('api/…')라 /apps/hwax_risk/ 서브패스 아래서도 그대로 풀린다.
export type Health = {
  ok: boolean;
  app_version: string;
  schema_version: number;
};

export type Me = {
  email: string | null;
  display_name: string | null;
  role: string | null;
  organization: string | null;
  anonymous: boolean;
  source: "bearer" | "cookie" | "none";
  portal_pat: { registered: boolean; email: string | null; groups: string[]; exp: number | null } | null;
  box: { hostname: string; secrets_valid: boolean };
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
  health: () => request<Health>("api/health"),
  me: () => request<Me>("api/me"),
  adapters: () => request<Adapter[]>("api/meta/adapters"),
};
