// 게이트 판정 표시 — 스냅샷 · 비교 화면이 같은 모양으로 G1~G7 을 보이고, fail 게이트에 사유를 적어 ack 한다(계획 §8.2.4 GateBanner)
import { useState } from "react";
import type { Column } from "./DataTable";
import { DataTable } from "./DataTable";
import { Badge } from "./Badge";
import { ErrorBanner } from "./StateBlocks";
import { Banner, Button, FormField, Input } from "../ui/primitives";
import { fmtCell, fmtEpoch } from "../format";
import { riskApi } from "../api/risk.api";
import { gateAckable, gateRows, gateVerdict } from "../lib/snapshotView";
import type { GateAcked, GateId, GateRecord, Gates } from "../types";

/** 게이트 id → 계획 §3.2.2 의 이름. 판정 · 까닭은 서버 값이 정본이다. */
export const GATE_LABEL: Record<string, string> = {
  G1: "이름 중복 · 자동 이름(dup_or_anon_names)",
  G2: "대응 미확정(sameas_pending)",
  G3: "간섭 미확정(iface_unconfirmed)",
  G4: "좌표계(coordinate)",
  G5: "부분 검출 범위(partial_scope)",
  G6: "단위 · 축척(unit_scale)",
  G7: "잣대 일치(yardstick_parity — 비교 전용)",
};

/** ack 사유 상한(routes.GATE_ACK_REASON_MAX). */
export const GATE_ACK_REASON_MAX = 300;

/** 판정 배지 — pass · fail(건수 · ack) · 판정 불가(까닭, 중립색). null 은 fail 이 아니다. */
export function GateVerdictBadge({ record }: { record: GateRecord | null | undefined }) {
  const v = gateVerdict(record);
  return (
    <Badge tone={v.tone} title={v.title}>
      {v.label}
    </Badge>
  );
}

type GateRow = { id: GateId; record: GateRecord };

/**
 * 판정표. `snapshotId` 를 주면 fail(차단이 아닌) 게이트마다 '사유 적고 진행(ack)' 과 이미 붙은 ack 의 '확인 취소' 를 둔다 — G6 은
 * 차단이라 버튼이 없다(서버도 422 gate_blocking). ack 해도 판정은 fail 로 남는다(§3.2.2).
 */
export function GateTable({
  gates,
  snapshotId,
  onChanged,
}: {
  gates: Gates | null | undefined;
  snapshotId?: string;
  onChanged?: () => void;
}) {
  const rows = gateRows(gates);
  const columns: Column<GateRow>[] = [
    {
      key: "id",
      header: "게이트",
      nowrap: true,
      cell: (g) => (
        <span title={GATE_LABEL[g.id]}>
          <strong>{g.id}</strong> <span className="text-xs text-muted-foreground">{g.record.key}</span>
        </span>
      ),
    },
    { key: "pass", header: "판정", nowrap: true, cell: (g) => <GateVerdictBadge record={g.record} /> },
    { key: "count", header: "건수", hint: "count", nowrap: true, cell: (g) => fmtCell(g.record.count) },
    { key: "threshold", header: "임계", hint: "threshold", nowrap: true, cell: (g) => fmtCell(g.record.threshold) },
    { key: "effect", header: "효과", hint: "effect", nowrap: true, cell: (g) => g.record.effect },
    {
      key: "detail",
      header: "근거",
      hint: "detail",
      cell: (g) =>
        g.record.detail.length === 0 ? (
          <span className="text-muted-foreground">없음</span>
        ) : (
          <code className="text-xs">{g.record.detail.map((d) => fmtCell(d)).join(" · ")}</code>
        ),
    },
    {
      key: "ack",
      header: "ack",
      cell: (g) => <GateAckCell id={g.id} record={g.record} snapshotId={snapshotId} onChanged={onChanged} />,
    },
  ];
  return <DataTable columns={columns} rows={rows} rowKey={(g) => g.id} empty="게이트 판정이 없습니다." />;
}

/** ack 칸 — 붙은 ack 의 누가 · 언제 · 사유, 그리고 (스냅샷 화면이면) 붙이기 · 취소. */
function GateAckCell({
  id,
  record,
  snapshotId,
  onChanged,
}: {
  id: GateId;
  record: GateRecord;
  snapshotId?: string;
  onChanged?: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  /**
   * 방금 붙이거나 취소한 ack 의 답 — 9bd5f48 의 `GET snapshots/{id}?part=state` 는 동결 때의 상태 원문(state_json)을 줘서 ack 를
   * 싣지 않는다(ack 는 gates_json 열 · rr_gate_acks 에만 남는다). 그래서 답을 이 칸에 들고 있고, 서버가 ack 를 실으면 그 값이 이긴다.
   */
  const [local, setLocal] = useState<GateAcked | null>(null);
  const shown = record.ack_by
    ? { by: record.ack_by, at: record.ack_at ?? null, reason: record.ack_reason ?? null, fromServer: true }
    : local && local.ack_by
      ? { by: local.ack_by, at: local.ack_at, reason: local.ack_reason, fromServer: false }
      : null;
  const acked = shown !== null;

  async function run(work: () => Promise<GateAcked>) {
    setBusy(true);
    setError(null);
    try {
      setLocal(await work());
      setOpen(false);
      setReason("");
      onChanged?.();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  const ackLine = shown ? (
    <span className="text-xs text-muted-foreground">
      {shown.by} · {fmtEpoch(shown.at)} · {shown.reason}
      {shown.fromServer ? null : " — 이 서버의 스냅샷 상태는 ack 를 다시 싣지 않아 새로 열면 이 줄이 보이지 않습니다."}
    </span>
  ) : null;

  if (!snapshotId) return ackLine ?? <span className="text-muted-foreground">—</span>;
  if (id === "G6" && record.pass !== true) {
    // G6 은 차단이다 — ack 로 넘기지 않고 소스를 고쳐 다시 캡처한다(unit_unknown 이면 REST 원문으로 다시 캡처해야 풀린다).
    return (
      <span className="text-xs text-muted-foreground">
        {record.reason === "unit_unknown" ? "REST 원문으로 다시 캡처해야 풀립니다." : "차단 — 소스를 고쳐 다시 캡처합니다."}
      </span>
    );
  }
  if (acked) {
    return (
      <span className="flex flex-col gap-1">
        {ackLine}
        <ErrorBanner error={error} />
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="w-fit"
          disabled={busy}
          onClick={() => run(() => riskApi.revokeGateAck(snapshotId, id))}
        >
          확인 취소
        </Button>
      </span>
    );
  }
  if (!gateAckable(id, record)) return <span className="text-muted-foreground">—</span>;
  return (
    <span className="flex flex-col gap-1">
      <ErrorBanner error={error} />
      {open ? (
        <form
          className="flex flex-col gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            if (reason.trim() === "") return;
            void run(() => riskApi.ackGate(snapshotId, id, reason.trim()));
          }}
        >
          <FormField label="사유" hint={`필수 · ${GATE_ACK_REASON_MAX}자까지`}>
            <Input
              maxLength={GATE_ACK_REASON_MAX}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              aria-label={`${id} ack 사유`}
            />
          </FormField>
          <span className="flex flex-wrap items-center gap-2">
            <Button type="submit" size="sm" disabled={busy || reason.trim() === ""}>
              ack 저장
            </Button>
            <Button type="button" variant="ghost" size="sm" onClick={() => setOpen(false)}>
              그만두기
            </Button>
          </span>
          <span className="text-xs text-muted-foreground">ack 해도 판정은 fail 로 남습니다.</span>
        </form>
      ) : (
        <Button type="button" variant="outline" size="sm" className="w-fit" onClick={() => setOpen(true)}>
          사유 적고 진행(ack)
        </Button>
      )}
    </span>
  );
}

/**
 * fail 게이트를 한 줄로 요약한다 — 판단은 만들지 않는다. 판정 불가(null)는 fail 이 아니라 따로 정보 줄로 센다.
 */
export function GateBanner({ gates }: { gates: Gates | null | undefined }) {
  const rows = gateRows(gates);
  const failed = rows.filter((g) => g.record.pass === false);
  const unknown = rows.filter((g) => g.record.pass === null || g.record.pass === undefined);
  return (
    <>
      {failed.length > 0 ? (
        <Banner
          title={`게이트 ${failed.map((g) => g.id).join(" · ")} fail.`}
          detail={failed
            .map((g) => `${g.id} ${GATE_LABEL[g.id] ?? g.record.key}${g.record.ack_by ? "(ack 있음)" : ""}`)
            .join(" / ")}
        />
      ) : null}
      {unknown.length > 0 ? (
        <Banner
          tone="info"
          title={`판정 불가 ${unknown.map((g) => g.id).join(" · ")} — fail 이 아닙니다.`}
          detail={unknown.map((g) => `${g.id} ${gateVerdict(g.record).label}`).join(" / ")}
        />
      ) : null}
    </>
  );
}
