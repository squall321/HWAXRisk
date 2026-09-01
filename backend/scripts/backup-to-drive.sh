#!/usr/bin/env bash
# HEAXHub appdata-to-drive.sh 호출 래퍼 — 등급 있는 원문(risk_review.db·exports/)은 평문 tar 에 싣지 않고
# age 암호 사본(.age)만 올린다(plan §5.2.5 (3a) ②). --dry-run 은 tar 에 들어갈 목록만 찍고 아무것도 올리지 않는다.
set -euo pipefail

DATA_DIR="${HWAXRISK_DATA_DIR:-${HEAX_DATA_DIR:-}}"
DRY_RUN=0
APPDATA_SCRIPT="${HEAXHUB_APPDATA_SCRIPT:-/home/koopark/claude/HEAXHub/deploy/apptainer/appdata-to-drive.sh}"

usage() {
  echo "사용법: backup-to-drive.sh [--dry-run] [--data-dir <경로>]"
  echo "  HWAXRISK_BACKUP_KEY(age 공개키)가 있으면 risk_review.db·exports/ 를 암호화해 실는다."
  echo "  키가 없으면 backup_unencrypted 경고를 찍고 평문으로 진행한다(백업 없음이 더 나쁘다)."
}

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY_RUN=1 ;;
    --data-dir) DATA_DIR="$2"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "✗ 모르는 인자: $1"; usage; exit 2 ;;
  esac
  shift
done

[ -n "$DATA_DIR" ] || { echo "✗ 데이터 디렉터리를 정할 수 없습니다 — HWAXRISK_DATA_DIR 또는 --data-dir"; exit 1; }
[ -d "$DATA_DIR" ] || { echo "✗ 데이터 디렉터리가 없습니다: $DATA_DIR"; exit 1; }

DB="$DATA_DIR/risk_review.db"
EXPORTS="$DATA_DIR/exports"
KEY="${HWAXRISK_BACKUP_KEY:-}"
if [ -z "$KEY" ] && [ -f "$DATA_DIR/secrets.env" ]; then
  KEY="$(sed -n 's/^HWAXRISK_BACKUP_KEY=//p' "$DATA_DIR/secrets.env" | tail -1)"
fi

ENCRYPTED=1
if [ -z "$KEY" ]; then
  ENCRYPTED=0
  echo "⚠ backup_unencrypted — HWAXRISK_BACKUP_KEY(age 공개키)가 없어 평문 사본이 나갑니다."
fi

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

# tar 에 실릴 목록. 평문 DB·exports 는 여기 들어가지 않는다(암호 사본만 들어간다).
MEMBERS=()
while IFS= read -r path; do
  rel="${path#"$DATA_DIR"/}"
  case "$rel" in
    risk_review.db|risk_review.db-wal|risk_review.db-shm) continue ;;
    exports|exports/*) continue ;;
    secrets.env|cred.key) continue ;;   # 시크릿은 애초에 tar 에 넣지 않는다(HEAXHub 스크립트와 같은 규칙)
  esac
  MEMBERS+=("$rel")
done < <(find "$DATA_DIR" -mindepth 1 -maxdepth 1 | sort)

if [ "$ENCRYPTED" = "1" ]; then
  [ -f "$DB" ] && MEMBERS+=("risk_review.db.age")
  [ -d "$EXPORTS" ] && MEMBERS+=("exports.tar.age")
else
  [ -f "$DB" ] && MEMBERS+=("risk_review.db")
  [ -d "$EXPORTS" ] && MEMBERS+=("exports/")
fi

if [ "$DRY_RUN" = "1" ]; then
  echo "# dry-run tar 목록 (data_dir=$DATA_DIR, encrypted=$ENCRYPTED)"
  for member in "${MEMBERS[@]:-}"; do [ -n "$member" ] && echo "$member"; done
  exit 0
fi

command -v age >/dev/null 2>&1 || { echo "✗ age 미설치 — 암호 사본을 만들 수 없습니다"; exit 1; }
command -v sqlite3 >/dev/null 2>&1 || { echo "✗ sqlite3 미설치"; exit 1; }

if [ "$ENCRYPTED" = "1" ]; then
  if [ -f "$DB" ]; then
    sqlite3 "$DB" ".backup '$STAGE/risk_review.db'"
    age -r "$KEY" -o "$DATA_DIR/risk_review.db.age" "$STAGE/risk_review.db"
    echo "· risk_review.db.age 갱신"
  fi
  if [ -d "$EXPORTS" ]; then
    tar -cf "$STAGE/exports.tar" -C "$DATA_DIR" exports
    age -r "$KEY" -o "$DATA_DIR/exports.tar.age" "$STAGE/exports.tar"
    echo "· exports.tar.age 갱신"
  fi
fi

[ -x "$APPDATA_SCRIPT" ] || { echo "✗ HEAXHub 백업 스크립트를 찾을 수 없습니다: $APPDATA_SCRIPT"; exit 1; }
HEAX_BACKUP_EXCLUDE="hwax_risk/risk_review.db hwax_risk/exports" "$APPDATA_SCRIPT"
echo "✓ 암호 사본 준비 후 app-data 백업 호출 완료"
