// 박스 자격 까닭(GET /me 의 box.reasons) — 고정 문구 대신 서버가 고른 글(message)과 고칠 길(fix)을 그대로 보인다.
import type { BoxReason } from "../types";
import { Banner } from "../ui/primitives";

/** `secrets_valid` 를 거짓으로 만드는 까닭(config.box_assessment) — 앱이 사람 자격을 저장 · 복호하지 못한다. */
export const BLOCKING_BOX_REASONS: ReadonlySet<string> = new Set([
  "host_mismatch",
  "missing_required",
  "cred_key_invalid",
  "cred_key_dev_fallback",
]);

/** 익명에게는 code 만 온다 — 그때 보일 짧은 말. 모르는 code 는 글자 그대로 보인다. */
const CODE_TITLE: Record<string, string> = {
  host_mismatch: "데이터 디렉터리를 옮겨 온 뒤 첫 기동입니다 — 등록된 PAT 를 이번 기동 동안 쓰지 않습니다.",
  missing_required: "자격 암호화 키가 없습니다.",
  cred_key_invalid: "자격 암호화 키를 읽지 못했거나 형식이 맞지 않습니다.",
  cred_key_dev_fallback: "자격 암호화 키를 개발용 폴백 파일에서 읽고 있습니다.",
  cred_key_path_missing: "키 경로가 가리키는 파일이 없습니다.",
  missing_optional: "없는 선택 키가 있습니다 — 앱은 돌고 그 길만 닫힙니다.",
};

/**
 * fix 의 셸 명령은 백틱 하나로 감싼 한 줄이다(데이터 디렉터리에서 돈다) — 그 조각만 코드 모양으로 보인다. 글은 텍스트로만
 * 그리고 HTML 로 풀지 않는다.
 */
function FixText({ text }: { text: string }) {
  const parts = text.split("`");
  return (
    <>
      {parts.map((part, i) =>
        i % 2 === 1 ? (
          <code key={i} className="mx-0.5 select-all break-all rounded bg-muted px-1 py-0.5 font-mono text-[0.8em]">
            {part}
          </code>
        ) : (
          <span key={i}>{part}</span>
        ),
      )}
    </>
  );
}

/**
 * 까닭마다 한 줄 — 막는 것(secrets_valid 를 거짓으로)은 오류, 키 경로 없음은 경고, 선택 키 없음은 정보다(앱은 돈다).
 * `only="blocking"` 은 홈처럼 막는 것만 보일 자리다.
 */
export function BoxReasons({ reasons, only }: { reasons: BoxReason[]; only?: "blocking" }) {
  const shown = only === "blocking" ? reasons.filter((r) => BLOCKING_BOX_REASONS.has(r.code)) : reasons;
  return (
    <>
      {shown.map((reason) => {
        const tone = BLOCKING_BOX_REASONS.has(reason.code)
          ? "error"
          : reason.code === "missing_optional"
            ? "info"
            : "warn";
        return (
          <Banner
            key={reason.code}
            tone={tone}
            title={reason.message ?? CODE_TITLE[reason.code] ?? reason.code}
            detail={reason.fix ? <FixText text={reason.fix} /> : undefined}
          />
        );
      })}
    </>
  );
}
