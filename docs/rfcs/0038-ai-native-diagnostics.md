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
3.  **Context Gap**: Knowing a function is "Hot" at `line 45` isn't enough; the Agent needs to see the signature to suggest a fix immediately.
4.  **Stream Pollution**: Dumping diagnostics to `stdout` breaks piping for tools like `jq` or `grep`.

---

## 3. Proposed Protocol

### 3.1 Output Dest & Truncation
- **Default**: Diagnostics MUST be written to `stderr` or a specified file (`--prof-md=report.md`).
- **Truncation**: Large tables (Hot Functions) MUST be truncated to the **Top 20** entries to prevent token overflow. A summary footer (e.g., "...and 45 other calls") must be included.

### 3.2 Standard Output Schema (GFM)
Output must follow GitHub Flavored Markdown (GFM) standards and include **Context Snippets**.

#### Example: `velo run --prof-md script.py`
```markdown
# Velo Diagnostic Report v1

| Metric | Value | Status |
| :--- | :--- | :--- |
| **Total Runtime** | 1.04s | 🟢 Within Budget |
| **Startup (Zygote)** | 12ms | ⚡ Instant |
| **Memory Delta** | +24MB | ✅ COW Efficient |

## 💻 System Environment
| Variable | Value |
| :--- | :--- |
| **VELO_MODE** | `dev` |
| **PYTHON_GIL** | `Enabled` |
| **PLATFORM** | `Darwin 14.2` |

## 🔍 Top Bottleneck Analysis

### 1. `heavy_compute` (492ms)
**Location:** `utils.py:45`
**Signature:** `def heavy_compute(data: List[int]) -> int:`
> **Agent Hint**: High self-time in a loop. Check for nested list comprehensions.

## Hot Functions (Top 20)
| Self % | Self | Function | Location |
| :--- | :--- | :--- | :--- |
| 47.3% | 492ms | `heavy_compute` | `utils.py:45` |
| 36.1% | 376ms | `_data_load` | `data/loader.py:12` |
... (truncated) ...
```

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
Implement a `MarkdownFormatter` in `src/common/diagnostics.rs`. 
- **Efficiency**: Use `std::fmt::Write` to build the string buffer without excessive heap allocations.
- **Purity**: Use `strip-ansi-escapes` to ensure no binary noise enters the token stream.
- **Safety**: Verify UTF-8 compatibility to prevent breaking LLM decoders with corrupted binary garbage.

### 4.3 Zero-Cost Instrumentation
All data collection required for `--prof-md` MUST be lazy-initialized and gated. If the flag is not present, no additional memory or CPU overhead should be incurred (Zero-Cost Path).

---

## 5. AI Integration: The Prompt Preamble

Velo provides a recommended **System Prompt Preamble** for AI-assisted profiling:

> "You are a Performance Engineer. When analyzing Velo Markdown Reports (RFC-0038), prioritize 'Self Time' over 'Total Time' to find actual optimization targets. Use the provided 'Code Context Snippets' to identify algorithmic inefficiencies without manually reading files unless necessary."

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
