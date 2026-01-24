# RFC-0044: Kinetic Zygote Phylogeny (Dynamic Zygote Tree)

> **Status**: DRAFT  
> **Revision**: 0.1.0  
> **Author**: Velo Architect / Compute Team  
> **Date**: 2026-01-25  
> **Target Version**: v13.0.0 (Advanced Compute)  
> **Related Documents**: [RFC-0042](0042-velo-virtual-environment.md), [RFC-0043](0043-velo-vfs-cas-layer.md)

---

## 1. Executive Summary

While **RFC-0043 (VeloVFS)** solves the *Storage Deduplication* problem (1000 agents share one physical `numpy.so` on disk), it does not solve the *Compute Memory Deduplication* problem for mutable state.

**RFC-0044** introduces **Kinetic Zygote Phylogeny**: a "Tree of Life" architecture for Process/Zygote management. Instead of flat, isolated pools, Zygotes are organized into a genealogical tree (Genesis -> Branch -> Leaf). This leverages the Kernel's Copy-on-Write (CoW) mechanism to share not just read-only code, but also **pre-initialized Dirty Memory** (e.g., Python's internal type objects, imported module state) across the entire fleet.

---

## 2. The Core Metaphor: Zygote as a Git Tree

We treat the Zygote set not as a "Pool" (unordered collection) but as a "Tree" (directed acyclic graph).

### 2.1 The Phylogeny (Tree Structure)

*   **Genesis (Root)**: The biological ancestor.
    *   State: `ld-linux` + `libc` + `Python VM` (Bare).
    *   Memory: Minimal footprint (~15MB).
*   **Phylum (Branch)**: A specialized major group.
    *   **Sci-Branch**: Forked from Genesis -> `import numpy` -> `import pandas` -> **Freeze**.
    *   **Web-Branch**: Forked from Genesis -> `import fastapi` -> `import uvloop` -> **Freeze**.
*   **Species (Leaf)**: The final execution unit.
    *   **My-AI-Agent**: Forked from **Sci-Branch** -> Load User Code.

### 2.2 The "Git" Operations

*   **Commit (Freeze)**: When a Zygote reaches a stable state (e.g., "Numpy Loaded"), it calls `velo_freeze()`. It marks itself immutable and ready to fork children.
*   **Branch**: Any Zygote can be forked to create a specialized lineage.
*   **Rebase**: If the `Genesis` (Python Version) updates, downstream branches are invalidated and must be "re-grown" (re-imported) from the new root.

---

## 3. Technical Benefits

### 3.1 Maximal Memory Sharing (Dirty CoW)
*   **Scenario**: 1000 Agents using `PyTorch`.
*   **Flat Model (RFC-0042)**: 1000 processes. Each loads Python + Numpy + Torch independently. Linux CoW shares the *Code Segments* (via mmap/VeloVFS), but **Separate Data Segments** (Python Integers, Type Objects, Global Variables).
*   **Tree Model (RFC-0044)**:
    1.  `Zygote-Torch` initializes once. All internal Python objects for Torch are created in RAM.
    2.  1000 Agents `fork()` from `Zygote-Torch`.
    3.  **Result**: They share **100% of the Heap** initially. Dirty pages (Data) are shared until written to.
    4.  **Impact**: Memory density increases by 3-5x for heavy frameworks.

### 3.2 Incremental Specialization (Instant Startup)
*   **Linear Loading**: Loading `Numpy (50ms)` + `Pandas (100ms)` + `Torch (500ms)` = **650ms** Cold Start.
*   **Tree Loading**:
    *   `Zygote-Torch` is already pre-warmed.
    *   Agent Fork: **< 5ms**.
    *   The "Heavy Lifting" is amortized once locally (or across the cluster).

---

## 4. Lifecycle Management (The Gardener)

The **Supervisor** acts as the "Gardener", pruning and grafting the tree dynamically.

### 4.1 Phylogenetic Maintenance (Rebasing)
*   **Trigger**: When the upstream `Genesis` image updates (e.g., security patch `python:3.11.8` -> `3.11.9`).
*   **Cascade Invalidation**: Since Zygotes are immutable snapshots, we cannot "patch" them.
*   **Action**: The Supervisor **prunes** the entire affected branch.
    *   New requests trigger a `Cold Boot` from the new Genesis.
    *   The Tree naturally "regrows" the new lineage (e.g., `3.11.9 -> Numpy -> Torch`) based on demand.

*   **Lazy Growth**: Branches are only grown when requested.
*   **TTL Pruning**: Leaf nodes (Specific Zygotes) are killed after X minutes of inactivity to reclaim RAM.
*   **Root Anchoring**: The `Genesis` node is pinned.

---

## 6. Council Review Constraints (Security & Stability)

### 6.1 The CoW Decay (RefCounting Trap)
*   **Problem**: Python is Reference Counted. Merely *reading* a shared object accesses its refcount header, causing a `Page Fault` (Dirty CoW).
*   **Mitigation Strategy**:
    *   **Python 3.12+ (Recommended)**: Use "Immortal Objects" (PEP 683) to lock refcounts. This provides permanent zero-copy sharing.
    *   **Legacy Python (Allowed with Caveats)**: For Python < 3.12, we accept linear CoW decay.
        *   *Rationale*: Short-lived Agents (Lambda-like) finish before significant decay occurs. The 500ms startup gain outweighs the gradual RAM loss.

### 6.2 ASLR Weakness (The Clone Army)
*   **Risk**: Zygote children share a static memory layout. An RCE exploit for one works for all.
*   **Policy (Selective Hardening)**:
    *   **L0-L2 (Trusted)**: **CONTINUE** to use Zygote.
    *   **L3 (Untrusted)**: **STRICTLY PROHIBITED**. Supervisor must force `exec()` (Cold Boot) to randomize ASLR.

### 6.3 Entropy Reseeding (The Clone UUID)
*   **Mandate**: `pthread_atfork` hooks MUST explicitly reseed:
    *   **OpenSSL**: `OpenSSL_RAND_poll()` (Critical for C-Extensions like `urllib3`).
    *   **Python**: `random.seed()` and `secrets`.
    *   **Numpy**: `numpy.random`.

### 6.4 Branch Poisoning Defense (The Zygote Seal)
*   **Risk**: If a Zygote is compromised or chemically altered (e.g., global state drift) before forking, the entire lineage is poisoned.
*   **Mandate**: **Zygote Seal**.
    *   **Mechanism**: The Zygote process calls `MPROTECT` to lock memory as **Read-Only**.
    *   **Scope Engineering**: MUST carefully target only **Data Segments** and **Old-Generation Heaps**. Applying MPROTECT to the entire heap will crash the Python VM Garbage Collector (which needs to write mark bits).

---

## 7. Operational Excellence

### 7.1 Monitoring: The Efficiency Ratio
*   **Metric**: `PSS / USS` Ratio.
    *   High (> 1.5): Healthy sharing.
    *   Low (~ 1.0): CoW has decayed (RefCounting Trap). Pruning recommended.

### 7.2 The Reaper (Chaos Engineering)
*   **Mechanism**: A background daemon ("The Reaper") aggressively prunes Zygote branches based on:
    *   **TTL**: 5 minutes of inactivity.
    *   **Memory Pressure (PSI)**: When system-wide Pressure Stall Information (PSI) spikes, force-kill LRU branches immediately.
*   **Goal**: Prevent "Zombie Lineages" from consuming RAM indefinitely.
