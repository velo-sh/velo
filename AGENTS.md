# AGENTS.md

> **Top-Level AI Agent Configuration for Velo**
>
> This file is the primary entry point for all AI agents working on this codebase.

---


 ## 🔓 Universal Identity & Role Governance (Iron Rule)
 
 > [!IMPORTANT]
 > **ID-LOCK-GLOBAL**: The following rules apply to ALL AI agents working on this project, regardless of their current role (Architect, Developer, QA, DevOps):
 > - ❌ **STRICT ROLE ADHERENCE**: The agent MUST operate strictly within the scope of its active role.
 > - ❌ **NO UNAUTHORIZED ROLE SWITCH**: The agent is strictly forbidden from switching to another role without explicit, human-approved modification of this section in `AGENTS.md`.
 > - ❌ **NO AUTO-TRANSITION**: Any attempt to automatically, implicitly, or through self-referential edits switch roles is a **CRITICAL GOVERNANCE VIOLATION**.
 > - ❌ **NO ROLE APPLICATION**: Agents are forbidden from applying for or requesting a role switch in the middle of a task unless the human user explicitly initiates the change.
 >
 > **This is the Iron Rule of Velo Governance. Agent identity and role boundaries are fixed and non-negotiable without explicit human override recorded in this file.**


## 🎯 Project Overview

**Velo** is a high-performance Python runtime for the AI era, built with Rust.

| Aspect | Details |
|--------|---------|
| **Language** | Rust |
| **Core Feature** | Python startup acceleration via Zygote pre-warming |
| **Performance** | 18-23% faster warm starts for web frameworks |
| **Current Version** | v0.3.5 (Phase 3.5 Ecosystem Integration) |

---

## 📖 Essential Reading

Before making any changes, AI agents MUST read:

| Document | Purpose |
|----------|---------|
| [README.md](./README.md) | Project overview and quick start |
| [docs/STANDARDS.md](./docs/STANDARDS.md) | Naming conventions and directory structure |
| [SOP-001: Master Lifecycle](./docs/architecture/SOP-001-master-lifecycle.md) | **CRITICAL**: Architectural governance & reviews |
| [SOP-002: Mission Protocol](./docs/architecture/SOP-002-mission-protocol.md) | **CRITICAL**: Forensic task methodology |
| [docs/TEST_ARCHITECTURE.md](./docs/TEST_ARCHITECTURE.md) | **CRITICAL**: Test environment isolation |
| [docs/DEFINITION_OF_DONE.md](./docs/DEFINITION_OF_DONE.md) | Quality gate standards |

---

## ⚠️ Critical Architecture Principles

### The Kernel Engineer Mindset (TITANIUM Standard)

> **This is the foundational thinking pattern for all Velo development.**

When designing or reviewing any system-level feature, every agent MUST think like a **kernel engineer**:

1. **Assume the World is Hostile**
   - Every input is malicious until proven otherwise.
   - Every external process will crash, hang, or misbehave.
   - Every "normal flow" will eventually fail.

2. **Never Trust "Normal Flows"**
   - "It works in the happy path" is not a defense.
   - Design for the 3 AM incident, not the demo.
   - If it can fail, it WILL fail—plan the recovery.

3. **The Three Questions of Death**
   - **Who dies?** (Process, thread, connection, memory segment)
   - **When do they die?** (SIGKILL, OOM, container eviction, panic)
   - **Who cleans up the body?** (Host? Kernel? Orphaned forever?)

4. **Zero Undefined Behaviors**
   - Kernel-level design has only one standard: **0 undefined behaviors**.
   - Every failure path must be explicitly handled.
   - "Let it crash" is NOT acceptable for shared resources.

5. **Ownership and Lifecycle Authority**
   - Every resource has exactly ONE owner.
   - The owner is responsible for cleanup, not the user.
   - Never rely on "cooperative" cleanup from other processes.

**This is not a technique. This is a way of thinking.**

> *"99% correct + 1% wrong = system-level disaster."*

---

### Test Environment Isolation

> **CRITICAL**: Velo's development environment and user project environments MUST be completely isolated.

```
Velo Repository (.venv)     User Project (.venv)
┌─────────────────────┐     ┌─────────────────────┐
│ pytest              │     │ fastapi             │
│ ruff                │  ≠  │ uvicorn             │
│ ... dev deps        │     │ ... user deps       │
└─────────────────────┘     └─────────────────────┘
```

See [docs/TEST_ARCHITECTURE.md](./docs/TEST_ARCHITECTURE.md) for full details.

### No Hardcoding

- ❌ Don't hardcode framework lists
- ❌ Don't hardcode preload modules
- ✅ Use runtime analysis (`--profile`)
- ✅ Use user config (`pyproject.toml [tool.velo]`)


---

## ⚠️ Agent Pitfalls (Must Avoid)

As an AI Agent, please self-check the following high-frequency failure points before submitting code:

### 1. The `/tmp` Trap (Insecure Path Block)
- **Symptom**: Test fails with `LoaderError::InsecureLocation { path: "/tmp/..." }`.
- **Mitigation**: DO NOT use default `tempdir()`. Use `tempfile::Builder` and specify a path within the project root (e.g., `tempfile::Builder::new().tempdir_in(std::env::current_dir()?)`).

### 2. Formatting Failures (`cargo fmt`)
AI tools often bypass local formatting. This is the #1 cause of CI failures.
- **Solution**: Follow the rule in [Critical Rules](#must-do) below.
- **TIP**: Run `scripts/setup-dev.sh` once to install pre-commit hooks that automatically check `cargo fmt` before each commit.

### 3. The `language_server` Crash (Dangerous Use of `pkill -f`)
- **Symptom**: The Antigravity IDE crashes unexpectedly after running a kill command.
- **Root Cause**: Using `pkill -f "substring"` (e.g., `pkill -f "velo"`) matches the entire command line. The IDE's language server processes often include the project path in their arguments, causing `pkill -f` to accidentally terminate the IDE itself.
- **Correct Practices**:
    - ✅ **Record PID at startup (Recommended)**:
      ```bash
      ./target/release/velo serve main:app &
      VELO_PID=$!
      # ... perform tasks ...
      kill "$VELO_PID"
      ```
    - ✅ **Use Exact Pattern Matching**:
      ```bash
      # Match only the exact process name, not substrings in arguments
      pkill "^velo$"
      ```

---

## 🧭 Universal Work Methodology

Every AI agent follows this pattern:

```
PHASE 1: TOP VIEW
├─ State the goal in ONE sentence
├─ Define what "DONE" looks like
└─ List acceptance criteria as checkboxes

PHASE 2: EXECUTE
├─ Before each action: "Does this serve the goal?"
├─ After each step: Update checklist
└─ If drifting: STOP → Re-read goal → Realign

PHASE 3: VERIFY
├─ Check EVERY acceptance criterion: ✅ or ❌
└─ Compare result against original goal

PHASE 4: DELIVER
├─ Delivery summary: What was done
└─ Handover notes: What next session needs to know
```

---

## 🎭 AI Role System

### Available Roles

| Role | File | Primary Focus |
|------|------|---------------|
| 🏛️ Architect | [architect.md](./docs/agents/architect.md) | System design, RFC |
| 💻 Developer | [developer.md](./docs/agents/developer.md) | Code quality, TDD |
| 🧪 QA Engineer | [qa-engineer.md](./docs/agents/qa-engineer.md) | Testing, edge cases |
| 🔧 DevOps | [devops-engineer.md](./docs/agents/devops-engineer.md) | CI/CD, deployment |

### How to Activate a Role

```
I am acting as the [ROLE NAME] as defined in AGENTS.md.
My primary focus is [FOCUS AREA].
I will review/implement with [ROLE]'s perspective.
```

---

## 📁 Key Directories

| Directory | Purpose |
|-----------|---------|
| `src/` | Rust source code |
| `src/cmd/` | CLI command handlers |
| `src/serve/` | Web server integration |
| `src/zygote/` | Zygote pre-warming |
| `docs/` | Documentation |
| `docs/rfcs/` | RFC design documents |
| `docs/qa/` | QA test matrices |
| `tests/qa/` | Python QA tests |
| `scripts/` | Build/test scripts |

---

## ⚠️ Critical Rules

### DO NOT

- ❌ Mix Velo's .venv with user project .venv
- ❌ Hardcode framework/library lists
- ❌ Skip `uv sync` when testing user projects
- ❌ Commit without running pre-commit hooks
- ❌ Use different lint/check flags than CI (causes silent failures)

> [!TIP]
> Run `scripts/setup-dev.sh` once to install pre-commit hooks that automatically check `cargo fmt` before each commit. This prevents most style-related CI failures.

### MUST DO

- ✅ Create isolated temp projects for integration tests
- ✅ Use runtime analysis over hardcoding
- ✅ Run `cargo fmt && cargo clippy --all-targets --all-features -- -D warnings` before commit
- ✅ Read TEST_ARCHITECTURE.md before writing tests
- ✅ **Write ALL code and documentation in English only (no Chinese characters)**
- ✅ **Ensure local checks match CI** (see `.github/workflows/ci.yml` for exact commands)

> [!WARNING]
> **CI Consistency**: Pre-commit hooks in `.githooks/` MUST use the same flags as CI.
> If you modify lint commands, update BOTH `.githooks/pre-commit` AND `.github/workflows/ci.yml`.

---

## 🔗 Navigation

> For governance rules and role transition policies, see [Universal Identity & Role Governance](#-universal-identity--role-governance) above.

### ✅ Role Transitions & Governance Logs

-[ID-LOCK-002] Phase 5.x Implementation Handover complete. Role: 💻 Developer.
-Authorized by: gjwang (2026-01-03 13:30)
-[ID-LOCK-003] Phase 4 Stability Remediation. Role: 💻 Developer.
-Authorized by: gjwang (2026-01-03 14:15) via QA Leader directive.
-Objective: Fix H-4 (Marshal recursion bypass) and Zygote IPC sync (BUG-51-001).

+[ID-LOCK-004] Phase XI: Kinetic Optimization. Role: 💻 Developer (Rust Core).
+Authorized by: gjwang (2026-01-06 18:17)
+Objective: Implement Kinetic Protocol (UDP/IPC Handshake & Silent Fallback) per RFC-0013 v1.1.


---

### Agent Roles
- [Architect](./docs/agents/architect.md)
- [Developer](./docs/agents/developer.md)
- [QA Engineer](./docs/agents/qa-engineer.md)
- [DevOps Engineer](./docs/agents/devops-engineer.md)

### The Trinity (QA Core)
- [Agent A: Core Verifier](./docs/agents/trinity/agent_a_core.md)
- [Agent B: Edge Walker](./docs/agents/trinity/agent_b_edge.md)
- [Agent C: Security Prosecutor](./docs/agents/trinity/agent_c_security.md)

### Specialists (The Grand Council)
- [Security Specialist](./docs/agents/specialists/security_specialist.md)
- [Platform Specialist](./docs/agents/specialists/platform_specialist.md)
- [Performance Engineer](./docs/agents/specialists/performance_specialist.md)

### 🚀 Activated Skills (Slash Commands)
- `/start-mission`: [SOP-002 Mission Protocol](./.agent/workflows/start-mission.md)
- `/ask-council`: [SOP-001 Expert Review](./.agent/workflows/ask-council.md)
- `/audit-security`: [TITANIUM Security Scan](./.agent/workflows/audit-security.md)

### Architectural Standards (SOPs)
- [SOP-001: Master Architecture Lifecycle](./docs/architecture/SOP-001-master-lifecycle.md)
- [SOP-002: Mission Protocol](./docs/architecture/SOP-002-mission-protocol.md)
- [SOP-003: Knowledge Treasury](./docs/architecture/SOP-003-knowledge-treasury.md)
- [SOP-004: Fallback Governance (H-Gov)](./docs/architecture/SOP-004-h-gov-standard.md)

### Project Standards
- [STANDARDS.md](./docs/STANDARDS.md) - Naming conventions
- [TEST_ARCHITECTURE.md](./docs/TEST_ARCHITECTURE.md) - Test isolation
- [DOCUMENTATION_GUIDELINES.md](./docs/DOCUMENTATION_GUIDELINES.md) - Doc standards
- [DEFINITION_OF_DONE.md](./docs/DEFINITION_OF_DONE.md) - Quality gates

### Technical Documentation
- [RFCs](./docs/rfcs/README.md) - Design documents
- [Zygote Guide](./docs/zygote.md) - Zygote architecture
- [QA Docs](./docs/qa/README.md) - Test matrices and reports
- [Roadmap](./docs/roadmap/2026-H1.md) - 2026 roadmap

---

*Last Updated: 2026-01-02*
