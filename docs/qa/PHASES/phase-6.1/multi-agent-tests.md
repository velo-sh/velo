# Multi-Agent Test Strategy: Phase 6.1

> **Strategy**: Divide & Conquer
> **Target**: Velo Serve & Analyze

---

## 🤖 Agent A: The Edge Walker (Complexity)

**Focus**: Topological complexity, large scale, and weird configurations.

| ID | Test Case | Goal |
|:---|:---|:---|
| **EDGE-61-001** | **Circular Factory** | `create_app()` that imports itself or loops. |
| **EDGE-61-002** | **Deep Nested App** | `app` located in `a.b.c.d.e.f.g.main`. |
| **EDGE-61-003** | **Symlink Maze** | Project root is a symlink to a symlink. |
| **EDGE-61-004** | **Mixed Encoding** | Source files with CP1252 comments (Windows compat). |

---

## 🤖 Agent B: The Stabilizer (Reliability)

**Focus**: Long-running stability, OS signals, and resource leaks.

| ID | Test Case | Goal |
|:---|:---|:---|
| **STAB-61-001** | **The Twitchy User** | Send SIGINT 50 times in 1 second. |
| **STAB-61-002** | **Memory Leak** | Reload 1000 times, ensure RSS < Baseline + 5%. |
| **STAB-61-003** | **Orphan Check** | Kill parent `velo` with -9, children MUST die. |
| **STAB-61-004** | **Startup Race** | Modify `main.py` exactly as `velo` starts. |

---

## 🤖 Agent C: The Gatekeeper (Security)

**Focus**: P0 Invariants and malicious inputs.

| ID | Test Case | Goal |
|:---|:---|:---|
| **SEC-61-001** | **Arg Injection** | `velo serve --bind "0.0.0.0; rm -rf /"` |
| **SEC-61-002** | **Path Traversal** | `velo serve ../../../etc/passwd` |
| **SEC-61-003** | **PID Race** | Symlink `/tmp/velo.pid` to `/etc/shadow`. |
| **SEC-61-004** | **Exposed Env** | Ensure `VELO_SECRET_KEY` not in `/health` or logs. |

---

## 🤖 Agent D: The Destroyer (Chaos)

**Focus**: System-level destruction (Linux/Mac only).

| ID | Test Case | Goal |
|:---|:---|:---|
| **DST-61-001** | **Disk Full** | Mount small loopback, fill it, run `velo serve`. |
| **DST-61-002** | **ReadOnly FS** | Run `velo serve` on RO mount (PID file fail). |
| **DST-61-003** | **Fork Bomb** | App spawns threads indefinitely. |

---
