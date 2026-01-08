# Blueprint: AI Serverless Indispensability (Vision to Reality)

To achieve the goal where "Python cold start pain was never necessary," we must solve three physical bottlenecks.

---

## 1. The Startup Speed Pillar (Sub-100ms Target)

### **What we do**:
We eliminate the "Search, Parse, Execute" cycle of Python's `import` system.

### **Audit Validation (Phase 6.2)**:
| Metric | Standard Runner | Zygote Mode | Target |
| :--- | :--- | :--- | :--- |
| Hot Restart | **~591ms** 🔴 | **~87ms** ✅ | < 100ms |
| Memory Overhead | 47MB ✅ | 47MB ✅ | < 50MB |

> **Conclusion**: Standard Runner **cannot** meet cold start goals. **Zygote is mandatory** for AI Serverless.

### **How we do it (Engineering)**:
1.  **Zygote Optimization**:
    - Instead of `python app.py`, Velo boots a **Zygote Master**.
    - It pre-loads `torch`, `transformers`, and basic logic.
    - When a request arrives, Rust triggers a `fork()` via UDS.
    - **Zero-Copy Inheritance**: The OS `fork()` gives the child worker all pre-loaded memory (COW) in < 5ms.
2.  **Fast Loader Implementation**:
    - Velo bypasses the sequential file-system lookups for `.py` files.
    - It pre-bundles all dependencies into a **Content-Addressable Blob**.
    - **Result**: No `import` delay, no `sys.path` searching.

---

## 2. The Memory Density Pillar (10x Density Target)

### **What we do**:
We move the "Weight" out of the worker and into the host.

### **How we do it (Engineering)**:
1.  **Memory Gravity (SHM Tech)**:
    - **Phase 7.0**: The Rust Host `mmap()`s the `.safetensors` model weights into **Shared Memory**.
    - **FD Passing**: Velo passes the memory file descriptors to spawned workers.
    - **Zero-Copy Access**: Python workers wrap the shared memory as Tensors.
    - **Security (H-19)**: Linux uses `F_SEAL_WRITE` to prevent memory poisoning.
    - **Benefit**: 1 replica uses 10GB. 100 replicas still use **10GB** (plus a few MB for individual heaps).

---

## 3. The Deployment Pillar (No-Dockerfile Target)

### **What we do**:
We replace the heavy Container-build cycle with a single "Binary + Bundle" execution.

### **How we do it (Engineering)**:
1.  **The `.veloc` Bundle**:
    - A single file containing the entire bytecode environment, dependencies, and model meta-assets.
2.  **The `velo` Binary**:
    - A statically-linked binary that acts as the Proxy + Supervisor + Loader.
    - To deploy: `curl | sh` to get Velo, then `velo run model.veloc`. No Docker, no layers, no registry.

---

## 4. The Security Pillar (Council-Mandated)

### **Security Expert Critique (RFC-0015 Review)**:
> *"A 'ReadOnly' mapping is not enough. A malicious worker can call `mprotect` to make its own mapping `PROT_WRITE` and corrupt the model weights for all workers."*

### **How we harden it (Engineering)**:
1.  **H-19: File Sealing** (Linux): Use `F_ADD_SEALS` + `F_SEAL_WRITE` on the SHM file descriptor. This blocks `mprotect` bypass at the kernel level.
2.  **H-20: HugePages**: Allocate large tensors (>1GB) using `MAP_HUGETLB` to minimize TLB pressure.
3.  **H-21: Liveness Guard**: Rust broadcasts `SHM_EXPIRE` before unmapping, preventing SIGSEGV in Python.

---

## 🚀 Execution Roadmap (The "How" of Delivery)

| Phase | Milestone | Outcome |
| :--- | :--- | :--- |
| **Current** | **AI Demo PoC** | Prove the Sensorial Difference (2.3s -> 87ms). |
| **Phase 7.0**| **Memory Gravity**| Implement `safetensors` SHM sharing with H-19/H-20/H-21. |
| **Phase 7.1**| **Kinetic Handshake**| Harden the sub-10ms IPC between Rust and Zygote. |
| **Phase 8.0**| **Velo Bundle v1** | Consolidate `velo build` to output the "Everything" bundle. |

---

**🏛️ Architect's Declaration**:
We are not just building a faster Python. We are building the **"Industrial substrate for AI Inference"**.
