# Council Review Summary: RFC-0015 (Memory Gravity)

> **Governance Authority**: [SOP-001 Master Lifecycle](../architecture/SOP-001-master-lifecycle.md)
> **Status**: ⚖️ IN REVIEW (Phase II: Critique)
> **Date**: 2026-01-06

---

## 1. The Summons (Phase I)

The following expert personas have been summoned to audit the Shared Tensor Memory architecture:

| Persona | Domain | Focus |
| :--- | :--- | :--- |
| **HPC Engineer** | Performance | Cache locality, Bus contention, HugePages. |
| **Rust Core Dev** | Systems | FD Passing safety, `unsafe` SHM management. |
| **Python Core Dev** | Runtime | `memoryview` stability, GC/RC handshake. |
| **Security Engineer** | Isolation | Memory poisoning, Memory-Write protection. |
| **Linux Specialist** | Kernel | `memfd_create` and sealing. |

---

## 2. The Critique (Phase II - Simulation)

### 🔴 HPC Engineer: "The TLB/Cache Warning"
> "SHM prevents RSS duplication, but a 70B model in shared memory will put immense pressure on the TLB. Without **HugePages** (2MB or 1GB pages), the page table walks will be a bottleneck. Also, we need to ensure the workers aren't competing for the same cache lines in a way that causes L3 thrashing."

### 🔴 Security Engineer: "The Poisoning Vector"
> "A 'ReadOnly' mapping in the child process is not enough. A malicious or compromised worker can call `mprotect` to make its own mapping `PROT_WRITE` and then corrupt the model weights for all other workers. We MUST use **file sealing (`F_ADD_SEALS`)** on Linux to prevent any subsequent writes at the file-descriptor level."

### 🔴 Python Core Dev: "The Dangling Memoryview"
> "If the Rust host reloads the model or exits, the SHM segment might be unmapped. Any Python `memoryview` or `torch.Tensor` pointing to that memory will cause a segmentation fault if accessed. We need a **Liveness Handshake** between the Zygote master and the host."

### 🔴 Linux Specialist: "Infrastructure Gaps"
> "We should prioritize `memfd_create` with `MFD_ALLOW_SEALING`. For macOS, we are forced into `shm_open` which lacks native sealing. We need a 'Least Privilege' verification on macOS to ensure workers aren't running as root, which would allow them to bypass SHM protections."

---

## 3. P0 Blocking Issues (Action Required)

1. **[P0-PERF] HugePage Support**: RFC-0015 must specify how the SHM Registry allocates memory for Large Tensors.
2. **[P0-SEC] File Sealing**: The implementation MUST seal the SHM file (`F_SEAL_WRITE`) after loading and before forking.
3. **[P1-STAB] Liveness Guard**: Implement an IPC mechanism for the host to notify workers before an SHM purge.

---

## 4. Verdict (Pending)

The architecture is **REQUEST CHANGES**.
The Architect must address HugePage allocation and FD Sealing before approval.
