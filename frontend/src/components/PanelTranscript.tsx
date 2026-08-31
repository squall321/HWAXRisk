// 패널 기록 — 앱 DB 의 좌석 발언·도구 사용·결정문·risk_spec 파싱 결과를 그린다(계획 §8.2.4). 포털 conv_store 를 읽지 않는다.
import { riskApi } from "../api/risk.api";
import { useAsync } from "../hooks/useAsync";
import type { Column } from "./DataTable";
import { DataTable, KeyValueTable } from "./DataTable";
import { ErrorBanner, LoadingBlock } from "./StateBlocks";
import { VerbatimBlock } from "./SectionCard";
import { JudgementBadge, SeverityBadge } from "./Badge";
import { fmtCell, fmtJson } from "../format";
import type { JsonObject, JsonValue, SeatTurn } from "../types";

/** risk_spec 안의 항목 1건을 표 한 줄로 편 것(값은 서버가 준 원문 그대로다). */
type SpecRow = {
  key: string;
  group: string;
  id: string;
  direction: string;
  domain: string;
  mechanism: string;
  severity: string;
  judgement: string;
  tools: string;
  raisedBy: string;
};

function isObject(value: JsonValue | undefined): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function objectsAt(spec: JsonObject, key: string): JsonObject[] {
  const value = spec[key];
  if (!Array.isArray(value)) return [];
  return value.filter(isObject);
}

function text(item: JsonObject, key: string): string {
  return fmtCell(item[key]);
}

/** `tool_calls` 는 목록이거나 수치라 형식만 맞춘다. */
function tools(item: JsonObject): string {
  const value = item["tool_calls"];
  if (value === undefined || value === null) return "-";
  if (Array.isArray(value)) return value.length === 0 ? "0" : value.map((v) => fmtCell(v)).join(", ");
  return fmtCell(value);
}

function specRows(spec: JsonObject): SpecRow[] {
  const rows: SpecRow[] = [];
  for (const group of ["findings", "gains"]) {
    objectsAt(spec, group).forEach((item, i) => {
      rows.push({
        key: `${group}#${i}`,
        group,
        id: text(item, "id"),
        direction: text(item, "direction"),
        domain: text(item, "domain"),
        mechanism: `${text(item, "mechanism")} · ${text(item, "mechanism_detail")}`,
        severity: text(item, "severity"),
        judgement: text(item, "judgement"),
        tools: tools(item),
        raisedBy: text(item, "raised_by"),
      });
    });
  }
  return rows;
}

export function PanelTranscript({ panelId }: { panelId: string }) {
  const transcript = useAsync((signal) => riskApi.getPanelTranscript(panelId, { signal }), [panelId]);

  const columns: Column<SeatTurn>[] = [
    { key: "seat", header: "좌석", cell: (t) => <code>{t.seat}</code>, nowrap: true },
    { key: "round", header: "라운드", cell: (t) => t.round, align: "right", nowrap: true },
    { key: "position", header: "position", cell: (t) => t.position ?? "-", nowrap: true },
    { key: "stance", header: "stance", cell: (t) => t.stance ?? "-", nowrap: true },
    { key: "say", header: "발언 발췌", cell: (t) => t.say_excerpt },
  ];

  const specColumns: Column<SpecRow>[] = [
    { key: "group", header: "구분", cell: (r) => r.group, nowrap: true },
    { key: "id", header: "id", cell: (r) => <code>{r.id}</code>, nowrap: true },
    { key: "direction", header: "direction", cell: (r) => r.direction, nowrap: true },
    { key: "domain", header: "domain", cell: (r) => r.domain, nowrap: true },
    { key: "mechanism", header: "mechanism", cell: (r) => r.mechanism },
    { key: "severity", header: "severity", cell: (r) => <SeverityBadge value={r.severity} />, nowrap: true },
    { key: "judgement", header: "judgement", cell: (r) => <JudgementBadge value={r.judgement} />, nowrap: true },
    { key: "tools", header: "도구 사용", cell: (r) => r.tools },
    { key: "raised", header: "raised_by", cell: (r) => r.raisedBy, nowrap: true },
  ];

  const spec = transcript.data?.risk_spec ?? null;
  const parsed = spec ? specRows(spec) : [];

  return (
    <div className="rr-stack">
      <ErrorBanner error={transcript.error} onRetry={transcript.reload} />
      {transcript.loading && !transcript.data ? <LoadingBlock /> : null}
      {transcript.data ? (
        <>
          <VerbatimBlock text={transcript.data.decision_text} label="결정문" />
          <h3 className="rr-subhead">좌석 발언</h3>
          <DataTable
            columns={columns}
            rows={transcript.data.turns}
            rowKey={(t, i) => `${t.seat}#${t.round}#${i}`}
            empty="좌석 발언이 없습니다."
          />
          <h3 className="rr-subhead">risk_spec 파싱 결과</h3>
          {spec ? (
            <>
              <KeyValueTable
                rows={[
                  { label: "verdict", value: fmtCell(spec["verdict"]) },
                  { label: "taxonomy_version", value: fmtCell(spec["taxonomy_version"]) },
                  { label: "findings / gains", value: `${objectsAt(spec, "findings").length} / ${objectsAt(spec, "gains").length}` },
                ]}
              />
              <DataTable
                columns={specColumns}
                rows={parsed}
                rowKey={(r) => r.key}
                empty="findings·gains 가 비어 있습니다."
              />
              <VerbatimBlock text={fmtJson(spec)} label="risk_spec 원문" />
            </>
          ) : (
            <p className="rr-muted">risk_spec 이 아직 없습니다(파싱 실패이거나 진행 중).</p>
          )}
        </>
      ) : null}
    </div>
  );
}
