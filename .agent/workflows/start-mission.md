---
description: Start a new Velo Mission (SOP-002) with Forensic Immersion and Plan Creation
---

# 🚀 Skill: Start Mission (Velo Methodology)

> **Authority**: SOP-002 Mission Protocol
> **Trigger**: When the user wants to solve a complex problem or start a new task.

## 1. 🕵️‍♀️ Phase I: Forensic Immersion (The "Context Setup")

You must first **read the history** before writing a plan.

1.  **Read the Mission Protocol**:
    - `view_file docs/architecture/SOP-002-mission-protocol.md`
2.  **Read the Forensic Standard**:
    - `view_file docs/governance/forensics/master_technical_forensics.md`
3.  **Identify the Target**:
    - Ask the user: "What is the specific target (file/module) for this mission?"
    - `run_command git log -p -n 5 <target_file>` (Understand recent changes).

## 2. 📝 Phase II: The Implementation Plan

Create or update `implementation_plan.md` following the **TITANIUM Standard**.

1.  **Use the Master Template**:
    - `view_file docs/architecture/SOP-002-mission-protocol.md` (See Section 3.2).
2.  **State the Goal**:
    - Write a clear "Problem Statement" and "Proposed Solution".
3.  **Define the Council**:
    - List the **3 Required Agents** from `docs/agents/trinity/` who must review this.

## 3. 🚦 Phase III: The "Go/No-Go"

1.  **Notify User**:
    - Present the Plan.
    - Ask: "Does this plan meet TITANIUM standards? Shall I summon the Council?"
