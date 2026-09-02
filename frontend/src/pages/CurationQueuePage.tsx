// 큐레이션 큐 화면 — kind 6종의 열린 항목을 사람이 결정한다(계획 §7.7). 자동 적용은 없고 결정은 전부 사람 손이다.
import { useMemo, useState } from "react";
import { riskApi } from "../api/risk.api";
import { useAsync } from "../hooks/useAsync";
import { SectionCard } from "../components/SectionCard";
import { DataTable } from "../components/DataTable";
import type { Column } from "../components/DataTable";
import { EmptyBlock, ErrorBanner, LoadingBlock } from "../components/StateBlocks";
import { Badge } from "../components/Badge";
import type { Tone } from "../components/Badge";
import { fmtEpoch, fmtJson } from "../format";
import type { CurationDecision, CurationKind, CurationRow, CurationStatus, JsonObject } from "../types";

/**
 * kind 별 결정 어휘 — 서버 `routes.CURATION_DECISIONS` 와 같은 집합이다.
 * 어휘를 화면이 새로 만들지 않는다(서버가 허용하지 않는 결정은 422 `decision_not_allowed_for_kind`).
 */
const KINDS: Array<{
  kind: CurationKind;
  label: string;
  what: string;
  decisions: Array<{ value: string; label: string; tone?: Tone }>;
}> = [
  {
    kind: "suspect_text",
    label: "의심 문구",
    what: "소스 원문에서 지시문처럼 읽히는 조각을 자리표시자로 가둔 것. 승인하면 원문을 복원하고 그 finding 을 회수로 되돌린다.",
    decisions: [
      { value: "approve", label: "승인(원문 복원)", tone: "ok" },
      { value: "reject", label: "기각(격리 유지)", tone: "bad" },
    ],
  },
  {
    kind: "label_match",
    label: "라벨 대조",
    what: "자동 라벨이 사람 판정과 부딪히거나 확신이 낮은 것. 여기서 닫아야 그 라벨이 정밀도·선례 분모에 든다.",
    decisions: [
      { value: "confirmed", label: "확인", tone: "ok" },
      { value: "refuted", label: "반증", tone: "warn" },
      { value: "inconclusive", label: "판정 보류", tone: "muted" },
      { value: "reject", label: "기각", tone: "bad" },
    ],
  },
  {
    kind: "pattern_candidate",
    label: "패턴 후보",
    what: "여러 과제에서 되풀이된 조합. 승격하면 선례·규칙으로 쓰인다(게이트 미달이면 서버가 422 로 막는다).",
    decisions: [
      { value: "known", label: "알려진 패턴", tone: "ok" },
      { value: "rule", label: "규칙으로", tone: "ok" },
      { value: "predictor", label: "예측기로", tone: "info" },
      { value: "suspended", label: "보류", tone: "muted" },
      { value: "deprecated", label: "폐기", tone: "warn" },
      { value: "reject", label: "기각", tone: "bad" },
    ],
  },
  {
    kind: "x_tag_promote",
    label: "자유 태그 승격",
    what: "타깃 3·패널 2 이상에서 같은 값으로 나온 `x:` 태그. 어느 축으로 올릴지는 사람이 고른다.",
    decisions: [
      { value: "promote", label: "승격", tone: "ok" },
      { value: "reject", label: "기각", tone: "bad" },
    ],
  },
  {
    kind: "cluster_merge",
    label: "근접 중복",
    what: "같은 family 안에서 거의 같은 두 클러스터. 자동 병합은 없다.",
    decisions: [
      { value: "merge", label: "병합", tone: "ok" },
      { value: "reject", label: "그대로 둠", tone: "bad" },
    ],
  },
  {
    kind: "unclassified_code",
    label: "미분류 코드",
    what: "택소노미 밖으로 떨어진 mechanism_detail. 옮길 값은 사람이 준다(별칭만 더하고 저장된 cluster_key 는 그대로다).",
    decisions: [
      { value: "map", label: "기존 값으로", tone: "ok" },
      { value: "new", label: "새 값으로", tone: "info" },
      { value: "reject", label: "기각", tone: "bad" },
    ],
  },
];

const KIND_BY_NAME = new Map(KINDS.map((k) => [k.kind, k]));

const STATUS_TONE: Record<CurationStatus, Tone> = { open: "warn", done: "ok", rejected: "muted" };

/** 결정에 값을 더 받아야 하는 kind — 어느 축인지·어느 값으로인지는 코드가 고를 수 없다. */
type ExtraField = { key: string; label: string; hint: string; options?: string[] };

function extraFieldFor(kind: CurationKind, decision: string, axes: string[]): ExtraField | null {
  if (kind === "x_tag_promote" && decision === "promote") {
    return { key: "axis", label: "올릴 축", hint: "`char:<axis>:<value>` 의 축입니다.", options: axes };
  }
  if (kind === "unclassified_code" && (decision === "map" || decision === "new")) {
    return { key: "mechanism_detail", label: "mechanism_detail", hint: "옮겨 갈 택소노미 값입니다." };
  }
  return null;
}

/** payload 에서 사람이 먼저 볼 한 줄. 아는 키만 꺼내고 나머지는 원문 접기로 넘긴다. */
function summarize(row: CurationRow): string {
  const p = row.payload ?? {};
  const pick = (key: string): string => (typeof p[key] === "string" ? (p[key] as string) : "");
  switch (row.kind) {
    case "x_tag_promote":
      return pick("tag");
    case "suspect_text":
      return pick("raw").slice(0, 120) || pick("sha1");
    case "cluster_merge":
      return [pick("a"), pick("b")].filter(Boolean).join("  ↔  ");
    case "pattern_candidate":
      return pick("pattern_id");
    default:
      return pick("finding_id") || pick("cluster_key_norm");
  }
}

function DecisionForm({
  row,
  axes,
  onDone,
}: {
  row: CurationRow;
  axes: string[];
  onDone: () => void;
}) {
  const spec = KIND_BY_NAME.get(row.kind);
  const [decision, setDecision] = useState(spec?.decisions[0]?.value ?? "reject");
  const [reason, setReason] = useState("");
  const [extra, setExtra] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [applied, setApplied] = useState<JsonObject | null>(null);

  const field = extraFieldFor(row.kind, decision, axes);

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      const body: CurationDecision = { decision, reason: reason.trim() || null };
      if (field) body.payload = { [field.key]: extra.trim() };
      const out = await riskApi.decideCuration(row.id, body);
      setApplied(out.applied);
      onDone();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  if (!spec) {
    return <span className="rr-muted">이 화면이 모르는 kind 입니다 — 서버를 갱신하세요.</span>;
  }

  return (
    <div className="rr-stack">
      <ErrorBanner error={error} />
      <p className="rr-muted">{spec.what}</p>
      <div className="rr-row">
        <label className="rr-field">
          <span>결정</span>
          <select
            className="rr-select"
            value={decision}
            onChange={(e) => {
              setDecision(e.target.value);
              setExtra("");
            }}
          >
            {spec.decisions.map((d) => (
              <option key={d.value} value={d.value}>
                {d.label}
              </option>
            ))}
          </select>
        </label>
        {field ? (
          <label className="rr-field">
            <span>{field.label}</span>
            {field.options ? (
              <select className="rr-select" value={extra} onChange={(e) => setExtra(e.target.value)}>
                <option value="">고르세요.</option>
                {field.options.map((opt) => (
                  <option key={opt} value={opt}>
                    {opt}
                  </option>
                ))}
              </select>
            ) : (
              <input className="rr-input" value={extra} onChange={(e) => setExtra(e.target.value)} />
            )}
          </label>
        ) : null}
        <label className="rr-field">
          <span>사유(선택)</span>
          <input className="rr-input" value={reason} onChange={(e) => setReason(e.target.value)} />
        </label>
        <button
          type="button"
          className="rr-btn rr-btn-primary"
          // 값을 더 받아야 하는 결정은 그 값이 빌 때 서버가 422 를 낸다 — 보내기 전에 막는다.
          disabled={busy || (field !== null && extra.trim() === "")}
          onClick={submit}
        >
          {busy ? "보내는 중." : "결정"}
        </button>
      </div>
      {field ? <span className="rr-muted">{field.hint}</span> : null}
      {applied && Object.keys(applied).length > 0 ? (
        <pre className="rr-verbatim">{fmtJson(applied)}</pre>
      ) : null}
    </div>
  );
}

export default function CurationQueuePage() {
  const [kind, setKind] = useState<"" | CurationKind>("");
  const [status, setStatus] = useState<CurationStatus>("open");
  const queue = useAsync(
    (signal) => riskApi.getCuration({ kind: kind || undefined, status }, { signal }),
    [kind, status],
  );
  // 축 목록은 서버가 준다 — 통제 어휘를 화면이 따로 갖지 않는다.
  const vocab = useAsync((signal) => riskApi.getVocab({ signal }), []);
  const axes = vocab.data?.promotable_axes ?? [];

  const [openId, setOpenId] = useState<string | null>(null);
  const rows = queue.data?.rows ?? [];

  const byKind = useMemo(() => {
    const acc: Record<string, number> = {};
    for (const r of rows) acc[r.kind] = (acc[r.kind] ?? 0) + 1;
    return acc;
  }, [rows]);

  const columns: Column<CurationRow>[] = [
    {
      key: "kind",
      header: "종류",
      nowrap: true,
      cell: (r) => <Badge tone="info">{KIND_BY_NAME.get(r.kind)?.label ?? r.kind}</Badge>,
    },
    { key: "subject", header: "대상", cell: (r) => <span className="rr-nowrap">{summarize(r) || "-"}</span> },
    {
      key: "status",
      header: "상태",
      nowrap: true,
      cell: (r) => <Badge tone={STATUS_TONE[r.status]}>{r.status}</Badge>,
    },
    { key: "created", header: "올라온 때", nowrap: true, cell: (r) => fmtEpoch(r.created_at) },
    {
      key: "decided",
      header: "결정",
      nowrap: true,
      cell: (r) => (r.decided_at ? `${r.decided_by ?? "-"} · ${fmtEpoch(r.decided_at)}` : "-"),
    },
  ];

  return (
    <>
      <SectionCard
        title="큐레이션 큐"
        subtitle="코드가 판정하지 않고 사람에게 넘긴 것들입니다. 자동 병합·자동 승격은 없습니다."
        actions={
          <button type="button" className="rr-btn rr-btn-quiet" onClick={queue.reload}>
            새로 고침
          </button>
        }
      >
        <div className="rr-row">
          <label className="rr-field">
            <span>종류</span>
            <select className="rr-select" value={kind} onChange={(e) => setKind(e.target.value as "" | CurationKind)}>
              <option value="">전체</option>
              {KINDS.map((k) => (
                <option key={k.kind} value={k.kind}>
                  {k.label}
                  {byKind[k.kind] ? ` (${byKind[k.kind]})` : ""}
                </option>
              ))}
            </select>
          </label>
          <label className="rr-field">
            <span>상태</span>
            <select
              className="rr-select"
              value={status}
              onChange={(e) => setStatus(e.target.value as CurationStatus)}
            >
              <option value="open">열림</option>
              <option value="done">결정됨</option>
              <option value="rejected">기각됨</option>
            </select>
          </label>
        </div>

        <ErrorBanner error={queue.error} onRetry={queue.reload} />
        <ErrorBanner error={vocab.error} />
        {queue.loading && rows.length === 0 ? (
          <LoadingBlock label="큐를 불러오는 중." />
        ) : (
          <DataTable
            columns={columns}
            rows={rows}
            rowKey={(r) => r.id}
            selectedKey={openId}
            onRowClick={(r) => setOpenId((prev) => (prev === r.id ? null : r.id))}
            empty={
              <EmptyBlock
                title="결정할 것이 없습니다."
                hint={
                  status === "open"
                    ? "야간 잡과 패널이 후보를 올리면 여기에 쌓입니다."
                    : "이 상태의 항목이 없습니다."
                }
              />
            }
          />
        )}
      </SectionCard>

      {rows
        .filter((r) => r.id === openId)
        .map((row) => (
          <SectionCard
            key={row.id}
            title={`${KIND_BY_NAME.get(row.kind)?.label ?? row.kind} — ${summarize(row) || row.id}`}
            subtitle={`올라온 때 ${fmtEpoch(row.created_at)}`}
          >
            {row.status === "open" ? (
              <DecisionForm
                row={row}
                axes={axes}
                onDone={() => {
                  queue.reload();
                  setOpenId(null);
                }}
              />
            ) : (
              <p className="rr-muted">
                이미 {row.status} 로 닫힌 항목입니다. 다시 결정하면 서버가 409 를 냅니다.
              </p>
            )}
            <h3 className="rr-subhead">payload 원문</h3>
            <pre className="rr-verbatim">{fmtJson(row.payload)}</pre>
            {row.decision && Object.keys(row.decision).length > 0 ? (
              <>
                <h3 className="rr-subhead">결정 기록</h3>
                <pre className="rr-verbatim">{fmtJson(row.decision)}</pre>
              </>
            ) : null}
          </SectionCard>
        ))}
    </>
  );
}
