#!/bin/bash
# =============================================================================
# Velo Local CI (Proxy)
# =============================================================================
# This script is a compatibility wrapper for scripts/v-ci.
# Please consider using scripts/v-ci directly.
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$SCRIPT_DIR/v-ci" "$@"
