// 시험이 읽는 컴파일 산출물 — tsc(tsconfig.test.json)가 CommonJS 로 옮긴 src 를 require 한다(새 의존 없이 node:test 로 돈다).
const fs = require("node:fs");
const path = require("node:path");

const OUT = path.join(__dirname, "..", "node_modules", ".cache", "hwax-risk-tests");

// frontend/package.json 이 type:module 이라 산출물(.js)이 ESM 으로 읽힌다 — 산출물 자리에 CommonJS 표지를 먼저 둔다.
fs.writeFileSync(path.join(OUT, "package.json"), '{"type":"commonjs"}\n');

module.exports = (rel) => require(path.join(OUT, rel));
