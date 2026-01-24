# RFC-0042: Velo Virtual Environment (VVE) - The Agentic Sandbox

> **Status**: DRAFT  
> **Revision**: 0.1.0 (Initial Proposal)  
> **Author**: Velo Architect / AI Safety Committee  
> **Date**: 2026-01-24  
> **Target Version**: v11.0.0+  
> **Parent Documents**: [RFC-0012](0012-full-armor-security-standard.md), [RFC-0019](0019-native-sovereignty.md)

---

## 1. Executive Summary

As AI Agents transition from "code generation" to "autonomous execution," the requirement for a secure, isolated, yet fully functional execution environment has become critical. Conventional isolation methods (MicroVMs, Containers) often introduce significant overhead or latency penalties that conflict with low-latency execution requirements.

RFC-0042 defines the **Velo Virtual Environment (VVE)**: a modular isolation architecture designed to provide full environment sovereignty (Private Rootfs, Network, and PID isolation) with sub-20ms startup latency by leveraging Zygote-based pre-initialization.


---

## 2. Motivation: The Execution Gap

Existing execution sandboxes present a trade-off between **Isolation Depth** (MicroVMs) and **Startup Performance** (Native Processes). For autonomous agents, the environment must be both "disposable" (to prevent state pollution) and "instantly available" (to minimize processing stalls).


Velo is uniquely positioned to fill this gap by applying Kernel-level namespaces *after* the Zygote fork but *before* the Agent code execution.

---

## 3. The Modular Isolation Spectrum (Capability Matrix)

Unlike rigid containers, Velo's sandbox is a **modular capability matrix**. Users can choose the level of isolation based on the specific intent of the Agent, with the ability to "opt-out" of even the most basic protections for maximum native performance.

| Tier | Name | Intent | Mechanism | Default |
| :--- | :--- | :--- | :--- | :--- |
| **L(-1)** | **Bare** | Performance Tuning | No shielding, raw OS process | No |
| **L0** | **Classic** | General Execution | ImportShield, VeloPaths | **Yes** |
| **L1** | **Forensic** | Audit & Governance | LOP (High-res logging), TraceID | Optional |
| **L2** | **Sovereign** | Filesystem Security | Landlock (VFS Access Control) | Optional |
| **L3** | **Titanium** | Untrusted Code | Seccomp (Syscall filtering), Cgroups | Optional |
| **L4** | **Virtual** | Full Virtualization | Namespaces, OverlayFS | Optional |


---

## 4. Configuration: Purposed-Driven Selection

VVE allows developers to "dial-in" the exact environment needed. A data-science agent might need **L0 (Performance) + L2 (File Safety)**, while a web-scraping agent needs **L4 (Networking) + L3 (Resource Caps)**.

### 4.1 Opt-Out Policy (The "Nitro" Switch)
Velo allows the explicit disabling of `ImportShield` or `PathSanitization` for legacy compatibility.

> **CRITICAL SECURITY REQUIREMENT**:
> To prevent privilege escalation, the "Nitro Switch" (L-1/L0 opt-out) is **gated by a Cluster-Level Policy**.
> *   **Local Dev**: Enabled by default.
> *   **Production**: Requires a signed `velo.policy.toml` or `VELO_ALLOW_UNSAFE=1` (Admin-only env var).
> An Agent executing with a user-level request for `tier: "L-1"` WILL FAIL if the cluster policy explicitly forbids it.

### 4.2 L4 VVE (Virtual Environment) Implementation

### 4.1 The "Instant Container" Workflow
1.  **Preparation**: Velo maintains a pre-mounted **LowerLayer** (ReadOnly Rootfs) containing the base OS and Python distribution.
2.  **Fork**: Zygote forks a new worker.
3.  **Encapsulation (Post-Fork)**: 
    *   Subprocess calls `unshare(CLONE_NEWNS | CLONE_NEWNET | CLONE_NEWPID | CLONE_NEWUSER)`.
    *   Mounts a per-session **UpperLayer** (Tmpfs/Ramdisk) for write capability.
    *   Executes `pivot_root` to switch to the isolated VVE root.
4.  **Activation**: The Python Agent starts, seeing a "Fresh VM" environment.

### 4.2 Filesystem Sovereignty (OverlayFS)
VVE uses OverlayFS to provide a "Writable Root" experience without persistent storage overhead.
*   **LowerDir**: `/opt/velo/rootfs/base`
*   **UpperDir**: `/tmp/velo-vve-{trace_id}/work`
*   **MergedDir**: Assigned as `/` for the Agent.

### 4.3 Identity & Privilege (User Namespaces)
Using User Namespaces, VVE allows the Agent to act as `root` (UID 0) inside the sandbox (enabling `pip install`, `apk add`, etc.) while mapped to an unprivileged user on the host.

### 4.4 Networking (Network Namespaces)
*   Isolated `lo` (loopback) interface.
*   **eBPF Datapath**: Unlike traditional `iptables` which suffer from lock contention at high churn, VVE MUST use **eBPF (TC/XDP)** for egress filtering. This allows lock-free packet inspection for thousands of ephemeral containers.

---

## 5. Challenges & Invariants

### 5.1 SHM Gravity (The Velo Dilemma)
Standard Velo performance relies on `/dev/shm` zero-copy.
*   **Challenge**: `pivot_root` moves the root mount, potentially obscuring the host's `/dev/shm` before the new environment is ready.
*   **Solution**: The Rust Supervisor follows a strict `unshare` -> `mount` sequence:
    1.  `unshare(CLONE_NEWNS)`: Create private mount namespace.
    2.  `mount --make-rslave /`: Prevent propagation of changes back to host.
    3.  `mount --bind /dev/shm <upper_layer_path>/dev/shm`: Bind host SHM to the target location *before* pivoting.
    4.  `pivot_root`: Switch root.
    5.  The bound SHM remains accessible at `/dev/shm` inside the new namespace.
    *Note: This relies on the file descriptor remaining valid across the namespace transition, which is standard Linux behavior.*

### 5.2 ABI Parity
The Rootfs base image must precisely match the Zygote's runtime ABI (glibc/musl version) to prevent `dlopen` failures of pre-loaded libraries.

### 5.3 Kubernetes Compatibility (The "Sticky Bit" Risk)
`CLONE_NEWUSER` is often restricted in managed Kubernetes environments (EKS/GKE) via `unprivileged_userns_clone`.
*   **Mitigation**: VVE detection logic must probe `/proc/sys/kernel/unprivileged_userns_clone` at startup.
*   **Fallback Policy**:
    *   **Default**: **Fail-Closed**. If L4 is requested but UserNS is blocked, the Agent fails to start. Silent degradation is forbidden.
    *   **Explicit Downgrade**: If and only if the Agent spec includes `allow_downgrade: true`, Velo will fallback to **L3 (Titanium)** (Seccomp/Cgroups only).

---

## 6. Implementation Roadmap

1.  **Phase A**: Prototyping `L2 (Landlock)` on Linux as a non-breaking security enhancement.
2.  **Phase B**: Implementing `unshare()` logic in the Rust Worker Supervisor.
3.  **Phase C**: Developing the `Base Image` distribution system for VVE.

---

## 7. Glossary
*   **OverlayFS**: A stackable filesystem that combines multiple directories into one.
*   **unshare(2)**: A Linux system call that creates a new namespace for the calling process.
*   **pivot_root(2)**: Moves the root filesystem of the calling process to a new directory.

---

## 8. References
*   [Linux Namespaces Manual](https://man7.org/linux/man-pages/man7/namespaces.7.html)
*   [E2B Sandbox Architecture](https://e2b.dev/docs/sandbox)
*   [Landlock LSM Documentation](https://landlock.io/)
