// 사람이 직접 제기하는 리스크 등록 폼 — 패널 산출과 같은 표에 origin='human' 으로 앉는다(계획 §4.3.1)
import { useState } from "react";
import { riskApi } from "../api/risk.api";
import { ErrorBanner } from "./StateBlocks";
import { Badge } from "./Badge";
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
      <div className="rr-row">
        <button type="button" className="rr-btn" onClick={() => setOpen(true)}>
          리스크 직접 등록
        </button>
        <span className="rr-muted">
          좌석이 못 본 것을 사람이 올립니다. 등록한 행은 표에 <Badge tone="info">사람</Badge> 로 보이고
          전문가 지지로 세지 않습니다.
        </span>
      </div>
    );
  }

  return (
    <div className="rr-stack">
      <ErrorBanner error={error} />
      {made ? (
        <div className="rr-banner rr-banner-info" role="status">
          <span className="rr-banner-title">등록했습니다 — {made}</span>
          <span className="rr-banner-detail">
            근거 등급은 인용에서 코드가 산출합니다(§0.2.1 (5)). 수정·삭제는 작성자만 할 수 있습니다.
          </span>
        </div>
      ) : null}

      <div className="rr-row">
        <label className="rr-field">
          <span>direction</span>
          <select className="rr-select" value={direction} onChange={(e) => setDirection(e.target.value as Direction)}>
            {DIRECTIONS.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
        </label>
        <label className="rr-field">
          <span>mechanism</span>
          <select className="rr-select" value={mechanism} onChange={(e) => setMechanism(e.target.value)}>
            <option value="unclassified">unclassified</option>
            {mechanisms.map((m) => (
              <option key={m.code} value={m.code}>
                {m.code} · {m.label}
              </option>
            ))}
          </select>
        </label>
        <label className="rr-field">
          <span>severity</span>
          <select className="rr-select" value={severity} onChange={(e) => setSeverity(e.target.value as Severity | "")}>
            <option value="">(미정)</option>
            {SEVERITIES.map((v) => (
              <option key={v} value={v}>
                {v}
              </option>
            ))}
          </select>
        </label>
        <label className="rr-field">
          <span>judgement</span>
          <select
            className="rr-select"
            value={judgement}
            onChange={(e) => setJudgement(e.target.value as Judgement | "")}
          >
            <option value="">(미정)</option>
            {JUDGEMENTS.map((v) => (
              <option key={v} value={v}>
                {v}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="rr-row">
        <label className="rr-field">
          <span>subject_key(선택)</span>
          <input className="rr-input" value={subject} onChange={(e) => setSubject(e.target.value)} />
        </label>
        <label className="rr-field">
          <span>trigger_condition(선택)</span>
          <input className="rr-input" value={trigger} onChange={(e) => setTrigger(e.target.value)} />
        </label>
      </div>

      <label className="rr-field">
        <span>claim — 무엇이 문제인가(필수, 2000자 이내)</span>
        <textarea className="rr-textarea" rows={3} value={claim} onChange={(e) => setClaim(e.target.value)} />
      </label>
      <label className="rr-field">
        <span>warrant — 왜 그렇게 보는가(선택)</span>
        <textarea className="rr-textarea" rows={2} value={warrant} onChange={(e) => setWarrant(e.target.value)} />
      </label>
      <label className="rr-field">
        <span>cites — 한 줄에 참조 하나(필수 1건 이상). 공백 뒤는 인용문입니다.</span>
        <textarea
          className="rr-textarea"
          rows={3}
          value={cites}
          onChange={(e) => setCites(e.target.value)}
          placeholder={"p:a1b2c3d4e5f6  두께 0.28mm\nreq:thickness\nvoc:F7-2024#ISS-1"}
        />
      </label>

      <div className="rr-row">
        <button type="button" className="rr-btn rr-btn-primary" disabled={busy || !ready} onClick={submit}>
          {busy ? "등록 중." : "등록"}
        </button>
        <button type="button" className="rr-btn rr-btn-quiet" onClick={() => setOpen(false)}>
          닫기
        </button>
        <span className="rr-muted">
          인용 {parsedCites.length}건
          {ready ? null : " — claim 과 인용 1건 이상이 필요합니다(서버도 같은 규칙으로 422 를 냅니다)."}
        </span>
      </div>
    </div>
  );
}
