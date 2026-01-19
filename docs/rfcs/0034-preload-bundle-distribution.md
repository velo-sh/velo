# RFC-0034: Preload Binary Packaging & Distribution

**Status**: DRAFT
**Author**: Velo Architect
**Date**: 2026-01-19
**Phase**: Phase 15 (Future)
**Scope**: Deployment, Distribution, Serverless

---

## 1. Executive Summary

This RFC proposes **Velo Bundle**, a system for packaging Python applications with all dependencies and assets into a single distributable file. Combined with Velo's runtime Zygote pre-warming, this eliminates cold-start latency in production deployments.

| Metric | Standard Deployment | Velo Bundle |
|:---|:---|:---|
| Cold Start | 5-10s (pip install + import) | **< 100ms** (deps pre-packaged, Zygote pre-warms at runtime) |
| Image Size | N/A (deps at runtime) | ~Dependencies + Assets |
| Distribution | pip + Docker layers | Single `.vbundle` file |

---

## 2. Motivation

### 2.1 The Serverless Cold Start Problem
Current serverless Python deployments suffer from:
1. **Dependency Installation**: `pip install` on every cold start
2. **Import Overhead**: Heavy frameworks (PyTorch, TensorFlow) take 2-5s to import
3. **Model Loading**: AI models require additional I/O from storage

### 2.2 The Velo Opportunity
Velo's Zygote architecture already solves import overhead via COW fork. The next step is to make this **portable and distributable**.

---

## 3. Architecture

### 3.1 Bundle Format (`.vbundle`)

> **Key Insight**: Zygote is a **runtime construct**, not a packaged artifact. The bundle contains static assets; Zygote pre-warming happens at deployment time.

```
┌─────────────────────────────────────────────────────────────┐
│                    Velo Bundle (.vbundle)                    │
├─────────────────────────────────────────────────────────────┤
│  Header (JSON)                                               │
│  ├── version: "1.0"                                         │
│  ├── python_version: "3.11.6"                               │
│  ├── platform: "linux-x86_64"                               │
│  ├── preload_modules: ["torch", "transformers", ...]        │
│  └── entrypoint: "app:main"                                 │
├─────────────────────────────────────────────────────────────┤
│  Dependencies (Static)                                       │
│  ├── site-packages/ (pre-installed wheels)                  │
│  ├── .venv/ (frozen virtualenv)                             │
│  └── requirements.lock                                      │
├─────────────────────────────────────────────────────────────┤
│  Application Code                                            │
│  ├── src/                                                   │
│  └── pyproject.toml                                         │
├─────────────────────────────────────────────────────────────┤
│  Assets (Optional)                                           │
│  ├── model.safetensors (Memory Gravity ready)               │
│  └── config.json                                            │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 Runtime Lifecycle

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│ velo bundle │────▶│  .vbundle   │────▶│ velo deploy │────▶│   Zygote    │
│   (build)   │     │   (ship)    │     │  (unpack)   │     │ (pre-warm)  │
└─────────────┘     └─────────────┘     └─────────────┘     └─────────────┘
      │                                        │                    │
      ▼                                        ▼                    ▼
  Package deps                         Extract to disk        Import preload
  Include assets                       Setup venv             Ready to fork()
```

**Zygote Pre-warming is a RUNTIME operation**:
1. `velo deploy` unpacks the bundle
2. Velo starts Zygote and imports `preload_modules`
3. Subsequent requests fork from the warmed Zygote

---

## 4. CLI Interface

```bash
# Build a bundle from pyproject.toml
velo bundle build --preload "torch,transformers" --output app.vbundle

# Build with model assets (Memory Gravity)
velo bundle build --include model.safetensors --output app.vbundle

# Run from bundle
velo bundle run app.vbundle

# Deploy to serverless (future)
velo bundle deploy app.vbundle --target aws-lambda
```

---

## 5. Technical Challenges

### 5.1 Platform Specificity
- **Problem**: Python bytecode and native extensions are platform-specific
- **Solution**: Bundle is tagged with `platform` (e.g., `linux-x86_64`). Cross-platform bundles require multi-arch build.

### 5.2 Dependency Isolation
- **Problem**: Bundled site-packages may conflict with system packages
- **Solution**: Bundle extracts to isolated directory; Velo sets `PYTHONPATH` exclusively to bundle paths.

### 5.3 Security
- **Problem**: Bundled code could be tampered
- **Solution**: Signed bundles with SHA256 manifest

---

## 6. Integration with Existing Features

| Feature | Integration |
|:---|:---|
| **Memory Gravity (RFC-0015)** | Bundle includes `.safetensors` as SHM-ready assets |
| **vtest (RFC-0028)** | Test with pre-bundled fixtures for consistent environment |
| **Kinetic (RFC-0013)** | Bundle includes pre-warmed Zygote socket binding |

---

## 7. Competitive Analysis

| Tool | Cold Start | Distribution | Velo Advantage |
|:---|:---|:---|:---|
| **Docker** | ~2s (layer extract) | Container registry | No container runtime needed |
| **Lambda Layers** | ~1s | AWS-specific | Platform agnostic |
| **PyInstaller** | ~500ms | Single binary | + COW fork + SHM sharing |
| **Velo Bundle** | **< 50ms** | `.vbundle` file | Full Zygote ecosystem |

---

## 8. Implementation Phases

### Phase 1: Core Bundle Format
- [ ] Define `.vbundle` file format specification
- [ ] Implement `velo bundle build` command
- [ ] Implement `velo bundle run` command

### Phase 2: Asset Integration
- [ ] Support `--include` for static assets
- [ ] Memory Gravity asset embedding (`.safetensors`)

### Phase 3: Distribution
- [ ] Bundle signing and verification
- [ ] Registry protocol (future: `velo bundle push/pull`)

---

## 9. Quality Gates

| Gate | Requirement |
|:---|:---|
| **Gate A** | Bundle runs on clean machine with only Velo installed |
| **Gate B** | Cold start from bundle < 100ms |
| **Gate C** | Memory Gravity assets load via SHM, not file I/O |
| **Gate D** | Bundle signature verification before execution |

---

## 10. Open Questions

1. **Multi-Python Support**: How to handle multiple Python versions in same bundle?
2. **Update Strategy**: How to patch a deployed bundle without full rebuild?
3. **Size Optimization**: How to minimize bundle size while preserving all dependencies?

---

**Custodian**: Velo Architect
**Last Updated**: 2026-01-19
