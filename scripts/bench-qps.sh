#!/usr/bin/env bash
# MedScribe -- Ingestion QPS Benchmark
#
# Measures how many pipeline-trigger requests per second the Go gateway can
# accept and enqueue to Kafka. Does NOT measure pipeline completion latency.
#
# Usage:
#   ./scripts/bench-qps.sh                     # defaults: 500 QPS, 30s
#   ./scripts/bench-qps.sh --qps 200 --duration 1m
#   ./scripts/bench-qps.sh --url http://host:8080 --sessions 200
#
# Prerequisites:
#   - k6 installed (brew install k6)
#   - Docker services running (docker compose up -d)

set -euo pipefail

# ── Defaults ────────────────────────────────────────────────────────────────
BASE_URL="http://localhost:8080"
TARGET_QPS=500
DURATION="30s"
MAX_VUS=200
NUM_SESSIONS=100
EMAIL=""
PASSWORD=""

# ── Parse args ──────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --url)       BASE_URL="$2";      shift 2 ;;
    --qps)       TARGET_QPS="$2";    shift 2 ;;
    --duration)  DURATION="$2";      shift 2 ;;
    --vus)       MAX_VUS="$2";       shift 2 ;;
    --sessions)  NUM_SESSIONS="$2";  shift 2 ;;
    --email)     EMAIL="$2";         shift 2 ;;
    --password)  PASSWORD="$2";      shift 2 ;;
    -h|--help)
      echo "Usage: $0 [--url URL] [--qps N] [--duration T] [--vus N] [--sessions N] [--email E] [--password P]"
      echo ""
      echo "Options:"
      echo "  --url        Gateway base URL          (default: http://localhost:8080)"
      echo "  --qps        Target requests/sec        (default: 500)"
      echo "  --duration   Sustained load duration     (default: 30s)"
      echo "  --vus        Max virtual users           (default: 200)"
      echo "  --sessions   Pre-created sessions count  (default: 100)"
      echo "  --email      Test user email             (auto-generated if omitted)"
      echo "  --password   Test user password           (auto-generated if omitted)"
      exit 0
      ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
K6_SCRIPT="${SCRIPT_DIR}/qps_bench.js"
SESSIONS_FILE=$(mktemp /tmp/medscribe_sessions_XXXXXX.json)
trap 'rm -f "$SESSIONS_FILE"' EXIT

# ── Preflight checks ───────────────────────────────────────────────────────
echo "=== MedScribe Ingestion QPS Benchmark ==="
echo ""

if ! command -v k6 &>/dev/null; then
  echo "ERROR: k6 not found. Install with: brew install k6"
  exit 1
fi

if ! command -v curl &>/dev/null; then
  echo "ERROR: curl not found."
  exit 1
fi

if ! command -v jq &>/dev/null; then
  echo "ERROR: jq not found. Install with: brew install jq"
  exit 1
fi

# Check gateway is reachable
if ! curl -sf "${BASE_URL}/healthz" -o /dev/null 2>/dev/null; then
  # Try without healthz in case it doesn't exist
  if ! curl -sf -o /dev/null -w '' "${BASE_URL}/api/auth/login" -X POST -d '{}' -H 'Content-Type: application/json' 2>/dev/null; then
    echo "WARNING: Gateway at ${BASE_URL} may not be reachable. Continuing anyway..."
  fi
fi

echo "Config:"
echo "  Gateway:    ${BASE_URL}"
echo "  Target QPS: ${TARGET_QPS}"
echo "  Duration:   ${DURATION} (+ 10s warm-up)"
echo "  Max VUs:    ${MAX_VUS}"
echo "  Sessions:   ${NUM_SESSIONS}"
echo ""

# ── Register + Login ────────────────────────────────────────────────────────
echo "-- Setting up test user..."

UNIQUE_ID="qps_$(date +%s)_${RANDOM}"
if [[ -z "$EMAIL" ]]; then
  EMAIL="${UNIQUE_ID}@bench.local"
fi
if [[ -z "$PASSWORD" ]]; then
  PASSWORD="BenchQPS!2024Secure"
fi

REG_RESPONSE=$(curl -sf -X POST "${BASE_URL}/api/auth/register" \
  -H 'Content-Type: application/json' \
  -d "{\"email\":\"${EMAIL}\",\"password\":\"${PASSWORD}\",\"full_name\":\"QPS Benchmark\",\"role\":\"doctor\",\"occupation\":\"benchmark\"}" \
  2>&1) || true

# Login (works even if registration failed because user already exists)
LOGIN_RESPONSE=$(curl -sf -X POST "${BASE_URL}/api/auth/login" \
  -H 'Content-Type: application/json' \
  -d "{\"email\":\"${EMAIL}\",\"password\":\"${PASSWORD}\"}")

if [[ -z "$LOGIN_RESPONSE" ]]; then
  echo "ERROR: Login failed. Check that the gateway is running and credentials are valid."
  echo "  Tried: email=${EMAIL}"
  exit 1
fi

TOKEN=$(echo "$LOGIN_RESPONSE" | jq -r '.access_token // empty')
if [[ -z "$TOKEN" ]]; then
  echo "ERROR: Could not extract access_token from login response:"
  echo "$LOGIN_RESPONSE"
  exit 1
fi

echo "  Authenticated as: ${EMAIL}"
echo ""

# ── Pre-create sessions ────────────────────────────────────────────────────
echo "-- Pre-creating ${NUM_SESSIONS} sessions..."

SESSION_IDS=()
FAIL_COUNT=0

for i in $(seq 1 "$NUM_SESSIONS"); do
  RESP=$(curl -sf -X POST "${BASE_URL}/api/session/start" \
    -H "Authorization: Bearer ${TOKEN}" \
    -H 'Content-Type: application/json' 2>/dev/null) || true

  SID=$(echo "$RESP" | jq -r '.session_id // empty' 2>/dev/null)
  if [[ -n "$SID" ]]; then
    SESSION_IDS+=("\"${SID}\"")
  else
    FAIL_COUNT=$((FAIL_COUNT + 1))
  fi

  # Progress indicator every 25 sessions
  if (( i % 25 == 0 )); then
    echo "  Created ${i}/${NUM_SESSIONS} sessions..."
  fi
done

CREATED=${#SESSION_IDS[@]}
if [[ "$CREATED" -eq 0 ]]; then
  echo "ERROR: Failed to create any sessions. Check gateway logs."
  exit 1
fi

echo "  Created ${CREATED} sessions (${FAIL_COUNT} failed)"
echo ""

# Write sessions JSON
IFS=','
echo "[${SESSION_IDS[*]}]" > "$SESSIONS_FILE"
unset IFS

# ── Pre-warm gateway ───────────────────────────────────────────────────────
# Fire ~200 trigger requests in parallel to populate the session cache, warm
# the PG connection pool, and prime the Kafka producer buffer. These are
# discarded from the benchmark -- their only purpose is to avoid cold-start
# outliers skewing the k6 metrics.
PREWARM_COUNT=200
echo "-- Pre-warming gateway with ${PREWARM_COUNT} requests..."

PAYLOAD='{"session_id":"PLACEHOLDER","patient_id":"prewarm","doctor_id":"prewarm","is_new_patient":true,"segments":[{"start":0,"end":3,"speaker":"doctor","raw_text":"Warm-up request","cleaned_text":"Warm-up request","confidence":"0.9"}]}'

PREWARM_OK=0
PREWARM_FAIL=0
for i in $(seq 1 "$PREWARM_COUNT"); do
  # Round-robin across sessions
  IDX=$(( (i - 1) % CREATED ))
  SID_RAW=$(echo "${SESSION_IDS[$IDX]}" | tr -d '"')
  BODY=$(echo "$PAYLOAD" | sed "s/PLACEHOLDER/${SID_RAW}/")

  HTTP_CODE=$(curl -sf -o /dev/null -w '%{http_code}' -X POST \
    "${BASE_URL}/api/session/${SID_RAW}/pipeline" \
    -H "Authorization: Bearer ${TOKEN}" \
    -H 'Content-Type: application/json' \
    -d "$BODY" 2>/dev/null) || HTTP_CODE="000"

  if [[ "$HTTP_CODE" == "202" ]]; then
    PREWARM_OK=$((PREWARM_OK + 1))
  else
    PREWARM_FAIL=$((PREWARM_FAIL + 1))
  fi
done
echo "  Pre-warm: ${PREWARM_OK} accepted, ${PREWARM_FAIL} failed"
# Brief pause to let Kafka flush the pre-warm messages
sleep 2
echo ""

# ── Run k6 ──────────────────────────────────────────────────────────────────
echo "-- Running k6 QPS benchmark..."
echo "   Target: ${TARGET_QPS} req/s for ${DURATION} after 10s warm-up"
echo ""

k6 run \
  --env BASE_URL="${BASE_URL}" \
  --env AUTH_TOKEN="${TOKEN}" \
  --env SESSIONS_FILE="${SESSIONS_FILE}" \
  --env TARGET_QPS="${TARGET_QPS}" \
  --env DURATION="${DURATION}" \
  --env MAX_VUS="${MAX_VUS}" \
  "$K6_SCRIPT"

echo ""
echo "=== Benchmark complete ==="
echo ""
echo "Key metrics to check above:"
echo "  trigger_latency_ms  -- p50/p95/p99 enqueue latency"
echo "  trigger_success_rate -- fraction of 202 responses"
echo "  http_reqs           -- actual achieved QPS (total / duration)"
echo "  iterations          -- total completed trigger requests"
echo ""
echo "If trigger_success_rate < 99%:"
echo "  - Check docker compose logs gateway for connection pool or Kafka errors"
echo "  - Check docker compose logs kafka for broker saturation"
echo "  - Check docker compose logs redis for memory or connection limits"
