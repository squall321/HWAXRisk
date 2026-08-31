// 게이트 판정 표시 — 스냅샷 화면과 비교 화면이 같은 모양으로 G1~G7 을 보인다(계획 §8.2.4 GateBanner).
import type { Column } from "./DataTable";
import { DataTable } from "./DataTable";
import { Badge } from "./Badge";
import { fmtCell } from "../format";
import type { Gate } from "../types";

/** 판정표. pass 는 서버가 준 값이고 화면은 색만 고른다. */
export function GateTable({ gates }: { gates: Gate[] }) {
  const columns: Column<Gate>[] = [
    { key: "id", header: "게이트", cell: (g) => <strong>{g.id}</strong>, nowrap: true },
    {
      key: "pass",
      header: "판정",
      cell: (g) => <Badge tone={g.pass ? "ok" : "bad"}>{g.pass ? "pass" : "fail"}</Badge>,
      nowrap: true,
    },
    { key: "value", header: "값", cell: (g) => fmtCell(g.value), nowrap: true },
    { key: "threshold", header: "임계", cell: (g) => fmtCell(g.threshold), nowrap: true },
    { key: "effect", header: "효과", cell: (g) => g.effect, nowrap: true },
    { key: "message", header: "메시지", cell: (g) => g.message },
  ];
  return <DataTable columns={columns} rows={gates} rowKey={(g) => g.id} empty="게이트 판정이 없습니다." />;
}

/** fail 인 게이트만 한 줄 배너로 요약한다 — 표기를 강제하되 판단은 만들지 않는다. */
export function GateBanner({ gates }: { gates: Gate[] }) {
  const failed = gates.filter((g) => !g.pass);
  if (failed.length === 0) return null;
  return (
    <div className="rr-banner rr-banner-error" role="alert">
      <span className="rr-banner-title">게이트 {failed.map((g) => g.id).join(" · ")} fail.</span>
      <span className="rr-banner-detail">{failed.map((g) => g.message).join(" / ")}</span>
    </div>
  );
}

/** 특정 게이트가 fail 인지(G6 → diff 생성 차단, G2 → 의미층 차단). */
export function isGateFailing(gates: Gate[] | null | undefined, id: string): boolean {
  if (!gates) return false;
  return gates.some((g) => g.id === id && !g.pass);
}
