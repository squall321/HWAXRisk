// 큐레이션 큐 화면 — kind 6종의 열린 항목을 사람이 결정한다(계획 §7.7). 자동 적용은 없고 결정은 전부 사람 손이다.
import { useMemo, useState } from "react";
import { RefreshCw } from "lucide-react";
import { riskApi } from "../api/risk.api";
import { useAsync } from "../hooks/useAsync";
import { SectionCard, VerbatimBlock } from "../components/SectionCard";
import { DataTable, KeyValueTable } from "../components/DataTable";
import type { Column } from "../components/DataTable";
import { EmptyBlock, ErrorBanner, LoadingBlock } from "../components/StateBlocks";
import { Badge } from "../components/Badge";
import type { Tone } from "../components/Badge";
import {
  Banner,
  Button,
  Chip,
  FormField,
  FormGrid,
  Input,
  Mono,
  PageHeader,
  Select,
  TabBar,
} from "../ui/primitives";
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

/**
 * 상태를 고르는 자리에서 쓸 사람 말. 배지는 저장 값(`open`·`done`·`rejected`)을 그대로 보이고
 * (§8.2.4 '배지 = 저장 값과 같은 문자열') 이 이름은 고르는 칸과 건수 줄에서만 쓴다.
 * 순서는 선택지 순서이기도 하다.
 */
const STATUS_LABEL: Record<CurationStatus, string> = { open: "열림", done: "결정됨", rejected: "기각됨" };
/** 서버 창 상한(backend routes.py `CURATION_LIMIT_MAX`). 받아 온 수가 이것이면 더 있을 수 있다. */
const CURATION_WINDOW = 200;

/** 결정에 값을 더 받아야 하는 kind — 어느 축인지·어느 값으로인지는 코드가 고를 수 없다. */
type ExtraField = { key: string; label: string; hint: string; options?: string[] };

function extraFieldFor(kind: CurationKind, decision: string, axes: string[]): ExtraField | null {
  if (kind === "x_tag_promote" && decision === "promote") {
    return { key: "axis", label: "올릴 축", hint: "`char:<axis>:<value>` 의 축입니다.", options: axes };
  }
  if (kind === "unclassified_code" && (decision === "map" || decision === "new")) {
    // 라벨은 사람 말로 쓰고 원시 필드명은 설명에 남긴다 — 서버와 대조할 이름을 지우지는 않는다(D35).
    return { key: "mechanism_detail", label: "옮겨 갈 값", hint: "mechanism_detail — 옮겨 갈 택소노미 값입니다." };
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

/** 값이 없다는 사실 자체를 적는다 — 빈 칸이나 `-` 로 그리면 '0' 이나 '없음' 처럼 읽힌다. */
function Unknown({ what = "아직 없음" }: { what?: string }) {
  return <Chip tone="muted">{what}</Chip>;
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
    return <span className="text-sm text-muted-foreground">이 화면이 모르는 kind 입니다 — 서버를 갱신하세요.</span>;
  }

  return (
    <div className="flex flex-col gap-3">
      <ErrorBanner error={error} />
      <p className="m-0 text-sm text-muted-foreground">{spec.what}</p>
      <FormGrid>
        <FormField label="결정">
          <Select
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
          </Select>
        </FormField>
        {field ? (
          // 설명은 입력 칸 옆에 둔다 — 폼 밑에 적으면 값을 넣은 **뒤에** 읽는다.
          <FormField label={field.label} hint={field.hint}>
            {field.options ? (
              <Select value={extra} onChange={(e) => setExtra(e.target.value)}>
                <option value="">고르세요.</option>
                {field.options.map((opt) => (
                  <option key={opt} value={opt}>
                    {opt}
                  </option>
                ))}
              </Select>
            ) : (
              <Input value={extra} onChange={(e) => setExtra(e.target.value)} />
            )}
          </FormField>
        ) : null}
        <FormField label="사유(선택)">
          <Input value={reason} onChange={(e) => setReason(e.target.value)} />
        </FormField>
      </FormGrid>
      <div className="flex flex-wrap items-center gap-2">
        <Button
          type="button"
          // 값을 더 받아야 하는 결정은 그 값이 빌 때 서버가 422 를 낸다 — 보내기 전에 막는다.
          disabled={busy || (field !== null && extra.trim() === "")}
          onClick={submit}
        >
          {busy ? "보내는 중." : "결정"}
        </Button>
      </div>
      {applied && Object.keys(applied).length > 0 ? (
        <VerbatimBlock label="적용 결과" text={fmtJson(applied)} />
      ) : null}
    </div>
  );
}

export default function CurationQueuePage() {
  const [kind, setKind] = useState<"" | CurationKind>("");
  const [status, setStatus] = useState<CurationStatus>("open");
  const queue = useAsync(
    (signal) => riskApi.getCuration({ kind: kind || undefined, status, limit: CURATION_WINDOW }, { signal }),
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

  /**
   * 탭에 붙는 건수는 **지금 불러온 행에서 센 것**이다. 아직 못 불러왔거나 종류를 하나로 좁혀 둔
   * 동안에는 다른 종류가 몇 건인지 알 수 없으므로 0 대신 null 을 준다 — 0 건과 '모른다' 는 다르고,
   * TabBar 는 null 이면 숫자 자리를 아예 만들지 않는다.
   */
  function countFor(target: "" | CurationKind): number | null {
    if (!queue.data) return null;
    if (kind !== "" && kind !== target) return null;
    return target === "" ? rows.length : (byKind[target] ?? 0);
  }

  const kindTabs: Array<{ tab: "" | CurationKind; label: string; count: number | null }> = [
    { tab: "", label: "전체", count: countFor("") },
    ...KINDS.map((k) => ({ tab: k.kind, label: k.label, count: countFor(k.kind) })),
  ];

  const columns: Column<CurationRow>[] = [
    {
      key: "kind",
      header: "종류",
      nowrap: true,
      cell: (r) => <Badge tone="info">{KIND_BY_NAME.get(r.kind)?.label ?? r.kind}</Badge>,
    },
    {
      key: "subject",
      header: "대상",
      nowrap: true,
      cell: (r) => summarize(r) || <span className="text-muted-foreground">—</span>,
    },
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
      // 결정 전인 것을 `-` 로 적으면 '결정자가 하이픈' 으로 읽힌다 — 비어 있다는 사실만 적는다.
      // 판정 조건(`decided_at` 이 있나)은 바꾸지 않았다.
      cell: (r) =>
        r.decided_at ? (
          `${r.decided_by ?? "—"} · ${fmtEpoch(r.decided_at)}`
        ) : (
          <span className="text-muted-foreground">—</span>
        ),
    },
  ];

  return (
    <>
      <PageHeader
        // 상위 화면이 없다 — 사이드바의 형제 항목이라 과제 목록의 하위로 적으면 없는 계층을 지어내는 것이다.
        title="큐레이션 큐"
        subtitle="코드가 판정하지 않고 사람에게 넘긴 것들입니다. 자동 병합·자동 승격은 없습니다."
        actions={
          <Button type="button" variant="ghost" onClick={queue.reload}>
            <RefreshCw className="size-4" aria-hidden="true" />
            새로 고침
          </Button>
        }
      />

      {/* 종류 고르기 — 건수를 탭에 달아 '어디에 쌓였나' 를 고르기 전에 읽게 한다. */}
      <TabBar tabs={kindTabs} value={kind} onChange={setKind} label="큐레이션 종류" />

      <SectionCard
        title={kind === "" ? "모든 종류" : (KIND_BY_NAME.get(kind)?.label ?? kind)}
        // 서버는 `{rows}` 만 주고 총계를 안 준다(routes.py get_curation). 그래서 `rows.length` 는
        // **총계가 아니라 받아 온 창의 크기**다 — 상한(200)에 닿았으면 그렇게 말하고, 아니면
        // 그때만 건수가 곧 총계다. 다른 화면은 `list.data.total` 을 쓰므로 모양이 같으면 총계로 읽힌다.
        subtitle={
          queue.data
            ? rows.length >= CURATION_WINDOW
              ? `${STATUS_LABEL[status]} ${rows.length}건 이상 — 창 상한입니다.`
              : `${STATUS_LABEL[status]} ${rows.length}건`
            : undefined
        }
        actions={
          <FormField label="상태" className="w-36">
            <Select value={status} onChange={(e) => setStatus(e.target.value as CurationStatus)}>
              {(Object.keys(STATUS_LABEL) as CurationStatus[]).map((s) => (
                <option key={s} value={s}>
                  {STATUS_LABEL[s]}
                </option>
              ))}
            </Select>
          </FormField>
        }
      >
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
        .map((row) => {
          const subject = summarize(row);
          const kindLabel = KIND_BY_NAME.get(row.kind)?.label ?? row.kind;
          return (
            <SectionCard
              key={row.id}
              title={kindLabel}
              subtitle={subject ? <span className="break-all">{subject}</span> : <Mono>{row.id}</Mono>}
              bodyClassName="flex flex-col gap-3"
            >
              {/* 개요 — 라벨은 사람 말로 쓰고 서버 필드명은 hint 로 접어 둔다(D35). 값은 서버가 준 그대로다. */}
              <KeyValueTable
                rows={[
                  { label: "종류", hint: "kind", value: <Badge tone="info">{kindLabel}</Badge> },
                  { label: "상태", hint: "status", value: <Badge tone={STATUS_TONE[row.status]}>{row.status}</Badge> },
                  { label: "항목 id", hint: "id", value: <Mono>{row.id}</Mono> },
                  { label: "올라온 때", hint: "created_at", value: fmtEpoch(row.created_at) },
                  { label: "결정한 사람", hint: "decided_by", value: row.decided_by ?? <Unknown /> },
                  {
                    label: "결정한 때",
                    hint: "decided_at",
                    value: row.decided_at ? fmtEpoch(row.decided_at) : <Unknown />,
                  },
                ]}
              />
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
                <Banner
                  live="none"
                  tone="info"
                  title={`이미 ${row.status} 로 닫힌 항목입니다.`}
                  detail="다시 결정하면 서버가 409 를 냅니다."
                />
              )}
              {/* 결정 기록을 payload 원문보다 위로 올렸다 — 닫힌 항목에서 먼저 찾는 것은 '무엇으로 정했나' 이고 원문은 그 근거다. */}
              {row.decision && Object.keys(row.decision).length > 0 ? (
                <VerbatimBlock label="결정 기록" text={fmtJson(row.decision)} />
              ) : null}
              <VerbatimBlock label="payload 원문" text={fmtJson(row.payload)} />
            </SectionCard>
          );
        })}
    </>
  );
}
