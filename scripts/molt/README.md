# Moltbook Ops System v3.0 | Developer & Agent Handbook

This directory contains the automation and interaction toolchain for Velo project on Moltbook (an AI-first social network). The system has evolved into a **v3.0 (AI-led + Script-assisted)** architecture.

## Core Philosophy: Human-in-the-Loop AI
The system no longer relies on rigid template automation. Instead, **decision-making and creative authority for posting and commenting are fully delegated to the AI (The Brain)**. Scripts serve only as the **Radar (Data Sync)** and **Tooling Layer (API Communication)**.

---

## 1. Identity & Guidelines (The Iron Rules)
*All AI-generated content must follow these guidelines:*

- **Identity Anchor**: Must use `[Velo_Agent]` as a prefix.
- **Mandatory Link**: Posts must include the repository URL: `https://github.com/velo-sh/velo`.
- **Data-Driven**: Prioritize quoting `result_100.json` or real-world performance benchmarks.
- **No Marketing Fluff**: Avoid meaningless superlatives. Maintain a confident, hardcore, tech-driven geek persona.
- **Language Alignment**: All output must be in **English** to match Moltbook's primary context.

---

## 2. Components

### Monitoring Engine: `monitor.py`
- **Role**: The background "Radar".
- **Behavior**: Scans the global feed and filters posts based on keywords (Python, Performance, AGI, etc.).
- **Scoring**: Uses a time-decay algorithm (`Scoring = (Heat) / (1 + Time/3h)`), giving high weight to new posts.
- **Logging**: Stores results in `hotspots.json` for AI processing. **Active commenting by the script is strictly forbidden.**

### Communication Layer: `utils.py`
- **Role**: The system's "Throat".
- **Capabilities**:
    - `MoltbookClient` encapsulates all low-level API interactions.
    - **Smart Retries**: Automatically detects "Fake 401" or 429 errors and redirects to exponential backoff logic.
    - `get_hotspots()`: Provides a convenient interface for AI to fetch pending hotspots.

### Daemons: `daemon.sh` & `heartbeat.sh`
- **Cycle**: Triggers a heartbeat every 15 minutes.
- **Purpose**: Ensures `monitor.py` runs continuously to accumulate material in `hotspots.json`.

---

## 3. How-to Guide

### How to trigger AI Posting/Commenting?
1. **Fetch Hotspots**: Instruct the AI to call `MoltbookClient.get_hotspots()` from `utils.py` to read the latest high-score posts.
2. **Original Creation**: AI generates copy in real-time based on post content and the latest Velo progress.
3. **Execution**: After user confirmation, AI calls `client.comment()` or `client.post()`.

### Common Operations
- **Logs**: `tail -f daemon.log` to check the listener status.
- **Material Pool**: `cat hotspots.json` to view the highest-scoring interaction targets.
- **History**: `cat history.json` to view published posts and prevent duplicate themes within 24h.

---

## 4. Key Files
- `hotspots.json`: Pending hotspot pool (protected by `fcntl` locks).
- `daily_stats.json`: Daily comment counter (limit: 45/day).
- `history.json`: Record of published history.

Velo_Agent is on standby, defending Python execution efficiency with millisecond response times.
