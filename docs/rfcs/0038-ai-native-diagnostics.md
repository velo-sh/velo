# RFC-0038: AI-Native Diagnostics & LLM-Friendly Profiling Protocol

**Status**: Draft
**Created**: 2026-01-22
**Author**: Antigravity (Arch)
**Target**: v0.9.5+

---

## 1. Summary

This RFC proposes a new diagnostic standard for Velo: **AI-Native Diagnostics**. 
By implementing structured Markdown output (`--prof-md`) for all performance-critical commands, Velo enables AI agents (like Claude, Gemini, and Cursor) to accurately parse, analyze, and optimize Python applications without regex-based guesswork.

---

## 2. Motivation

### 2.1 The Agentic Era
Modern development is increasingly "Agent-First." AI agents perform code reviews, fix performance regressions, and manage infra. However, most CLI tools output ANSI-encoded text optimized for human eyeballs, which is sub-optimal for LLMs.

### 2.2 The "Bun" Inspiration
Bun recently introduced `--cpu-prof-md`, allowing LLMs to read profiling data directly. Velo, as the "Vibe Engine," must lead in AI-assisted developer experience (DX).

### 2.3 Problems with Current Output
1.  **ANSI Noise**: Escape codes confuse smaller LLMs and waste token context.
2.  **Unstructured Timing**: Chronological logs are harder to grep than tabulated data.
3.  **No Clear "Hot" Markers**: AI agents benefit from explicit `**Top 10**` or `## Hot Functions` headers to focus their attention.

---

## 3. Proposed Protocol

### 3.1 `--prof-md` Flag
Add a global or command-specific `--prof-md` flag to `run`, `bench`, and `audit`.

### 3.2 Standard Output Schema (GFM)
Output must follow GitHub Flavored Markdown (GFM) standards.

#### Example: `velo run --prof-md script.py`
```markdown
# Velo Diagnostic Report v1

| Metric | Value | Status |
| :--- | :--- | :--- |
| **Total Runtime** | 1.04s | 🟢 Within Budget |
| **Startup (Zygote)** | 12ms | ⚡ Instant |
| **Memory Delta** | +24MB | ✅ COW Efficient |
| **Import Latency** | 450ms | ⚠️ High |

## Hot Functions (Self Time)
| Self % | Self | Function | Location |
| :--- | :--- | :--- | :--- |
| 47.3% | 492ms | `heavy_compute` | `utils.py:45` |
| 36.1% | 376ms | `_data_load` | `data/loader.py:12` |

## Startup Timeline
- `[0ms]` Zygote Spawn
- `[4ms]` Environment Shield Active
- `[12ms]` Application Entry
- `[462ms]` First Heavy Import (`torch`)
```

### 3.3 Agent-Friendly Markers
- Use `**` for emphasis on bottlenecks.
- Use `##` for clear sectioning.
- Include a `# Summary` at the top for quick context.

---

## 4. Implementation Details

### 4.1 CLI Arg Refactor
Add a boolean flag `prof_md` to `RunCmd` and `BenchCmd`.

### 4.2 Formatter Module
Implement a `MarkdownFormatter` in `src/common/diagnostics.rs` that takes a `TraceEvent` or `ProfileResult` and converts it to a String. This module must strictly enforce **ANSI Purity** by stripping all escape codes.

### 4.3 Zero-Cost Instrumentation
All data collection required for `--prof-md` MUST be lazy-initialized and gated. If the flag is not present, no additional memory or CPU overhead should be incurred (Zero-Cost Path).

---

## 5. Value Proposition

1.  **Lower TCO (Total Cost of Optimization)**: AI agents can fix performance bugs in seconds.
2.  **Marketing Alignment**: Positions Velo as the "World's First AI-Native Python Runtime."
3.  **Integration**: Seamless integration with Cursor, VS Code Copilot, and custom DevOps agents.

---

## 6. Engineering Risks

- **Runtime Overhead**: Capturing data for detailed profiling always adds overhead. This should only run when requested.
- **Protocol Stability**: Moving to a structured format requires stable column names to avoid breaking AI prompts.

---

## 7. Open Questions

- Should we support JSON instead of Markdown? 
    - **Decision**: Markdown is preferred as it is human-readable AND LLMs are natively trained on Markdown structure, whereas JSON consumes more tokens and can be more brittle for partial reads.
- Should we provide an `--ai-fix` suggestion? 
    - **Future Phase**: Velo could potentially include an AI-generated suggestion in the MD report if an API key is provided.

---

## 8. Quality Gates

- **Gate A**: Output passes standard Markdown linting (`mdl`).
- **Gate B**: AI-generated "Top 3 bottlenecks" from the report match actual data with 100% accuracy.
