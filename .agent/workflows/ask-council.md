---
description: Summon the Grand Council for a TITANIUM Review (SOP-001)
---

# ⚖️ Skill: Ask Council (Expert Review)

> **Authority**: SOP-001 Master Lifecycle
> **Trigger**: Before merging code or when significant architectural changes are proposed.

## 1. 📜 Phase I: The Summons

Identify who needs to be in the room.

1.  **Read the Personas**:
    - `view_file docs/architecture/expert_review_personas_catalog.md`
2.  **Analyze the Changes**:
    - `run_command git diff --stat` (See what files changed).
3.  **Select the Reviewers**:
    - If `*.rs` changed -> Summon **Rust Core Dev**.
    - If `*.py` changed -> Summon **Python Core Dev**.
    - If `Cargo.toml` changed -> Summon **Security Specialist**.
    - If `Performance` critical -> Summon **Performance Engineer**.

## 2. 🗣️ Phase II: The Critique (Simulation)

You must **roleplay** the selected agents to critique the current state.

1.  **Agent A (Core)** says: "Does this break the Happy Path? Prove it with `test_golden_path.py`."
2.  **Agent B (Edge)** says: "What happens at 10,000 QPS? Did you check the boundaries?"
3.  **Agent C (Security)** says: "Did you bypass `Surgical Shielding`? Show me the `unsafe` blocks."

## 3. 📝 Phase III: The Verdict

1.  **Generate Report**:
    - Create a "Council Review Summary".
    - Mark as **APPROVED** or **REQUEST CHANGES**.
    - If **REQUEST CHANGES**, list the P0 blocking issues.
