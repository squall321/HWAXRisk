# 앱 DB(SQLite) 저장소 — RiskStore(stdlib sqlite3 + Lock), PRAGMA user_version 마이그레이션(v1 = plan §5.2.2 rr_* DDL 전문), 살림 표 _schema_migrations·_user_credentials
from __future__ import annotations

import shutil
import sqlite3
import threading
import time
from pathlib import Path

from app import config
from app.errors import AppError

# owner_sub 컬럼의 값은 heax 사용자 이메일(소문자)이다. 원천은 identity.py 의 heax `GET /api/v1/auth/me` 되묻기(plan §5.2.1·§8.2.8)이며
# X-Heax-User-* 헤더는 service 모드 앱에 복사되지 않고 위조 가능하므로 원천으로 쓰지 않는다.
# 아래 DDL 은 plan §5.2.2 A~H 의 ```sql 블록을 바이트 그대로 옮긴 것이다(고치려면 plan 을 먼저 고친다).
_DDL_V1_SQL = """\
CREATE TABLE IF NOT EXISTS rr_projects (
  id TEXT PRIMARY KEY, owner_sub TEXT NOT NULL,
  code TEXT NOT NULL, name TEXT, stage TEXT,
  predecessor_project_id TEXT,                  -- 계보(UI 입력) → RA revision_of
  adh_team TEXT, adh_group TEXT,                -- 사용자 확인값, 자동 채움 금지
  ra_entity_id INTEGER, adh_character_record_id TEXT,
  character_status TEXT CHECK(character_status IN ('seed','panel','confirmed')) DEFAULT 'seed',
  created_at INTEGER, updated_at INTEGER,
  UNIQUE(owner_sub, code));

CREATE TABLE IF NOT EXISTS rr_sources (
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL, owner_sub TEXT NOT NULL,
  kind TEXT NOT NULL CHECK(kind IN ('mcad','dyna','dyna_result','ecad')),
  app_key TEXT, ref_json TEXT NOT NULL, ref_key TEXT NOT NULL,   -- ref_key = kind:app_key:정렬 ref 문자열
  bridge_declared INTEGER DEFAULT 0, probe_json TEXT, probe_at INTEGER,
  adapter_version TEXT, created_at INTEGER,
  UNIQUE(project_id, ref_key));

CREATE TABLE IF NOT EXISTS rr_snapshots (
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL, owner_sub TEXT NOT NULL,
  ir_version TEXT NOT NULL, ir_hash TEXT NOT NULL,
  ir_json TEXT NOT NULL,                        -- rr_ir 원본(유일)
  source_ids_json TEXT NOT NULL,                -- [{kind, app_key, ref, hash, tool_version, tol_params}]
  kinds_json TEXT NOT NULL,                     -- ['mcad','dyna',…]
  node_count INTEGER, edge_count INTEGER, missing_json TEXT, warnings_n INTEGER,
  degraded TEXT,                                -- null | 'mcp_degraded'
  adapter_versions_json TEXT, ra_entity_id INTEGER, adh_digest_record_id TEXT,
  created_at INTEGER,
  UNIQUE(project_id, ir_hash));
CREATE INDEX IF NOT EXISTS ix_rr_snapshots_project ON rr_snapshots(project_id, created_at);

CREATE TABLE IF NOT EXISTS rr_snapshot_calls (                -- 행 정의는 §2.11.4
  call_id TEXT PRIMARY KEY,                     -- '<snapshot_id[:8]>-<seq:03d>'
  snapshot_id TEXT NOT NULL, owner_sub TEXT NOT NULL,
  seq INTEGER NOT NULL, source_kind TEXT NOT NULL, app_key TEXT,
  channel TEXT NOT NULL CHECK(channel IN ('mcp','rest')), tool TEXT NOT NULL,
  args_json TEXT, args_hash TEXT, ok INTEGER NOT NULL DEFAULT 1, http_status INTEGER,
  response_sha256 TEXT, response_gz BLOB, response_bytes INTEGER,
  started_at INTEGER, duration_ms INTEGER, error TEXT);
CREATE INDEX IF NOT EXISTS ix_rr_calls_snapshot ON rr_snapshot_calls(snapshot_id, seq);

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
  PRIMARY KEY(target_key, agent_key));

CREATE TABLE IF NOT EXISTS rr_coverage (                      -- §6.8.1
  target_key TEXT NOT NULL, agent_key TEXT NOT NULL, owner_sub TEXT NOT NULL,
  domain TEXT NOT NULL, tier TEXT, origin TEXT CHECK(origin IN ('primary','counter')),
  status TEXT NOT NULL CHECK(status IN ('pending','assigned','running','done','done_weak','abstain',
                                        'failed','skipped','deferred','carried')) DEFAULT 'pending',
  cycle INTEGER DEFAULT 1, retry INTEGER DEFAULT 0,
  panel_id TEXT, opinion_id TEXT, adh_record_id TEXT, ra_assessment_id INTEGER,
  carried_from_opinion_id TEXT, reason TEXT,
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
  model_json TEXT,                              -- D6 모델 출처 {runtime, provider, model, endpoint_host, captured ∈ health_snapshot|caller_reported|unavailable, engine_rev, chair_rev, seat_contract_rev, model_end?}(§6.7.2 1·7단계, §6.11)
  retry INTEGER DEFAULT 0, error TEXT, started_at INTEGER, ended_at INTEGER, created_at INTEGER,
  UNIQUE(target_key, panel_no));

CREATE TABLE IF NOT EXISTS rr_jobs (
  id TEXT PRIMARY KEY, target_key TEXT NOT NULL, owner_sub TEXT NOT NULL, tier TEXT,
  state TEXT NOT NULL CHECK(state IN ('queued','running','paused','cancelling','cancelled','completed','failed')),
  pause_reason TEXT CHECK(pause_reason IN ('diminishing','daily_cap','user')),
  concurrency INTEGER DEFAULT 1, params_json TEXT, progress_json TEXT,
  panels_done INTEGER DEFAULT 0, panels_total INTEGER, error TEXT, created_at INTEGER, updated_at INTEGER);
CREATE INDEX IF NOT EXISTS ix_rr_jobs_state ON rr_jobs(state, created_at);

CREATE TABLE IF NOT EXISTS rr_seat_opinions (
  opinion_id TEXT PRIMARY KEY, target_key TEXT NOT NULL, panel_id TEXT NOT NULL, owner_sub TEXT NOT NULL,
  agent_key TEXT NOT NULL, domain TEXT NOT NULL,
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
  finding_id TEXT PRIMARY KEY, claim_uid TEXT NOT NULL UNIQUE,   -- '<panel_id>#F1' | '#G1'
  target_key TEXT NOT NULL, panel_id TEXT NOT NULL, opinion_id TEXT,
  project_id TEXT NOT NULL, snapshot_id TEXT, diff_id TEXT, owner_sub TEXT NOT NULL,
  visibility TEXT CHECK(visibility IN ('private','org')) DEFAULT 'private',
  direction TEXT NOT NULL CHECK(direction IN ('risk','improvement','neutral')),
  domain TEXT, mechanism TEXT, mechanism_detail TEXT, mechanism_free TEXT,
  change_kind TEXT, subject_key TEXT, ckeys_json TEXT, trigger_condition TEXT,
  severity TEXT CHECK(severity IN ('경미','중대','치명')), sev3 INTEGER,
  judgement TEXT CHECK(judgement IN ('OK','WARNING','FAIL','undetermined')),
  detectability TEXT, detect_tool TEXT,
  evidence_grade TEXT, precedent TEXT CHECK(precedent IN ('in_range','out_of_range','none')),
  dangling INTEGER DEFAULT 0, cluster_key TEXT NOT NULL,
  finding_json TEXT NOT NULL,                   -- finding 전체 + feature_snapshot + precedent_refs
  status TEXT NOT NULL CHECK(status IN ('open','verified','dismissed','mitigated','superseded')) DEFAULT 'open',
  status_reason TEXT, superseded_by TEXT,
  ra_entity_id INTEGER, adh_record_id TEXT,
  taxonomy_version TEXT, rule_version TEXT, ir_version TEXT, diff_version TEXT,
  created_at INTEGER, updated_at INTEGER);
CREATE INDEX IF NOT EXISTS ix_rr_findings_cluster ON rr_findings(cluster_key);
CREATE INDEX IF NOT EXISTS ix_rr_findings_subject ON rr_findings(subject_key);
CREATE INDEX IF NOT EXISTS ix_rr_findings_mech ON rr_findings(mechanism, mechanism_detail, change_kind);
CREATE INDEX IF NOT EXISTS ix_rr_findings_project ON rr_findings(project_id, status);

CREATE TABLE IF NOT EXISTS rr_registry (
  target_key TEXT NOT NULL, cluster_key TEXT NOT NULL, owner_sub TEXT NOT NULL,
  visibility TEXT CHECK(visibility IN ('private','org')) DEFAULT 'private',
  merged_json TEXT NOT NULL,                    -- 대표 finding + member finding_ids + resolving_checks 집합 + precedent_clusters
  support INTEGER DEFAULT 1, contested INTEGER DEFAULT 0,
  direction TEXT, mechanism TEXT, mechanism_detail TEXT, change_kind TEXT, subject_key TEXT,
  severity TEXT, sev3 INTEGER, judgement TEXT, evidence_grade TEXT, precedent TEXT,
  weak_subject INTEGER DEFAULT 0, priority REAL,   -- §4.3.2 · §4.7.1
  status TEXT NOT NULL CHECK(status IN ('open','verified','dismissed','mitigated','superseded')) DEFAULT 'open',
  verified_by_json TEXT, stale_json TEXT,       -- §4.8 {<T′>: {stale: bool, unraised: bool}}
  superseded_by TEXT, ra_entity_id INTEGER, updated_at INTEGER,
  PRIMARY KEY(target_key, cluster_key));
CREATE INDEX IF NOT EXISTS ix_rr_registry_cluster ON rr_registry(cluster_key);
CREATE INDEX IF NOT EXISTS ix_rr_registry_subject ON rr_registry(subject_key, status);

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
  kind TEXT NOT NULL CHECK(kind IN ('unclassified_code','pattern_candidate','label_match','x_tag_promote')),
  payload_json TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('open','done','rejected')) DEFAULT 'open',
  decision_json TEXT, decided_by TEXT, decided_at INTEGER, created_at INTEGER);
CREATE INDEX IF NOT EXISTS ix_rr_queue ON rr_curation_queue(kind, status, created_at);

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

# 버전 오름차순. 한 버전 = 한 트랜잭션. 허용 연산은 CREATE TABLE IF NOT EXISTS · ADD COLUMN · CREATE INDEX IF NOT EXISTS 뿐(plan §5.2.5 (6)).
MIGRATIONS: list[tuple[int, list[str]]] = [(1, _DDL_V1)]

# 살림 표 2개 — rr_ 접두가 아니고 export 대상이 아니다(plan §5.2.5 (6)·§8.2.7). 버전 밖에서 항상 CREATE TABLE IF NOT EXISTS.
_HOUSEKEEPING_DDL: list[str] = [
    "CREATE TABLE IF NOT EXISTS _schema_migrations(version INTEGER PRIMARY KEY, applied_at INTEGER, app_version TEXT)",
    "CREATE TABLE IF NOT EXISTS _user_credentials(owner_sub TEXT PRIMARY KEY, portal_pat TEXT NOT NULL, pat_sub TEXT, "
    "pat_email TEXT, pat_groups_json TEXT, pat_exp INTEGER, registered_at INTEGER)",
]


class RiskStore:
    """앱 프로세스 하나가 소유하는 SQLite 저장소. REST·MCP·러너가 같은 인스턴스와 Lock 을 공유한다."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None
        self._existed = False

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

    # ------------------------------------------------------------ 살림 표 _user_credentials(러너 자격 (b), plan §8.2.7)
    def get_credential(self, owner_sub: str) -> dict | None:
        """owner_sub 의 행(dict) 또는 None. portal_pat 값도 포함되므로 응답에 그대로 싣지 않는다."""
        with self._lock:
            row = self.conn.execute("SELECT * FROM _user_credentials WHERE owner_sub = ?", (owner_sub,)).fetchone()
        return dict(row) if row is not None else None

    def upsert_credential(self, owner_sub: str, portal_pat: str, pat_sub: str | None, pat_email: str | None,
                          pat_groups_json: str, pat_exp: int | None) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT INTO _user_credentials(owner_sub, portal_pat, pat_sub, pat_email, pat_groups_json, pat_exp, registered_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(owner_sub) DO UPDATE SET portal_pat=excluded.portal_pat, "
                "pat_sub=excluded.pat_sub, pat_email=excluded.pat_email, pat_groups_json=excluded.pat_groups_json, "
                "pat_exp=excluded.pat_exp, registered_at=excluded.registered_at",
                (owner_sub, portal_pat, pat_sub, pat_email, pat_groups_json, pat_exp, int(time.time())),
            )
            self.conn.commit()

    def delete_credential(self, owner_sub: str) -> int:
        """삭제한 행 수(0 또는 1)."""
        with self._lock:
            cur = self.conn.execute("DELETE FROM _user_credentials WHERE owner_sub = ?", (owner_sub,))
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
