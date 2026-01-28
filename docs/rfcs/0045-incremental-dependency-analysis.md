# RFC-0045: Incremental Dependency Analysis

**Status**: Draft  
**Author**: Velo Architect  
**Date**: 2026-01-27  
**Scope**: velo-graph, Hot Reload, Performance

---

## 1. Executive Summary

This RFC proposes **Incremental Dependency Analysis** for the `velo-graph` module. Instead of full graph reconstruction on every file change, Velo will maintain a persistent cache and propagate only affected changes—enabling near-instant hot reload response.

---

## 2. The Problem

### Current Behavior
```
File modified → Full AST scan (all files) → Rebuild graph → 500ms-2s
```

### Pain Points
1. **Slow Hot Reload**: Even single-file changes trigger full analysis
2. **High CPU Usage**: Constant re-parsing wastes resources
3. **Poor UX**: Developers wait for stale-check completion

---

## 3. Proposed Solution

### 3.1 Graph Cache Architecture

```
┌─────────────────────────────────┐
│ Persistent Graph Cache (.velo/) │
│ ├── graph.bin (serialized DAG) │
│ ├── mtimes.json (file hashes)  │
│ └── dirty.log (pending updates)│
└─────────────────────────────────┘
```

### 3.2 Incremental Update Algorithm

```
1. File Watcher detects change to `utils.py`
2. Compare mtime/hash with cache
3. If changed:
   a. Re-parse ONLY `utils.py`
   b. Mark downstream dependents as "dirty"
   c. Propagate dirty status transitively
4. Return updated subgraph
```

### 3.3 Dirty Propagation

```
utils.py (modified)
    │
    ├── api.py (imports utils) → DIRTY
    │       │
    │       └── main.py (imports api) → DIRTY
    │
    └── tests/test_utils.py → DIRTY
```

---

## 4. Technical Design

### 4.1 Data Structures

```rust
/// Cached dependency node
struct CachedNode {
    path: PathBuf,
    hash: Blake3Hash,
    mtime: SystemTime,
    imports: Vec<PathBuf>,
    is_dirty: bool,
}

/// Incremental graph cache
struct GraphCache {
    nodes: HashMap<PathBuf, CachedNode>,
    reverse_deps: HashMap<PathBuf, Vec<PathBuf>>, // who imports me?
}
```

### 4.2 Serialization

- **Format**: `rkyv` for zero-copy deserialization
- **Location**: `${PROJECT}/.velo/graph.cache`
- **Invalidation**: Full rebuild if cache version mismatches

### 4.3 File Watching Integration

| Platform | Backend |
|:---|:---|
| Linux | `inotify` via `notify` crate |
| macOS | `FSEvents` via `notify` crate |

---

## 5. Scope & Affected Components

| Component | Change |
|:---|:---|
| `velo-graph` | New `IncrementalAnalyzer` trait |
| `velo-core` | Cache path management |
| `velo-cli` | `velo watch` mode integration |
| `.velo/` | New cache directory structure |

---

## 6. Success Metrics

| Metric | Current | Target |
|:---|:---|:---|
| Single-file change latency | 500ms-2s | < 50ms |
| CPU usage (watch mode) | High | Minimal (event-driven) |
| Memory (graph cache) | 0 | < 10MB for 10K files |

---

## 7. Risks & Mitigations

| Risk | Mitigation |
|:---|:---|
| Cache corruption | Fallback to full rebuild |
| Cross-platform consistency | Abstract via `notify` crate |
| Dynamic imports missed | Document limitation; static-only |

---

## 8. Implementation Phases

| Phase | Milestone | Timeline |
|:---|:---|:---|
| 1 | Graph cache serialization | v1.2 |
| 2 | Incremental update engine | v1.3 |
| 3 | CLI `watch` mode integration | v1.4 |

---

## 9. Open Questions

1. Should we cache across Zygote restarts?
2. How to handle `importlib` dynamic imports?
3. Should cache be shareable across CI nodes?

---

**Custodian**: Velo Architect  
**Requires**: Council Review before Implementation
