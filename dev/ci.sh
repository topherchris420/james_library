#!/usr/bin/env bash
set -euo pipefail

if [ -f "dev/docker-compose.ci.yml" ]; then
  COMPOSE_FILE="dev/docker-compose.ci.yml"
elif [ -f "docker-compose.ci.yml" ] && [ "$(basename "$(pwd)")" = "dev" ]; then
  COMPOSE_FILE="docker-compose.ci.yml"
else
  echo "❌ Run this script from repo root or dev/ directory."
  exit 1
fi

compose_cmd=(docker compose -f "$COMPOSE_FILE")
SMOKE_CACHE_DIR="${SMOKE_CACHE_DIR:-.cache/buildx-smoke}"

run_in_ci() {
  local cmd="$1"
  "${compose_cmd[@]}" run --rm local-ci bash -c "$cmd"
}

build_smoke_image() {
  if docker buildx version >/dev/null 2>&1; then
    mkdir -p "$SMOKE_CACHE_DIR"
    local build_args=(
      --load
      --target dev
      --cache-to "type=local,dest=$SMOKE_CACHE_DIR,mode=max"
      -t R.A.I.N.-local-smoke:latest
      .
    )
    if [ -f "$SMOKE_CACHE_DIR/index.json" ]; then
      build_args=(--cache-from "type=local,src=$SMOKE_CACHE_DIR" "${build_args[@]}")
    fi
    docker buildx build "${build_args[@]}"
  else
    DOCKER_BUILDKIT=1 docker build --target dev -t R.A.I.N.-local-smoke:latest .
  fi
}

print_help() {
  cat <<'EOF'
R.A.I.N. Local CI in Docker

Usage: ./dev/ci.sh <command>

Commands:
  build-image     Build/update the local CI image
  shell           Open an interactive shell inside the CI container
  rust            Run the canonical Rust quality gate in the CI container
  python          Run the canonical Python quality gate in the CI container
  web             Run the canonical web quality gate in the CI container
  governance      Run the canonical governance/docs quality gate in the CI container
  lint            Alias for rust
  lint-strict     Run rustfmt + full clippy warnings gate (container only)
  lint-delta      Run strict lint delta gate on changed Rust lines (container only)
  test            Run the canonical Rust test gate (container only)
  test-component  Run component tests only
  test-integration Run integration tests only
  test-system     Run system tests only
  test-live       Run live tests (requires credentials)
  test-manual     Run manual test scripts (dockerignore, etc.)
  build           Run the canonical Rust build smoke gate (container only)
  audit           Run cargo audit (container only)
  deny            Run cargo deny check (container only)
  security        Run cargo audit + cargo deny (container only)
  docker-smoke    Build and verify runtime image (host docker daemon)
  all             Run rust, python, web, governance, and docker-smoke gates
  clean           Remove local CI containers and volumes
EOF
}

if [ $# -lt 1 ]; then
  print_help
  exit 1
fi

case "$1" in
  build-image)
    "${compose_cmd[@]}" build local-ci
    ;;

  shell)
    "${compose_cmd[@]}" run --rm local-ci bash
    ;;

  rust|lint)
    run_in_ci "bash ./scripts/ci/quality_gate.sh rust"
    ;;

  lint-strict)
    run_in_ci "./scripts/ci/rust_quality_gate.sh --strict"
    ;;

  lint-delta)
    run_in_ci "./scripts/ci/rust_strict_delta_gate.sh"
    ;;

  python)
    run_in_ci "bash ./scripts/ci/quality_gate.sh python"
    ;;

  web)
    run_in_ci "bash ./scripts/ci/quality_gate.sh web"
    ;;

  governance)
    run_in_ci "bash ./scripts/ci/quality_gate.sh governance"
    ;;

  test)
    run_in_ci "bash ./scripts/ci/quality_gate.sh rust"
    ;;

  test-component)
    run_in_ci "cargo test --test component --locked --verbose"
    ;;

  test-integration)
    run_in_ci "cargo test --test integration --locked --verbose"
    ;;

  test-system)
    run_in_ci "cargo test --test system --locked --verbose"
    ;;

  test-live)
    run_in_ci "cargo test --test live -- --ignored --verbose"
    ;;

  test-manual)
    run_in_ci "bash tests/manual/test_dockerignore.sh"
    ;;

  build)
    run_in_ci "bash ./scripts/ci/quality_gate.sh rust"
    ;;

  audit)
    run_in_ci "cargo audit"
    ;;

  deny)
    run_in_ci "cargo deny check licenses sources"
    ;;

  security)
    run_in_ci "cargo deny check licenses sources"
    run_in_ci "cargo audit"
    ;;

  docker-smoke)
    build_smoke_image
    docker run --rm R.A.I.N.-local-smoke:latest --version
    ;;

  all)
    run_in_ci "bash ./scripts/ci/quality_gate.sh all"
    build_smoke_image
    docker run --rm R.A.I.N.-local-smoke:latest --version
    ;;

  clean)
    "${compose_cmd[@]}" down -v --remove-orphans
    ;;

  *)
    print_help
    exit 1
    ;;
esac
