#!/usr/bin/env bash
# MedScribe -- full pipeline load test wrapper
#
# Runs the k6 script in tests/load/pipeline_test.js against the Go gateway.
#
# Usage:
#   ./scripts/load-test.sh
#   ./scripts/load-test.sh --url http://127.0.0.1:8080 --vus 10 --duration 5m

set -euo pipefail

BASE_URL="http://localhost:8080"
VUS="10"
DURATION="5m"
ARTIFACTS_DIR=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --url) BASE_URL="$2"; shift 2 ;;
    --vus) VUS="$2"; shift 2 ;;
    --duration) DURATION="$2"; shift 2 ;;
    --artifacts-dir) ARTIFACTS_DIR="$2"; shift 2 ;;
    -h|--help)
      echo "Usage: $0 [--url URL] [--vus N] [--duration T] [--artifacts-dir DIR]"
      echo ""
      echo "Options:"
      echo "  --url       Gateway base URL   (default: http://localhost:8080)"
      echo "  --vus       Max virtual users  (default: 10)"
      echo "  --duration  Test duration      (default: 5m)"
      echo "  --artifacts-dir  Output directory for raw benchmark artifacts"
      exit 0
      ;;
    *)
      echo "Unknown option: $1"
      exit 1
      ;;
  esac
done

if ! command -v k6 >/dev/null 2>&1; then
  echo "ERROR: k6 not found. Install it first."
  echo "  macOS: brew install k6"
  echo "  Linux: https://grafana.com/docs/k6/latest/set-up/install-k6/"
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
K6_SCRIPT="${SCRIPT_DIR}/../tests/load/pipeline_test.js"

SUMMARY_EXPORT_ARGS=()
TEE_ARGS=()
if [[ -n "$ARTIFACTS_DIR" ]]; then
  mkdir -p "$ARTIFACTS_DIR"
  SUMMARY_FILE="${ARTIFACTS_DIR%/}/k6-summary.json"
  LOG_FILE="${ARTIFACTS_DIR%/}/console.log"
  METADATA_FILE="${ARTIFACTS_DIR%/}/run-metadata.txt"
  SUMMARY_EXPORT_ARGS=(--summary-export "$SUMMARY_FILE")
  TEE_ARGS=(tee "$LOG_FILE")

  {
    echo "benchmark=full-pipeline-load"
    echo "date=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "base_url=${BASE_URL}"
    echo "vus=${VUS}"
    echo "duration=${DURATION}"
    echo "host_os=$(uname -s)"
    echo "host_arch=$(uname -m)"
  } > "$METADATA_FILE"
fi

echo "=== MedScribe Full Pipeline Load Test ==="
echo "Gateway:  ${BASE_URL}"
echo "VUs:      ${VUS}"
echo "Duration: ${DURATION}"
if [[ -n "$ARTIFACTS_DIR" ]]; then
  echo "Artifacts: ${ARTIFACTS_DIR}"
fi
echo ""

if [[ -n "$ARTIFACTS_DIR" ]]; then
  k6 run \
    "${SUMMARY_EXPORT_ARGS[@]}" \
    --env BASE_URL="${BASE_URL}" \
    --env VUS="${VUS}" \
    --env DURATION="${DURATION}" \
    "${K6_SCRIPT}" 2>&1 | "${TEE_ARGS[@]}"
else
  k6 run \
    --env BASE_URL="${BASE_URL}" \
    --env VUS="${VUS}" \
    --env DURATION="${DURATION}" \
    "${K6_SCRIPT}"
fi
