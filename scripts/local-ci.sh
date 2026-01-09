#!/bin/bash
# =============================================================================
# Velo Local CI Script
# =============================================================================
# Run CI locally (macOS) or in Docker (Ubuntu simulation)
#
# BEST PRACTICES:
# 1. FAIL FAST: Environment checks run FIRST
# 2. DRY: Uses shared ci-common.sh library
# 3. MODULAR: Separate phases that can be run individually

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

# Source common library
source "$SCRIPT_DIR/ci-common.sh"

# =============================================================================
# Configuration
# =============================================================================
IMAGE_NAME="velo-ci-optimized"
DOCKERFILE="Dockerfile.test"

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
    echo "  --build      Build Docker image only"
    echo "  --shell      Interactive Docker shell for debugging"
    echo "  --quick      Quick local check (build + unit tests only)"
    echo "  --check      Environment check only (fail fast)"
    echo "  --help       Show this help"
    echo ""
    echo "Examples:"
    echo "  $0                 # Full local CI"
    echo "  $0 --docker        # Simulate Ubuntu CI"
    echo "  $0 --check         # Quick environment validation"
}

# =============================================================================
# Docker Functions
# =============================================================================
docker_build() {
    log_step "Building Docker image..."
    docker build -t "$IMAGE_NAME" -f "$DOCKERFILE" .
    log_success "Docker image built"
}

docker_run() {
    # Ensure image exists
    if ! docker image inspect "$IMAGE_NAME" &>/dev/null; then
        docker_build
    fi
    
    log_step "Running CI in Docker (Ubuntu 22.04)..."
    docker run --rm \
        -v "$PROJECT_ROOT:/workspace" \
        -e GITHUB_ACTIONS=true \
        "$IMAGE_NAME"
}

docker_shell() {
    # Ensure image exists
    if ! docker image inspect "$IMAGE_NAME" &>/dev/null; then
        docker_build
    fi
    
    log_step "Starting interactive Docker shell..."
    docker run --rm -it \
        -v "$PROJECT_ROOT:/workspace" \
        -e GITHUB_ACTIONS=true \
        "$IMAGE_NAME" \
        bash
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
    
    # Run full CI pipeline
    run_full_ci ".venv" "tests/qa/test_phase6_2_env_pollution.py tests/qa/test_phase6_2_regression.py"
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
