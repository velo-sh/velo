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
| [docs/TEST_ARCHITECTURE.md](./docs/TEST_ARCHITECTURE.md) | **CRITICAL**: Test environment isolation |
| [docs/DEFINITION_OF_DONE.md](./docs/DEFINITION_OF_DONE.md) | Quality gate standards |

---

## ⚠️ Critical Architecture Principles

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
- **Root Cause**: Velo's security policy strictly forbids loading code from insecure paths like `/tmp`, `/var/tmp`, `/dev/shm` to prevent symlink attacks.
- **Mitigation**: DO NOT use default `tempdir()`. Use `tempfile::Builder` and specify a path within the project root (e.g., `tempfile::Builder::new().tempdir_in(std::env::current_dir()?)`).

### 2. Formatting Failures (`cargo fmt`)
AI tools often bypass local formatting. This is the #1 cause of CI failures.
- **Solution**: Follow the rule in [Critical Rules](#must-do) below.
- **TIP**: Run `scripts/setup-dev.sh` once to install pre-commit hooks that automatically check `cargo fmt` before each commit.

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

> [!TIP]
> Run `scripts/setup-dev.sh` once to install pre-commit hooks that automatically check `cargo fmt` before each commit. This prevents most style-related CI failures.

### MUST DO

- ✅ Create isolated temp projects for integration tests
- ✅ Use runtime analysis over hardcoding
- ✅ Run `cargo fmt && cargo clippy` before commit
- ✅ Read TEST_ARCHITECTURE.md before writing tests

---

 ## 🔗 Navigation

### Agent Roles
- [Architect](./docs/agents/architect.md)
- [Developer](./docs/agents/developer.md)
- [QA Engineer](./docs/agents/qa-engineer.md)
- [DevOps Engineer](./docs/agents/devops-engineer.md)

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
