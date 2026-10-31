// 시험이 읽는 컴파일 산출물 — tsc(tsconfig.test.json)가 CommonJS 로 옮긴 src 를 require 한다(새 의존 없이 node:test 로 돈다).
const fs = require("node:fs");
const path = require("node:path");

const OUT = path.join(__dirname, "..", "node_modules", ".cache", "hwax-risk-tests");
const MARK = path.join(OUT, "package.json");
const BODY = '{"type":"commonjs"}\n';

// frontend/package.json 이 type:module 이라 산출물(.js)이 ESM 으로 읽힌다 — 산출물 자리에 CommonJS 표지를 먼저 둔다.
// node --test 는 시험 파일마다 프로세스를 따로 띄워 함께 돌린다. 그 자리에 그냥 덮어쓰면 다른 프로세스가 반쯤 쓴 표지를 읽어
// 'Unexpected end of JSON input' 으로 죽는다(실제로 한 번 났다) — 이미 있으면 건드리지 않고, 없으면 임시 파일에 쓴 뒤 이름을 바꾼다(원자적).
let present = false;
try {
  present = fs.readFileSync(MARK, "utf8") === BODY;
} catch {
  present = false;
}
if (!present) {
  const tmp = `${MARK}.${process.pid}.tmp`;
  fs.writeFileSync(tmp, BODY);
  fs.renameSync(tmp, MARK);
}

module.exports = (rel) => require(path.join(OUT, rel));
