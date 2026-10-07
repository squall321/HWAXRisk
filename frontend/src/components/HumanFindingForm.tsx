// 사람이 직접 제기하는 리스크 등록 폼 — 패널 산출과 같은 표에 origin='human' 으로 앉는다(계획 §4.3.1)
import { useState } from "react";
import { Plus } from "lucide-react";
import { riskApi } from "../api/risk.api";
import { ErrorBanner } from "./StateBlocks";
import { Badge } from "./Badge";
import { Banner, Button, FormField, FormGrid, Input, Select, Textarea } from "../ui/primitives";
import type { Direction, HumanFindingCreate, Judgement, Severity, TaxonomyAxis } from "../types";

const DIRECTIONS: Direction[] = ["risk", "improvement", "neutral"];
const SEVERITIES: Severity[] = ["경미", "중대", "치명"];
const JUDGEMENTS: Judgement[] = ["OK", "WARNING", "FAIL", "undetermined"];

/**
 * 인용은 최소 1건이다 — 서버가 `cites:[]` 를 422 로 막는다(§4.3.1). 폼도 같은 규칙을 먼저 적용해
 * 사용자가 422 를 보고 나서야 알게 되지 않도록 한다.
 */
export function HumanFindingForm({
  targetKey,
  mechanisms,
  onCreated,
}: {
  targetKey: string;
  /** `GET /meta/taxonomy` 의 mechanism 축 — 어휘를 화면이 따로 갖지 않는다. */
  mechanisms: TaxonomyAxis[];
  onCreated: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [direction, setDirection] = useState<Direction>("risk");
  const [mechanism, setMechanism] = useState("unclassified");
  const [severity, setSeverity] = useState<Severity | "">("");
  const [judgement, setJudgement] = useState<Judgement | "">("");
  const [subject, setSubject] = useState("");
  const [trigger, setTrigger] = useState("");
  const [claim, setClaim] = useState("");
  const [warrant, setWarrant] = useState("");
  const [cites, setCites] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [made, setMade] = useState<string | null>(null);

  /** 한 줄에 하나씩 적은 참조. `ref  quote` 로 공백 뒤는 인용문으로 본다. */
  const parsedCites = cites
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const gap = line.search(/\s/);
      return gap === -1
        ? { ref: line }
        : { ref: line.slice(0, gap), quote: line.slice(gap + 1).trim() };
    });

  const ready = claim.trim() !== "" && parsedCites.length > 0;

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      const body: HumanFindingCreate = {
        direction,
        mechanism,
        claim: claim.trim(),
        cites: parsedCites,
        subject_key: subject.trim() || null,
        trigger_condition: trigger.trim() || null,
        warrant: warrant.trim() || null,
        severity: severity || null,
        judgement: judgement || null,
      };
      const out = await riskApi.createFinding(targetKey, body);
      setMade(out.finding_id);
      setClaim("");
      setWarrant("");
      setCites("");
      setTrigger("");
      onCreated();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  if (!open) {
    return (
      <div className="flex flex-wrap items-center gap-2">
        <Button type="button" variant="outline" onClick={() => setOpen(true)}>
          <Plus className="size-4" aria-hidden="true" />
          리스크 직접 등록
        </Button>
        <span className="text-sm text-muted-foreground">
          좌석이 못 본 것을 사람이 올립니다. 등록한 행은 표에 <Badge tone="info">사람</Badge> 로 보이고
          전문가 지지로 세지 않습니다.
        </span>
      </div>
    );
  }

  return (
    <div className="mt-3 flex flex-col gap-3">
      <ErrorBanner error={error} />
      {made ? (
        <Banner
          tone="info"
          live="status"
          title={`등록했습니다 — ${made}`}
          detail="근거 등급은 인용에서 코드가 산출합니다(§0.2.1 (5)). 수정·삭제는 작성자만 할 수 있습니다."
        />
      ) : null}

      <FormGrid>
        <FormField label="방향" hint="direction">
          <Select value={direction} onChange={(e) => setDirection(e.target.value as Direction)}>
            {DIRECTIONS.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </Select>
        </FormField>
        <FormField label="메커니즘" hint="mechanism">
          <Select value={mechanism} onChange={(e) => setMechanism(e.target.value)}>
            <option value="unclassified">unclassified</option>
            {mechanisms.map((m) => (
              <option key={m.code} value={m.code}>
                {m.code} · {m.label}
              </option>
            ))}
          </Select>
        </FormField>
        <FormField label="심각도" hint="severity">
          <Select value={severity} onChange={(e) => setSeverity(e.target.value as Severity | "")}>
            <option value="">(미정)</option>
            {SEVERITIES.map((v) => (
              <option key={v} value={v}>
                {v}
              </option>
            ))}
          </Select>
        </FormField>
        <FormField label="판정" hint="judgement">
          <Select value={judgement} onChange={(e) => setJudgement(e.target.value as Judgement | "")}>
            <option value="">(미정)</option>
            {JUDGEMENTS.map((v) => (
              <option key={v} value={v}>
                {v}
              </option>
            ))}
          </Select>
        </FormField>
      </FormGrid>

      <FormGrid>
        <FormField label="대상 키" hint="subject_key · 선택">
          <Input value={subject} onChange={(e) => setSubject(e.target.value)} />
        </FormField>
        <FormField label="발생 조건" hint="trigger_condition · 선택">
          <Input value={trigger} onChange={(e) => setTrigger(e.target.value)} />
        </FormField>
      </FormGrid>

      <FormField label="무엇이 문제인가" hint="claim · 필수 · 2000자 이내">
        <Textarea rows={3} value={claim} onChange={(e) => setClaim(e.target.value)} />
      </FormField>
      <FormField label="왜 그렇게 보는가" hint="warrant · 선택">
        <Textarea rows={2} value={warrant} onChange={(e) => setWarrant(e.target.value)} />
      </FormField>
      <FormField label="근거 참조" hint="cites · 한 줄에 하나 · 1건 이상 필수. 공백 뒤는 인용문입니다.">
        <Textarea
          rows={3}
          value={cites}
          onChange={(e) => setCites(e.target.value)}
          placeholder={"p:a1b2c3d4e5f6  두께 0.28mm\nreq:thickness\nvoc:F7-2024#ISS-1"}
        />
      </FormField>

      <div className="flex flex-wrap items-center gap-2">
        <Button type="button" disabled={busy || !ready} onClick={submit}>
          {busy ? "등록 중." : "등록"}
        </Button>
        <Button type="button" variant="ghost" onClick={() => setOpen(false)}>
          닫기
        </Button>
        <span className="text-sm text-muted-foreground">
          인용 {parsedCites.length}건
          {ready ? null : " — claim 과 인용 1건 이상이 필요합니다(서버도 같은 규칙으로 422 를 냅니다)."}
        </span>
      </div>
    </div>
  );
}
