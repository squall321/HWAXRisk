// 실 백엔드(이 가지의 코드 · 스크래치 하네스)가 보낸 응답을 줄여 옮긴 견본 — tsc 가 화면 타입과 견준다(칸이 빠지거나 값 종류가 다르면 빌드가 깨진다)
import type {
  CellList,
  CellsDisposed,
  ClosureCells,
  Coverage,
  IssueList,
  IssueRow,
  PortalPatSummary,
  Registry,
  SnapshotHeader,
  SnapshotState,
  SynthReportPage,
} from "../types";

/**
 * 견본 하나 — 타입이 요구하는 칸이 다 있고 값 종류가 맞아야 받는다(25d7b07 · FE-5 — 타입이 서버와 다르면 tsc 가 그 거짓을 지켜 준다).
 * 서버가 더 싣는 칸은 받는다(화면이 읽지 않는 열까지 타입에 적지 않는다). 견본은 화면 코드가 import 하지 않아 번들에 들지 않는다 —
 * 시험(tests/m3.test.cjs)이 렌더에 쓴다.
 */
function sample<T>() {
  return <U extends T>(value: U): T => value;
}

/** 카드 대조 대상 진행판 — 사슬(쟁점 잡 대기) · 종합 보고서 판 · 잔여 · 끝난 검토 잡(검토 순서는 앞 둘만). */
export const coverageCells = sample<Coverage>()({
  "target_key": "diff:220d3f493372488c978fefa91334eb1e",
  "job": null,
  "roster_size": 6,
  "by_domain": {
    "mech": {
      "done": 2
    },
    "sim": {
      "done_weak": 2
    },
    "xd": {
      "done": 1,
      "done_weak": 1
    }
  },
  "by_status": {
    "abstain": 0,
    "assigned": 0,
    "carried": 0,
    "deferred": 0,
    "done": 3,
    "done_weak": 3,
    "failed": 0,
    "pending": 0,
    "running": 0,
    "skipped": 0
  },
  "strong": {
    "done": 3,
    "done_weak": 3,
    "ratio": 0.5
  },
  "unseated_n": 0,
  "level": "C2",
  "close_level": "C3",
  "flow": "cells",
  "units": {
    "rev": 1,
    "status": "ok",
    "reviewable_n": 5
  },
  "review": {
    "units": 5,
    "cells": {
      "total": 30,
      "by_state": {
        "pending": 1,
        "running": 0,
        "reviewed": 28,
        "na_irrelevant": 0,
        "no_input": 0,
        "failed": 0,
        "skipped": 1
      },
      "by_basis": {
        "cards": 18,
        "background": 5,
        "role_only": 5,
        "search_only": 0,
        "noinput": 0
      },
      "in_scope": {
        "job_id": "7376fbf2e2ec421fb27f919a5ba13afb",
        "total": 1,
        "by_state": {
          "pending": 0,
          "running": 0,
          "reviewed": 0,
          "na_irrelevant": 0,
          "no_input": 0,
          "failed": 0,
          "skipped": 1
        }
      },
      "out_of_scope_pending": 1,
      "failed_open": 0,
      "form_only": null
    },
    "experts": {
      "total": 6,
      "by_state": {
        "planned": 1,
        "running": 0,
        "ready": 5,
        "partial": 0,
        "blocked": 0
      }
    },
    "cards": null,
    "quality": null,
    "order": [
      {
        "order": 1,
        "agent_key": "mech-test-seal",
        "domain": "mech",
        "rank_in_domain": 1,
        "tier": "A",
        "deferred": false,
        "input_gaps": [],
        "state": "ready",
        "cards_total": 10,
        "checkable_n": 6
      },
      {
        "order": 2,
        "agent_key": "sim-syn-0",
        "domain": "sim",
        "rank_in_domain": 1,
        "tier": "A",
        "deferred": false,
        "input_gaps": [],
        "state": "ready",
        "cards_total": 4,
        "checkable_n": 0
      }
    ],
    "dispositions": {
      "retried": 1,
      "skipped": 1
    },
    "filter": {
      "mode": "on",
      "approved": true,
      "would_filter": 0,
      "filtered": 0,
      "audited": 0,
      "audit": {
        "risk_miss": 0,
        "relevance_miss": 0,
        "undetermined": 0,
        "kept": 0,
        "upper95": null,
        "upper95_conservative": null,
        "n_audit": 0,
        "floor_met": true,
        "pending": 0
      },
      "shadow": {
        "would_filter": 0,
        "sampled": 0,
        "risk_miss": 0,
        "upper95": null
      },
      "widened": [],
      "off": false,
      "saved_calls_est": 0
    },
    "noinput": {
      "experts": 0,
      "cells": 0,
      "by_outcome": {
        "impact": 0,
        "unknown": 0,
        "request": 0,
        "none": 0
      }
    },
    "job": {
      "id": "7376fbf2e2ec421fb27f919a5ba13afb",
      "mode": "reviews",
      "chain": true,
      "state": "queued",
      "hold_code": null,
      "hold_until": null,
      "hold_n": 0,
      "error": null,
      "credential_email": "tester@example.test",
      "scope": {
        "agents": [
          "xd-syn-1"
        ],
        "unit_ids": [
          "u-911b94d08006"
        ]
      },
      "phase": "pack",
      "progress": {
        "packs": null,
        "experts": null,
        "cells": null,
        "calls": null,
        "breaker": null,
        "server": null,
        "reopened_extra": {
          "cells": 0,
          "runs": 0,
          "calls_est": 0,
          "consented": {
            "cells": 0,
            "calls_est": 0
          },
          "unconsented": {
            "cells": 0,
            "calls_est": 0
          },
          "allowance": 2,
          "expected": 0,
          "max_calls": 30000,
          "hold": null
        }
      },
      "waiting": null,
      "signal": {
        "workers": []
      }
    }
  },
  "external_sync": {
    "ra": {
      "state": "pending",
      "pending_ops": 0,
      "reason": "sender_unwired",
      "message": "RA 반영 안 됨 — 보내는 쪽이 아직 배선되지 않았다(M4). 대기 0건, 보낸 것 없음."
    },
    "adh": {
      "state": "pending",
      "pending_ops": 0,
      "reason": "sender_unwired",
      "message": "AIDataHub 반영 안 됨 — 보내는 쪽이 아직 배선되지 않았다(M4). 대기 0건, 보낸 것 없음."
    }
  },
  "level_label": "C2(열린 셀 1 · 쟁점 진행 1건 · 깊이 미달 xd 1/2 · 후속 낡음(재검토 1셀) · 재개방 1셀 · 사람 넘김 1셀 · 미토의 쟁점 3건(주장 FAIL 3) · 검토 품질 기준 밖 1항 · 카드 0장 1명 · 카드 없는 영역 — 역할 판단만 · sim · 2차 영향 미실행(넘김 0건 표만) · 결손 사냥 미실행)",
  "qualifiers": [
    {
      "acked": false,
      "basis_hash": "9d2a450d0617",
      "basis_n": 1,
      "blocking": true,
      "crowded": [],
      "item": "skipped",
      "label": "사람 넘김 1셀",
      "n": 1
    },
    {
      "ack": {
        "at": 1793434084,
        "by": "tester@example.test",
        "reason": "남은 넷은 다음 리비전 심사에서 패널로 본다",
        "state": "revoked"
      },
      "acked": false,
      "basis_hash": "9348bcb41e74",
      "basis_n": 3,
      "blocking": true,
      "held_fail": 3,
      "item": "issues_untried",
      "label": "미토의 쟁점 3건(주장 FAIL 3)",
      "n": 3,
      "p1": 3,
      "sentences": [
        "전문가 4명이 FAIL 로 봤으나 미토의",
        "전문가 3명이 FAIL 로 봤으나 미토의",
        "전문가 4명이 FAIL 로 봤으나 미토의"
      ]
    },
    {
      "ack": {
        "at": 1793434108,
        "by": "tester@example.test",
        "reason": "품질 기준 밖 1항은 표본이 작아서다",
        "state": "valid"
      },
      "acked": true,
      "basis_hash": "d911a58df3bb",
      "basis_n": 1,
      "blocking": true,
      "item": "quality",
      "label": "검토 품질 기준 밖 1항",
      "n": 1,
      "out_of_bounds": [],
      "strong_ratio_cells": 0.6429
    },
    {
      "acked": false,
      "basis_hash": "aa7507972784",
      "basis_n": 1,
      "blocking": false,
      "item": "no_cards",
      "label": "카드 0장 1명",
      "n": 1
    },
    {
      "acked": false,
      "basis_hash": "01aa2c1f3cba",
      "basis_n": 1,
      "blocking": false,
      "domains": [
        "sim"
      ],
      "item": "depth_no_cards",
      "label": "카드 없는 영역 — 역할 판단만 · sim",
      "mixed": {},
      "n": 1
    },
    {
      "acked": false,
      "basis_hash": "9897a5657f9b",
      "basis_n": 0,
      "blocking": false,
      "item": "cross_not_run",
      "label": "2차 영향 미실행(넘김 0건 표만)",
      "n": 0,
      "pairs": 0
    },
    {
      "acked": false,
      "basis_hash": "8df4c986a5ff",
      "basis_n": 0,
      "blocking": false,
      "item": "mech_not_run",
      "label": "결손 사냥 미실행",
      "n": 0
    }
  ],
  "stage": {
    "mode": "issues",
    "job_id": "1df2ed1b1115469292ff04095d46ccca",
    "state": "queued",
    "hold_code": null,
    "pause_reason": null,
    "error": null
  },
  "report": {
    "version_no": 6,
    "trigger": "ack",
    "narrative_state": "full",
    "created_at": 1793434108
  }
});

/** 다시 연 셀 몫이 여유를 넘어 consent_extra 로 멈춘 검토 잡(살아 있는 잡에 사람의 force 다시를 얹었다). */
export const coveragePausedConsent = sample<Coverage>()({
  "target_key": "diff:46a774d6d3fd463f9750b66704c2357b",
  "job": null,
  "roster_size": 6,
  "by_domain": {
    "mech": {
      "done": 1,
      "pending": 1
    },
    "sim": {
      "pending": 2
    },
    "xd": {
      "pending": 1,
      "done_weak": 1
    }
  },
  "by_status": {
    "abstain": 0,
    "assigned": 0,
    "carried": 0,
    "deferred": 0,
    "done": 1,
    "done_weak": 1,
    "failed": 0,
    "pending": 4,
    "running": 0,
    "skipped": 0
  },
  "strong": {
    "done": 1,
    "done_weak": 1,
    "ratio": 0.5
  },
  "unseated_n": 4,
  "level": "C0",
  "close_level": "C3",
  "flow": "cells",
  "units": {
    "rev": 1,
    "status": "ok",
    "reviewable_n": 5
  },
  "review": {
    "units": 5,
    "cells": {
      "total": 30,
      "by_state": {
        "pending": 22,
        "running": 0,
        "reviewed": 7,
        "na_irrelevant": 0,
        "no_input": 0,
        "failed": 0,
        "skipped": 1
      },
      "by_basis": {
        "cards": 7,
        "background": 0,
        "role_only": 0,
        "search_only": 0,
        "noinput": 0
      },
      "in_scope": {
        "job_id": "24aa4b0cfde648c88587016781ad72df",
        "total": 8,
        "by_state": {
          "pending": 7,
          "running": 0,
          "reviewed": 0,
          "na_irrelevant": 0,
          "no_input": 0,
          "failed": 0,
          "skipped": 1
        }
      },
      "out_of_scope_pending": 15,
      "failed_open": 0,
      "form_only": null
    },
    "experts": {
      "total": 6,
      "by_state": {
        "planned": 5,
        "running": 0,
        "ready": 1,
        "partial": 0,
        "blocked": 0
      }
    },
    "cards": null,
    "quality": null,
    "order": [
      {
        "order": 1,
        "agent_key": "mech-test-seal",
        "domain": "mech",
        "rank_in_domain": 1,
        "tier": "A",
        "deferred": false,
        "input_gaps": [],
        "state": "ready",
        "cards_total": 10,
        "checkable_n": 6
      },
      {
        "order": 2,
        "agent_key": "sim-syn-0",
        "domain": "sim",
        "rank_in_domain": 1,
        "tier": "A",
        "deferred": false,
        "input_gaps": [],
        "state": "planned",
        "cards_total": null,
        "checkable_n": null
      }
    ],
    "dispositions": {
      "retried": 3,
      "skipped": 1
    },
    "filter": {
      "mode": "on",
      "approved": true,
      "would_filter": 0,
      "filtered": 0,
      "audited": 0,
      "audit": {
        "risk_miss": 0,
        "relevance_miss": 0,
        "undetermined": 0,
        "kept": 0,
        "upper95": null,
        "upper95_conservative": null,
        "n_audit": 0,
        "floor_met": true,
        "pending": 0
      },
      "shadow": {
        "would_filter": 0,
        "sampled": 0,
        "risk_miss": 0,
        "upper95": null
      },
      "widened": [],
      "off": false,
      "saved_calls_est": 0
    },
    "noinput": {
      "experts": 0,
      "cells": 0,
      "by_outcome": {
        "impact": 0,
        "unknown": 0,
        "request": 0,
        "none": 0
      }
    },
    "job": {
      "id": "24aa4b0cfde648c88587016781ad72df",
      "mode": "reviews",
      "chain": true,
      "state": "paused",
      "hold_code": "consent_extra",
      "hold_until": null,
      "hold_n": 1,
      "error": "다시 연 셀 1개(호출 추정 5회)가 여유 2회(동의받은 추정 33회의 0% · 최소 2회)를 넘었다 — 사람이 그 몫에 동의하면(재개 consent=true) 이어 돌고, 동의하지 않으면 그 셀을 넘긴다(넘김의 filter state=pending). 아무것도 차감하지 않았고 그 셀은 이 잡에 묶인 채 기다린다",
      "credential_email": "tester@example.test",
      "scope": {
        "agents": [
          "xd-syn-1",
          "mech-test-seal",
          "mech-syn-0"
        ]
      },
      "phase": "pack",
      "progress": {
        "packs": null,
        "experts": null,
        "cells": null,
        "calls": null,
        "breaker": null,
        "server": null,
        "reopened_extra": {
          "cells": 2,
          "runs": 2,
          "calls_est": 10.5,
          "consented": {
            "cells": 1,
            "calls_est": 5.25
          },
          "unconsented": {
            "cells": 1,
            "calls_est": 5.25
          },
          "allowance": 2,
          "expected": 28,
          "max_calls": 30000,
          "hold": "consent_extra"
        }
      },
      "waiting": null,
      "signal": {
        "workers": []
      }
    }
  },
  "external_sync": {
    "ra": {
      "state": "pending",
      "pending_ops": 0,
      "reason": "sender_unwired",
      "message": "RA 반영 안 됨 — 보내는 쪽이 아직 배선되지 않았다(M4). 대기 0건, 보낸 것 없음."
    },
    "adh": {
      "state": "pending",
      "pending_ops": 0,
      "reason": "sender_unwired",
      "message": "AIDataHub 반영 안 됨 — 보내는 쪽이 아직 배선되지 않았다(M4). 대기 0건, 보낸 것 없음."
    }
  },
  "level_label": "C0(열린 셀 22 · 사람 넘김 1셀 · 카드 없는 영역 — 역할 판단만 · sim·mech(그중 1명)·xd(그중 1명) · 2차 영향 미실행(넘김 0건 표만) · 결손 사냥 미실행)",
  "qualifiers": [
    {
      "acked": false,
      "basis_hash": "9d2a450d0617",
      "basis_n": 1,
      "blocking": true,
      "crowded": [],
      "item": "skipped",
      "label": "사람 넘김 1셀",
      "n": 1
    },
    {
      "acked": false,
      "basis_hash": "9db7dec6a6d7",
      "basis_n": 3,
      "blocking": false,
      "domains": [
        "sim"
      ],
      "item": "depth_no_cards",
      "label": "카드 없는 영역 — 역할 판단만 · sim·mech(그중 1명)·xd(그중 1명)",
      "mixed": {
        "mech": 1,
        "xd": 1
      },
      "n": 3
    },
    {
      "acked": false,
      "basis_hash": "9897a5657f9b",
      "basis_n": 0,
      "blocking": false,
      "item": "cross_not_run",
      "label": "2차 영향 미실행(넘김 0건 표만)",
      "n": 0,
      "pairs": 0
    },
    {
      "acked": false,
      "basis_hash": "8df4c986a5ff",
      "basis_n": 0,
      "blocking": false,
      "item": "mech_not_run",
      "label": "결손 사냥 미실행",
      "n": 0
    }
  ],
  "stage": null,
  "report": {
    "version_no": 1,
    "trigger": "reviews_partial",
    "narrative_state": "none",
    "created_at": 1793433834
  }
});

/** 완결 판정(캐시) — 잔여 · 조건 · 깊이 · 확인 이력. */
export const closureCells = sample<ClosureCells>()({
  "c1": true,
  "c2": false,
  "c3": false,
  "close_level": "C3",
  "counts": {
    "cells": {
      "actual": 30,
      "by_state": {
        "failed": 0,
        "na_irrelevant": 0,
        "no_input": 0,
        "pending": 1,
        "reviewed": 28,
        "running": 0,
        "skipped": 1
      },
      "expected": 30,
      "reviewed_by_basis": {
        "background": 5,
        "cards": 18,
        "filtered": 0,
        "noinput": 0,
        "role_only": 5,
        "search_only": 0
      },
      "verdict_gaps": 0
    },
    "experts": {
      "active_by_domain": {
        "mech": 2,
        "sim": 2,
        "xd": 2
      },
      "carded_by_domain": {
        "mech": 2,
        "xd": 2
      },
      "cardless_mixed": {},
      "filtered_only": 0,
      "have_by_domain": {
        "mech": 2,
        "xd": 1
      },
      "input_gap": 0,
      "input_gap_keys": [],
      "no_card_domains": [
        "sim"
      ],
      "reports": {
        "blocked": 0,
        "expected": 6,
        "missing": 0,
        "partial": 0,
        "ready": 5
      },
      "reviewed_cards": 3
    },
    "failed": {
      "by_code": {},
      "open": 0
    },
    "filter": {
      "audit": {
        "failed": 0,
        "floor_met": true,
        "kept": 0,
        "n_audit": 0,
        "pending": 0,
        "relevance_miss": 0,
        "risk_miss": 0,
        "sampled": 0,
        "undetermined": 0,
        "upper95": null,
        "upper95_conservative": null
      },
      "by_domain": {},
      "n": 0,
      "off": false,
      "shadow": {
        "risk_miss": 0,
        "sampled": 0,
        "upper95": null,
        "would_filter": 0
      },
      "widened": [],
      "would_filter": 0
    },
    "handoffs": {
      "lines": 0,
      "pairs": 0
    },
    "invariants": [],
    "issues": {
      "by_outcome": {
        "escalated": 1,
        "undetermined": 1
      },
      "by_state": {
        "inconclusive": 1,
        "queued": 1,
        "resolved": 1,
        "untried_cap": 2
      },
      "cap": {
        "base": 2,
        "hard": 2
      },
      "held_fail": {
        "selected": 5,
        "untried": 3
      },
      "open": 1,
      "p1": {
        "open": 1,
        "run": 2,
        "selected": 5,
        "untried": 3
      }
    },
    "mechanisms_reported": {
      "codes": 0,
      "free": 0
    },
    "no_input": {
      "by_outcome": {
        "impact": 0,
        "none": 0,
        "request": 0,
        "unknown": 0
      },
      "cells": 0,
      "experts": 0
    },
    "quality": {
      "out_of_bounds": [],
      "strong_ratio_cells": 0.6429
    },
    "registry": {
      "attention": {
        "A": 6,
        "B": 10,
        "C": 0,
        "D": 0
      },
      "card_fail_claimed": 5,
      "clusters": 16
    },
    "roster": 6,
    "skipped": {
      "by_note": [
        {
          "by": "tester@example.test",
          "n": 1,
          "note": "이 단위는 다음 리비전에서 다시 본다"
        }
      ],
      "experts": 1,
      "n": 1
    },
    "units": {
      "excluded_by_reason": {
        "incomparable_same": 5,
        "not_design_relevant": 2,
        "null_one_side": 6
      },
      "reviewable": 5,
      "unassigned": 0
    }
  },
  "detail": {
    "cells_hash": "366f65a14d9d729e",
    "depth": {
      "mech": {
        "active": 2,
        "cardless": 0,
        "have": 2,
        "need": 2
      },
      "sim": {
        "active": 0,
        "cardless": 2,
        "exempt": "no_cards",
        "have": 0,
        "need": 0
      },
      "xd": {
        "active": 2,
        "cardless": 0,
        "have": 1,
        "need": 2
      }
    },
    "fresh": {
      "issues": false,
      "reopened_since": 1,
      "report": false,
      "report_version": 6,
      "selected": true,
      "synth_version": 3
    },
    "skipped_ratio": 0.0333,
    "strong_ratio_cells": 0.6429
  },
  "flow": "cells",
  "level": "C2",
  "level_current": "C1",
  "level_label": "C2(열린 셀 1 · 쟁점 진행 1건 · 깊이 미달 xd 1/2 · 후속 낡음(재검토 1셀) · 재개방 1셀 · 사람 넘김 1셀 · 미토의 쟁점 3건(주장 FAIL 3) · 검토 품질 기준 밖 1항 · 카드 0장 1명 · 카드 없는 영역 — 역할 판단만 · sim · 2차 영향 미실행(넘김 0건 표만) · 결손 사냥 미실행)",
  "previous_level": "C2",
  "qualifiers": [
    {
      "acked": false,
      "basis_hash": "9d2a450d0617",
      "basis_n": 1,
      "blocking": true,
      "crowded": [],
      "item": "skipped",
      "label": "사람 넘김 1셀",
      "n": 1
    },
    {
      "ack": {
        "at": 1793434084,
        "by": "tester@example.test",
        "reason": "남은 넷은 다음 리비전 심사에서 패널로 본다",
        "state": "revoked"
      },
      "acked": false,
      "basis_hash": "9348bcb41e74",
      "basis_n": 3,
      "blocking": true,
      "held_fail": 3,
      "item": "issues_untried",
      "label": "미토의 쟁점 3건(주장 FAIL 3)",
      "n": 3,
      "p1": 3,
      "sentences": [
        "전문가 4명이 FAIL 로 봤으나 미토의",
        "전문가 3명이 FAIL 로 봤으나 미토의",
        "전문가 4명이 FAIL 로 봤으나 미토의"
      ]
    },
    {
      "ack": {
        "at": 1793434108,
        "by": "tester@example.test",
        "reason": "품질 기준 밖 1항은 표본이 작아서다",
        "state": "valid"
      },
      "acked": true,
      "basis_hash": "d911a58df3bb",
      "basis_n": 1,
      "blocking": true,
      "item": "quality",
      "label": "검토 품질 기준 밖 1항",
      "n": 1,
      "out_of_bounds": [],
      "strong_ratio_cells": 0.6429
    },
    {
      "acked": false,
      "basis_hash": "aa7507972784",
      "basis_n": 1,
      "blocking": false,
      "item": "no_cards",
      "label": "카드 0장 1명",
      "n": 1
    },
    {
      "acked": false,
      "basis_hash": "01aa2c1f3cba",
      "basis_n": 1,
      "blocking": false,
      "domains": [
        "sim"
      ],
      "item": "depth_no_cards",
      "label": "카드 없는 영역 — 역할 판단만 · sim",
      "mixed": {},
      "n": 1
    },
    {
      "acked": false,
      "basis_hash": "9897a5657f9b",
      "basis_n": 0,
      "blocking": false,
      "item": "cross_not_run",
      "label": "2차 영향 미실행(넘김 0건 표만)",
      "n": 0,
      "pairs": 0
    },
    {
      "acked": false,
      "basis_hash": "8df4c986a5ff",
      "basis_n": 0,
      "blocking": false,
      "item": "mech_not_run",
      "label": "결손 사냥 미실행",
      "n": 0
    }
  ],
  "raised": false,
  "regressed": true,
  "roster_size": 6,
  "status_counts": {
    "failed": 0,
    "na_irrelevant": 0,
    "no_input": 0,
    "pending": 1,
    "reviewed": 28,
    "running": 0,
    "skipped": 1
  },
  "target_key": "diff:220d3f493372488c978fefa91334eb1e",
  "unseated_n": 1,
  "acks": [
    {
      "item": "issues_untried",
      "ack_at": 1793434084,
      "ack_by": "tester@example.test",
      "ack_reason": "남은 넷은 다음 리비전 심사에서 패널로 본다",
      "basis_n": 3,
      "basis_hash": "9348bcb41e74",
      "revoked_by": "tester@example.test",
      "revoked_at": 1793434089,
      "state": "revoked"
    },
    {
      "item": "quality",
      "ack_at": 1793434108,
      "ack_by": "tester@example.test",
      "ack_reason": "품질 기준 밖 1항은 표본이 작아서다",
      "basis_n": 1,
      "basis_hash": "d911a58df3bb",
      "revoked_by": null,
      "revoked_at": null,
      "state": "valid"
    }
  ]
});

/**
 * 쟁점 목록 — 끝난 쟁점(상향 · 닻 원자 없어 판정 못 함)과 상한 밖 쟁점(행은 셋만, 10-31 risk-flow 하네스 응답). outcome_json 은
 * 원장 값 그대로다 — 그 전 서버는 늘 null 을 실었다(routes._issue_row_out 의 `_loads(…, None)`).
 */
export const issueList = sample<IssueList>()({
  "target_key": "diff:c9ab40e90bbb423fbda517858a65ed20",
  "total": 5,
  "limit": 100,
  "offset": 0,
  "ledger_rev": "eb3978db71d7ecbb",
  "cap": {
    "base": 2,
    "hard": 2,
    "run": 2
  },
  "rows": [
    {
      "issue_id": "iss-2a94004f3767",
      "rank": 1,
      "types": [
        "held_fail"
      ],
      "p_class": "P1",
      "priority": 3.36,
      "anchor_cluster_key": "34e330c1bddc",
      "unit_id": "u-911b94d08006",
      "state": "resolved",
      "state_reason": null,
      "outcome": "escalated",
      "outcome_json": {
        "atom_finding_ids": [
          "172a0bf9fcef43d89419beaa391d1c22#F1"
        ],
        "contest_note": "",
        "grade_after": "경험칙",
        "judgement_after": "FAIL",
        "panel_id": "172a0bf9fcef43d89419beaa391d1c22",
        "severity_after": "치명"
      },
      "distribution": {
        "raisers": 4,
        "raisers_by_domain": {
          "mech": 2,
          "xd": 2
        },
        "by_judgement_claimed": {
          "FAIL": 4
        },
        "by_severity": {
          "중대": 4
        },
        "opposers": 0
      },
      "panel_id": "172a0bf9fcef43d89419beaa391d1c22",
      "seats": [
        {
          "key": "mech-test-seal",
          "domain": "mech",
          "issue_role": "raiser"
        },
        {
          "key": "xd-syn-0",
          "domain": "xd",
          "issue_role": "raiser"
        },
        {
          "key": "sim-syn-0",
          "domain": "sim",
          "issue_role": "adjacent"
        },
        {
          "key": "sim-syn-1",
          "domain": "sim",
          "issue_role": "adjacent"
        }
      ],
      "selected_round": 1,
      "attempts": 1,
      "charged": 0,
      "reargue": null
    },
    {
      "issue_id": "iss-b82ef4ca0007",
      "rank": 2,
      "types": [
        "held_fail"
      ],
      "p_class": "P1",
      "priority": 3.36,
      "anchor_cluster_key": "61aa2e165c3c",
      "unit_id": "u-c6d4d4298036",
      "state": "inconclusive",
      "state_reason": "no_matching_atom",
      "outcome": "undetermined",
      "outcome_json": {
        "atom_finding_ids": [],
        "contest_note": "",
        "grade_after": null,
        "judgement_after": null,
        "panel_id": "63ffa587c2594f009685dfafc9339560",
        "severity_after": null
      },
      "distribution": {
        "raisers": 4,
        "raisers_by_domain": {
          "mech": 2,
          "xd": 2
        },
        "by_judgement_claimed": {
          "FAIL": 4
        },
        "by_severity": {
          "중대": 4
        },
        "opposers": 0
      },
      "panel_id": "63ffa587c2594f009685dfafc9339560",
      "seats": [
        {
          "key": "mech-test-seal",
          "domain": "mech",
          "issue_role": "raiser"
        },
        {
          "key": "xd-syn-0",
          "domain": "xd",
          "issue_role": "raiser"
        },
        {
          "key": "sim-syn-0",
          "domain": "sim",
          "issue_role": "adjacent"
        },
        {
          "key": "sim-syn-1",
          "domain": "sim",
          "issue_role": "adjacent"
        }
      ],
      "selected_round": 1,
      "attempts": 1,
      "charged": 0,
      "reargue": null
    },
    {
      "issue_id": "iss-17052ec6e667",
      "rank": 4,
      "types": [
        "held_fail"
      ],
      "p_class": "P1",
      "priority": 3.36,
      "anchor_cluster_key": "da7a96e22979",
      "unit_id": "u-c15fc1038497",
      "state": "untried_cap",
      "state_reason": "cap",
      "outcome": null,
      "outcome_json": null,
      "distribution": {
        "raisers": 4,
        "raisers_by_domain": {
          "mech": 2,
          "xd": 2
        },
        "by_judgement_claimed": {
          "FAIL": 4
        },
        "by_severity": {
          "중대": 4
        },
        "opposers": 0
      },
      "panel_id": null,
      "seats": [],
      "selected_round": 1,
      "attempts": 0,
      "charged": 0,
      "reargue": null
    }
  ]
});

/**
 * 다시 토의 표기가 선 쟁점 행 둘 — 근거가 바뀌어 선 표기(issues._reraise — 칸이 다 있다)와, 사람이 다시 올린 쟁점의 새 패널이
 * 판정 못 함을 낸 표기(issues._keep_verdict — 10-31 risk-flow 전에 선 행은 label · new_panel_failed 뿐, 뒤에는 at · round 도 선다 —
 * issueRepanelFailedRow). 뒤의 꼴을 누르면 화면 전체가 백지였다(raisers_added.length).
 */
export const issueReargueRows = sample<IssueRow[]>()([
  {
    "issue_id": "iss-3e52cbc31f8e",
    "rank": 1,
    "types": [
      "held_fail"
    ],
    "p_class": "P1",
    "priority": 4.032,
    "anchor_cluster_key": "34e330c1bddc",
    "unit_id": "u-911b94d08006",
    "state": "resolved",
    "state_reason": null,
    "outcome": "escalated",
    "outcome_json": null,
    "distribution": {
      "raisers": 2,
      "raisers_by_domain": {
        "mech": 2
      },
      "by_judgement_claimed": {
        "FAIL": 2
      },
      "by_severity": {
        "중대": 2
      },
      "opposers": 2
    },
    "panel_id": "2ccc63fe4b5f401f9b304426a6ce68b9",
    "seats": [
      {
        "key": "mech-test-seal",
        "domain": "mech",
        "issue_role": "raiser"
      },
      {
        "key": "mech-syn-0",
        "domain": "mech",
        "issue_role": "raiser"
      },
      {
        "key": "xd-syn-0",
        "domain": "xd",
        "issue_role": "opposer"
      },
      {
        "key": "xd-syn-1",
        "domain": "xd",
        "issue_role": "opposer"
      }
    ],
    "selected_round": 1,
    "attempts": 1,
    "charged": 0,
    "reargue": {
      "label": "패널 판정 — 근거 바뀜, 다시 토의 필요",
      "at": 1793437945,
      "basis_hash": "0b8613ac135b61e8",
      "claimed_after": {
        "critical_experts": 0,
        "fail_experts": 1,
        "judgement": "FAIL",
        "sev3": 2,
        "severity": "중대",
        "verified_fail_experts": 1
      },
      "claimed_before": {
        "critical_experts": 0,
        "fail_experts": 2,
        "judgement": "FAIL",
        "sev3": 2,
        "severity": "중대",
        "verified_fail_experts": 2
      },
      "opposers_added": [
        "mech-syn-0"
      ],
      "opposers_removed": [],
      "panel_basis_hash": "b280a3550b18ed0c",
      "raisers_added": [],
      "raisers_removed": [
        "mech-syn-0"
      ],
      "round": 1
    }
  },
  {
    "issue_id": "iss-5d1f8db2af1f",
    "rank": 1,
    "types": [
      "held_fail"
    ],
    "p_class": "P1",
    "priority": 4.032,
    "anchor_cluster_key": "34e330c1bddc",
    "unit_id": "u-911b94d08006",
    "state": "resolved",
    "state_reason": null,
    "outcome": "escalated",
    "outcome_json": null,
    "distribution": {
      "raisers": 2,
      "raisers_by_domain": {
        "mech": 2
      },
      "by_judgement_claimed": {
        "FAIL": 2
      },
      "by_severity": {
        "중대": 2
      },
      "opposers": 2
    },
    "panel_id": "4602acf204094fa7877999fac5d0fc93",
    "seats": [
      {
        "key": "mech-test-seal",
        "domain": "mech",
        "issue_role": "raiser"
      },
      {
        "key": "mech-syn-0",
        "domain": "mech",
        "issue_role": "raiser"
      },
      {
        "key": "xd-syn-0",
        "domain": "xd",
        "issue_role": "opposer"
      },
      {
        "key": "xd-syn-1",
        "domain": "xd",
        "issue_role": "opposer"
      }
    ],
    "selected_round": 1,
    "attempts": 2,
    "charged": 0,
    "reargue": {
      "label": "패널 판정 — 근거 바뀜, 다시 토의 필요(새 패널 결정 못 함)",
      "new_panel_failed": {
        "at": 1793437946,
        "panel_id": "4602acf204094fa7877999fac5d0fc93",
        "reason": "no_decision"
      }
    }
  }
]);

/** 등록부(attention=A,B) — 쟁점 패널이 덮은 행(before_issue)과 보통 행 둘(목록 칸은 앞 셋만). */
export const registryAB = sample<Registry>()({
  "target_key": "diff:220d3f493372488c978fefa91334eb1e",
  "rows": [
    {
      "target_key": "diff:220d3f493372488c978fefa91334eb1e",
      "cluster_key": "34e330c1bddc",
      "owner_sub": "tester@example.test",
      "visibility": "private",
      "support": 3,
      "contested": 0,
      "direction": "risk",
      "mechanism": "interface",
      "mechanism_detail": "clearance",
      "change_kind": "topology",
      "subject_key": "ck:9d294273f47d|ck:aa041b8c5f55",
      "severity": "치명",
      "sev3": 3,
      "judgement": "FAIL",
      "evidence_grade": "경험칙",
      "precedent": "none",
      "weak_subject": 0,
      "priority": 3.6,
      "status": "open",
      "verified_by_json": null,
      "stale_json": null,
      "superseded_by": null,
      "ra_entity_id": null,
      "updated_at": 1793433833,
      "support_experts": 3,
      "support_domains": 2,
      "support_units": 1,
      "support_verified": 3,
      "attention": "A",
      "issue_id": "iss-4232cfa0e43d",
      "issue_state": "escalated",
      "merged": {
        "before_issue": {
          "claimed": {
            "critical_experts": 0,
            "fail_experts": 3,
            "judgement": "FAIL",
            "sev3": 2,
            "severity": "중대",
            "verified_fail_experts": 3
          },
          "distribution": {
            "by_judgement_claimed": {
              "FAIL": 3
            },
            "by_severity": {
              "중대": 3
            },
            "raisers_by_domain": {
              "mech": 2,
              "xd": 1
            }
          },
          "evidence_grade": "경험칙",
          "judgement": "WARNING",
          "sev3": 2,
          "severity": "중대",
          "support_domains": 2,
          "support_experts": 3,
          "support_units": 1,
          "support_verified": 3
        },
        "cites": [
          {
            "quote": "정적 접착 실링 부위의 **유효 접착폭**은 최악 공차 누적에서도 0.8",
            "ref": "card:DOC-CCT-MECH-2026-0000000101"
          },
          {
            "quote": "",
            "ref": "c:4ff9b96c5122"
          }
        ],
        "claim": "카드의 조건과 변경 줄을 맞대어 보니 판정이 이렇다",
        "claim_finding_id": "8ccec9a8b7fb8cd306c0320381880365#F9868488538052",
        "claimed": {
          "critical_experts": 0,
          "fail_experts": 3,
          "judgement": "FAIL",
          "sev3": 2,
          "severity": "중대",
          "verified_fail_experts": 3
        },
        "cluster_key": "34e330c1bddc",
        "contest_notes": [],
        "direction": "risk",
        "distribution": {
          "by_judgement_claimed": {
            "FAIL": 3
          },
          "by_severity": {
            "중대": 3
          },
          "raisers_by_domain": {
            "mech": 2,
            "xd": 1
          }
        },
        "domains": [
          "mech",
          "xd"
        ],
        "human_refs": [],
        "member_ids": [
          "8ccec9a8b7fb8cd306c0320381880365#F9868488538052",
          "9fef43501ab56d910acae9f7ff483684#F9868488538052",
          "fa9d8b895fcd9bfd480bb45488012922#F9868488538052"
        ],
        "names": [],
        "owner_domain": "mech",
        "panels": [],
        "precedent_counts": {
          "none": 3
        },
        "raised_by": [
          "mech-syn-0",
          "mech-test-seal",
          "xd-syn-0"
        ],
        "rejected_refs": [],
        "resolving_checks": [
          "test:시험으로 확인한다"
        ],
        "severity_counts": {
          "중대": 3
        },
        "stored_cluster_key": "34e330c1bddc",
        "trigger_condition": "none",
        "unit_ids": [
          "u-911b94d08006"
        ],
        "w_det": 2.0,
        "warrant": "근거 카드 [card:DOC-CCT-MECH-2026-0000000101] «정적 접착 실링 부위의 **유효 접착폭**은 최악 공차 누적에서도 0.8»"
      }
    },
    {
      "target_key": "diff:220d3f493372488c978fefa91334eb1e",
      "cluster_key": "4734035336e0",
      "owner_sub": "tester@example.test",
      "visibility": "private",
      "support": 6,
      "contested": 0,
      "direction": "risk",
      "mechanism": "process",
      "mechanism_detail": "unclassified",
      "change_kind": "topology",
      "subject_key": "ck:76e9d99d77e1|ck:f639342bc16f",
      "severity": "중대",
      "sev3": 2,
      "judgement": "WARNING",
      "evidence_grade": "경험칙",
      "precedent": "none",
      "weak_subject": 0,
      "priority": 2.4,
      "status": "open",
      "verified_by_json": null,
      "stale_json": null,
      "superseded_by": null,
      "ra_entity_id": null,
      "updated_at": 1793433833,
      "support_experts": 6,
      "support_domains": 3,
      "support_units": 1,
      "support_verified": 6,
      "attention": "B",
      "issue_id": null,
      "issue_state": null,
      "merged": {
        "cites": [
          {
            "quote": "",
            "ref": "c:560518043b4c"
          }
        ],
        "claim": "카드 밖 위험 1",
        "claim_finding_id": "6db1a2d14c62f471a9eb09656a6886bd#F40982427986694",
        "claimed": {
          "critical_experts": 0,
          "fail_experts": 0,
          "judgement": "WARNING",
          "sev3": 2,
          "severity": "중대",
          "verified_fail_experts": 0
        },
        "cluster_key": "4734035336e0",
        "contest_notes": [],
        "direction": "risk",
        "distribution": {
          "by_judgement_claimed": {
            "WARNING": 6
          },
          "by_severity": {
            "중대": 6
          },
          "raisers_by_domain": {
            "mech": 2,
            "sim": 2,
            "xd": 2
          }
        },
        "domains": [
          "xd",
          "mech",
          "sim"
        ],
        "human_refs": [],
        "member_ids": [
          "6db1a2d14c62f471a9eb09656a6886bd#F40982427986694",
          "8ccec9a8b7fb8cd306c0320381880365#F40982427986694",
          "9d4e7d6b62456648d6fbb9d5a11ef477#F40982427986694"
        ],
        "names": [],
        "owner_domain": "xd",
        "panels": [],
        "precedent_counts": {
          "none": 6
        },
        "raised_by": [
          "mech-syn-0",
          "mech-test-seal",
          "sim-syn-0"
        ],
        "rejected_refs": [],
        "resolving_checks": [
          "test:고온 고습 시험으로 박리를 본다"
        ],
        "severity_counts": {
          "중대": 6
        },
        "stored_cluster_key": "4734035336e0",
        "trigger_condition": "none",
        "unit_ids": [
          "u-d9cee7dd6041"
        ],
        "w_det": 2.0,
        "warrant": "변경 줄의 계면"
      }
    }
  ],
  "truncated": false,
  "total": 2,
  "ledger_rev": "c62fb6f1cbc6e91f",
  "verdict_candidate": {
    "verdict": "no-go",
    "counts": {
      "clusters": 16,
      "FAIL": 2,
      "WARNING": 14,
      "OK": 0,
      "undetermined": 0
    },
    "reasons": [
      "미기각 FAIL 클러스터 1건"
    ]
  },
  "verdict_final": null
});

/** 종합 보고서 본문 첫 쪽(md). */
export const reportSummaryPage = sample<SynthReportPage>()({
  "target_key": "diff:220d3f493372488c978fefa91334eb1e",
  "version": 6,
  "report_uid": "rp-0b42377dac0c1493",
  "title": "리스크 심사 보고서 v6 [C2(열린 셀 1 · 쟁점 진행 1건 · 깊이 미달 xd 1/2 · 후속 낡음(재검토 1셀) · 재개방 1셀 · 사람 넘김 1셀 · 미토의 쟁점 3건(주장 FAIL 3) · 검토 품질 기준 밖 1항 · 카드 0장 1명 · 카드 없는 영역 — 역할 판단만 · sim · 2차 영향 미실행(넘김 0건 표만) · 결손 사냥 미실행)] — diff:220d3f493372488c978fefa91334eb1e",
  "level_label": "C2(열린 셀 1 · 쟁점 진행 1건 · 깊이 미달 xd 1/2 · 후속 낡음(재검토 1셀) · 재개방 1셀 · 사람 넘김 1셀 · 미토의 쟁점 3건(주장 FAIL 3) · 검토 품질 기준 밖 1항 · 카드 0장 1명 · 카드 없는 영역 — 역할 판단만 · sim · 2차 영향 미실행(넘김 0건 표만) · 결손 사냥 미실행)",
  "narrative_state": "full",
  "trigger": "ack",
  "counts": {
    "cells": {
      "actual": 30,
      "by_state": {
        "failed": 0,
        "na_irrelevant": 0,
        "no_input": 0,
        "pending": 1,
        "reviewed": 28,
        "running": 0,
        "skipped": 1
      },
      "expected": 30,
      "reviewed_by_basis": {
        "background": 5,
        "cards": 18,
        "filtered": 0,
        "noinput": 0,
        "role_only": 5,
        "search_only": 0
      },
      "verdict_gaps": 0
    },
    "experts": {
      "active_by_domain": {
        "mech": 2,
        "sim": 2,
        "xd": 2
      },
      "carded_by_domain": {
        "mech": 2,
        "xd": 2
      },
      "cardless_mixed": {},
      "filtered_only": 0,
      "have_by_domain": {
        "mech": 2,
        "xd": 1
      },
      "input_gap": 0,
      "input_gap_keys": [],
      "no_card_domains": [
        "sim"
      ],
      "reports": {
        "blocked": 0,
        "expected": 6,
        "missing": 0,
        "partial": 0,
        "ready": 5
      },
      "reviewed_cards": 3
    },
    "failed": {
      "by_code": {},
      "open": 0
    },
    "filter": {
      "audit": {
        "failed": 0,
        "floor_met": true,
        "kept": 0,
        "n_audit": 0,
        "pending": 0,
        "relevance_miss": 0,
        "risk_miss": 0,
        "sampled": 0,
        "undetermined": 0,
        "upper95": null,
        "upper95_conservative": null
      },
      "by_domain": {},
      "n": 0,
      "off": false,
      "shadow": {
        "risk_miss": 0,
        "sampled": 0,
        "upper95": null,
        "would_filter": 0
      },
      "widened": [],
      "would_filter": 0
    },
    "handoffs": {
      "lines": 0,
      "pairs": 0
    },
    "invariants": [],
    "issues": {
      "by_outcome": {
        "escalated": 1,
        "undetermined": 1
      },
      "by_state": {
        "inconclusive": 1,
        "queued": 1,
        "resolved": 1,
        "untried_cap": 2
      },
      "cap": {
        "base": 2,
        "hard": 2
      },
      "held_fail": {
        "selected": 5,
        "untried": 3
      },
      "open": 1,
      "p1": {
        "open": 1,
        "run": 2,
        "selected": 5,
        "untried": 3
      }
    },
    "mechanisms_reported": {
      "codes": 0,
      "free": 0
    },
    "no_input": {
      "by_outcome": {
        "impact": 0,
        "none": 0,
        "request": 0,
        "unknown": 0
      },
      "cells": 0,
      "experts": 0
    },
    "quality": {
      "out_of_bounds": [],
      "strong_ratio_cells": 0.6429
    },
    "registry": {
      "attention": {
        "A": 6,
        "B": 10,
        "C": 0,
        "D": 0
      },
      "card_fail_claimed": 5,
      "clusters": 16
    },
    "roster": 6,
    "skipped": {
      "by_note": [
        {
          "by": "tester@example.test",
          "n": 1,
          "note": "이 단위는 다음 리비전에서 다시 본다"
        }
      ],
      "experts": 1,
      "n": 1
    },
    "units": {
      "excluded_by_reason": {
        "incomparable_same": 5,
        "not_design_relevant": 2,
        "null_one_side": 6
      },
      "reviewable": 5,
      "unassigned": 0
    }
  },
  "created_at": 1793434108,
  "format": "md",
  "part": "summary",
  "pages_total": 4,
  "page_no": 1,
  "page": {
    "page_no": 1,
    "kind": "synthesis_report",
    "title": "리스크 심사 보고서 v6 [C2(열린 셀 1 · 쟁점 진행 1건 · 깊이 미달 xd 1/2 · 후속 낡음(재검토 1셀) · 재개방 1셀 · 사람 넘김 1셀 · 미토의 쟁점 3건(주장 FAIL 3) · 검토 품질 기준 밖 1항 · 카드 0장 1명 · 카드 없는 영역 — 역할 판단만 · sim · 2차 영향 미실행(넘김 0건 표만) · 결손 사냥 미실행)] — diff:220d3f493372488c978fefa91334eb1e — 쪽 1/4",
    "blocks": {
      "background": [
        "# 리스크 심사 보고서 v6 [C2(열린 셀 1 · 쟁점 진행 1건 · 깊이 미달 xd 1/2 · 후속 낡음(재검토 1셀) · 재개방 1셀 · 사람 넘김 1셀 · 미토의 쟁점 3건(주장 FAIL 3) · 검토 품질 기준 밖 1항 · 카드 0장 1명 · 카드 없는 영역 — 역할 판단만 · sim · 2차 영향 미실행(넘김 0건 표만) · 결손 사냥 미실행)] — diff:220d3f493372488c978fefa91334eb1e",
        "- 완결: C2(열린 셀 1 · 쟁점 진행 1건 · 깊이 미달 xd 1/2 · 후속 낡음(재검토 1셀) · 재개방 1셀 · 사람 넘김 1셀 · 미토의 쟁점 3건(주장 FAIL 3) · 검토 품질 기준 밖 1항 · 카드 0장 1명 · 카드 없는 영역 — 역할 판단만 · sim · 2차 영향 미실행(넘김 0건 표만) · 결손 사냥 미실행)",
        "- 잔여 사람 넘김 1셀 · 막음",
        "- 잔여 미토의 쟁점 3건(주장 FAIL 3) · 막음",
        "- 잔여 검토 품질 기준 밖 1항 · 막음 · 확인됨",
        "- 잔여 카드 0장 1명 · 표기",
        "- 잔여 카드 없는 영역 — 역할 판단만 · sim · 표기",
        "- 잔여 2차 영향 미실행(넘김 0건 표만) · 표기",
        "- 잔여 결손 사냥 미실행 · 표기",
        "- 수: 전문가 6 · 검토 대상 단위 5 · 셀 30/30(failed 0 · na_irrelevant 0 · no_input 0 · pending 1 · reviewed 28 · running 0 · skipped 1)",
        "- 전문가 보고서: 기대 6 · ready 5 · partial 0 · blocked 0 · 누락 0",
        "**마감 범위 미완 — 열린 셀 1**"
      ],
      "results": [],
      "recommendation": [],
      "minutes": []
    }
  },
  "next_page": 2
});

/** 셀 목록 — 검토한 셀 · 사람이 넘긴 셀 · 사람이 다시 연 셀. */
export const cellRows = sample<CellList>()({
  "target_key": "diff:220d3f493372488c978fefa91334eb1e",
  "total": 3,
  "limit": 30,
  "offset": 0,
  "rows": [
    {
      "target_key": "diff:220d3f493372488c978fefa91334eb1e",
      "unit_id": "u-911b94d08006",
      "agent_key": "mech-test-seal",
      "owner_sub": "tester@example.test",
      "domain": "mech",
      "unit_seq": 1,
      "state": "reviewed",
      "route": "review",
      "route_forced": "rank1",
      "basis": "cards",
      "run_id": "84aaa3b04e5f42dd87dd1bfc1905d49e",
      "heartbeat_at": null,
      "priority": 0,
      "tries": 5,
      "charged": 0,
      "infra_streak": 0,
      "not_before": null,
      "error_code": null,
      "error_class": null,
      "error": null,
      "knob": null,
      "credential_kind": "owner",
      "model": "fake-glm",
      "llm_calls": 5,
      "tokens_in": 5000,
      "tokens_out": 500,
      "elapsed_ms": 13,
      "truncated": 0,
      "rows_expected": 17,
      "rows_missing": 0,
      "stamp": 0,
      "soft_over": 0,
      "cards_expected": 6,
      "cards_judged": 6,
      "n_fail": 1,
      "n_warning": 1,
      "n_ok": 4,
      "n_na": 0,
      "n_undetermined": 0,
      "n_disputed": 0,
      "n_flipped": 0,
      "n_offcard": 1,
      "offcard_state": "done",
      "offcard_capped": 0,
      "quote_ok": 6,
      "quote_n": 6,
      "refs_ok": 6,
      "refs_n": 6,
      "bg_full_n": 4,
      "bg_title_only_n": 0,
      "unit_hash": "70fd7d61b5fe891e",
      "pack_hash": "6f424ef9db8b9a01ff311647544e62d2a4ad652fcde854cb2a8697868cbe6441",
      "input_hash": "f98bb3cc2829b185",
      "prompt_rev": "offcard=cr-offcard-2,sweep=cr-sweep-2,verdict=cr-verdict-2",
      "verify_rev": "verify-1",
      "status_source": "code",
      "decided_by": null,
      "decided_at": null,
      "decide_note": null,
      "reopened_n": 0,
      "started_at": 1793433893,
      "finished_at": 1793433893,
      "created_at": 1793433832,
      "updated_at": 1793433893,
      "filter_reason": null
    },
    {
      "target_key": "diff:220d3f493372488c978fefa91334eb1e",
      "unit_id": "u-911b94d08006",
      "agent_key": "xd-syn-1",
      "owner_sub": "tester@example.test",
      "domain": "xd",
      "unit_seq": 1,
      "state": "skipped",
      "route": "review",
      "route_forced": "tier_a_pending",
      "basis": null,
      "run_id": "7376fbf2e2ec421fb27f919a5ba13afb",
      "heartbeat_at": null,
      "priority": 0,
      "tries": 2,
      "charged": 2,
      "infra_streak": 0,
      "not_before": null,
      "error_code": "no_rows",
      "error_class": "content",
      "error": "no_rows: 판정 행이 하나도 없다(가짜)",
      "knob": null,
      "credential_kind": null,
      "model": null,
      "llm_calls": 0,
      "tokens_in": 0,
      "tokens_out": 0,
      "elapsed_ms": 14,
      "truncated": null,
      "rows_expected": null,
      "rows_missing": null,
      "stamp": 0,
      "soft_over": 0,
      "cards_expected": null,
      "cards_judged": null,
      "n_fail": 0,
      "n_warning": 0,
      "n_ok": 0,
      "n_na": 0,
      "n_undetermined": 0,
      "n_disputed": 0,
      "n_flipped": 0,
      "n_offcard": 0,
      "offcard_state": "todo",
      "offcard_capped": 0,
      "quote_ok": 0,
      "quote_n": 0,
      "refs_ok": 0,
      "refs_n": 0,
      "bg_full_n": 0,
      "bg_title_only_n": 0,
      "unit_hash": "70fd7d61b5fe891e",
      "pack_hash": "88ba3d9180c93f4660646fe61b3197d2028372ac6f6b9f1ae4849424c680526b",
      "input_hash": "7fcfd24a7fb17fa6",
      "prompt_rev": "offcard=cr-offcard-2,sweep=cr-sweep-2,verdict=cr-verdict-2",
      "verify_rev": "verify-1",
      "status_source": "human",
      "decided_by": "tester@example.test",
      "decided_at": 1793433964,
      "decide_note": "이 단위는 다음 리비전에서 다시 본다",
      "reopened_n": 0,
      "started_at": 1793433954,
      "finished_at": 1793434015,
      "created_at": 1793433832,
      "updated_at": 1793433964,
      "filter_reason": null
    },
    {
      "target_key": "diff:220d3f493372488c978fefa91334eb1e",
      "unit_id": "u-9fd76670057f",
      "agent_key": "xd-syn-1",
      "owner_sub": "tester@example.test",
      "domain": "xd",
      "unit_seq": 2,
      "state": "pending",
      "route": null,
      "route_forced": "human_retry",
      "basis": null,
      "run_id": "84aaa3b04e5f42dd87dd1bfc1905d49e",
      "heartbeat_at": null,
      "priority": 0,
      "tries": 0,
      "charged": 0,
      "infra_streak": 0,
      "not_before": null,
      "error_code": null,
      "error_class": null,
      "error": null,
      "knob": null,
      "credential_kind": null,
      "model": null,
      "llm_calls": 0,
      "tokens_in": null,
      "tokens_out": null,
      "elapsed_ms": null,
      "truncated": null,
      "rows_expected": null,
      "rows_missing": null,
      "stamp": 0,
      "soft_over": 0,
      "cards_expected": null,
      "cards_judged": null,
      "n_fail": 0,
      "n_warning": 0,
      "n_ok": 0,
      "n_na": 0,
      "n_undetermined": 0,
      "n_disputed": 0,
      "n_flipped": 0,
      "n_offcard": 0,
      "offcard_state": "todo",
      "offcard_capped": 0,
      "quote_ok": 0,
      "quote_n": 0,
      "refs_ok": 0,
      "refs_n": 0,
      "bg_full_n": 0,
      "bg_title_only_n": 0,
      "unit_hash": "e35bcf4679ea16fe",
      "pack_hash": "88ba3d9180c93f4660646fe61b3197d2028372ac6f6b9f1ae4849424c680526b",
      "input_hash": null,
      "prompt_rev": "offcard=cr-offcard-2,sweep=cr-sweep-2,verdict=cr-verdict-2",
      "verify_rev": "verify-1",
      "status_source": "human",
      "decided_by": "tester@example.test",
      "decided_at": 1793433979,
      "decide_note": null,
      "reopened_n": 1,
      "started_at": 1793433954,
      "finished_at": null,
      "created_at": 1793433832,
      "updated_at": 1793433979,
      "filter_reason": null
    }
  ]
});

/** 살아 있는 잡에 얹은 force 다시 — 그 셀 몫으로 잡이 consent_extra 로 멈췄다(job.hold). */
export const retryAdopted = sample<CellsDisposed>()({
  "target_key": "diff:46a774d6d3fd463f9750b66704c2357b",
  "matched": 1,
  "retried": 1,
  "not_failed": 0,
  "keys_total": 1,
  "keys": [
    [
      "u-c15fc1038497",
      "xd-syn-1"
    ]
  ],
  "experts": 1,
  "changed": true,
  "job": {
    "action": "adopted",
    "job_id": "24aa4b0cfde648c88587016781ad72df",
    "adopted": 1,
    "waiting": 0,
    "hold": "consent_extra"
  },
  "audit_id": "98e5660aa5de458eb0759d08ed0c1fc5"
});

/**
 * 과제 상세(GET /projects/{id})의 스냅샷 머리 둘 — `degraded` 는 bool 이 아니라 호환 열 그대로(degraded_json 의 첫 code | null)다.
 * 스크래치 백엔드에서 강등 표지가 있는 캡처 · 없는 캡처를 동결해 받았다.
 */
export const projectSnapshotHeaders = sample<SnapshotHeader[]>()([
  {
    "id": "c1364a995ffe44869a48603efd1230e6",
    "ir_version": "1.0",
    "ir_hash": "354c78c47bdf9c38ab5de19870547a672a1b249e31ada63dce4819921f5b7743",
    "kinds_json": "[\"mcad\"]",
    "node_count": 5,
    "edge_count": 3,
    "warnings_n": 0,
    "degraded": null,
    "created_at": 1756600100
  },
  {
    "id": "04bd0b27d59d48cb934146c7536bcc2c",
    "ir_version": "1.0",
    "ir_hash": "119c457224649ab2e98ff8dc95ad2b1eb77148371387ff7611ac987d52793249",
    "kinds_json": "[\"mcad\",\"dyna\"]",
    "node_count": 7,
    "edge_count": 4,
    "warnings_n": 0,
    "degraded": "mcp_degraded",
    "created_at": 1756600000
  }
]);

/** 사람이 다시 올린 결과 쟁점의 새 패널이 결정을 못 낸 행(issues._keep_verdict) — 10-31 risk-flow 뒤의 꼴(label · new_panel_failed ·
 * at · round, 근거가 바뀐 표기와 같은 at · round 다). */
export const issueRepanelFailedRow = sample<IssueRow>()({
  "issue_id": "iss-2a94004f3767",
  "rank": 1,
  "types": [
    "held_fail"
  ],
  "p_class": "P1",
  "priority": 3.36,
  "anchor_cluster_key": "34e330c1bddc",
  "unit_id": "u-911b94d08006",
  "state": "resolved",
  "state_reason": null,
  "outcome": "escalated",
  "outcome_json": {
    "atom_finding_ids": [
      "172a0bf9fcef43d89419beaa391d1c22#F1"
    ],
    "contest_note": "",
    "grade_after": "경험칙",
    "judgement_after": "FAIL",
    "panel_id": "172a0bf9fcef43d89419beaa391d1c22",
    "severity_after": "치명"
  },
  "distribution": {
    "raisers": 4,
    "raisers_by_domain": {
      "mech": 2,
      "xd": 2
    },
    "by_judgement_claimed": {
      "FAIL": 4
    },
    "by_severity": {
      "중대": 4
    },
    "opposers": 0
  },
  "panel_id": "5050d76762f64e3795c77322def2cda8",
  "seats": [
    {
      "key": "mech-test-seal",
      "domain": "mech",
      "issue_role": "raiser"
    },
    {
      "key": "xd-syn-0",
      "domain": "xd",
      "issue_role": "raiser"
    },
    {
      "key": "sim-syn-0",
      "domain": "sim",
      "issue_role": "adjacent"
    },
    {
      "key": "sim-syn-1",
      "domain": "sim",
      "issue_role": "adjacent"
    }
  ],
  "selected_round": 1,
  "attempts": 2,
  "charged": 0,
  "reargue": {
    "label": "패널 판정 — 근거 바뀜, 다시 토의 필요(새 패널 결정 못 함)",
    "at": 1793442339,
    "new_panel_failed": {
      "at": 1793442339,
      "panel_id": "5050d76762f64e3795c77322def2cda8",
      "reason": "no_decision"
    },
    "round": 1
  }
});

/** 패널 대상 진행판 — Claude 패널 잡이 외부 응답자 워커가 없어 멈췄다(pause_reason 없음 · hold_code external_worker — 10-31 risk-flow 에
 * 생긴 두 칸). */
export const coveragePanelHeld = sample<Coverage>()({
  "target_key": "t1",
  "job": {
    "id": "f8befdcb27b34fc882d2a798f66ce36e",
    "tier": "A",
    "state": "paused",
    "pause_reason": null,
    "hold_code": "external_worker",
    "hold_until": null,
    "panels_done": 0,
    "panels_total": 1,
    "error": "chair_failed: 의장 실패 — 외부 응답자가 없다 — 설정 EXTERNAL_LLM_WAIT_S — 잡을 멈췄다(보류 external_worker · 좌석 재시도는 차감하지 않았다). 잡 주인의 Claude Code 에서 워크플로 hwax-risk-claude 를 그 사람의 PAT 로 (다시) 돌린 뒤 재개한다",
    "signal": null,
    "llm": "claude",
    "consent_external": {
      "at": 1793442339,
      "by": "peer@x",
      "source": "web"
    }
  },
  "roster_size": 7,
  "by_domain": {
    "mech": {
      "pending": 2
    },
    "pcb": {
      "pending": 1
    },
    "rel": {
      "pending": 1
    },
    "sim": {
      "pending": 2
    },
    "xd": {
      "pending": 1
    }
  },
  "by_status": {
    "abstain": 0,
    "assigned": 0,
    "carried": 0,
    "deferred": 0,
    "done": 0,
    "done_weak": 0,
    "failed": 0,
    "pending": 7,
    "running": 0,
    "skipped": 0
  },
  "strong": {
    "done": 0,
    "done_weak": 0,
    "ratio": null
  },
  "unseated_n": 7,
  "level": "C0",
  "close_level": "C2",
  "flow": "panels",
  "units": {
    "status": "none"
  },
  "review": null,
  "external_sync": {
    "ra": {
      "state": "pending",
      "pending_ops": 0,
      "dead_ops": 0,
      "reason": "credential_missing:HWAXRISK_PORTAL_PAT_RW",
      "message": "RA 반영 안 됨 — 박스에 RA 쓰기 자격(HWAXRISK_PORTAL_PAT_RW)이 없어 보내는 쪽이 꺼져 있다. 대기 0건, 보낸 것 없음.",
      "retracted": 0,
      "retract_absent": 0,
      "retract_pending": 0,
      "retract_failed": 0,
      "retract_reasons": {}
    },
    "adh": {
      "state": "pending",
      "pending_ops": 0,
      "dead_ops": 0,
      "reason": "sender_unwired",
      "message": "AIDataHub 반영 안 됨 — 보내는 쪽이 아직 배선되지 않았다(M4). 대기 0건, 보낸 것 없음."
    }
  }
});

/** `GET /me` 의 portal_pat — 웹 등록(source web)이 거절된 뒤 쉬는 중(last_error · paused_until, 10-31 risk-flow). 박스 칸은 싣지 않는다. */
export const portalPatPaused = sample<PortalPatSummary>()({
  "registered": false,
  "email": null,
  "groups": [],
  "exp": null,
  "auto": {
    "enabled": true,
    "due": false,
    "due_reason": "absent",
    "last_source": null,
    "last_at": null,
    "last_error": "web-pat_email_mismatch: PAT 의 email 이 현재 사용자와 다릅니다.",
    "last_error_kind": "final",
    "last_error_at": 1793442339,
    "paused_until": 1793463939,
    "how_to_stop": "자동 등록이 켜져 있는 동안은 등록된 PAT 를 지우거나 포털에서 폐기해도 웹 리스크 앱을 열 때나 Claude 에서 hwax_risk 도구를 부를 때 다시 만든다 — 멈추는 길은 웹 리스크 앱 설정 화면의 '자동 등록' 스위치다(끄면 화면도 게이트웨이도 저절로 받지 않는다)."
  }
});

/** 스냅샷 상태의 요구 여유(`signals["req.margin"]`)와 결측 — 동결이 요구를 대조했다(10-31 risk-flow — 위반 · 여유 · 미측정 한 줄씩). */
export const snapshotStateMargin = sample<Pick<SnapshotState, "signals" | "missing">>()({
  "signals": {
    "req.margin": {
      "derived_from": [],
      "kind": "table",
      "known": true,
      "refs": [
        "req:plate1_t",
        "req:plate2_t",
        "req:ghost_t",
        "d:plate1_t",
        "d:plate2_t",
        "d:ghost_t"
      ],
      "text": "req:plate1_t lte 1.0 mm actual=1.2 margin=-0.2 · req:plate2_t between [0.9,1.5] mm actual=1.0 margin=0.1 · req:ghost_t lte 2.0 mm actual=미측정 margin=미측정",
      "unit": null,
      "value": [
        {
          "actual": 1.2,
          "known": true,
          "limit": 1.0,
          "margin": -0.2,
          "name": "plate1_t",
          "op": "lte",
          "rel": -0.2,
          "status": "candidate",
          "unit": "mm"
        },
        {
          "actual": 1.0,
          "known": true,
          "limit": [
            0.9,
            1.5
          ],
          "margin": 0.1,
          "name": "plate2_t",
          "op": "between",
          "rel": 0.167,
          "status": "candidate",
          "unit": "mm"
        },
        {
          "actual": null,
          "known": false,
          "limit": 2.0,
          "margin": null,
          "name": "ghost_t",
          "op": "lte",
          "rel": null,
          "status": "candidate",
          "unit": "mm"
        }
      ]
    }
  },
  "missing": {
    "dyna_absent": false,
    "dyna_capture_failed": false,
    "dyna_result_absent": false,
    "ecad_absent": true,
    "ecad_capture_failed": false,
    "iface_kinds_absent": false,
    "material_density_unsourced": false,
    "mcad_absent": false,
    "mcad_capture_failed": false,
    "req_absent": false,
    "result_kind_mismatch": false,
    "scenario_uncovered": false,
    "volume_null": false,
    "world_transform_absent": false
  }
});
