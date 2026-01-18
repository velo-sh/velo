#!/usr/bin/env bash
# =============================================================================
# Velo Docker CI Runner
# =============================================================================
# Run local CI in a Linux container (simulates GitHub Actions)
#
# Usage:
#   ./scripts/docker-ci.sh           # Run full CI
#   ./scripts/docker-ci.sh --shell   # Interactive shell for debugging
#   ./scripts/docker-ci.sh --build   # Just rebuild images
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Image names
BASE_IMAGE="velo-ci-base"
CI_IMAGE="velo-ci"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() { echo -e "${BLUE}ℹ${NC} $1"; }
log_success() { echo -e "${GREEN}✓${NC} $1"; }
log_warn() { echo -e "${YELLOW}⚠${NC} $1"; }
log_error() { echo -e "${RED}✗${NC} $1"; }

# Check Docker
check_docker() {
    if ! command -v docker &> /dev/null; then
        log_error "Docker is not installed. Please install Docker first."
        exit 1
    fi
    
    if ! docker info &> /dev/null; then
        log_error "Docker daemon is not running. Please start Docker."
        exit 1
    fi
}

# Build base image if needed
build_base() {
    if ! docker image inspect "$BASE_IMAGE" &> /dev/null; then
        log_info "Building base image (first time only)..."
        DOCKER_BUILDKIT=1 docker build \
            -t "$BASE_IMAGE" \
            -f "$PROJECT_ROOT/Dockerfile.base" \
            "$PROJECT_ROOT"
        log_success "Base image built: $BASE_IMAGE"
    else
        log_info "Base image exists: $BASE_IMAGE"
    fi
}

# Build CI image
build_ci() {
    log_info "Building CI image..."
    DOCKER_BUILDKIT=1 docker build \
        -t "$CI_IMAGE" \
        -f "$PROJECT_ROOT/Dockerfile.ci" \
        "$PROJECT_ROOT"
    log_success "CI image built: $CI_IMAGE"
}

# Run CI
run_ci() {
    log_info "Running CI in Docker container..."
    echo ""
    
    # NOTE: We use anonymous volumes for target/ and .venv/ to prevent
    # host's macOS binaries from overwriting container's Linux binaries
    docker run --rm \
        -v "$PROJECT_ROOT:/workspace:delegated" \
        -v /workspace/target \
        -v /workspace/.venv \
        -e GITHUB_ACTIONS=true \
        -e CI=true \
        -e VELO_ENV=ci \
        "$CI_IMAGE" \
        bash scripts/local-ci.sh
}

# Interactive shell
run_shell() {
    log_info "Starting interactive shell..."
    docker run --rm -it \
        -v "$PROJECT_ROOT:/workspace:delegated" \
        -v /workspace/target \
        -v /workspace/.venv \
        -e GITHUB_ACTIONS=true \
        -e CI=true \
        -e VELO_ENV=ci \
        "$CI_IMAGE" \
        bash
}

# Main
main() {
    cd "$PROJECT_ROOT"
    check_docker
    
    case "${1:-}" in
        --shell|-s)
            build_base
            build_ci
            run_shell
            ;;
        --build|-b)
            build_base
            build_ci
            log_success "Images ready!"
            ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  (none)      Run full CI suite"
            echo "  --shell     Open interactive shell"
            echo "  --build     Build images only"
            echo "  --help      Show this help"
            ;;
        *)
            build_base
            build_ci
            run_ci
            ;;
    esac
}

main "$@"
