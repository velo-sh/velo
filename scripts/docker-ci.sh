#!/bin/bash
# =============================================================================
# Velo Docker CI (Proxy)
# =============================================================================
# This script is a compatibility wrapper for scripts/v-ci.
# Please consider using scripts/v-ci --docker directly.
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Map old flags to new system
ARGS=("--docker")
for arg in "$@"; do
    case "$arg" in
        --shell) ARGS+=("--shell") ;;
        --build) ARGS+=("--build") ;;
        *) ARGS+=("$arg") ;;
    esac
done

exec "$SCRIPT_DIR/v-ci" "${ARGS[@]}"
