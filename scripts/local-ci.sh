#!/bin/bash
# Local CI Simulation Script
# ==========================
# Run GitHub Actions CI locally using Docker.
#
# Usage:
#   ./scripts/local-ci.sh           # Run full CI
#   ./scripts/local-ci.sh --build   # Just build the image
#   ./scripts/local-ci.sh --shell   # Interactive shell for debugging

set -euo pipefail

IMAGE_NAME="velo-ci-ubuntu"
DOCKERFILE="Dockerfile.ci"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

print_usage() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  --build    Build the CI Docker image only"
    echo "  --shell    Start interactive shell for debugging"
    echo "  --quick    Run quick tests only (skip full CI suite)"
    echo "  --help     Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0              # Run full CI simulation"
    echo "  $0 --shell      # Debug in Ubuntu container"
}

build_image() {
    echo -e "${YELLOW}🔨 Building CI Docker image...${NC}"
    docker build -t "$IMAGE_NAME" -f "$DOCKERFILE" .
    echo -e "${GREEN}✅ Image built successfully${NC}"
}

run_ci() {
    echo -e "${YELLOW}🚀 Running Local CI Simulation (Ubuntu 22.04)${NC}"
    echo ""
    
    # Check if image exists, build if not
    if ! docker image inspect "$IMAGE_NAME" &>/dev/null; then
        build_image
    fi
    
    docker run --rm \
        -v "$(pwd):/workspace" \
        -e GITHUB_ACTIONS=true \
        "$IMAGE_NAME"
}

run_shell() {
    echo -e "${YELLOW}🐚 Starting interactive shell...${NC}"
    
    # Check if image exists, build if not
    if ! docker image inspect "$IMAGE_NAME" &>/dev/null; then
        build_image
    fi
    
    docker run --rm -it \
        -v "$(pwd):/workspace" \
        -e GITHUB_ACTIONS=true \
        "$IMAGE_NAME" \
        bash
}

run_quick() {
    echo -e "${YELLOW}⚡ Running quick CI check...${NC}"
    
    if ! docker image inspect "$IMAGE_NAME" &>/dev/null; then
        build_image
    fi
    
    docker run --rm \
        -v "$(pwd):/workspace" \
        -e GITHUB_ACTIONS=true \
        "$IMAGE_NAME" \
        bash -c "
            uv venv --python 3.11 && \
            uv sync --extra dev && \
            cargo build --release && \
            cargo test --lib && \
            echo '✅ Quick check passed!'
        "
}

# Parse arguments
case "${1:-}" in
    --build)
        build_image
        ;;
    --shell)
        run_shell
        ;;
    --quick)
        run_quick
        ;;
    --help|-h)
        print_usage
        ;;
    "")
        run_ci
        ;;
    *)
        echo -e "${RED}Unknown option: $1${NC}"
        print_usage
        exit 1
        ;;
esac
