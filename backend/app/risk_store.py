# 앱 DB(SQLite) 저장소 — RiskStore(stdlib sqlite3 + Lock), PRAGMA user_version 마이그레이션(v1 = plan §5.2.2 rr_* 41표 DDL 전문), 살림 표 _schema_migrations·_user_credentials
from __future__ import annotations

import shutil
import sqlite3
import threading
import time
from collections.abc import Iterable, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from app import config
from app.errors import AppError

# owner_sub 컬럼의 값은 heax 사용자 이메일(소문자)이다. 원천은 identity.py 의 heax `GET /api/v1/auth/me` 되묻기(plan §5.2.1·§8.2.8)이며
# X-Heax-User-* 헤더는 service 모드 앱에 복사되지 않고 위조 가능하므로 원천으로 쓰지 않는다.
# 아래 DDL 은 plan §5.2.2 A~H 의 ```sql 블록 8개(rr_ 41표·인덱스 58)를 바이트 그대로 옮긴 것이다 — 블록 경계의 빈 줄
# 하나 말고는 문장이 문서와 같다(고치려면 plan 을 먼저 고친다).
_DDL_V1_SQL = """\
CREATE TABLE IF NOT EXISTS rr_projects (
  id TEXT PRIMARY KEY, owner_sub TEXT NOT NULL,
  code TEXT NOT NULL, name TEXT, stage TEXT,
  predecessor_project_id TEXT,                  -- 계보(UI 입력) → RA revision_of
  adh_team TEXT, adh_group TEXT,                -- 사용자 확인값, 자동 채움 금지
  ra_entity_id INTEGER, adh_character_record_id TEXT,
  character_status TEXT CHECK(character_status IN ('seed','panel','confirmed')) DEFAULT 'seed',
  classification TEXT NOT NULL CHECK(classification IN ('internal','confidential')) DEFAULT 'confidential',  -- §5.2.5 (3) 반출 경계, 등록 화면 필수 선택
  lifecycle TEXT NOT NULL CHECK(lifecycle IN ('active','shipped','cancelled','archived')) DEFAULT 'active',
  closed_at INTEGER,                            -- lifecycle 이 active 를 떠난 시각
  corpus_excluded INTEGER NOT NULL DEFAULT 0,   -- 1 = 학습·통계·회수에서 제외(§0.6 코퍼스 필터)
  excluded_reason TEXT,                         -- 'fixture' | 'misregistered' | 'duplicate' | 'user' — corpus_excluded=1 이면 필수
  status TEXT NOT NULL CHECK(status IN ('active','purged')) DEFAULT 'active',
  mcp_visibility TEXT NOT NULL CHECK(mcp_visibility IN ('private','org')) DEFAULT 'private',  -- §5.1 원칙 9 투영·MCP 노출 토글(소유자만). private 면 RA 객체 미생성(external_sync.ra='withheld')·MCP 읽기 404 not_visible
  mcp_visibility_by TEXT, mcp_visibility_at INTEGER,   -- 토글 주체·시각(rr_audit(action='project.mcp_visibility') 동반)
  purged_at INTEGER, purge_report_json TEXT,    -- §5.2.6 회수 결과(층별 성공·불가 사유)
  merged_into TEXT,                             -- 중복 등록 병합 대상 project_id(§8.2.3 POST /projects/{id}/merge, P4)
  product_code TEXT,                            -- 대표 제품 코드(§7.6 라벨 경로 4 VOC 조회 키). 없으면 NULL 이고 경로 4 는 그 과제를 건너뛴다
  product_refs_json TEXT,                       -- [{kind: 'ra_model'|'product_code', value, ra_entity_id}] 다중 제품 연결(§7.6 경로 1·2 의 (a) 항)
  predecessor_product_code TEXT,                -- 계보 과제의 product_code(전작 VOC 를 이 과제 브리프에 실을 때의 조회 키)
  created_at INTEGER, updated_at INTEGER,
  UNIQUE(owner_sub, code));
CREATE INDEX IF NOT EXISTS ix_rr_projects_corpus ON rr_projects(status, corpus_excluded);
CREATE INDEX IF NOT EXISTS ix_rr_projects_product ON rr_projects(product_code);
CREATE INDEX IF NOT EXISTS ix_rr_projects_mcpvis ON rr_projects(mcp_visibility, status);

CREATE TABLE IF NOT EXISTS rr_requirements (                   -- §2.8b 요구 규격·치수 한계·필수 시나리오. 과제에 붙고 스냅샷에 복사되지 않는다
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL, owner_sub TEXT NOT NULL,
  kind TEXT NOT NULL CHECK(kind IN ('dim_limit','scenario','standard')),
  name TEXT NOT NULL,                           -- dim_limit: rr_dim_vocab.name · scenario: 시나리오 이름 · standard: 규격 번호
  op TEXT CHECK(op IN ('lte','gte','between')), -- dim_limit 전용, 그 밖에는 NULL
  value_json TEXT,                              -- dim_limit: 스칼라 또는 [lo,hi] · scenario: {taxonomy_key, required} · standard: {clause, title}
  unit TEXT,                                    -- dim_limit 전용. rr_dim_vocab.unit 과 다르면 등록 시 400 unit_mismatch
  source_ref TEXT,                              -- 요구의 출처 문자열(card:·paper:·URL·문서명). standard 는 필수
  status TEXT NOT NULL CHECK(status IN ('candidate','confirmed','waived')) DEFAULT 'candidate',
  waive_reason TEXT,                            -- status='waived' 이면 필수(422)
  inherited_from TEXT,                          -- 승계 원본 rr_requirements.id(§2.8b (2))
  decided_by TEXT, decided_at INTEGER, created_at INTEGER, updated_at INTEGER,
  UNIQUE(project_id, kind, name));
CREATE INDEX IF NOT EXISTS ix_rr_req_project ON rr_requirements(project_id, kind, status);
-- 불변식: kind='dim_limit' 이면 op·value_json·unit 이 전부 NOT NULL 이고 name 이 rr_dim_vocab 에 있다. 요구 편집은 ir_hash 를 바꾸지 않고 rr_states 재계산만 트리거한다(§2.8b (1)).

CREATE TABLE IF NOT EXISTS rr_project_members (                -- §5.2.1 멤버십. 과제 생성 시 owner 행 자동 삽입
  project_id TEXT NOT NULL, owner_sub TEXT NOT NULL,   -- 과제 owner 의 복제(§5.2.1 신원 앵커)
  email TEXT NOT NULL,
  role TEXT NOT NULL CHECK(role IN ('owner','editor','viewer')),
  added_by TEXT, added_at INTEGER, updated_at INTEGER,
  PRIMARY KEY(project_id, email));
CREATE INDEX IF NOT EXISTS ix_rr_members_email ON rr_project_members(email, role);
-- 불변식: 과제마다 role='owner' 행이 정확히 1건이고 그 email == rr_projects.owner_sub. 이양은 두 행 UPDATE + rr_projects.owner_sub + 하위 표 owner_sub 를 한 트랜잭션에서.

CREATE TABLE IF NOT EXISTS rr_sources (
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL, owner_sub TEXT NOT NULL,
  kind TEXT NOT NULL CHECK(kind IN ('mcad','dyna','dyna_result','ecad')),
  app_key TEXT, ref_json TEXT NOT NULL, ref_key TEXT NOT NULL,   -- ref_key = kind:app_key:정렬 ref 문자열
  bridge_declared INTEGER DEFAULT 0, probe_json TEXT, probe_at INTEGER,
  adapter_version TEXT, created_at INTEGER,
  UNIQUE(project_id, ref_key));
CREATE INDEX IF NOT EXISTS ix_rr_sources_refkey ON rr_sources(ref_key);   -- 타 과제 동일 원천 감지(§8.2.3 duplicate_of)

CREATE TABLE IF NOT EXISTS rr_snapshots (
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL, owner_sub TEXT NOT NULL,
  ir_version TEXT NOT NULL, ir_hash TEXT NOT NULL,
  ir_json TEXT NOT NULL,                        -- rr_ir 원본(유일)
  source_ids_json TEXT NOT NULL,                -- [{kind, app_key, ref, hash, tool_version, tol_params}]
  kinds_json TEXT NOT NULL,                     -- ['mcad','dyna',…]
  node_count INTEGER, edge_count INTEGER, missing_json TEXT, warnings_n INTEGER,
  degraded TEXT,                                -- degraded_json 의 첫 값(호환 컬럼) | null
  degraded_json TEXT,                           -- §2.2 degraded 코드 배열(소스별 목록의 합집합)
  primary_source TEXT CHECK(primary_source IN ('mcad','dyna','ecad')),   -- §2.2. ir_hash 입력은 아니고 조회·화면·게이트 분기 키다
  capture_partial INTEGER NOT NULL DEFAULT 0,   -- 1 = 선택 호출 실패 또는 예산 초과로 부분 캡처(§2.11.3)
  app_versions_json TEXT,                       -- {kind: {version, captured_via, extra}} — A 계획의 source_ids_json.tool_version 유령 필드를 대체한다
  adapter_versions_json TEXT, ra_entity_id INTEGER, adh_digest_record_id TEXT,
  job_id TEXT,                                  -- 이 스냅샷을 만든 rr_snapshot_jobs.id
  created_at INTEGER,
  UNIQUE(project_id, ir_hash));
CREATE INDEX IF NOT EXISTS ix_rr_snapshots_project ON rr_snapshots(project_id, created_at);

CREATE TABLE IF NOT EXISTS rr_snapshot_jobs (                 -- §2.11.3 스냅샷 동결 잡. 실패해도 행이 남아 무엇이 왜 실패했는지가 보인다
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL, owner_sub TEXT NOT NULL,
  label TEXT, kinds_json TEXT NOT NULL, params_json TEXT,     -- params: {report_ids, detect_result_file_id, allow_large}
  state TEXT NOT NULL CHECK(state IN ('queued','running','done','partial','failed')) DEFAULT 'queued',
  snapshot_id TEXT,                             -- done|partial 이면 채워진다
  error_json TEXT,                              -- {stage, kind, tool, call_id, message} — 실패·부분의 지점
  budget_s INTEGER, elapsed_ms INTEGER, calls_n INTEGER, calls_failed_n INTEGER,
  started_at INTEGER, finished_at INTEGER, created_at INTEGER);
CREATE INDEX IF NOT EXISTS ix_rr_snapshot_jobs_project ON rr_snapshot_jobs(project_id, created_at);
CREATE INDEX IF NOT EXISTS ix_rr_snapshot_jobs_state ON rr_snapshot_jobs(state, created_at);
-- 기동 시 state='running' 인 행은 'failed'(error_json.stage='restart')로 마감한다. 배치 패널 잡 표(rr_jobs)와 별개다 — 수명·상태 어휘·소유가 다르다.

CREATE TABLE IF NOT EXISTS rr_snapshot_calls (                -- 행 정의는 §2.11.4
  call_id TEXT PRIMARY KEY,                     -- '<job_id[:8]>-<seq:03d>' — 실패 잡에는 스냅샷이 없으므로 접두는 잡 id 다
  job_id TEXT NOT NULL, snapshot_id TEXT,       -- snapshot_id 는 NULL 허용(실패·부분 잡의 원문 보존, 30일 뒤 response_gz=NULL)
  owner_sub TEXT NOT NULL,
  seq INTEGER NOT NULL, source_kind TEXT NOT NULL, app_key TEXT,
  channel TEXT NOT NULL CHECK(channel IN ('mcp','rest')), tool TEXT NOT NULL,
  args_json TEXT, args_hash TEXT, ok INTEGER NOT NULL DEFAULT 1, http_status INTEGER,
  response_sha256 TEXT, response_gz BLOB, response_bytes INTEGER,
  contract_ok INTEGER,                          -- §2.13.1 response_contract 검사 결과(NULL = 계약 미정의)
  contract_missing_json TEXT,                   -- 빠진 JSON pointer 목록(위반 시)
  reused_from_call_id TEXT,                     -- §2.11.3 재요청 시 원문 재사용
  started_at INTEGER, duration_ms INTEGER, error TEXT);
CREATE INDEX IF NOT EXISTS ix_rr_calls_snapshot ON rr_snapshot_calls(snapshot_id, seq);
CREATE INDEX IF NOT EXISTS ix_rr_calls_job ON rr_snapshot_calls(job_id, seq);
CREATE INDEX IF NOT EXISTS ix_rr_calls_args ON rr_snapshot_calls(args_hash, ok);   -- 재사용 조회

CREATE TABLE IF NOT EXISTS rr_ir_nodes (
  snapshot_id TEXT NOT NULL, nid TEXT NOT NULL, owner_sub TEXT NOT NULL,
  kind TEXT, source_kind TEXT, name TEXT, name_norm TEXT,
  ckey TEXT, dn TEXT, geom_fp TEXT, asm_key TEXT, material_norm TEXT,
  size_sorted_json TEXT, volume REAL, attrs_json TEXT,
  PRIMARY KEY(snapshot_id, nid));
CREATE INDEX IF NOT EXISTS ix_rr_nodes_ckey ON rr_ir_nodes(ckey);
CREATE INDEX IF NOT EXISTS ix_rr_nodes_name ON rr_ir_nodes(name_norm);
CREATE INDEX IF NOT EXISTS ix_rr_nodes_fp ON rr_ir_nodes(geom_fp);

CREATE TABLE IF NOT EXISTS rr_ir_edges (
  snapshot_id TEXT NOT NULL, eid TEXT NOT NULL, owner_sub TEXT NOT NULL,
  kind TEXT NOT NULL, kind_family TEXT NOT NULL, a TEXT NOT NULL, b TEXT NOT NULL,
  ck_a TEXT, ck_b TEXT, subject_key TEXT, status TEXT, attrs_json TEXT,
  PRIMARY KEY(snapshot_id, eid));
CREATE INDEX IF NOT EXISTS ix_rr_edges_subject ON rr_ir_edges(subject_key);
CREATE INDEX IF NOT EXISTS ix_rr_edges_kind ON rr_ir_edges(snapshot_id, kind);

CREATE TABLE IF NOT EXISTS rr_part_keys (
  ckey TEXT PRIMARY KEY, owner_sub TEXT NOT NULL,
  visibility TEXT CHECK(visibility IN ('private','org')) DEFAULT 'private',
  status TEXT NOT NULL CHECK(status IN ('candidate','confirmed','merged')) DEFAULT 'candidate',
  merged_into TEXT, display_name TEXT,          -- §2.7.3 display_name(RA part 축 value)
  name_norm_canon TEXT NOT NULL, geom_bucket TEXT NOT NULL, material_norm TEXT NOT NULL,
  vocab_version TEXT,                           -- 이 행의 name_norm_canon 을 만든 rr_dim_vocab 버전(§2.7.1 재계산 — 메이저 승급 후 옛 행 식별)
  aliases_json TEXT,                            -- [{project_id, domain, label, local_key, name_norm}] 동의어 원장(§2.7.3)
  ra_part_entity_id INTEGER, first_project_id TEXT, first_snapshot_id TEXT, first_nid TEXT,
  n_projects INTEGER DEFAULT 1, n_snapshots INTEGER DEFAULT 1,
  merge_evidence_json TEXT,                     -- §2.7.3 자동 승계 근거 {method, score, base_snapshot_id, target_snapshot_id, base_nid, target_nid}(사람 병합은 NULL)
  created_by TEXT, decided_by TEXT, decided_at INTEGER, created_at INTEGER, updated_at INTEGER);   -- decided_by = 'code:pair_correspondence' | 사용자 sub
CREATE INDEX IF NOT EXISTS ix_rr_part_keys_canon ON rr_part_keys(name_norm_canon);
CREATE INDEX IF NOT EXISTS ix_rr_part_keys_merged ON rr_part_keys(merged_into);

CREATE TABLE IF NOT EXISTS rr_sameas (
  id TEXT PRIMARY KEY, owner_sub TEXT NOT NULL,
  scope TEXT NOT NULL CHECK(scope IN ('intra','pair','global')),   -- intra: 한 스냅샷 안 mcad↔dyna↔ecad, pair: base↔target, global: ckey 쌍(§2.6.2 1단계)
  pair_key TEXT NOT NULL,                       -- intra: project_id, pair: 정렬한 두 project_id '|' 결합, global: '-'
  a_stable TEXT NOT NULL, b_stable TEXT NOT NULL,   -- stable key(§2.6.2 1단계): mcad canon_key · dyna name_norm_canon+'@'+elem_class · ecad refdes · global 은 ckey
  method TEXT, score REAL, status TEXT NOT NULL CHECK(status IN ('confirmed','rejected')),
  prev_status TEXT, prev_decided_by TEXT, prev_decided_at INTEGER,   -- §5.9.5 rekey — 뒤집힌 확정의 직전 값(번복 이력, 행 하나로 유지)
  evidence TEXT, decided_by TEXT, decided_at INTEGER, snapshot_id_at_decision TEXT,
  UNIQUE(scope, pair_key, a_stable, b_stable));

CREATE TABLE IF NOT EXISTS rr_iface_ledger (
  project_id TEXT NOT NULL, pair_key TEXT NOT NULL, owner_sub TEXT NOT NULL,
  kind_override TEXT, status TEXT NOT NULL CHECK(status IN ('confirmed','rejected','manual')),
  note TEXT, geom_fp_a TEXT, geom_fp_b TEXT, needs_review INTEGER DEFAULT 0,
  decided_by TEXT, decided_at INTEGER, snapshot_id_at_decision TEXT,
  PRIMARY KEY(project_id, pair_key));

CREATE TABLE IF NOT EXISTS rr_dim_vocab (                     -- 행 정의는 §2.8
  name TEXT PRIMARY KEY,
  kind TEXT NOT NULL CHECK(kind IN ('overall','thickness','gap','offset','count','param','result','other')),
  unit TEXT, description TEXT, synonyms_json TEXT, stop_tokens_json TEXT,
  tol_abs REAL, tol_rel REAL,                   -- §3.3.4 dims_named 변경 임계(없으면 0.02 mm · 1%)
  vocab_version TEXT, created_by TEXT, created_at INTEGER);

CREATE TABLE IF NOT EXISTS rr_dim_defs (                      -- 행 정의는 §2.8
  project_id TEXT NOT NULL, name TEXT NOT NULL, owner_sub TEXT NOT NULL,
  extractor TEXT NOT NULL,                      -- §2.8 제한 문법 문자열(node[ck=…].attr · edge[name=A|B].attr · dim(a)-dim(b) · const:…)
  created_by TEXT, created_at INTEGER, updated_at INTEGER,
  PRIMARY KEY(project_id, name));

CREATE TABLE IF NOT EXISTS rr_states (
  snapshot_id TEXT PRIMARY KEY, owner_sub TEXT NOT NULL,
  state_json TEXT NOT NULL, feature_json TEXT NOT NULL,
  rule_hits_json TEXT, character_seed_json TEXT, gates_json TEXT NOT NULL,
  summary_text TEXT, summary_status TEXT CHECK(summary_status IN ('ok','lint_failed')),   -- §3.2.7
  blocked INTEGER DEFAULT 0, state_version TEXT, rule_version TEXT, taxonomy_version TEXT, computed_at INTEGER);

CREATE TABLE IF NOT EXISTS rr_diffs (
  id TEXT PRIMARY KEY, owner_sub TEXT NOT NULL,
  base_snapshot_id TEXT NOT NULL, target_snapshot_id TEXT NOT NULL,
  base_project_id TEXT NOT NULL, target_project_id TEXT NOT NULL,
  pair_kind TEXT CHECK(pair_kind IN ('same_project_revision','cross_project')),
  diff_version TEXT NOT NULL, diff_json TEXT NOT NULL, summary_text TEXT NOT NULL,
  summary_status TEXT CHECK(summary_status IN ('ok','lint_failed')),
  stats_json TEXT, comparability_json TEXT, gates_json TEXT, diff_hash TEXT,
  ra_entity_id INTEGER, created_at INTEGER,
  UNIQUE(base_snapshot_id, target_snapshot_id));

CREATE TABLE IF NOT EXISTS rr_diff_events (
  diff_id TEXT NOT NULL, cid TEXT NOT NULL, owner_sub TEXT NOT NULL,
  layer TEXT NOT NULL CHECK(layer IN ('structural','parametric','semantic')),
  code TEXT NOT NULL, change_kind TEXT, subject_key TEXT, ckeys_json TEXT,
  magnitude REAL, unit TEXT, rel REAL,
  confidence TEXT CHECK(confidence IN ('high','medium','low')),
  design_relevant INTEGER DEFAULT 1, unconfirmed INTEGER DEFAULT 0, excluded_reason TEXT,
  text TEXT,                                    -- 정규 표기(§3.4.1)
  PRIMARY KEY(diff_id, cid));
CREATE INDEX IF NOT EXISTS ix_rr_events_code ON rr_diff_events(code);
CREATE INDEX IF NOT EXISTS ix_rr_events_kind ON rr_diff_events(change_kind);
CREATE INDEX IF NOT EXISTS ix_rr_events_subject ON rr_diff_events(subject_key);

CREATE TABLE IF NOT EXISTS rr_gate_acks (                     -- §3.2.2 게이트 레코드의 ack_by·ack_at·ack_reason 이 사는 곳
  snapshot_id TEXT NOT NULL, gate TEXT NOT NULL CHECK(gate IN ('G1','G2','G3','G4','G5','G6','G7')),
  owner_sub TEXT NOT NULL, diff_id TEXT,        -- G7·pair 게이트는 diff 스코프
  ack_by TEXT NOT NULL, ack_at INTEGER NOT NULL, ack_reason TEXT NOT NULL,   -- reason ≤300자, 빈 문자열 금지(422)
  gates_hash TEXT NOT NULL,                     -- ack 시점 gates_json 의 sha1[:12] — 게이트 재계산으로 상태가 바뀌면 ack 는 stale
  revoked_by TEXT, revoked_at INTEGER,          -- DELETE 는 행 삭제가 아니라 revoke 표기(§5.2.1 삭제 없음)
  PRIMARY KEY(snapshot_id, gate));
-- ack 가 붙어도 gates_json 의 pass 는 false 로 남는다(§3.2.2). G6 은 blocking 이라 ack 로 넘길 수 없다(422 gate_blocking).

CREATE TABLE IF NOT EXISTS rr_targets (
  target_key TEXT PRIMARY KEY, owner_sub TEXT NOT NULL,
  kind TEXT NOT NULL CHECK(kind IN ('snap','diff')), ref_id TEXT NOT NULL,
  project_id TEXT NOT NULL, base_project_id TEXT, ir_hash TEXT NOT NULL,
  principal_json TEXT, consent_at INTEGER, roster_frozen_at INTEGER,
  level TEXT NOT NULL DEFAULT 'C0',             -- C0 | C1 | C2 | C2(closed) | C3
  close_level TEXT,                             -- Settings risk_default_close_level 스냅샷(C2|C3)
  verdict_candidate TEXT, verdict_final TEXT CHECK(verdict_final IN ('go','conditional','no-go','undetermined')),
  verdict_note TEXT, verdict_by TEXT, verdict_at INTEGER,
  external_sync_json TEXT NOT NULL,             -- §5.5.3
  superseded_by TEXT, report_ids_json TEXT, planner_version TEXT,
  created_at INTEGER, updated_at INTEGER);
CREATE INDEX IF NOT EXISTS ix_rr_targets_project ON rr_targets(project_id, created_at);

CREATE TABLE IF NOT EXISTS rr_roster (                        -- §6.3
  target_key TEXT NOT NULL, agent_key TEXT NOT NULL, owner_sub TEXT NOT NULL, domain TEXT NOT NULL,
  relevance REAL, rank_in_domain INTEGER, ecad_dependent INTEGER DEFAULT 0, frozen_at INTEGER,
  role_sha TEXT, persona_rev TEXT,              -- 로스터 동결 시점의 좌석 원본 role 문자열 sha256[:12] 와 그 값의 사람이 읽는 판번호(§7.7 스탬프) — 페르소나가 바뀐 뒤 회수한 발췌를 E7 에서 [이전 정의] 로 표기하는 근거
  PRIMARY KEY(target_key, agent_key));

CREATE TABLE IF NOT EXISTS rr_coverage (                      -- §6.8.1
  target_key TEXT NOT NULL, agent_key TEXT NOT NULL, owner_sub TEXT NOT NULL,
  domain TEXT NOT NULL, tier TEXT, origin TEXT CHECK(origin IN ('primary','counter')),
  status TEXT NOT NULL CHECK(status IN ('pending','assigned','running','done','done_weak','abstain',
                                        'failed','skipped','deferred','carried')) DEFAULT 'pending',
  cycle INTEGER DEFAULT 1, retry INTEGER DEFAULT 0,
  panel_id TEXT, opinion_id TEXT, adh_record_id TEXT, ra_assessment_id INTEGER,
  carried_from_opinion_id TEXT, reason TEXT,
  status_source TEXT NOT NULL CHECK(status_source IN ('code','human')) DEFAULT 'code',
  decided_by TEXT, decided_at INTEGER,          -- 사람 전이(skipped·carried→pending)의 주체·시각, PUT /targets/{key}/coverage/{agent_key}
  model TEXT,                                   -- 종결 시 그 패널의 rr_panels.model_json.model 사본(진행판·통합 보고서 모델 혼합 표, D6)
  started_at INTEGER, finished_at INTEGER, updated_at INTEGER,
  PRIMARY KEY(target_key, agent_key));
-- 부분 유니크 인덱스 rr_cov_active(§6.8.1): 활성(assigned|running) 행만 담는 작은 인덱스로 편성기의 rowcount 선점 UPDATE 와 불변식 검사를 빠르게 한다.
-- 다른 타깃 동시 착석은 막지 않는다(Tier A 는 두 타깃이 같은 대표 15명을 원한다). '전문가 전역 동시 1석' 정책으로 바꾸려면 열을 (agent_key) 로 줄이는 마이그레이션 1건이다.
CREATE UNIQUE INDEX IF NOT EXISTS rr_cov_active ON rr_coverage(agent_key, target_key) WHERE status IN ('assigned','running');
CREATE INDEX IF NOT EXISTS ix_rr_cov_status ON rr_coverage(target_key, status);

CREATE TABLE IF NOT EXISTS rr_panels (
  id TEXT PRIMARY KEY, target_key TEXT NOT NULL, owner_sub TEXT NOT NULL,
  panel_no INTEGER NOT NULL, tier TEXT, seats_json TEXT NOT NULL,
  chair_template TEXT NOT NULL DEFAULT 'risk-review', modifiers_json TEXT, rounds INTEGER,
  engine TEXT CHECK(engine IN ('web','mcp')), tool_mode TEXT CHECK(tool_mode IN ('tools','evidence_only')),
  conv_id TEXT, report_id INTEGER,
  status TEXT NOT NULL CHECK(status IN ('planned','running','done','error')) DEFAULT 'planned',
  decision_text TEXT, risk_spec_json TEXT, risk_spec_parsed INTEGER DEFAULT 0,
  quality_json TEXT, llm_calls INTEGER, llm_calls_planned INTEGER,
  budget_json TEXT,                             -- §6.10.2 {S, R, T, est_low, est_high, cap, rounds_planned, tools_planned}
  evidence_refs_json TEXT,                      -- 이 패널 브리프에 실린 E0~E9 항목의 ref 목록(인용 추적)
  evidence_excluded_json TEXT,                  -- 사람이 RecallPreview·POST jobs 의 exclude_evidence 로 뺀 항목 키·ref 목록(§5.6, rr_audit 동반)
  brief_gz BLOB, brief_hash TEXT,               -- 이 패널이 실제로 받은 evidence 배열의 직렬화 전문 gzip 과 그 sha256[:12] — 브리프는 시변 조립물이라 원문이 없으면 quote·인용 재현이 불가하다(§5.6.1)
  brief_item_hashes_json TEXT,                  -- {E0:'<sha256[:12]>', E0c:…, …, M:…} 항목별 해시. 같은 타깃의 이전 패널과 비교해 quality_json.brief_drift[] 를 만든다
  brief_token_hash TEXT, brief_token_exp INTEGER,      -- §8.2.5 MCP `risk_get_brief` 대조용. UI·REST 가 발급한 1회용 토큰의 sha256[:32] 와 만료(발급 시각 + risk_brief_token_ttl_s). 토큰 원문은 저장하지 않는다
  model_json TEXT,                              -- D6 모델 출처 {runtime, provider, model, endpoint_host, captured ∈ health_snapshot|caller_reported|unavailable, engine_rev, chair_rev, seat_contract_rev, sampling{temperature, top_p, max_tokens, seed?}, model_end?}(§6.7.2 1·7단계, §6.11)
  retry INTEGER DEFAULT 0, error TEXT, started_at INTEGER, ended_at INTEGER, created_at INTEGER,
  UNIQUE(target_key, panel_no));

CREATE TABLE IF NOT EXISTS rr_jobs (
  id TEXT PRIMARY KEY, target_key TEXT NOT NULL, owner_sub TEXT NOT NULL, tier TEXT,
  state TEXT NOT NULL CHECK(state IN ('queued','running','paused','cancelling','cancelled','completed','failed')),
  pause_reason TEXT CHECK(pause_reason IN ('diminishing','daily_cap','user')),
  concurrency INTEGER DEFAULT 1, params_json TEXT, progress_json TEXT,   -- params_json 에 user_memo·modifiers·exclude_evidence[] 보존
  state_by TEXT, state_at INTEGER,              -- pause/resume/cancel 주체·시각(자동 정지는 'code:diminishing'·'code:daily_cap')
  credential_email TEXT,                        -- 러너가 실제로 쓴 PAT 의 email(§0.1.6 (b) 후보 순서), 서비스 자격이면 'service'
  panels_done INTEGER DEFAULT 0, panels_total INTEGER, error TEXT, created_at INTEGER, updated_at INTEGER);
CREATE INDEX IF NOT EXISTS ix_rr_jobs_state ON rr_jobs(state, created_at);

CREATE TABLE IF NOT EXISTS rr_panel_calls (                   -- 패널 중 좌석 도구 호출 원문. 포털 conv_store 는 사본이고 이 표가 정본이다(§6.7.2 7단계)
  call_id TEXT PRIMARY KEY,                     -- '<panel_id[:8]>-<seq:03d>'
  panel_id TEXT NOT NULL, target_key TEXT NOT NULL, owner_sub TEXT NOT NULL,
  seq INTEGER NOT NULL, agent_key TEXT, round INTEGER,        -- agent_key 가 NULL 이면 좌석 귀속 불가(지정 도구·공용 주입)
  source TEXT NOT NULL CHECK(source IN ('sse','events','tool_inject')),   -- sse: 러너 직접 캡처 · events: POST /panels/{id}/complete 의 events[] · tool_inject: delib_opts.tools 결과
  tool TEXT NOT NULL, app_key TEXT, args_text TEXT,
  ok INTEGER NOT NULL DEFAULT 1,
  result_gz BLOB, result_bytes INTEGER, sha256 TEXT,          -- 원문 전문(절단 없음). sha256 은 gzip 해제본의 해시
  conv_id TEXT, activity_idx INTEGER,           -- 포털 대화 좌표(있을 때만) — 레거시 'tool:conv:<conv_id>#<idx>' 참조 해석 키
  started_at INTEGER, duration_ms INTEGER, error TEXT);
CREATE INDEX IF NOT EXISTS ix_rr_panel_calls_panel ON rr_panel_calls(panel_id, seq);
CREATE INDEX IF NOT EXISTS ix_rr_panel_calls_agent ON rr_panel_calls(agent_key, started_at);
CREATE INDEX IF NOT EXISTS ix_rr_panel_calls_conv ON rr_panel_calls(conv_id, activity_idx);

CREATE TABLE IF NOT EXISTS rr_seat_opinions (
  opinion_id TEXT PRIMARY KEY, target_key TEXT NOT NULL, panel_id TEXT NOT NULL, owner_sub TEXT NOT NULL,
  agent_key TEXT NOT NULL, domain TEXT NOT NULL, persona_rev TEXT,   -- 이 의견을 낸 시점의 좌석 페르소나 판번호(rr_roster.persona_rev 사본) — E7 [이전 정의] 접두 판정
  origin TEXT CHECK(origin IN ('primary','counter','adversary','new')),   -- adversary·new 는 원장 미집계 의견(§6.7 8단계·§6.8.3 4)
  cycle INTEGER DEFAULT 1,
  opinion_json TEXT NOT NULL,                   -- seat_opinion 전체(§0.1.3)
  final_stance TEXT CHECK(final_stance IN ('agree','conditional','oppose','abstain')),
  tool_calls_n INTEGER, tool_calls_ok INTEGER, knowledge_hits_n INTEGER,
  cited_refs_json TEXT, quality_json TEXT, raised_finding_ids_json TEXT,
  excerpt_for_rag TEXT,                         -- ≤1500자, E7·AIDataHub 섹션 2 의 원천
  adh_record_id TEXT, ra_assessment_id INTEGER, created_at INTEGER,
  UNIQUE(target_key, agent_key, cycle));
CREATE INDEX IF NOT EXISTS ix_rr_opinions_agent ON rr_seat_opinions(agent_key, created_at);

CREATE TABLE IF NOT EXISTS rr_findings (
  finding_id TEXT PRIMARY KEY, claim_uid TEXT NOT NULL UNIQUE,   -- '<panel_id>#F1' | '#G1' | 사람은 '<target_key>#H<n>'(§0.2.2)
  origin TEXT NOT NULL CHECK(origin IN ('llm','human')) DEFAULT 'llm',
  author_sub TEXT,                              -- origin='human' 일 때 필수(작성자 이메일), llm 이면 NULL
  target_key TEXT NOT NULL, panel_id TEXT, opinion_id TEXT,      -- panel_id 는 origin='human' 에서만 NULL 허용(CHECK 로 강제하지 않고 파서·API 가 보장)
  project_id TEXT NOT NULL, snapshot_id TEXT, diff_id TEXT, owner_sub TEXT NOT NULL,
  visibility TEXT CHECK(visibility IN ('private','org')) DEFAULT 'private',
  direction TEXT NOT NULL CHECK(direction IN ('risk','improvement','neutral')),
  domain TEXT, mechanism TEXT, mechanism_detail TEXT, mechanism_free TEXT,
  change_kind TEXT, subject_key TEXT, ckeys_json TEXT, trigger_condition TEXT,
  severity TEXT CHECK(severity IN ('경미','중대','치명')), sev3 INTEGER,
  judgement TEXT CHECK(judgement IN ('OK','WARNING','FAIL','undetermined')),
  detectability TEXT, detect_tool TEXT,
  evidence_grade TEXT, precedent TEXT CHECK(precedent IN ('in_range','out_of_range','none')),
  requirement_ref TEXT,                         -- §2.8b (5) 이 finding 이 가리키는 요구 `req:<name>`(없으면 NULL). cites 와 별개로 '무슨 요구를 어겼나' 를 조인한다
  dangling INTEGER DEFAULT 0, cluster_key TEXT NOT NULL,      -- 삽입 시 동결. 조인은 resolve_cluster_key() 를 거친다(§4.3.2)
  finding_json TEXT NOT NULL,                   -- finding 전체 + feature_snapshot + precedent_refs + ref_aliases
  recall_eligible INTEGER NOT NULL DEFAULT 1,   -- 0 = suspect_text 적중(§3.4.1) 또는 actor_verified=false 패널 산출 → E5·E7 후보 제외(그 타깃 등록부·보고서에는 남는다)
  status TEXT NOT NULL CHECK(status IN ('open','rejected_in_panel','verified','dismissed','mitigated','superseded')) DEFAULT 'open',
  status_source TEXT NOT NULL CHECK(status_source IN ('code','label_auto','label_manual','human')) DEFAULT 'code',
  status_decided_by TEXT, status_decided_at INTEGER,
  status_reason TEXT, superseded_by TEXT,
  ra_entity_id INTEGER, adh_record_id TEXT,
  taxonomy_version TEXT, rule_version TEXT, ir_version TEXT, diff_version TEXT,
  created_at INTEGER, updated_at INTEGER);
CREATE INDEX IF NOT EXISTS ix_rr_findings_cluster ON rr_findings(cluster_key);
CREATE INDEX IF NOT EXISTS ix_rr_findings_req ON rr_findings(requirement_ref);
CREATE INDEX IF NOT EXISTS ix_rr_findings_origin ON rr_findings(origin, target_key);
CREATE INDEX IF NOT EXISTS ix_rr_findings_recall ON rr_findings(recall_eligible, status);
CREATE INDEX IF NOT EXISTS ix_rr_findings_subject ON rr_findings(subject_key);
CREATE INDEX IF NOT EXISTS ix_rr_findings_mech ON rr_findings(mechanism, mechanism_detail, change_kind);
CREATE INDEX IF NOT EXISTS ix_rr_findings_project ON rr_findings(project_id, status);

CREATE TABLE IF NOT EXISTS rr_registry (
  target_key TEXT NOT NULL, cluster_key TEXT NOT NULL, owner_sub TEXT NOT NULL,
  visibility TEXT CHECK(visibility IN ('private','org')) DEFAULT 'private',
  merged_json TEXT NOT NULL,                    -- 대표 finding + member finding_ids + resolving_checks 집합 + precedent_clusters + rejected_refs
  support INTEGER DEFAULT 1, contested INTEGER DEFAULT 0,
  rejected INTEGER DEFAULT 0,                   -- §4.7.1 status='rejected_in_panel' 원자 수(support 와 분리). support=0 AND rejected≥1 이면 행 status 도 rejected_in_panel
  family_key TEXT,                              -- §4.3.2 sha1(mechanism|mechanism_detail|change_kind)[:12] — subject 를 뺀 키. 근접 중복 클러스터 스캔의 묶음
  direction TEXT, mechanism TEXT, mechanism_detail TEXT, change_kind TEXT, subject_key TEXT,
  severity TEXT, sev3 INTEGER, judgement TEXT, evidence_grade TEXT, precedent TEXT,
  weak_subject INTEGER DEFAULT 0, priority REAL,   -- §4.3.2 · §4.7.1
  status TEXT NOT NULL CHECK(status IN ('open','rejected_in_panel','verified','dismissed','mitigated','superseded')) DEFAULT 'open',
  status_source TEXT NOT NULL CHECK(status_source IN ('code','label_auto','label_manual','human')) DEFAULT 'code',
  status_decided_by TEXT, status_decided_at INTEGER, status_note TEXT,
  status_basis_json TEXT,                       -- {evidence_ref?, label_id?, finding_ids[], support_at_decision, sev3_at_decision, grade_at_decision} — 재제기 비교의 기준선(§4.7.1)
  needs_review_json TEXT,                       -- {escalated: bool, since: <epoch>, by_target: '<T′>', delta: {sev3, grade, support}} — 사람이 닫은 행이 더 강한 근거로 재제기됐을 때
  verified_by_json TEXT, stale_json TEXT,       -- §4.8 {<T′>: {stale: bool, unraised: bool}}
  human_n INTEGER DEFAULT 0,                    -- §4.7.1 사람 finding 수(support 와 분리, 좌석으로 세지 않는다)
  superseded_by TEXT, ra_entity_id INTEGER, updated_at INTEGER,
  PRIMARY KEY(target_key, cluster_key));
CREATE INDEX IF NOT EXISTS ix_rr_registry_cluster ON rr_registry(cluster_key);
CREATE INDEX IF NOT EXISTS ix_rr_registry_subject ON rr_registry(subject_key, status);
CREATE INDEX IF NOT EXISTS ix_rr_registry_family ON rr_registry(family_key, status);

CREATE TABLE IF NOT EXISTS rr_cluster_alias (                 -- §4.3.2 cluster_key 생명주기. 옛 키 → 새 키의 유일한 자리
  old_cluster_key TEXT PRIMARY KEY, new_cluster_key TEXT NOT NULL, owner_sub TEXT NOT NULL,
  reason TEXT NOT NULL CHECK(reason IN ('taxonomy_major','ckey_merge','iface_alias','dim_rename','cluster_merge')),
  evidence_json TEXT,                           -- {from, to, subject_before, subject_after, score?, vocab_version?, taxonomy_version?}
  decided_by TEXT NOT NULL, decided_at INTEGER NOT NULL,
  revoked_by TEXT, revoked_at INTEGER);         -- revoke 는 행 삭제가 아니라 표기(§5.2.1) — resolve_cluster_key() 가 건너뛴다
CREATE INDEX IF NOT EXISTS ix_rr_cluster_alias_new ON rr_cluster_alias(new_cluster_key);
-- 불변식: resolve_cluster_key() 체인 ≤5홉이고 순환 0(야간 잡이 rr_metrics(dimension=global, metric=nightly_cluster_alias_cycle) 로 건수를 남긴다).

CREATE TABLE IF NOT EXISTS rr_registry_status_log (           -- append-only. 등록부·finding status 의 전이 이력(§4.7.1, §7.6)
  id TEXT PRIMARY KEY, target_key TEXT NOT NULL, cluster_key TEXT NOT NULL, owner_sub TEXT NOT NULL,
  seq INTEGER NOT NULL,                         -- (target_key, cluster_key) 안에서 1부터 증가, 응답 status_log_seq
  from_status TEXT, to_status TEXT NOT NULL,
  source TEXT NOT NULL CHECK(source IN ('code','label_auto','label_manual','human')),
  decided_by TEXT, decided_at INTEGER NOT NULL,
  evidence_ref TEXT, note TEXT, label_id TEXT,
  basis_json TEXT,                              -- 그 시점 support·sev3·evidence_grade·member finding_ids
  applied INTEGER NOT NULL DEFAULT 1,           -- 0 = 우선순위 규칙에 막혀 status 를 바꾸지 못한 시도(§7.6 conflict_with_human) — 시도도 남긴다
  UNIQUE(target_key, cluster_key, seq));
CREATE INDEX IF NOT EXISTS ix_rr_status_log_cluster ON rr_registry_status_log(cluster_key, decided_at);

CREATE TABLE IF NOT EXISTS rr_claim_refs (
  claim_uid TEXT NOT NULL, ref_type TEXT NOT NULL, ref TEXT NOT NULL, quote TEXT,
  owner_sub TEXT NOT NULL, target_key TEXT NOT NULL, dangling INTEGER DEFAULT 0,
  PRIMARY KEY(claim_uid, ref_type, ref));
CREATE INDEX IF NOT EXISTS ix_rr_claim_refs_ref ON rr_claim_refs(ref);

CREATE TABLE IF NOT EXISTS rr_character (
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL, owner_sub TEXT NOT NULL,
  facet TEXT NOT NULL CHECK(facet IN ('intent','constraint','anomaly','lineage','vulnerability','strength','tradeoff','unknown')),
  tag TEXT, tags_json TEXT,                     -- tag = 대표 태그(통제 어휘 첫 항목, 없으면 NULL — 병합 키), tags_json = 전체 태그 배열(§4.6.4 2)
  statement TEXT NOT NULL, polarity TEXT, cites_json TEXT, by_json TEXT,   -- by_json = 좌석 키 배열(§4.6.1 by)
  variants_json TEXT, dissent_json TEXT,        -- §4.6.4 2 후속 문장·상반 polarity 축어 보존
  first_target_key TEXT, support_panels INTEGER DEFAULT 1, support_targets INTEGER DEFAULT 1, confidence REAL,
  recall_eligible INTEGER NOT NULL DEFAULT 1,   -- 0 = suspect_text 적중 또는 actor_verified=false 패널 산출 → E6 후보 제외(§3.4.1)
  needs_review INTEGER DEFAULT 0,               -- §4.8 5
  status TEXT NOT NULL CHECK(status IN ('seed','panel','confirmed','superseded')),
  superseded_by TEXT, decided_by TEXT, decided_at INTEGER, created_at INTEGER, updated_at INTEGER);
CREATE INDEX IF NOT EXISTS ix_rr_character_project ON rr_character(project_id, facet, status);
CREATE INDEX IF NOT EXISTS ix_rr_character_tag ON rr_character(tag);

CREATE TABLE IF NOT EXISTS rr_iface_alias (
  alias_key TEXT PRIMARY KEY,                   -- '<ckey_a>|<ckey_b>' 정렬
  canonical_a TEXT NOT NULL, canonical_b TEXT NOT NULL, owner_sub TEXT NOT NULL,
  visibility TEXT CHECK(visibility IN ('private','org')) DEFAULT 'private',
  aliases_json TEXT NOT NULL,                   -- [{name_a, name_b, asm_key_a, asm_key_b, project_id, snapshot_id}]
  source TEXT NOT NULL CHECK(source IN ('auto','human')), score REAL,
  status TEXT NOT NULL CHECK(status IN ('active','revoked')) DEFAULT 'active',   -- §5.9.5 rekey — 사람이 별칭을 되돌리면 revoked 로 표기(행 삭제 없음)하고 영향 finding 의 subject_key·cluster_key 를 재계산한다
  revoked_by TEXT, revoked_at INTEGER,
  ra_alias_ids_json TEXT, n_targets INTEGER DEFAULT 0, created_at INTEGER, updated_at INTEGER);
CREATE INDEX IF NOT EXISTS ix_rr_alias_a ON rr_iface_alias(canonical_a);
CREATE INDEX IF NOT EXISTS ix_rr_alias_b ON rr_iface_alias(canonical_b);

CREATE TABLE IF NOT EXISTS rr_delta_priors (
  change_kind TEXT NOT NULL, mechanism TEXT NOT NULL, mechanism_detail TEXT NOT NULL,
  n_raised INTEGER DEFAULT 0, n_targets INTEGER DEFAULT 0, n_verified INTEGER DEFAULT 0, n_dismissed INTEGER DEFAULT 0,
  n_improvement INTEGER DEFAULT 0, sev_hist_json TEXT, top_resolving_checks_json TEXT,
  visibility TEXT CHECK(visibility IN ('private','org')) DEFAULT 'private', stats_version TEXT, updated_at INTEGER,
  PRIMARY KEY(change_kind, mechanism, mechanism_detail));
-- rr_delta_priors 의 n_raised·n_targets·n_improvement·sev_hist_json·top_resolving_checks_json 은 아래 기여 표의 합으로만 쓴다(§4.7.1, 증분 += 없음).

CREATE TABLE IF NOT EXISTS rr_delta_contrib (                 -- §4.7.1 타깃별 기여(등록부 병합마다 UPSERT, 멱등)
  change_kind TEXT NOT NULL, mechanism TEXT NOT NULL, mechanism_detail TEXT NOT NULL, target_key TEXT NOT NULL,
  owner_sub TEXT NOT NULL,
  n_raised INTEGER DEFAULT 0, n_improvement INTEGER DEFAULT 0,
  n_raised_human INTEGER DEFAULT 0,             -- §4.7.1 사람 finding 기여(좌석 n_raised 와 분리, priors 합산은 §0.5.3 risk_prior_include_human)
  sev_hist_json TEXT, resolving_checks_json TEXT, updated_at INTEGER,
  PRIMARY KEY(change_kind, mechanism, mechanism_detail, target_key));
CREATE INDEX IF NOT EXISTS ix_rr_delta_contrib_target ON rr_delta_contrib(target_key);

CREATE TABLE IF NOT EXISTS rr_labels (
  id TEXT PRIMARY KEY, finding_id TEXT NOT NULL, pattern_id TEXT, project_id TEXT, owner_sub TEXT NOT NULL,
  source TEXT NOT NULL CHECK(source IN ('incident','test_run','voc','sim','expert_review','manual')),
  outcome TEXT NOT NULL CHECK(outcome IN ('confirmed','refuted','inconclusive')),
  severity_observed TEXT, matched_by TEXT NOT NULL CHECK(matched_by IN ('auto','manual')),
  match_score REAL, evidence_ref TEXT NOT NULL, evidence_note TEXT, occurred_at INTEGER,
  labeled_by TEXT, labeled_at INTEGER,
  UNIQUE(finding_id, source, evidence_ref));
CREATE INDEX IF NOT EXISTS ix_rr_labels_finding ON rr_labels(finding_id);
CREATE INDEX IF NOT EXISTS ix_rr_labels_pattern ON rr_labels(pattern_id);

CREATE TABLE IF NOT EXISTS rr_patterns (
  id TEXT PRIMARY KEY, owner_sub TEXT NOT NULL,
  visibility TEXT CHECK(visibility IN ('private','org')) DEFAULT 'private',
  cluster_key_norm TEXT NOT NULL,               -- subject 를 별칭 수준으로 정규화한 cluster_key
  mechanism TEXT, mechanism_detail TEXT, change_kind TEXT, subject_class TEXT,
  status TEXT NOT NULL CHECK(status IN ('candidate','known','rule','predictor','deprecated','suspended')),
  n_findings INTEGER, n_targets INTEGER, n_projects INTEGER, n_experts INTEGER,
  n_confirmed INTEGER DEFAULT 0, n_refuted INTEGER DEFAULT 0, precision REAL,
  merged_into TEXT,                             -- §4.3.2 4 — cluster_key_norm 이 별칭으로 합쳐졌을 때 대표 패턴 id(행 삭제 없음, 체인 ≤5)
  feature_ranges_json TEXT, card_record_id TEXT, design_trait_tag TEXT,
  curated_by TEXT, promoted_at INTEGER, suspended_reason TEXT, created_at INTEGER, updated_at INTEGER,
  UNIQUE(cluster_key_norm));
CREATE INDEX IF NOT EXISTS ix_rr_patterns_status ON rr_patterns(status);

CREATE TABLE IF NOT EXISTS rr_rules (
  id TEXT PRIMARY KEY, pattern_id TEXT, rule_version TEXT NOT NULL,
  mechanism TEXT, mechanism_detail TEXT, change_kind TEXT,
  condition_json TEXT NOT NULL, severity TEXT NOT NULL CHECK(severity IN ('경미','중대','치명')),
  why_it_matters TEXT NOT NULL, fix_hint TEXT, backtest_json TEXT,
  source TEXT NOT NULL CHECK(source IN ('seed','pattern')),
  status TEXT NOT NULL CHECK(status IN ('draft','active','retired')) DEFAULT 'draft',
  activated_by TEXT, activated_at INTEGER, created_at INTEGER);
CREATE INDEX IF NOT EXISTS ix_rr_rules_status ON rr_rules(status);

CREATE TABLE IF NOT EXISTS rr_metrics (
  period TEXT NOT NULL, dimension TEXT NOT NULL CHECK(dimension IN ('expert','domain','mechanism','pattern','project','global')),
  key TEXT NOT NULL, metric TEXT NOT NULL, value REAL, n INTEGER, computed_at INTEGER,
  visibility TEXT CHECK(visibility IN ('private','org')) DEFAULT 'private',
  PRIMARY KEY(period, dimension, key, metric));

CREATE TABLE IF NOT EXISTS rr_curation_queue (
  id TEXT PRIMARY KEY, owner_sub TEXT NOT NULL,
  kind TEXT NOT NULL CHECK(kind IN ('unclassified_code','pattern_candidate','label_match','x_tag_promote','suspect_text','cluster_merge')),
  payload_json TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('open','done','rejected')) DEFAULT 'open',
  decision_json TEXT, decided_by TEXT, decided_at INTEGER, created_at INTEGER);
CREATE INDEX IF NOT EXISTS ix_rr_queue ON rr_curation_queue(kind, status, created_at);

CREATE TABLE IF NOT EXISTS rr_audit (                         -- append-only. 사람 행위 한정(자동 전이는 각 표의 *_source 로 구분, §0.6)
  id TEXT PRIMARY KEY, owner_sub TEXT NOT NULL,
  actor TEXT NOT NULL, actor_verified INTEGER NOT NULL DEFAULT 1,   -- MCP 경로의 actor 는 0(§6.11)
  channel TEXT NOT NULL CHECK(channel IN ('web','rest','mcp','import')),
  scope TEXT NOT NULL CHECK(scope IN ('project','snapshot','diff','target','registry','coverage','job','panel','finding','member')),
  subject_id TEXT NOT NULL,                     -- project_id · snapshot_id · target_key · '<target_key>#<cluster_key>' · job_id …
  project_id TEXT,                              -- 조회 환원용(멤버십 판정·GET /projects/{id}/audit)
  action TEXT NOT NULL,                         -- 'member.put' 'project.transfer' 'project.lifecycle' 'project.purge' 'gate.ack' 'gate.ack.revoke'
                                                -- 'coverage.skip' 'coverage.uncarry' 'job.pause|resume|cancel' 'brief.exclude'
                                                -- 'registry.status' 'verdict.final' 'finding.add|edit|delete' 'import.conflict'
                                                -- 'project.classification' 'project.mcp_visibility'(§5.1 원칙 9 노출 토글) 'recall.approve' 'curation.decide' 'rekey'
  before_json TEXT, after_json TEXT, reason TEXT,
  at INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS ix_rr_audit_subject ON rr_audit(scope, subject_id, at);
CREATE INDEX IF NOT EXISTS ix_rr_audit_project ON rr_audit(project_id, at);
CREATE INDEX IF NOT EXISTS ix_rr_audit_actor ON rr_audit(actor, at);
-- 열람(GET) 로그는 남기지 않는다 — §10 #29 결정 항목이고 기본값은 '남기지 않음' 이다.

CREATE TABLE IF NOT EXISTS rr_id_map (
  portal_kind TEXT NOT NULL CHECK(portal_kind IN ('project','snapshot','diff','opinion','registry','character','pattern','expert','trait')),
  portal_id TEXT NOT NULL, owner_sub TEXT NOT NULL,
  ra_entity_id INTEGER, ra_type_slug TEXT, adh_record_id TEXT, adh_external_id TEXT,
  ra_synced_at INTEGER, adh_synced_at INTEGER,
  PRIMARY KEY(portal_kind, portal_id));
CREATE INDEX IF NOT EXISTS ix_rr_id_map_ra ON rr_id_map(ra_entity_id);
CREATE INDEX IF NOT EXISTS ix_rr_id_map_adh ON rr_id_map(adh_record_id);
"""


def _split_statements(sql: str) -> list[str]:
    """DDL 텍스트를 sqlite3.complete_statement 로 문장 단위로 나눈다(주석·줄바꿈 보존)."""
    out, buf = [], ""
    for line in sql.splitlines(keepends=True):
        buf += line
        if sqlite3.complete_statement(buf):
            out.append(buf.strip())
            buf = ""
    return out


_DDL_V1: list[str] = _split_statements(_DDL_V1_SQL)

# v2 — 브리프 조립이 부른 외부 도구의 응답 원문(§5.6.2 E10). rr_panel_calls 에 넣지 않는 이유는 셋이다 —
# 그 표는 panel_id NOT NULL 이고(브리프는 패널 편성 전에도 돈다), record_panel_calls 가 패널 시작 때
# `DELETE WHERE panel_id = ?` 로 지우며(브리프 원문이 사라진다), E10 결과는 패널이 아니라 **타깃 단위로 24 h
# 공유**된다. 정본 §5.6.2 는 `rr_panel_calls(source_kind='brief')` 라 적지만 그 표의 열은 `source` 이고
# CHECK 어휘 확장은 마이그레이션 허용 연산 밖이라, 구조가 맞는 별도 표로 둔다(context-notes D18).
_DDL_V2_SQL = """
CREATE TABLE IF NOT EXISTS rr_brief_calls (                   -- 브리프 조립이 부른 외부 도구 응답 원문(§5.6.2 E10)
  call_id TEXT PRIMARY KEY,                     -- 'b-<sha256(target_key|tool|args_hash)[:24]>' — 키 하나당 한 행(§5.6.2)
  target_key TEXT NOT NULL, owner_sub TEXT NOT NULL,
  tool TEXT NOT NULL, app_key TEXT,
  args_json TEXT NOT NULL, args_hash TEXT NOT NULL,           -- 24 h 재사용 판정 키는 (target_key, tool, args_hash)
  ok INTEGER NOT NULL DEFAULT 1,
  result_gz BLOB, result_bytes INTEGER, sha256 TEXT,          -- 원문 전문(절단 없음). voc:·paper: 참조 해석의 원장
  fetched_at INTEGER NOT NULL,                  -- 재사용 창(24 h) 판정 기준 시각
  duration_ms INTEGER, error TEXT);
CREATE INDEX IF NOT EXISTS ix_rr_brief_calls_reuse ON rr_brief_calls(target_key, tool, args_hash, fetched_at);
"""
_DDL_V2: list[str] = _split_statements(_DDL_V2_SQL)

# 버전 오름차순. 한 버전 = 한 트랜잭션. 허용 연산은 CREATE TABLE IF NOT EXISTS · ADD COLUMN · CREATE INDEX IF NOT EXISTS 뿐(plan §5.2.5 (6)).
MIGRATIONS: list[tuple[int, list[str]]] = [(1, _DDL_V1), (2, _DDL_V2)]

# 살림 표 2개 — rr_ 접두가 아니고 export 대상이 아니다(plan §5.2.5 (6)·§8.2.7). 버전 밖에서 항상 CREATE TABLE IF NOT EXISTS.
# _user_credentials 열 정의는 plan §8.2.7 전문 그대로다 — 평문 열 portal_pat 은 폐기고 값은 portal_pat_enc(BLOB) 하나에만 있다.
_HOUSEKEEPING_DDL: list[str] = [
    "CREATE TABLE IF NOT EXISTS _schema_migrations(version INTEGER PRIMARY KEY, applied_at INTEGER, app_version TEXT)",
    "CREATE TABLE IF NOT EXISTS _user_credentials(owner_sub TEXT PRIMARY KEY, portal_pat_enc BLOB NOT NULL, "
    "pat_sub TEXT, pat_email TEXT, pat_groups_json TEXT, pat_scopes_json TEXT NOT NULL, pat_jti TEXT NOT NULL, "
    "pat_exp INTEGER, revoked_at INTEGER, revoked_seen_at INTEGER, registered_at INTEGER)",
]


class RiskStore:
    """앱 프로세스 하나가 소유하는 SQLite 저장소. REST·MCP·러너가 같은 인스턴스와 Lock 을 공유한다."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        # RLock 이다 — tx() 안에서 execute·query 를 다시 부르는 같은 스레드가 자기 락에 막히면 안 된다.
        self._lock = threading.RLock()
        self._conn: sqlite3.Connection | None = None
        self._existed = False
        self._tx_depth = 0

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise AppError("E300", "저장소가 열려 있지 않습니다 — open() 을 먼저 호출하세요.")
        return self._conn

    def open(self) -> None:
        """연결을 연다(멱등). WAL 켜고 외래키는 끈다(외래키는 문자열 계약, DB 제약으로 강제하지 않는다)."""
        if self._conn is not None:
            return
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._existed = self.db_path.is_file() and self.db_path.stat().st_size > 0
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=OFF")
        self._conn = conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def migrate(self) -> int:
        """PRAGMA user_version(정본) 보다 높은 버전만 순서대로 적용한다(멱등). 이력은 _schema_migrations 에 남긴다.

        기존 DB 에 적용할 버전이 있으면 적용 직전 `risk_review.db.pre-migrate-<ts>` 사본을 남기고(plan §5.2.5 (6)),
        DB 버전이 코드 최대 버전보다 높으면 예외(기동 실패). 적용 후 살림 표 2개를 만들고 버전을 돌려준다.
        """
        with self._lock:
            conn = self.conn
            current = self._schema_version_unlocked()
            latest = MIGRATIONS[-1][0]
            if current > latest:
                raise AppError(
                    "E300",
                    f"DB 스키마 버전({current})이 앱 코드({latest})보다 높습니다 — 앱을 갱신하세요.",
                )
            if self._existed and current < latest:
                self._backup_unlocked(f"pre-migrate-{int(time.time())}")
            conn.execute(_HOUSEKEEPING_DDL[0])
            conn.commit()
            for version, statements in MIGRATIONS:
                if version <= current:
                    continue
                try:
                    conn.execute("BEGIN")
                    for sql in statements:
                        conn.execute(sql)
                    conn.execute(
                        "INSERT INTO _schema_migrations(version, applied_at, app_version) VALUES (?, ?, ?)",
                        (version, int(time.time()), config.APP_VERSION),
                    )
                    conn.execute(f"PRAGMA user_version = {int(version)}")
                    conn.commit()
                except sqlite3.Error as exc:
                    conn.rollback()
                    raise AppError("E300", f"마이그레이션 v{version} 실패: {exc}") from exc
            for sql in _HOUSEKEEPING_DDL:
                conn.execute(sql)
            conn.commit()
            return self._schema_version_unlocked()

    def _backup_unlocked(self, suffix: str) -> Path:
        """WAL 을 체크포인트한 뒤 DB 파일을 `<db>.<suffix>` 로 복사한다."""
        self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        target = self.db_path.with_name(f"{self.db_path.name}.{suffix}")
        shutil.copy2(self.db_path, target)
        return target

    def _schema_version_unlocked(self) -> int:
        return int(self.conn.execute("PRAGMA user_version").fetchone()[0])

    def schema_version(self) -> int:
        """PRAGMA user_version 의 스키마 버전(미적용이면 0, plan §5.2.5 (6))."""
        with self._lock:
            return self._schema_version_unlocked()

    def tables(self) -> list[str]:
        """rr_ 접두 표 이름(정렬)."""
        with self._lock:
            rows = self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'rr\\_%' ESCAPE '\\' ORDER BY name"
            ).fetchall()
        return [r["name"] for r in rows]

    # ------------------------------------------------------------ 원시 도구(모듈들이 자기 SQL 을 이 위에서 돌린다)
    # 각 모듈은 sqlite3.connect 를 따로 열지 않고 여기 넷만 쓴다. 'select *' 대신 컬럼을 명시해 뒤에 붙는 열에 깨지지 않게 한다.
    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        """BEGIN IMMEDIATE 트랜잭션. 정상 종료면 commit, 예외면 rollback 하고 예외를 그대로 올린다.

        재진입 안전 — 이미 열린 트랜잭션 안에서 다시 부르면 새 BEGIN 없이 같은 트랜잭션에 합류하고,
        가장 바깥 블록이 끝날 때 한 번만 commit 한다. 안쪽에서 난 예외는 바깥까지 전파되므로 전체가 rollback 된다.
        """
        with self._lock:
            if self._tx_depth > 0:
                self._tx_depth += 1
                try:
                    yield self.conn
                finally:
                    self._tx_depth -= 1
                return
            conn = self.conn
            conn.execute("BEGIN IMMEDIATE")
            self._tx_depth = 1
            try:
                yield conn
            except BaseException:
                conn.rollback()
                raise
            else:
                conn.commit()
            finally:
                self._tx_depth = 0

    def query(self, sql: str, params: Sequence[Any] | Mapping[str, Any] = ()) -> list[sqlite3.Row]:
        """SELECT 결과 전부(sqlite3.Row 리스트). row['col'] 로 읽고 dict(row) 로 바꿀 수 있다."""
        with self._lock:
            return self.conn.execute(sql, params).fetchall()

    def query_one(self, sql: str, params: Sequence[Any] | Mapping[str, Any] = ()) -> sqlite3.Row | None:
        """첫 행 또는 None."""
        with self._lock:
            return self.conn.execute(sql, params).fetchone()

    def execute(self, sql: str, params: Sequence[Any] | Mapping[str, Any] = ()) -> int:
        """문장 하나를 돌리고 rowcount 를 돌려준다. tx() 밖이면 바로 commit, 안이면 그 트랜잭션에 맡긴다."""
        with self._lock:
            cur = self.conn.execute(sql, params)
            if self._tx_depth == 0:
                self.conn.commit()
            return cur.rowcount

    def executemany(self, sql: str, seq_of_params: Iterable[Sequence[Any] | Mapping[str, Any]]) -> int:
        """같은 문장을 여러 파라미터로 돌리고 rowcount 를 돌려준다. commit 규칙은 execute 와 같다."""
        with self._lock:
            cur = self.conn.executemany(sql, seq_of_params)
            if self._tx_depth == 0:
                self.conn.commit()
            return cur.rowcount

    # ------------------------------------------------------------ 살림 표 _user_credentials(러너 자격 (b), plan §8.2.7)
    def get_credential(self, owner_sub: str) -> dict | None:
        """owner_sub 의 행(dict) 또는 None. 값은 응답·로그에 그대로 싣지 않는다(plan §8.2.7).

        저장 열은 `portal_pat_enc`(BLOB) 하나이고 평문 열은 없다. 저장소는 그 값을 해석하지 않는다 —
        Fernet 암복호(`HWAXRISK_CRED_KEY`)는 identity 쪽 몫이라 여기서는 BLOB 을 문자열로 되돌려
        `portal_pat` 키로 넘기기만 한다.
        """
        with self._lock:
            row = self.conn.execute(
                "SELECT owner_sub, portal_pat_enc, pat_sub, pat_email, pat_groups_json, pat_scopes_json, pat_jti,"
                " pat_exp, revoked_at, revoked_seen_at, registered_at"
                " FROM _user_credentials WHERE owner_sub = ?", (owner_sub,)).fetchone()
        if row is None:
            return None
        out = dict(row)
        blob = out.pop("portal_pat_enc")
        out["portal_pat"] = bytes(blob).decode("utf-8") if blob is not None else ""
        return out

    def upsert_credential(self, owner_sub: str, portal_pat: str, pat_sub: str | None, pat_email: str | None,
                          pat_groups_json: str, pat_exp: int | None,
                          pat_scopes_json: str = "[]", pat_jti: str = "") -> None:
        """등록·재등록(UPSERT). 넘어온 값은 `portal_pat_enc` BLOB 으로만 들어간다(평문 열 없음)."""
        with self._lock:
            self.conn.execute(
                "INSERT INTO _user_credentials(owner_sub, portal_pat_enc, pat_sub, pat_email, pat_groups_json,"
                " pat_scopes_json, pat_jti, pat_exp, registered_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(owner_sub) DO UPDATE SET "
                "portal_pat_enc=excluded.portal_pat_enc, pat_sub=excluded.pat_sub, pat_email=excluded.pat_email, "
                "pat_groups_json=excluded.pat_groups_json, pat_scopes_json=excluded.pat_scopes_json, "
                "pat_jti=excluded.pat_jti, pat_exp=excluded.pat_exp, registered_at=excluded.registered_at, "
                # 재등록은 폐기 표기를 지운다 — 지우지 않으면 credential_pat 이 계속 None 이라 영구 강등된다.
                "revoked_at=NULL, revoked_seen_at=NULL",
                (owner_sub, portal_pat.encode("utf-8"), pat_sub, pat_email, pat_groups_json,
                 pat_scopes_json, pat_jti, pat_exp, int(time.time())),
            )
            if self._tx_depth == 0:                 # tx() 안이면 바깥 트랜잭션에 맡긴다(execute 와 같은 규칙).
                self.conn.commit()

    def delete_credential(self, owner_sub: str) -> int:
        """삭제한 행 수(0 또는 1)."""
        with self._lock:
            cur = self.conn.execute("DELETE FROM _user_credentials WHERE owner_sub = ?", (owner_sub,))
            if self._tx_depth == 0:
                self.conn.commit()
        return cur.rowcount


# ---------------------------------------------------------------- 프로세스 단일 인스턴스
# REST 핸들러·MCP 도구·러너가 같은 인스턴스를 쓴다. DB 경로가 바뀌면(테스트가 HWAXRISK_DATA_DIR 를 바꾼 경우) 다시 연다.
_store: RiskStore | None = None
_store_lock = threading.Lock()


def get_store() -> RiskStore:
    """현재 설정의 DB 경로에 대한 열린·마이그레이션된 RiskStore 를 돌려준다."""
    global _store
    db_path = config.settings.db_path
    with _store_lock:
        if _store is None or _store.db_path != db_path:
            if _store is not None:
                _store.close()
            store = RiskStore(db_path)
            store.open()
            store.migrate()
            _store = store
        return _store


def close_store() -> None:
    """프로세스 단일 인스턴스를 닫는다(lifespan 종료용)."""
    global _store
    with _store_lock:
        if _store is not None:
            _store.close()
            _store = None
