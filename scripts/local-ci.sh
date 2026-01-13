#!/bin/bash
# =============================================================================
# Velo Local CI Script
# =============================================================================
# Run CI locally (macOS) or in Docker (Ubuntu simulation)
#
# Docker CI uses a single base image + volume caching for incremental builds:
# - velo-ci-base: Contains Rust, Python 3.11, uv
# - velo-cargo-cache: Persists compiled dependencies between runs
# - velo-cargo-registry: Persists Cargo registry cache

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

# Source common library
source "$SCRIPT_DIR/ci-common.sh"

# =============================================================================
# Configuration
# =============================================================================
IMAGE_NAME="velo-ci-base"
DOCKERFILE="Dockerfile.base"

# Docker volumes for caching
CARGO_CACHE="velo-cargo-cache"
CARGO_REGISTRY="velo-cargo-registry"

# =============================================================================
# Usage
# =============================================================================
print_usage() {
    echo "Velo Local CI"
    echo ""
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  (no args)    Run full CI locally (macOS)"
    echo "  --docker     Run full CI in Docker (Ubuntu simulation)"
    echo "  --build      Build Docker base image"
    echo "  --shell      Interactive Docker shell for debugging"
    echo "  --quick      Quick local check (build + unit tests only)"
    echo "  --check      Environment check only (fail fast)"
    echo "  --clean      Clean Docker volumes (fresh start)"
    echo "  --help       Show this help"
    echo ""
    echo "Examples:"
    echo "  $0                 # Full local CI"
    echo "  $0 --docker        # Simulate Ubuntu CI"
    echo "  $0 --check         # Quick environment validation"
    echo "  $0 --clean         # Reset Docker caches"
}

# =============================================================================
# Docker Functions
# =============================================================================
docker_build() {
    log_step "Building Docker base image..."
    docker build -t "$IMAGE_NAME" -f "$DOCKERFILE" .
    log_success "Docker image built"
}

docker_run() {
    # Ensure image exists
    if ! docker image inspect "$IMAGE_NAME" &>/dev/null; then
        docker_build
    fi
    
    log_step "Running CI in Docker (Ubuntu + Python 3.11)..."
    docker run --rm \
        -v "$PROJECT_ROOT:/workspace" \
        -v "$CARGO_CACHE:/workspace/target" \
        -v "$CARGO_REGISTRY:/root/.cargo/registry" \
        -e GITHUB_ACTIONS=true \
        -e UV_PYTHON=python3.11 \
        "$IMAGE_NAME" \
        bash -c '
            echo "🚀 Velo CI (Docker)"
            echo ""
            echo "==================== Phase 1: Build ===================="
            cargo build --release
            echo ""
            echo "==================== Phase 2: Setup Python ===================="
            uv venv --python 3.11 .venv
            source .venv/bin/activate
            uv sync
            echo ""
            echo "==================== Phase 3: Pre-Flight ===================="
            ./target/release/velo debug pre-flight || true
            echo ""
            echo "==================== Phase 4: Test ===================="
            source scripts/ci-common.sh
            pytest tests/qa -v --tb=short
            echo ""
            echo "=========================================="
            echo "✅ ALL CI CHECKS PASSED!"
            echo "=========================================="
        '
}

docker_shell() {
    # Ensure image exists
    if ! docker image inspect "$IMAGE_NAME" &>/dev/null; then
        docker_build
    fi
    
    log_step "Starting interactive Docker shell..."
    docker run --rm -it \
        -v "$PROJECT_ROOT:/workspace" \
        -v "$CARGO_CACHE:/workspace/target" \
        -v "$CARGO_REGISTRY:/root/.cargo/registry" \
        -e GITHUB_ACTIONS=true \
        -e UV_PYTHON=python3.11 \
        "$IMAGE_NAME" \
        bash
}

docker_clean() {
    log_step "Cleaning Docker volumes..."
    docker volume rm -f "$CARGO_CACHE" "$CARGO_REGISTRY" 2>/dev/null || true
    log_success "Docker volumes cleaned"
}

# =============================================================================
# Local CI Functions
# =============================================================================
run_local_ci() {
    echo ""
    echo "🚀 Velo Local CI (macOS)"
    echo "========================"
    echo ""
    
    # Phase 0: FAIL FAST environment check
    check_env_fast
    
    # Run full CI pipeline with SSOT test paths
    run_full_ci ".venv" "tests/qa"
}

run_quick_check() {
    echo ""
    echo "⚡ Velo Quick Check"
    echo "==================="
    echo ""
    
    # Phase 0: FAIL FAST environment check
    check_env_fast
    
    # Quick build + test only
    log_step "Quick build..."
    cargo build --release
    
    log_step "Quick test..."
    cargo test --lib
    
    echo ""
    log_success "Quick check passed!"
}

# =============================================================================
# Main
# =============================================================================
case "${1:-}" in
    --docker)
        export CHECK_DOCKER=true
        check_env_fast
        docker_run
        ;;
    --build)
        export CHECK_DOCKER=true
        check_env_fast
        docker_build
        ;;
    --shell)
        export CHECK_DOCKER=true
        check_env_fast
        docker_shell
        ;;
    --clean)
        docker_clean
        ;;
    --quick)
        run_quick_check
        ;;
    --check)
        check_env_fast
        ;;
    --help|-h)
        print_usage
        ;;
    "")
        run_local_ci
        ;;
    *)
        log_error "Unknown option: $1"
        print_usage
        exit 1
        ;;
esac
