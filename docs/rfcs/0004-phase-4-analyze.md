# RFC-0004: Phase 4.0 Smart Optimization

> **Status**: `Draft`  
> **Author**: Velo Core Team  
> **Created**: 2026-01-02  
> **Target Release**: Velo v0.4.0  
> **Discussion**: [GitHub Discussions](https://github.com/velo-sh/velo/discussions)

---

## 1. Executive Summary

### 1.1 Background

Phase 3.5 delivered `velo serve` with 18-23% faster startup. However, users still have to manually configure preload modules. Phase 4.0 introduces **automatic analysis** to detect import bottlenecks and suggest optimizations.

### 1.2 Goal

```bash
$ velo analyze

📊 Import Analysis
├─ fastapi (89ms)
├─ numpy (156ms) ← SLOW
└─ pandas (203ms) ← SLOWEST

💡 Optimization Suggestions:
  1. Add to preload: pandas, numpy
  2. Consider lazy import for: matplotlib

Estimated improvement: 15-25% faster startup
```

### 1.3 Design Principles ⚠️ CRITICAL

> **Core Philosophy**: Runtime analysis over hardcoding. Velo must work with ANY Python library, not just popular frameworks.

#### ❌ Anti-Patterns (Current Phase 3.5 Problems)

```rust
// BAD: Hardcoded framework list
pub enum Framework { FastAPI, Django, Flask, Unknown }

// BAD: Static preload mapping
Framework::FastAPI => vec!["fastapi", "pydantic", ...]
```

**Problems with hardcoding**:
- New frameworks (Sanic, Litestar, Tornado...) = Unknown
- Custom libraries = not optimized
- Every new framework requires code changes
- Maintenance burden grows linearly

#### ✅ Best Practices

| Principle | Implementation |
|-----------|----------------|
| **Measure, don't guess** | Use `--profile` to get real import times |
| **User-defined config** | Read from `velo.toml`, don't hardcode |
| **Heuristics as fallback** | Framework detection = hint only |
| **Zero magic** | Show user what modules will be preloaded |

```rust
// GOOD: Runtime analysis
pub fn analyze_imports(script: &Path) -> Vec<ImportMetric> {
    let output = run_with_profile(script);
    parse_import_times(output)  // Real data, not hardcoded
}

// GOOD: User config > heuristics
fn get_preload_modules(project: &Path) -> Vec<String> {
    if let Some(config) = read_velo_toml(project) {
        return config.preload;  // User knows best
    }
    suggest_from_analysis()  // Fallback to runtime data
}
```

#### Migration Path

```
Phase 3.5 (current):  Hardcoded framework detection
                      ↓
Phase 4.0 (this RFC): Runtime analysis + velo.toml
                      ↓
Phase 4.1 (future):   Deprecate hardcoded framework.rs
```

---

## 2. Proposed Features

### 2.1 `velo analyze` Command

```bash
# Basic usage
velo analyze

# Analyze specific file
velo analyze main.py

# Output to file
velo analyze --output report.json

# With preload recommendations
velo analyze --suggest-preload
```

### 2.2 Import Time Breakdown

```
┌─────────────────────────────────────────────────────────┐
│                  Import Tree Analysis                   │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  Total import time: 847ms                               │
│                                                         │
│  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓░░░░░░░░░░░░░░ pandas (203ms) 24%     │
│  ▓▓▓▓▓▓▓▓▓▓▓░░░░░░░░░░░░░░░░░░ numpy (156ms) 18%      │
│  ▓▓▓▓▓▓░░░░░░░░░░░░░░░░░░░░░░░ torch (134ms) 16%      │
│  ▓▓▓▓▓░░░░░░░░░░░░░░░░░░░░░░░░ httpx (112ms) 13%      │
│  ▓▓▓▓░░░░░░░░░░░░░░░░░░░░░░░░░ fastapi (89ms) 10%     │
│  ▓▓░░░░░░░░░░░░░░░░░░░░░░░░░░░ others (153ms) 18%     │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

### 2.3 Auto-Generate velo.toml

```bash
$ velo analyze --fix

✅ Created velo.toml with recommended preload:

[zygote]
preload = ["pandas", "numpy", "fastapi", "httpx"]
```

---

## 3. Technical Design

### 3.1 CLI Interface

```rust
// src/cmd/analyze.rs
#[derive(Parser)]
pub struct AnalyzeArgs {
    /// Entry point file (default: auto-detect)
    pub file: Option<PathBuf>,
    
    #[arg(long)]
    pub output: Option<PathBuf>,
    
    #[arg(long)]
    pub suggest_preload: bool,
    
    #[arg(long)]
    pub fix: bool,
    
    #[arg(long, default_value = "100")]
    pub slow_threshold_ms: u64,
}
```

### 3.2 Analysis Flow

```
1. Run script with --profile (existing feature)
2. Parse import times from sitecustomize output
3. Build import dependency tree
4. Identify bottlenecks (> threshold_ms)
5. Generate recommendations
```

### 3.3 Code Reuse

```rust
// Reuse existing profile.rs
use crate::profile::{ProfileData, parse_profile_output};

// New analysis module
mod analyze {
    pub struct ImportTree { ... }
    pub struct Bottleneck { ... }
    pub fn suggest_preload(tree: &ImportTree) -> Vec<String>;
}
```

---

## 4. Implementation Plan

### Phase 4.0.1: Basic Analysis (1 week)

- [ ] Create `src/cmd/analyze.rs`
- [ ] Parse `--profile` output into structured data
- [ ] Implement visual bar chart output
- [ ] Add `--slow-threshold-ms` flag

### Phase 4.0.2: Recommendations (1 week)

- [ ] Implement preload suggestion algorithm
- [ ] Generate `velo.toml` with `--fix`
- [ ] Add lazy import suggestions
- [ ] Documentation

---

## 5. Success Metrics

| Metric | Target |
|--------|--------|
| Analysis time | < 5 seconds |
| Preload accuracy | > 80% useful suggestions |
| Compatibility | 100% CPython compatible |

---

## 6. Verification Plan

### Automated Tests

```bash
# Unit tests
cargo test --lib analyze

# Integration tests
uv run pytest tests/qa/test_phase4_analyze.py -v
```

### Manual Verification

```bash
# Test on real project
cd /path/to/fastapi-project
velo analyze

# Verify preload suggestions
velo analyze --suggest-preload

# Verify fix mode
velo analyze --fix
cat velo.toml
```

---

**Document End**
