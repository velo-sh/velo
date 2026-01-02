# 🏛️ Architect Code Review: Velo Codebase

> **Date**: 2026-01-02  
> **Scope**: src/**  
> **Status**: Phase 4.1 Planning

---

## Executive Summary

Codebase is well-organized but showing signs of growth pain. Key recommendations focus on **modularization** and **deprecation** of legacy patterns.

---

## Codebase Metrics

| Module | Lines | Functions | Status |
|--------|-------|-----------|--------|
| `cmd/analyze.rs` | 854 | 42 | ⚠️ Too large |
| `zygote/mod.rs` | 423 | 29 | Good |
| `cache.rs` | 369 | 15 | Good |
| `serve/framework.rs` | 150 | 6 | ⚠️ Hardcoded |

---

## Issues & Recommendations

### 🔴 P0: Hardcoded Framework Detection

**Location**: `src/serve/framework.rs`

**Problem**: Static framework list violates No-Hardcoding principle.

**Action**: Add `#[deprecated]` per RFC-0005.

---

### 🔴 P1: `analyze.rs` Too Large (854 lines)

**Recommendation**: Split into modules:

```
src/cmd/analyze/
├── mod.rs     # Entry point
├── args.rs    # AnalyzeArgs
├── config.rs  # VeloConfig
├── display.rs # Bar charts
└── report.rs  # JSON output
```

---

### 🟡 P2-P4: Minor Issues

| Issue | Location | Fix |
|-------|----------|-----|
| Inline color codes | `analyze.rs` | Extract to `terminal/colors.rs` |
| Inconsistent errors | Mixed anyhow/custom | Create `error.rs` hierarchy |
| Path validation | `analyze.rs` | Move to `util/path.rs` |

---

## Priority Order

| Priority | Task | Effort |
|----------|------|--------|
| P0 | Deprecate Framework enum | 1 day |
| P1 | Split analyze.rs | 2 days |
| P2 | Extract colors | 0.5 day |

---

**Document End**
