// 정규 키(ckey) 원장 조작 — 고른 노드의 키에 이름 붙이기 · 다른 키로 병합 · 병합 되돌리기 · 독립 키 확정(B34 149 · 계획 §2.7.3 · §5.9.2)
import { useMemo, useState } from "react";
import { riskApi } from "../api/risk.api";
import { ErrorBanner } from "./StateBlocks";
import { Banner, Button, FormField, Input, Mono, Select, SubPanel } from "../ui/primitives";
import type { CkeyLedgerDecision, IrNode, JsonObject } from "../types";

/** 정규 키 꼴(ir_builder — 'ck:' + sha1 앞 12자리). 다른 과제의 키를 손으로 적을 때 이 꼴만 받는다(서버는 into 를 검사하지 않는다). */
export const CKEY_RE = /^ck:[0-9a-f]{12}$/;

type Pending = { decision: CkeyLedgerDecision; confirm: string } | null;

/** 결정의 사람 말 — 확인 글과 결과 줄에 쓴다. */
function resultLine(row: JsonObject): string {
  const decision = String(row.decision ?? "");
  if (decision === "merge_key") return `${String(row.ckey)} → ${String(row.merged_into)} 로 병합했습니다.`;
  if (decision === "unmerge_key") return `${String(row.ckey)} 의 병합을 되돌렸습니다(독립 확정 키).`;
  if (decision === "confirm_key") return `${String(row.ckey)} 를 독립 키로 확정했습니다.`;
  if (decision === "rename_key") return `${String(row.ckey)} 의 이름을 «${String(row.display_name)}» 로 붙였습니다.`;
  return JSON.stringify(row);
}

/**
 * 고른 노드의 정규 키 원장(`POST /sameas/decide` 의 ckey 결정 넷). 병합 · 되돌리기는 원장에만 쓰고 이미 동결된 스냅샷의 ckey 는
 * 바뀌지 않는다 — 조회 · 회수는 유효 키(merged_into 를 따라간 키)로 잇는다. 지금 키 상태(병합 여부 · 붙은 이름)를 읽는 길은 이 서버에
 * 없어(rr_part_keys 조회 경로가 없다) 결과 줄로만 확인한다.
 */
export function KeyLedgerPanel({ node, nodes, onClose }: { node: IrNode; nodes: IrNode[]; onClose: () => void }) {
  const ckey = node.ckey;
  const [displayName, setDisplayName] = useState("");
  const [into, setInto] = useState("");
  const [typedInto, setTypedInto] = useState("");
  const [pending, setPending] = useState<Pending>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [done, setDone] = useState<string | null>(null);

  /** 이 스냅샷의 다른 정규 키(이름과 함께, 한 번씩). */
  const others = useMemo(() => {
    const seen = new Map<string, string>();
    for (const n of nodes) {
      if (!n.ckey || n.ckey === ckey || seen.has(n.ckey)) continue;
      seen.set(n.ckey, `${n.label} · ${n.kind}`);
    }
    return Array.from(seen, ([key, label]) => ({ key, label })).sort((a, b) => a.label.localeCompare(b.label));
  }, [nodes, ckey]);

  if (!ckey) {
    return (
      <SubPanel className="mt-3" title={`정규 키 원장 — ${node.label}`}>
        <p className="m-0 text-sm text-muted-foreground">이 노드에는 정규 키(ckey)가 없습니다.</p>
      </SubPanel>
    );
  }

  const target = typedInto.trim() !== "" ? typedInto.trim() : into;
  const typedBad = typedInto.trim() !== "" && !CKEY_RE.test(typedInto.trim());

  async function send(decision: CkeyLedgerDecision) {
    setBusy(true);
    setError(null);
    setDone(null);
    try {
      const out = await riskApi.decideSameAs([decision]);
      setDone(out.results.map(resultLine).join(" "));
      setPending(null);
      setDisplayName("");
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <SubPanel
      className="mt-3"
      title={
        <span className="flex flex-wrap items-center gap-2">
          정규 키 원장 — {node.label} <Mono>{ckey}</Mono>
        </span>
      }
      actions={
        <Button type="button" variant="ghost" size="sm" onClick={onClose}>
          닫기
        </Button>
      }
    >
      <p className="m-0 text-xs text-muted-foreground">
        원장에만 씁니다 — 이미 동결된 스냅샷의 키는 그대로이고 조회 · 회수가 유효 키로 잇습니다. 이 서버는 키의 지금 상태(병합 ·
        이름)를 읽는 길을 주지 않아 결과 줄로만 확인합니다.
      </p>
      <ErrorBanner error={error} />
      {done ? <Banner tone="info" live="status" title={done} /> : null}

      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          if (displayName.trim() === "") return;
          void send({ decision: "rename_key", ckey, display_name: displayName.trim() });
        }}
      >
        <FormField label="표시 이름" hint="rename_key · display_name" className="min-w-[14rem]">
          <Input value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
        </FormField>
        <Button type="submit" variant="outline" size="sm" disabled={busy || displayName.trim() === ""}>
          이름 붙이기
        </Button>
      </form>

      <div className="flex flex-wrap items-end gap-2">
        <FormField label="병합할 대표 키" hint="merge_key · 이 스냅샷의 키" className="min-w-[14rem]">
          <Select value={into} onChange={(e) => setInto(e.target.value)}>
            <option value="">고르세요</option>
            {others.map((o) => (
              <option key={o.key} value={o.key}>
                {o.label} — {o.key}
              </option>
            ))}
          </Select>
        </FormField>
        <FormField
          label="또는 다른 과제의 키"
          hint="ck: + 16진 12자리"
          error={typedBad ? "정규 키 꼴(ck:…)이 아닙니다." : undefined}
          className="min-w-[12rem]"
        >
          <Input value={typedInto} onChange={(e) => setTypedInto(e.target.value)} placeholder="ck:" />
        </FormField>
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={busy || target === "" || typedBad || target === ckey}
          onClick={() =>
            setPending({
              decision: { decision: "merge_key", ckey_from: ckey, ckey_into: target },
              confirm: `${ckey} 를 ${target} 로 병합합니다. 두 키가 한 부품으로 이어져 회수 · 등록부가 대표 키로 묶입니다.`,
            })
          }
        >
          병합…
        </Button>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={busy}
          onClick={() =>
            setPending({
              decision: { decision: "unmerge_key", ckey },
              confirm: `${ckey} 의 병합을 되돌립니다 — 병합 대상을 비우고 독립 확정 키가 됩니다(자동 승계 병합도 되돌립니다).`,
            })
          }
        >
          병합 되돌리기…
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          disabled={busy}
          onClick={() => void send({ decision: "confirm_key", ckey })}
        >
          독립 키로 확정
        </Button>
      </div>

      {pending ? (
        <Banner tone="warn" live="status" title={pending.confirm}>
          <span className="flex flex-wrap items-center gap-2">
            <Button type="button" size="sm" disabled={busy} onClick={() => void send(pending.decision)}>
              그대로 진행
            </Button>
            <Button type="button" variant="ghost" size="sm" onClick={() => setPending(null)}>
              그만두기
            </Button>
          </span>
        </Banner>
      ) : null}
    </SubPanel>
  );
}
