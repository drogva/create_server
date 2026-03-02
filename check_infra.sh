#!/usr/bin/env bash
set -a
source /home/rocky/check/.env
set +a

# 카카오톡 전송 함수

# ----------------------------
# Kakao
# ----------------------------
send_kakao() {
  local MSG="$1"
  RESPONSE=$(curl -s -X POST "https://kauth.kakao.com/oauth/token" \
    -d "grant_type=refresh_token" \
    -d "client_id=$REST_API_KEY" \
    -d "refresh_token=$RT")
  AT=$(echo "$RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin).get('access_token', 'fail'))")
  if [ "$AT" != "fail" ]; then
    TEMPLATE=$(python3 -c "import json, sys; print(json.dumps({'object_type': 'text', 'text': sys.argv[1], 'link': {'web_url': 'http://localhost'}}))" "$MSG")
    curl -s -X POST "https://kapi.kakao.com/v2/api/talk/memo/default/send" \
      -H "Authorization: Bearer $AT" \
      --data-urlencode "template_object=$TEMPLATE" > /dev/null
  fi
}

# ----------------------------
# NHN Token
# ----------------------------
refresh_nhn_token() {
  OS_TOKEN=$(curl -s -X POST "https://api-identity-infrastructure.nhncloudservice.com/v2.0/tokens" \
    -H "Content-Type: application/json" \
    -d "{ \"auth\": { \"tenantId\": \"$T_ID\", \"passwordCredentials\": { \"username\": \"$USER_ID\", \"password\": \"$USER_PW\" } } }" \
    | jq -r '.access.token.id')
}
refresh_nhn_token

# ----------------------------
# 기대 스펙(정책)
# ----------------------------
expected_vcpu() {
  case "$1" in
    cpu|gpu|win) echo "4" ;;
    *)           echo "0" ;;
  esac
}
expected_ram_gb() {
  case "$1" in
    cpu) echo "8" ;;
    gpu) echo "32" ;;
    win) echo "16" ;;
    *)   echo "0" ;;
  esac
}
expected_disk_gb() {
  case "$1" in
    cpu|gpu) echo "200" ;;
    win)     echo "50" ;;
    *)       echo "0" ;;
  esac
}
expected_gpu_tag() {
  case "$1" in
    gpu) echo "g2" ;;
    *)   echo "" ;;
  esac
}

# ----------------------------
# 서버 1대 조회 + 검증 + (PASS/FAIL 모두 알림)
# ----------------------------
check_one_server() {
  local S_ID="$1"
  local S_NAME="$2"
  local TYPE="$3"

  local EXP_VCPU EXP_RAM_GB EXP_DISK_GB EXP_GPU_TAG
  EXP_VCPU="$(expected_vcpu "$TYPE")"
  EXP_RAM_GB="$(expected_ram_gb "$TYPE")"
  EXP_DISK_GB="$(expected_disk_gb "$TYPE")"
  EXP_GPU_TAG="$(expected_gpu_tag "$TYPE")"

  # 서버 상세
  local S_FULL FLAVOR_ID ACTUAL_IP ACTUAL_SG V_ID
  S_FULL=$(curl -s -X GET "https://kr1-api-instance-infrastructure.nhncloudservice.com/v2/$T_ID/servers/$S_ID" \
    -H "X-Auth-Token: $OS_TOKEN")

  FLAVOR_ID=$(echo "$S_FULL" | jq -r '.server.flavor.id')
  ACTUAL_IP=$(echo "$S_FULL" | jq -r '.server.addresses[] | .[] | .addr' | tr '\n' ',' | sed 's/,$//')
  ACTUAL_SG=$(echo "$S_FULL" | jq -r '.server.security_groups[].name' | tr '\n' ' ' | sed 's/ $//')
  V_ID=$(echo "$S_FULL" | jq -r '.server["os-extended-volumes:volumes_attached"][0].id // empty' 2>/dev/null || true)

  # Flavor
  local FLAVOR_RAW V_CPU RAM_MB RAM_GB FLAVOR_NAME EXTRA_SPECS
  FLAVOR_RAW=$(curl -s -X GET "https://kr1-api-instance-infrastructure.nhncloudservice.com/v2/$T_ID/flavors/$FLAVOR_ID" \
    -H "X-Auth-Token: $OS_TOKEN")

  V_CPU=$(echo "$FLAVOR_RAW" | jq -r '.flavor.vcpus // "0"')
  RAM_MB=$(echo "$FLAVOR_RAW" | jq -r '.flavor.ram // "0"')
  RAM_GB=$(( RAM_MB / 1024 ))
  FLAVOR_NAME=$(echo "$FLAVOR_RAW" | jq -r '.flavor.name // empty' 2>/dev/null || true)
  EXTRA_SPECS=$(echo "$FLAVOR_RAW" | jq -c '.flavor."OS-FLV-EXT-DATA:extra_specs" // {}' 2>/dev/null || echo "{}")

  # Volume
  local V_TYPE V_SIZE
  V_TYPE="조회실패"
  V_SIZE="0"
  if [ -n "${V_ID:-}" ]; then
    local V_RAW
    V_RAW=$(curl -s -X GET "https://kr1-api-block-storage-infrastructure.nhncloudservice.com/v2/$T_ID/volumes/$V_ID" \
      -H "X-Auth-Token: $OS_TOKEN")
    V_TYPE=$(echo "$V_RAW" | jq -r '.volume.volume_type // "N/A"')
    V_SIZE=$(echo "$V_RAW" | jq -r '.volume.size // "0"')
  fi

  # 정책 검증
  local FAIL_REASON=""
  [ "$V_CPU"   != "$EXP_VCPU"    ] && FAIL_REASON+="CPU(${V_CPU}!=${EXP_VCPU}) "
  [ "$RAM_GB"  != "$EXP_RAM_GB"  ] && FAIL_REASON+="RAM(${RAM_GB}!=${EXP_RAM_GB}GB) "
  [ "$V_SIZE"  != "$EXP_DISK_GB" ] && FAIL_REASON+="DISK(${V_SIZE}!=${EXP_DISK_GB}GB) "

  if [ -n "$EXP_GPU_TAG" ]; then
    local GPU_MATCH="no"
    if echo "${FLAVOR_NAME,,}"  | grep -q "${EXP_GPU_TAG,,}"; then GPU_MATCH="yes"; fi
    if echo "${EXTRA_SPECS,,}"  | grep -q "${EXP_GPU_TAG,,}"; then GPU_MATCH="yes"; fi
    [ "$GPU_MATCH" != "yes" ] && FAIL_REASON+="GPU_TAG(${EXP_GPU_TAG} not found) "
  fi

  # 리포트 (PASS/FAIL 모두 전송)
  local HEADER STATUS
  if [ -n "$FAIL_REASON" ]; then
    STATUS="❌ FAIL"
    HEADER="❌ [스펙 불일치] $S_NAME ($TYPE) : $FAIL_REASON"
  else
    STATUS="✅ PASS"
    HEADER="✅ [스펙 일치] $S_NAME ($TYPE)"
  fi

  local REPORT
  REPORT="$HEADER
────────────────
⚙️ CPU: ${V_CPU} Core (정책 ${EXP_VCPU})
🧠 RAM: ${RAM_GB} GB (정책 ${EXP_RAM_GB})
💾 Disk: $V_TYPE / ${V_SIZE}GB (정책 ${EXP_DISK_GB})
🏷️ Flavor: ${FLAVOR_NAME:-N/A}
📍 IP: $ACTUAL_IP
🛡️ SG: $ACTUAL_SG"

  echo "$STATUS $S_NAME"
  send_kakao "$REPORT"
}

echo "🚀 user* 인스턴스 자동 탐색 → cpu/gpu/win 스펙 검증 시작..."

# ----------------------------
# 1) 전체 서버 목록 조회
#    (이 API는 limit/pagination이 있을 수 있음. 필요 시 marker/next 처리 추가 가능)
# ----------------------------
ALL=$(curl -s -X GET "https://kr1-api-instance-infrastructure.nhncloudservice.com/v2/$T_ID/servers" \
  -H "X-Auth-Token: $OS_TOKEN")

# ----------------------------
# 2) 이름이 test로 시작하고, testXX-(cpu|gpu|win) 패턴만 필터
# ----------------------------
echo "$ALL" \
  | jq -r '
      .servers[]
      | select(.name | test("^test[0-9]+-(cpu|gpu|win)$"))
      | "\(.id) \(.name)"
    ' \
  | while read -r SID SNAME; do
      # TYPE 추출: cpu/gpu/win
      TYPE="${SNAME##*-}"
      check_one_server "$SID" "$SNAME" "$TYPE"
    done

