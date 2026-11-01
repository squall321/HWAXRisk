// 실 백엔드(이 가지의 코드 · 스크래치 하네스)가 보낸 응답을 줄여 옮긴 견본 — tsc 가 화면 타입과 견준다(칸이 빠지거나 값 종류가 다르면 빌드가 깨진다)
import type {
  CellList,
  CellsDisposed,
  ClosureCells,
  Coverage,
  CoverageJob,
  DiffDoc,
  IssueList,
  IssueRow,
  PartKey,
  PortalPatSummary,
  ProjectDetail,
  ProjectList,
  Registry,
  SameAs,
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
/** 카드 대조 대상 진행판 — 사슬(쟁점 잡 대기) · 종합 보고서 판 · 잔여 · 끝난 검토 잡(검토 순서는 앞 둘만). 주인으로 받았다 — 웹 진행판이 싣는
 * 부른 사람의 역할(my_role, 가지 wt1101/risk-open)을 더했다. */
export const coverageCells = sample<Coverage>()({
  "target_key": "diff:220d3f493372488c978fefa91334eb1e",
  "my_role": "owner",
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
    "hold": "consent_extra",
    "signals": []
  },
  "audit_id": "98e5660aa5de458eb0759d08ed0c1fc5"
});

/**
 * 과제 상세(GET /projects/{id})의 스냅샷 머리 둘 — `degraded` 는 bool 이 아니라 호환 열 그대로(`degraded_json` 의 첫 code | null)이고,
 * `degraded_json` 은 전부다. 이름(label)은 그 스냅샷을 만든 동결 잡의 것이라 동결 잡 없이 언 손 픽스처는 null 이다. 스크래치 백엔드(가지
 * wt1031/risk-reads)에서 동결 잡으로 얼린 것(DV1)과 손 픽스처를 받았다.
 */
export const projectSnapshotHeaders = sample<SnapshotHeader[]>()([
  {
    "id": "5bff75c1afac45489edb1d979c1e28db",
    "ir_version": "1.0",
    "ir_hash": "a72492cca1ba6add7027edc23d121f65e1a2db076a6b5372effa8a5facd4d43d",
    "kinds_json": "[\"mcad\",\"ecad\"]",
    "node_count": 3,
    "edge_count": 3,
    "warnings_n": 4,
    "degraded": "app_version_unknown",
    "degraded_json": [
      "app_version_unknown",
      "ecad_absent"
    ],
    "created_at": 1793441473,
    "label": "DV1",
    "app_versions": {
      "ecad": {},
      "mcad": {
        "captured_via": null,
        "extra": null,
        "version": null
      }
    },
    "adapter_versions": {
      "ecad": "0.0-stub",
      "mcad": "1.0"
    }
  },
  {
    "id": "129d7610f7794d71af4f64b54ca5c554",
    "ir_version": "1.0",
    "ir_hash": "e54be20938709506e72c05d7d97453e76780a8778d077c17e6175d163366bfea",
    "kinds_json": "[\"mcad\",\"dyna\",\"dyna_result\"]",
    "node_count": 7,
    "edge_count": 4,
    "warnings_n": 0,
    "degraded": "no_secid",
    "degraded_json": [
      "no_secid"
    ],
    "created_at": 1756600000,
    "label": null,
    "app_versions": {
      "dyna": {},
      "dyna_result": {},
      "mcad": {}
    },
    "adapter_versions": {
      "dyna": "1.0",
      "dyna_result": "1.0",
      "mcad": "1.0"
    }
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
    "signals": [],
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

/** 패널 대상 진행판 — 보류 external_worker 로 멈춘 Claude 패널 잡을 주인이 취소한 뒤(취소가 보류 열을 비운다 — 반대 검토 10-31, 그 전에는
 * hold_code 가 남았다). */
export const coveragePanelCancelledAfterHold = sample<Coverage>()({
  "target_key": "t1",
  "job": {
    "id": "14b7390ea84a4d67a714880cf26e239f",
    "tier": "A",
    "state": "cancelled",
    "pause_reason": null,
    "hold_code": null,
    "hold_until": null,
    "panels_done": 0,
    "panels_total": 1,
    "error": null,
    "signal": null,
    "signals": [],
    "llm": "claude",
    "consent_external": {
      "at": 1793447741,
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

/** `GET /me` 의 portal_pat — 게이트웨이 교환이 실패한 뒤(Claude 에 넣은 PAT 의 청중이 모자라다). 쉬는 것은 게이트웨이 길뿐이라 웹 길은
 * 받을 까닭을 그대로 말한다(due true · paused_until null — 반대 검토 10-31). 박스 칸은 싣지 않는다. */
export const portalPatGatewayFailed = sample<PortalPatSummary>()({
  "registered": false,
  "email": null,
  "groups": [],
  "exp": null,
  "auto": {
    "enabled": true,
    "due": true,
    "due_reason": "absent",
    "last_source": null,
    "last_at": null,
    "last_error": "widen_audience: Claude 에 넣은 PAT 의 청중이 모자라다 — 포털 토큰 화면에서 모든 청중(mcp-gateway·step-forge 포함)으로 새로 발급해 Claude 에 넣는다",
    "last_error_kind": "final",
    "last_error_at": 1793447742,
    "paused_until": null,
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

/**
 * 과제 상세(GET /projects/{id}) — 편집자로 받았다(구성원이 연다 — 가지 wt1031/risk-reads). 과제 행의 메타 열(코퍼스 제외 bool · 제품 연결
 * 배열 · 수명 주기를 shipped 로 바꿔 닫은 때가 찍혔다) · 멤버 표({email, role}) · 스냅샷 머리의 이름 · 판 · 강등 표지 전부. 스크래치 백엔드에서
 * 동결 잡 둘(DV1 · DV2 — 같은 초)과 손 픽스처 하나를 얼려 받았다. 대상 표는 비었다 — 대상 머리 타입(`unseated_n` · `superseded_by`)은
 * 이 응답이 싣지 않는 칸을 요구한다(FE-7 의 남긴 것, 이 견본 밖). 부른 사람의 역할(my_role — 편집자)은 가지 wt1101/risk-open 이
 * 더한 칸이다(쓰기 단추를 가른다).
 */
export const projectDetailMember = sample<ProjectDetail>()({
  "project": {
    "id": "a3e072a3c6944e928d90a826f5907884",
    "owner_sub": "syn@example.com",
    "code": "DEMO-7",
    "name": "시연 과제",
    "stage": "DV1",
    "predecessor_project_id": null,
    "adh_team": null,
    "adh_group": null,
    "character_status": "seed",
    "created_at": 1793441473,
    "updated_at": 1793441473,
    "classification": "confidential",
    "lifecycle": "shipped",
    "closed_at": 1793441473,
    "corpus_excluded": false,
    "excluded_reason": null,
    "mcp_visibility": "private",
    "product_code": "SM-X100",
    "product_refs_json": [
      {
        "kind": "product_code",
        "value": "SM-X100"
      },
      {
        "kind": "ra_model",
        "value": "X100"
      }
    ],
    "predecessor_product_code": null,
    "status": "active"
  },
  "members": [
    {
      "email": "editor@example.com",
      "role": "editor"
    },
    {
      "email": "syn@example.com",
      "role": "owner"
    },
    {
      "email": "viewer@example.com",
      "role": "viewer"
    }
  ],
  "sources": [
    {
      "id": "d56e75c97e92463d9fc2c94fa88b35de",
      "kind": "mcad",
      "app_key": "heax-step_forge",
      "ref": {
        "detect_job_id": "01JDET",
        "stepforge_project_id": "001a02ba21cd51064a68c35"
      },
      "bridge_declared": false,
      "probe": {
        "capture_mode": "rest_primary",
        "detail": "capture_ok calls=8 app_key=heax-step_forge",
        "reachable": true,
        "status": "linked"
      },
      "probe_at": 1793441473,
      "status": "linked"
    }
  ],
  "snapshots": [
    {
      "id": "5bff75c1afac45489edb1d979c1e28db",
      "ir_version": "1.0",
      "ir_hash": "a72492cca1ba6add7027edc23d121f65e1a2db076a6b5372effa8a5facd4d43d",
      "kinds_json": "[\"mcad\",\"ecad\"]",
      "node_count": 3,
      "edge_count": 3,
      "warnings_n": 4,
      "degraded": "app_version_unknown",
      "degraded_json": [
        "app_version_unknown",
        "ecad_absent"
      ],
      "created_at": 1793441473,
      "label": "DV1",
      "app_versions": {
        "ecad": {},
        "mcad": {
          "captured_via": null,
          "extra": null,
          "version": null
        }
      },
      "adapter_versions": {
        "ecad": "0.0-stub",
        "mcad": "1.0"
      }
    },
    {
      "id": "95644d3def2c4c338fb53ea095d4b45d",
      "ir_version": "1.0",
      "ir_hash": "a5d7e4bfd302672a2b0df6ccb0c853befbe916fdba432d99992bab11e6b8b0e5",
      "kinds_json": "[\"mcad\",\"ecad\"]",
      "node_count": 3,
      "edge_count": 3,
      "warnings_n": 4,
      "degraded": "app_version_unknown",
      "degraded_json": [
        "app_version_unknown",
        "ecad_absent"
      ],
      "created_at": 1793441473,
      "label": "DV2",
      "app_versions": {
        "ecad": {},
        "mcad": {
          "captured_via": null,
          "extra": null,
          "version": null
        }
      },
      "adapter_versions": {
        "ecad": "0.0-stub",
        "mcad": "1.0"
      }
    },
    {
      "id": "129d7610f7794d71af4f64b54ca5c554",
      "ir_version": "1.0",
      "ir_hash": "e54be20938709506e72c05d7d97453e76780a8778d077c17e6175d163366bfea",
      "kinds_json": "[\"mcad\",\"dyna\",\"dyna_result\"]",
      "node_count": 7,
      "edge_count": 4,
      "warnings_n": 0,
      "degraded": "no_secid",
      "degraded_json": [
        "no_secid"
      ],
      "created_at": 1756600000,
      "label": null,
      "app_versions": {
        "dyna": {},
        "dyna_result": {},
        "mcad": {}
      },
      "adapter_versions": {
        "dyna": "1.0",
        "dyna_result": "1.0",
        "mcad": "1.0"
      }
    }
  ],
  "targets": [],
  "jobs": [],
  "character_top_tags": [],
  "my_role": "editor"
});

/** 과제 목록(GET /projects) — 편집자로 받았다. 제 과제(owner)와 구성원 과제(editor), 카드마다 등급 · 수명 주기 · 코퍼스 제외 · 내 역할. */
export const projectCardsMember = sample<ProjectList>()({
  "projects": [
    {
      "id": "2e480ea06bc24f7c8b1d62a21f4310e3",
      "code": "ED-1",
      "name": "편집자 과제",
      "stage": null,
      "targets": [],
      "last_snapshot_id": null,
      "sources": [],
      "last_snapshot_at": null,
      "open_targets": 0,
      "coverage_pct": null,
      "level": null,
      "classification": "internal",
      "lifecycle": "active",
      "corpus_excluded": false,
      "my_role": "owner"
    },
    {
      "id": "a3e072a3c6944e928d90a826f5907884",
      "code": "DEMO-7",
      "name": "시연 과제",
      "stage": "DV1",
      "targets": [],
      "last_snapshot_id": "5bff75c1afac45489edb1d979c1e28db",
      "sources": [
        {
          "kind": "mcad",
          "app_key": "heax-step_forge",
          "status": "linked"
        }
      ],
      "last_snapshot_at": 1793441473,
      "open_targets": 0,
      "coverage_pct": null,
      "level": null,
      "classification": "confidential",
      "lifecycle": "shipped",
      "corpus_excluded": false,
      "my_role": "editor"
    }
  ]
});

/**
 * 스냅샷 상태(GET /snapshots/{id}?part=state) — G3 에 ack 를 붙인 뒤 받았다. 게이트는 지금 살아 있는 ack 를 얹어 오고 `gates_hash` 는
 * ack 답의 것과 같다. 게이트에서 만든 글(신호 `gates.summary` 의 값 · 글과 summary_text 의 [게이트] 줄)도 그 ack 를 말한다(반대 검토 10-31 —
 * 같은 게이트를 고친 백엔드에서 다시 받아 그 둘을 옮겼다). 신호 · 규칙 적중 · 성격 씨앗 · 특징 벡터는 앞 몇 개로 줄였다.
 */
export const snapshotStateAcked = sample<SnapshotState>()({
  "blocked": false,
  "character_seed": [
    {
      "cites": [
        "p:8051c8e0492d"
      ],
      "rule": "seed.structure.rigid_frame_load_path",
      "tag": "char:structure:rigid_frame_load_path",
      "text": "PLATE_2 degree=2 / leaf 3"
    }
  ],
  "feature_vector": {
    "known": [
      true,
      true
    ],
    "names": [
      "n_leaf",
      "n_files"
    ],
    "transform": [
      "log1p",
      "log1p"
    ],
    "values": [
      1.386294,
      0.693147
    ],
    "version": "fv-1.0"
  },
  "gates": {
    "G1": {
      "ack_at": null,
      "ack_by": null,
      "ack_reason": null,
      "blocking": false,
      "count": 0,
      "detail": [],
      "effect": "none",
      "key": "dup_or_anon_names",
      "pass": true,
      "reason": null,
      "threshold": 5.0
    },
    "G2": {
      "ack_at": null,
      "ack_by": null,
      "ack_reason": null,
      "blocking": false,
      "count": 0,
      "detail": [],
      "effect": "none",
      "key": "sameas_pending",
      "pass": true,
      "reason": null,
      "threshold": 0
    },
    "G3": {
      "ack_at": 1793441473,
      "ack_by": "syn@example.com",
      "ack_reason": "계면 확인 뒤 진행",
      "blocking": false,
      "count": 1,
      "detail": [
        "e:c650f4ca3da5"
      ],
      "effect": "mark",
      "key": "iface_unconfirmed",
      "pass": false,
      "reason": null,
      "threshold": 0
    },
    "G4": {
      "ack_at": null,
      "ack_by": null,
      "ack_reason": null,
      "blocking": false,
      "count": 0,
      "detail": [],
      "effect": "none",
      "key": "coordinate",
      "pass": true,
      "reason": null,
      "threshold": 0
    },
    "G5": {
      "ack_at": null,
      "ack_by": null,
      "ack_reason": null,
      "blocking": false,
      "count": 0,
      "detail": [],
      "effect": "none",
      "key": "partial_scope",
      "pass": true,
      "reason": null,
      "threshold": 0
    },
    "G6": {
      "ack_at": null,
      "ack_by": null,
      "ack_reason": null,
      "blocking": true,
      "count": 0,
      "detail": [],
      "effect": "none",
      "key": "unit_scale",
      "pass": true,
      "reason": null,
      "threshold": 0
    }
  },
  "ir_hash": "e54be20938709506e72c05d7d97453e76780a8778d077c17e6175d163366bfea",
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
    "result_kind_mismatch": false,
    "volume_null": false,
    "world_transform_absent": false
  },
  "precedent": {
    "corpus_n": 0,
    "out_of_range_count": 0,
    "per_feature": {}
  },
  "project_id": "a3e072a3c6944e928d90a826f5907884",
  "rule_hits": [
    {
      "evaluable": true,
      "fix_hint": "«set_interface 로 kind 확정 또는 형상 수정 후 재검출»",
      "found": {
        "count": 1,
        "refs": [
          "e:c650f4ca3da5"
        ],
        "text": "interference_auto_present 1건"
      },
      "not_evaluable_reason": null,
      "pass": false,
      "payload_hash": "f750af522107c4e40bba300036f14e39db6b894b5a70bdb6d889beb85652745c",
      "refs": [
        "e:c650f4ca3da5"
      ],
      "rule": "R-001",
      "severity": "중대",
      "version": "rules-1.0",
      "why_it_matters": "«간섭이 auto 로 남아 있으면 억지끼움 의도인지 설계오류인지 확정되지 않은 것이다»"
    }
  ],
  "rule_version": "rules-1.0",
  "seed_rules_version": "seed-1.0",
  "signals": {
    "gates.summary": {
      "derived_from": [],
      "kind": "table",
      "known": true,
      "refs": [
        "gate:G1",
        "gate:G2",
        "gate:G3",
        "gate:G4",
        "gate:G5",
        "gate:G6"
      ],
      "text": "G1 pass · G2 pass · G3 fail(1, ack 있음) · G4 pass · G5 pass · G6 pass",
      "unit": null,
      "value": {
        "G1": {
          "ack": false,
          "count": 0,
          "pass": true
        },
        "G2": {
          "ack": false,
          "count": 0,
          "pass": true
        },
        "G3": {
          "ack": true,
          "count": 1,
          "pass": false
        },
        "G4": {
          "ack": false,
          "count": 0,
          "pass": true
        },
        "G5": {
          "ack": false,
          "count": 0,
          "pass": true
        },
        "G6": {
          "ack": false,
          "count": 0,
          "pass": true
        }
      }
    },
    "counts.leaf": {
      "derived_from": [],
      "kind": "count",
      "known": true,
      "refs": [],
      "text": "leaf=3",
      "unit": null,
      "value": 3
    },
    "counts.edges.interference": {
      "derived_from": [],
      "kind": "count",
      "known": true,
      "refs": [],
      "text": "interference=1",
      "unit": null,
      "value": 1
    }
  },
  "snapshot_id": "129d7610f7794d71af4f64b54ca5c554",
  "state_version": "1.0",
  "summary_status": "ok",
  "summary_text": "[대상] 스냅샷 129d7610 ir_hash=e54be2093870 소스 mcad=sha-mcad dyna=abcd12340000 dyna_result=sha-report ecad=absent\n[게이트] G1 pass · G2 pass · G3 fail(1, ack 있음) · G4 pass · G5 pass · G6 pass\n[구조] 파일 1 · 리프 3 · 어셈블리 1 · 엣지 tied 1 touching 0 clearance 0 interference 1 · 고아 0 · cross_file 0 [sig:counts.*]\n[상위 계면] PLATE_2↔BRACKET_L interference penetration_depth≥0.05 mm(lower_bound) status=auto(미확정 초안) [e:c650f4ca3da5] · 근접 간극 clearance 없음\n[치수] dims_named 없음\n[재료] 재질 종류 2 · 미기재 0 [sig:counts.material_null]\n[Dyna] pid 2 · {\"*CONTACT_TIED_SURFACE_TO_SURFACE\":1} · pid 1 worst_stress=231.4 MPa · pid 2 worst_stress=120.0 MPa\n[규칙] R-001 fail(1건) [rule:R-001] · R-002 pass [rule:R-002] · R-003 pass [rule:R-003] · R-004 pass [rule:R-004] · R-005 pass [rule:R-005] · R-006 pass [rule:R-006] · R-007 평가 불가(source_absent) [rule:R-007]\n[씨앗] char:structure:rigid_frame_load_path · char:interface:bracket_l_plate_2 · char:analysis:dyna_with_results\n[결측] ecad_absent",
  "taxonomy_version": "1.2",
  "computed_at": 1793441473,
  "gates_hash": "83e79926329a"
});

/** 대응표(GET /sameas) — 같은 과제의 두 판(DV1 → DV2)이라 pair_key 가 같은 과제 id 둘이다. 행은 모두 자동 확정이라 없다. */
export const sameAsPairKey = sample<SameAs>()({
  "pair_key": "a3e072a3c6944e928d90a826f5907884|a3e072a3c6944e928d90a826f5907884",
  "pairs": [],
  "pending_n": 0,
  "G2": {
    "ack_at": null,
    "ack_by": null,
    "ack_reason": null,
    "blocking": false,
    "count": 0,
    "detail": [],
    "effect": "none",
    "key": "sameas_pending",
    "pass": true,
    "reason": null,
    "threshold": 0
  }
});

/**
 * 키 대장(GET /part-keys/{ckey}) — 보기 멤버로 받은 병합된 키. 별칭은 그 사람이 구성원인 과제의 것만이고, 원장 행은 주인의 것이라 `mine` 은
 * false 다(이 사람의 결정은 404 — 화면이 결정을 잠근다).
 */
export const partKeyMerged = sample<PartKey>()({
  "ckey": "ck:5363abb47438",
  "status": "merged",
  "merged_into": "ck:4bbe8075874f",
  "display_name": null,
  "aliases": [
    {
      "domain": "mcad",
      "label": "STACK_ASM",
      "local_key": "/sif-e2e/a_stack.step/STACK_ASM",
      "name_norm": "stack_asm",
      "project_id": "a3e072a3c6944e928d90a826f5907884"
    }
  ],
  "decided_by": "syn@example.com",
  "decided_at": 1793441473,
  "mine": false
});

/** 키 대장 — 같은 병합된 키를 주인으로 받았다(`mine` true — 확정만 잠기고 되돌리기 · 이름 · 병합은 열린다). */
export const partKeyMergedOwn = sample<PartKey>()({
  "ckey": "ck:5363abb47438",
  "status": "merged",
  "merged_into": "ck:4bbe8075874f",
  "display_name": null,
  "aliases": [
    {
      "domain": "mcad",
      "label": "STACK_ASM",
      "local_key": "/sif-e2e/a_stack.step/STACK_ASM",
      "name_norm": "stack_asm",
      "project_id": "a3e072a3c6944e928d90a826f5907884"
    }
  ],
  "decided_by": "syn@example.com",
  "decided_at": 1793441473,
  "mine": true
});

/** 키 대장 — 주인으로 받은 이름 붙은 후보 키(이름만 붙이면 status 는 candidate 그대로다). */
export const partKeyNamed = sample<PartKey>()({
  "ckey": "ck:4bbe8075874f",
  "status": "candidate",
  "merged_into": null,
  "display_name": "보호 필름",
  "aliases": [
    {
      "domain": "mcad",
      "label": "PLATE_2",
      "local_key": "/sif-e2e/a_stack.step/STACK_ASM/PLATE_2",
      "name_norm": "plate_2",
      "project_id": "a3e072a3c6944e928d90a826f5907884"
    }
  ],
  "decided_by": "syn@example.com",
  "decided_at": 1793441473,
  "mine": true
});

/** 진행판의 패널 잡(GET /targets/{key}/coverage → job) — 동시 1 잡의 도는 패널 하나. `signals` 는 `signal` 과 같은 한 줄이다. */
export const coverageJobRunning = sample<NonNullable<CoverageJob>>()({
  "id": "c89846800b9546ab851712d371ce4493",
  "tier": "A",
  "state": "running",
  "pause_reason": null,
  "hold_code": null,
  "hold_until": null,
  "panels_done": 0,
  "panels_total": 1,
  "error": null,
  "signal": {
    "frames": 12,
    "last_event_at": 1793441473,
    "last_frame_at": 1793441473,
    "last_step": "1라운드 · 좌석 발언",
    "panel_id": "dae1b44057504811ae7ec7eb01d42c10",
    "panel_no": 1,
    "started_at": 1793441473,
    "frame_idle_s": 0,
    "event_idle_s": 0
  },
  "signals": [
    {
      "frames": 12,
      "last_event_at": 1793441473,
      "last_frame_at": 1793441473,
      "last_step": "1라운드 · 좌석 발언",
      "panel_id": "dae1b44057504811ae7ec7eb01d42c10",
      "panel_no": 1,
      "started_at": 1793441473,
      "frame_idle_s": 0,
      "event_idle_s": 0
    }
  ]
});

/**
 * 진행판의 패널 잡 — 동시 2 잡(잡의 concurrency, 사용자 결정 10-31 · 가지 wt1031/risk-concurrency)이 패널 둘을 함께 돌린다. `signals` 는
 * 패널 차례대로 두 줄이고 `signal` 은 마지막에 적힌 하나다(실 백엔드 하네스의 응답).
 */
export const coverageJobTwoPanels = sample<NonNullable<CoverageJob>>()({
  "id": "74ba8c229cbc4f73883c60638f3b2509",
  "tier": "A",
  "state": "running",
  "pause_reason": null,
  "hold_code": null,
  "hold_until": null,
  "panels_done": 0,
  "panels_total": 2,
  "error": null,
  "signal": {
    "frames": 1,
    "last_event_at": 1793453979,
    "last_frame_at": 1793453979,
    "last_step": "1라운드 · 좌석 조회",
    "panel_id": "fb0e1c812c3346d3a6e4c425ff578ece",
    "panel_no": 2,
    "started_at": 1793453979,
    "frame_idle_s": 0,
    "event_idle_s": 0
  },
  "signals": [
    {
      "frames": 2,
      "last_event_at": 1793453979,
      "last_frame_at": 1793453979,
      "last_step": "2라운드 · 좌석 발언",
      "panel_id": "31ee04675f604d159a78fcba293c7288",
      "panel_no": 1,
      "started_at": 1793453979,
      "frame_idle_s": 0,
      "event_idle_s": 0
    },
    {
      "frames": 1,
      "last_event_at": 1793453979,
      "last_frame_at": 1793453979,
      "last_step": "1라운드 · 좌석 조회",
      "panel_id": "fb0e1c812c3346d3a6e4c425ff578ece",
      "panel_no": 2,
      "started_at": 1793453979,
      "frame_idle_s": 0,
      "event_idle_s": 0
    }
  ]
});

/**
 * 비교 본문(GET /diffs/{id}?part=diff — MCP risk_get_diff(part='diff') 와 같은 함수) — 이 가지의 실제 생산자(합성 다건 syn40 기본 씨앗 →
 * 동결 → create_diff)가 쓴 것을 층마다 앞 항목 하나 · 사건은 주체 열쇠 꼴(부품 dn · asm: · contact# · dim: · [dn, metric])마다 하나로
 * 줄였다(요약문은 앞 네 줄, stats 는 줄이기 전 그대로). 최상위 pair_kind 와 노드가 아닌 주체 열쇠 넷은 rr_diff.v1 계약에 적혔다
 * (HWAXRisk context-notes OI-1).
 */
export const diffDocSyn40 = sample<DiffDoc>()({
  "base": {
    "ir_hash": "27a577d0712db2b726ffecfa49ec2eba70c2c054b8b2ef988506c82e7e31576e",
    "label": "DV1",
    "snapshot_id": "fc136c2947d5408aa5fc678231225938"
  },
  "character_seed": [
    {
      "cites": [
        "c:6c26910abc0f",
        "c:b26fea6947bb",
        "c:d077d6aa6b52"
      ],
      "tag": "char:change_style:topology_change",
      "text": "change_kind topology 25건"
    }
  ],
  "comparability": {
    "G7": {
      "blocking": false,
      "count": 0,
      "detail": [
        "reason=tol_keys_partial(4)"
      ],
      "effect": "none",
      "key": "yardstick_parity",
      "pass": true,
      "threshold": 0
    },
    "adapter_parity": true,
    "app_version_parity": null,
    "base_blocked": false,
    "capture_parity": true,
    "coordinate_ok": true,
    "ecad": {
      "adapter_parity": true,
      "base": "absent",
      "excluded_reason": null,
      "target": "absent"
    },
    "ir_version_parity": true,
    "partial_any": false,
    "primary_source_parity": true,
    "result_parity": true,
    "result_present": true,
    "result_reason": null,
    "scope_parity": true,
    "source_schema_drift_kinds": [],
    "source_schema_parity": true,
    "target_blocked": false,
    "tol_keys_known": true,
    "tol_parity": true,
    "unit_parity": true
  },
  "correspondence": {
    "fuzzy_skipped": null,
    "matched": [
      {
        "ckey": "ck:ffff81eb3ae7",
        "dn": "p:016702820e11",
        "method": "exact_path",
        "nid_base": "p:016702820e11",
        "nid_target": "p:016702820e11",
        "score": 1.0,
        "status": "auto"
      }
    ],
    "method_counts": {
      "exact_path": 72,
      "fingerprint": 26,
      "fuzzy": 0,
      "ledger": 0,
      "manual": 0,
      "name_norm": 4,
      "pid_map": 0
    },
    "pending_n": 0,
    "unmatched_base": [
      "p:22ed6efeab7f"
    ],
    "unmatched_target": [
      "p:1efba85c7d22"
    ]
  },
  "created_at": 1793510615,
  "diff_id": "ffd9b846579942b9a973f2951604194d",
  "diff_version": "1.0",
  "pair_kind": "same_project_revision",
  "parametric": {
    "dims_delta": [
      {
        "after": 1.96,
        "attr": "value",
        "before": 1.96,
        "cid": "c:e74662569e88",
        "delta": 0.0,
        "design_relevant": true,
        "excluded_reason": null,
        "flag": "noise",
        "lower_bound": false,
        "method": "measured",
        "name": "bg_t1",
        "null_reason": null,
        "rel_delta": 0.0,
        "size_pct": null,
        "subject_key": "dim:bg_t1",
        "text": "bg_t1 1.960→1.960 mm (+0.0%) [c:e74662569e88] [d:bg_t1]",
        "unit": "mm"
      }
    ],
    "edge_params": [
      {
        "after": 70.0,
        "attr": "contact_area_est",
        "before": null,
        "cid": "c:01f0a307c2ad",
        "ckey_a": "ck:59d75fb78cf9",
        "ckey_b": "ck:5d9066b47c17",
        "delta": null,
        "design_relevant": true,
        "dn_a": "p:6bd67913cd71",
        "dn_b": "p:f523152dd621",
        "eid_base": "e:d3bd671cb5a8",
        "eid_target": "e:d3bd671cb5a8",
        "excluded_reason": "null_one_side",
        "flag": "null_one_side",
        "kind_family": "iface",
        "lower_bound": false,
        "rel_delta": null,
        "size_pct": null,
        "subject_key": "ck:59d75fb78cf9|ck:5d9066b47c17",
        "text": "p:6bd67913cd71↔p:f523152dd621 contact_area_est 미측정→70.0 mm2(밴드면적) [c:01f0a307c2ad]",
        "unit": "mm2"
      }
    ],
    "materials": [
      {
        "after": "al6061",
        "before": "abs",
        "cid": "c:4a8fbd5ba876",
        "ckey": "ck:63cc6c0ebda5",
        "design_relevant": true,
        "dn": "p:db1f4dca286d",
        "excluded_reason": null,
        "field": "material_norm",
        "flag": "changed",
        "text": "강화유리 WINDOW material.material_norm abs→al6061 [c:4a8fbd5ba876]"
      }
    ],
    "node_params": [
      {
        "after": 0.675,
        "attr": "centroid_world[2]",
        "before": 0.675,
        "cid": "c:00176f8037b5",
        "ckey": "ck:2bb6a3e8be43",
        "delta": 0.0,
        "design_relevant": true,
        "dn": "p:9e8f04705e92",
        "excluded_reason": null,
        "flag": "noise",
        "lower_bound": false,
        "rel_delta": 0.0,
        "size_pct": 85,
        "subject_key": "ck:2bb6a3e8be43",
        "text": "SPRING_PERADA centroid_world_z 0.675→0.675 mm (+0.0%) [c:00176f8037b5]",
        "unit": "mm"
      }
    ],
    "result_delta": [
      {
        "after": 0.108,
        "attr": "worst_disp",
        "before": 0.108,
        "case_key_after": null,
        "case_key_before": null,
        "cid": "c:0133919eb378",
        "ckey": "ck:22148f7afff6",
        "delta": 0.0,
        "design_relevant": true,
        "dn": "p:8316fcc3edcb",
        "excluded_reason": null,
        "flag": "noise",
        "kind": "sphere",
        "lower_bound": false,
        "metric": "worst_disp",
        "pid_after": 3,
        "pid_before": 3,
        "rel_delta": 0.0,
        "size_pct": null,
        "subject_key": "ck:22148f7afff6",
        "text": "p:8316fcc3edcb worst_disp 0.108→0.108 mm (+0.0%) [c:0133919eb378]",
        "unit": "mm"
      }
    ],
    "rollup_delta": [
      {
        "asm_key": "syn_phone",
        "cid": "c:09f695202b80",
        "design_relevant": true,
        "edges_external": {
          "after": 0,
          "before": 0
        },
        "edges_internal": {
          "after": 47,
          "before": 47
        },
        "excluded_reason": null,
        "n_leaf": {
          "after": 69,
          "before": 70
        },
        "orphan_leaf": {
          "after": 27,
          "before": 29
        },
        "path_prefix": "syn_phone",
        "text": "asm:syn_phone 리프 70→69 [c:09f695202b80]"
      }
    ]
  },
  "project_id": "c88db46ea9f1408e8f33af6a5dfcf6ba",
  "rule_version": "rules-1.0",
  "semantic": {
    "blocked_by": null,
    "events": [
      {
        "after": 6,
        "before": 5,
        "change_kind": "topology",
        "cid": "c:6c26910abc0f",
        "code": "asm.rollup_changed",
        "confidence": "high",
        "derived_from": [
          "c:7fac4e30e937"
        ],
        "design_relevant": true,
        "excluded_reason": null,
        "lower_bound": false,
        "magnitude": {
          "rel": null,
          "unit": null,
          "value": null
        },
        "neighborhood": {
          "ckeys": [],
          "k": 1
        },
        "subject": {
          "ckeys": [],
          "dns": [
            "asm:syn_phone/rear_asm"
          ],
          "eids": {},
          "names": [
            "syn_phone/rear_asm"
          ]
        },
        "subject_key": "asm:syn_phone/rear_asm",
        "text": "asm:syn_phone/rear_asm edges_internal 5→6 · external 3→3 [c:6c26910abc0f]",
        "unconfirmed": false
      },
      {
        "after": null,
        "before": null,
        "change_kind": "topology",
        "cid": "c:f63d73bbc718",
        "code": "contact.added",
        "confidence": "medium",
        "derived_from": [
          "c:74cc28f72ab6"
        ],
        "design_relevant": true,
        "excluded_reason": null,
        "lower_bound": false,
        "magnitude": {
          "rel": null,
          "unit": null,
          "value": null
        },
        "neighborhood": {
          "ckeys": [],
          "k": 1
        },
        "subject": {
          "ckeys": [
            "ck:cbb23e443f48",
            "ck:1d5150b2dd17"
          ],
          "dns": [
            "p:b72f6a187949",
            "p:f478722bb7ed"
          ],
          "eids": {
            "base": null,
            "target": "e:060fd94d4ed2"
          },
          "names": [
            "p:b72f6a187949",
            "p:f478722bb7ed"
          ]
        },
        "subject_key": "ck:1d5150b2dd17|ck:cbb23e443f48",
        "text": "p:b72f6a187949↔p:f478722bb7ed contact.added [c:f63d73bbc718]",
        "unconfirmed": false
      },
      {
        "after": 3,
        "before": 2,
        "change_kind": "topology",
        "cid": "c:384d67c74cee",
        "code": "contact.scope_changed",
        "confidence": "high",
        "derived_from": [
          "c:ba132c316770"
        ],
        "design_relevant": true,
        "excluded_reason": null,
        "lower_bound": false,
        "magnitude": {
          "rel": null,
          "unit": null,
          "value": null
        },
        "neighborhood": {
          "ckeys": [],
          "k": 1
        },
        "subject": {
          "ckeys": [],
          "dns": [
            "contact#16"
          ],
          "eids": {},
          "names": [
            "contact#16"
          ]
        },
        "subject_key": "contact#16",
        "text": "contact#16 scope 멤버 2→3 [c:384d67c74cee]",
        "unconfirmed": false
      },
      {
        "after": 1.222,
        "before": 1.63,
        "change_kind": "dimension",
        "cid": "c:6535ff633104",
        "code": "dim.named_changed",
        "confidence": "high",
        "derived_from": [
          "c:089e51f7bd08"
        ],
        "design_relevant": true,
        "excluded_reason": null,
        "lower_bound": false,
        "magnitude": {
          "rel": -0.250307,
          "unit": "mm",
          "value": -0.408
        },
        "neighborhood": {
          "ckeys": [],
          "k": 1
        },
        "subject": {
          "ckeys": [],
          "dns": [
            "dim:syn_holder_tinuda"
          ],
          "eids": {},
          "names": [
            "syn_holder_tinuda"
          ]
        },
        "subject_key": "dim:syn_holder_tinuda",
        "text": "syn_holder_tinuda 1.630→1.222 mm (−25.0%) [c:6535ff633104]",
        "unconfirmed": false
      },
      {
        "after": 0.734,
        "before": 0.565,
        "change_kind": "result",
        "cid": "c:33036e3ffdff",
        "code": "result.part_metric_shift",
        "confidence": "high",
        "derived_from": [
          "c:ac8699e1dfa2"
        ],
        "design_relevant": true,
        "excluded_reason": null,
        "lower_bound": false,
        "magnitude": {
          "rel": 0.299115,
          "unit": "mm",
          "value": 0.169
        },
        "neighborhood": {
          "ckeys": [],
          "k": 1
        },
        "subject": {
          "ckeys": [
            "ck:db8062fcff37"
          ],
          "dns": [
            "p:65bf9cd8552b",
            "worst_disp"
          ],
          "eids": {},
          "names": [
            "p:65bf9cd8552b"
          ]
        },
        "subject_key": "ck:db8062fcff37",
        "text": "p:65bf9cd8552b worst_disp 0.565→0.734 mm (+29.9%) [c:33036e3ffdff]",
        "unconfirmed": false
      }
    ]
  },
  "stats": {
    "edges_added": 12,
    "edges_kind_changed": 4,
    "edges_removed": 13,
    "events": 54,
    "events_by_change_kind": {
      "consistency": 1,
      "count": 5,
      "dimension": 14,
      "discretization": 1,
      "material": 1,
      "parameter": 1,
      "placement": 2,
      "result": 3,
      "topology": 25,
      "type": 1
    },
    "events_by_confidence": {
      "high": 24,
      "low": 4,
      "medium": 26
    },
    "excluded_by_reason": {
      "null_one_side": 6
    },
    "nodes_added": 1,
    "nodes_matched": 102,
    "nodes_removed": 2,
    "params_changed": 48,
    "params_excluded": 6,
    "params_noise": 1011
  },
  "structural": {
    "dyna": {
      "contacts_added": [
        "c:74cc28f72ab6"
      ],
      "contacts_removed": [
        "c:402e8a44a508"
      ],
      "scope_changed": [
        {
          "cid": "c:ba132c316770",
          "contact_index": 16,
          "dns_after": [
            "p:38d7f8fdd922",
            "p:8316fcc3edcb",
            "p:b2d7508f0dc1"
          ],
          "dns_before": [
            "p:8316fcc3edcb",
            "p:b2d7508f0dc1"
          ],
          "pids_after": [
            "p:03d11e0181c5",
            "p:a864133aef88",
            "p:fc934073360a"
          ],
          "pids_before": [
            "p:a864133aef88",
            "p:fc934073360a"
          ],
          "text": "contact#16 scope 멤버 2→3 [c:ba132c316770]"
        }
      ]
    },
    "edge_changes": [
      {
        "cid": "c:10c7075f20ce",
        "ckey_a": "ck:339b26192529",
        "ckey_b": "ck:859370414198",
        "confidence": "medium",
        "cross_file": false,
        "dn_a": "p:9a33cdde40ba",
        "dn_b": "p:b6c465121a88",
        "eid_base": "e:1cf154c06c8b",
        "eid_target": null,
        "excluded_reason": null,
        "kind_family": "hier",
        "kind_from": "part_of",
        "kind_to": null,
        "op": "removed",
        "rank_delta": null,
        "rank_from": null,
        "rank_to": null,
        "status_from": "auto",
        "status_to": null,
        "text": "p:9a33cdde40ba↔p:b6c465121a88 hier removed [c:10c7075f20ce]"
      }
    ],
    "hierarchy_moves": [
      {
        "asm_key_from": "syn_phone/camera_asm",
        "asm_key_to": "syn_phone/display_asm",
        "cid": "c:24b1fd05c5d2",
        "ckey": "ck:7d9c64a3ee61",
        "confidence": "medium",
        "correspondence_method": "fingerprint",
        "correspondence_score": 0.95,
        "dn": "p:48e65655f30c",
        "domain": "mcad",
        "excluded_reason": null,
        "kind": "part",
        "label": "PLATE_VUNUDA",
        "neighborhood_1hop": [],
        "nid_base": "p:48e65655f30c",
        "nid_target": "p:90ec62f071ae",
        "op": "moved_in_tree",
        "text": "PLATE_VUNUDA moved_in_tree [c:24b1fd05c5d2]"
      }
    ],
    "node_changes": [
      {
        "asm_key_from": "syn_phone/camera_asm",
        "asm_key_to": "syn_phone/display_asm",
        "cid": "c:24b1fd05c5d2",
        "ckey": "ck:7d9c64a3ee61",
        "confidence": "medium",
        "correspondence_method": "fingerprint",
        "correspondence_score": 0.95,
        "dn": "p:48e65655f30c",
        "domain": "mcad",
        "excluded_reason": null,
        "kind": "part",
        "label": "PLATE_VUNUDA",
        "neighborhood_1hop": [],
        "nid_base": "p:48e65655f30c",
        "nid_target": "p:90ec62f071ae",
        "op": "moved_in_tree",
        "text": "PLATE_VUNUDA moved_in_tree [c:24b1fd05c5d2]"
      }
    ],
    "orphans_delta": {
      "base": [
        "p:016702820e11"
      ],
      "became_orphan": [
        "p:1efba85c7d22"
      ],
      "left_orphan": [
        "p:22ed6efeab7f"
      ],
      "target": [
        "p:016702820e11"
      ]
    }
  },
  "summary_status": "ok",
  "summary_text": "[대상] base «DV1» fc136c29 ir=27a577d0712d → target «DV2» 664a7fcf ir=8f567d6e6526 [sig:ir_hash]\n[비교가능성] tol_parity=true · result_parity=true · unit_parity=true · scope_parity=true · coordinate_ok=true · same-as pending 0 · 제외 null_one_side 6건 [gate:G7]\n[구조] +1파트 −2파트 교체 1 [c:372c494ddc0c] · 계면 +12 −13 [c:10c7075f20ce] · rank 상승 1 하락 1 [c:23b06a04d77d] · 간섭 신규 1 해소 1 · 고아 +4 −6 · 롤업 변화 9 [c:09f695202b80]\n[의미] topology: «p:6bd67913cd71↔p:f523152dd621 kind interference→tied (rank 3→2)» [c:14f07f347510] · «p:23a0f1887d58↔p:844488beab72 kind tied→touching (rank 2→1)» [c:bdf1d0e48e9e] · «p:77032ce25f2d↔p:ab8d0f9797a4 kind tied→interference (rank 2→3)» [c:4ff9b96c5122] · «p:16b0a01db0cc↔p:ed91f6c1b142 kind touching→tied (rank 1→2)» [c:b557f2434e6f] · «p:3a639645d76e↔p:90153dc5b73b iface.clearance_cleared (clearance)» [c:09ef5a2e10a7] · … 외 20건 | type: «CLAMP_RADADA part.replaced» [c:4329999c9a74] (confidence=low) | … 외 28건",
  "target": {
    "ir_hash": "8f567d6e6526467fbd377e50fdf600270453cb83aa73036b329590205a2ac402",
    "label": "DV2",
    "snapshot_id": "664a7fcf3c8d48e39127e828b4d8fae3"
  },
  "taxonomy_version": "1.2"
});
