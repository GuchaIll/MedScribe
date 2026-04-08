#!/usr/bin/env bash
# scripts/generate-proto.sh
#
# Compiles all .proto definitions into Go stubs under proto/gen/go/.
# The generated directory forms the shared Go module  github.com/medscribe/proto
# imported by every Go service (api, orchestrator, ingest, …).
#
# Requirements:
#   protoc      — brew install protobuf  |  apt install -y protobuf-compiler
#   Go 1.24+    — protoc-gen-go and protoc-gen-go-grpc are auto-installed below
#
# Usage:
#   ./scripts/generate-proto.sh           # generate + tidy
#   SKIP_TIDY=1 ./scripts/generate-proto.sh  # skip go mod tidy (offline / CI)
set -euo pipefail

# ─── paths ────────────────────────────────────────────────────────────────────
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROTO_DIR="${REPO_ROOT}/proto"
OUT_DIR="${REPO_ROOT}/proto/gen/go"

# ─── pinned plugin versions ───────────────────────────────────────────────────
PROTOC_GEN_GO_VERSION="v1.36.6"
PROTOC_GEN_GO_GRPC_VERSION="v1.5.1"

# ─── colour helpers ───────────────────────────────────────────────────────────
green()  { printf '\033[0;32m%s\033[0m\n' "$*"; }
yellow() { printf '\033[0;33m%s\033[0m\n' "$*"; }
red()    { printf '\033[0;31m%s\033[0m\n' "$*"; }
die()    { red "ERROR: $*"; exit 1; }

# Put Go-installed binaries on PATH for the duration of this script.
export PATH="${GOPATH:-$(go env GOPATH)}/bin:${PATH}"

# ─── dependency checks ────────────────────────────────────────────────────────
ensure_protoc() {
  if ! command -v protoc &>/dev/null; then
    die "protoc not found.
  macOS  : brew install protobuf
  Debian : apt install -y protobuf-compiler
  Manual : https://grpc.io/docs/protoc-installation/"
  fi
  yellow "  protoc              : $(protoc --version)"
}

# install go plugin if the binary is absent; never downgrades automatically.
ensure_go_plugin() {
  local name="$1"
  local pkg="$2"
  local version="$3"

  if ! command -v "${name}" &>/dev/null; then
    yellow "  ${name}: not found — installing ${pkg}@${version}"
    go install "${pkg}@${version}"
  fi
  yellow "  ${name}  : $(${name} --version 2>&1 | head -1)"
}

green "==> checking dependencies"
ensure_protoc
ensure_go_plugin \
  protoc-gen-go \
  google.golang.org/protobuf/cmd/protoc-gen-go \
  "${PROTOC_GEN_GO_VERSION}"
ensure_go_plugin \
  protoc-gen-go-grpc \
  google.golang.org/grpc/cmd/protoc-gen-go-grpc \
  "${PROTOC_GEN_GO_GRPC_VERSION}"

# ─── clean output directory ───────────────────────────────────────────────────
green "==> cleaning proto/gen/go/"
rm -rf "${OUT_DIR}"
mkdir -p "${OUT_DIR}"

# ─── protoc invocation ────────────────────────────────────────────────────────
# --proto_path is set to proto/ so that cross-package imports such as
#   import "common/v1/types.proto"
# resolve correctly from every .proto file regardless of its location.
#
# paths=source_relative mirrors the directory structure under proto/:
#   common/v1/types.proto  →  proto/gen/go/common/v1/types.pb.go
# This avoids the long github.com/… prefix that the default paths=import creates.
green "==> running protoc"
protoc \
  --proto_path="${PROTO_DIR}" \
  --go_out="${OUT_DIR}" \
  --go_opt=paths=source_relative \
  --go-grpc_out="${OUT_DIR}" \
  --go-grpc_opt=paths=source_relative \
  common/v1/types.proto \
  common/v1/health.proto \
  ingest/v1/ingest.proto \
  orchestrator/v1/orchestrator.proto \
  auth/v1/auth.proto

# ─── print manifest ───────────────────────────────────────────────────────────
green "==> generated files"
find "${OUT_DIR}" -name "*.go" | sort | while IFS= read -r f; do
  printf "    %s\n" "${f#"${REPO_ROOT}/"}"
done

# ─── bootstrap / tidy the shared proto Go module ─────────────────────────────
# This module is imported by every Go service.
# Local development: each service go.mod carries a replace directive, e.g.
#   replace github.com/medscribe/proto => ../../proto/gen/go
# CI / production: tag and publish github.com/medscribe/proto vX.Y.Z instead.
PROTO_MOD="${OUT_DIR}/go.mod"

if [[ ! -f "${PROTO_MOD}" ]]; then
  green "==> initialising proto/gen/go/go.mod"
  (
    cd "${OUT_DIR}"
    go mod init github.com/medscribe/proto
  )
fi

if [[ "${SKIP_TIDY:-0}" != "1" ]]; then
  green "==> tidying proto/gen/go/go.mod"
  (cd "${OUT_DIR}" && go mod tidy)
fi

green "==> done — stubs are in proto/gen/go/"
