# Project Rift: Open Source Launch Plan

> **Mission**: Liberate the VeloVFS technology from the Velo Monolith and donate it to the global developer community as a standalone I/O accelerator: **Velo Rift**.

---

## 1. The Separation Strategy (The Great Decoupling)

Currently, Velo is a monolithic crate. To execute the "Rift" vision, we must refactor into a **Cargo Workspace**.

### 1.1 Target Repository Structure
```text
velo/
├── Cargo.toml (Workspace Root)
├── crates/
│   ├── velo-vfs/           # [OPEN SOURCE] The Core Engine (FUSE/CAS/DAX)
│   │   ├── src/lib.rs      # Library crate
│   │   └── Cargo.toml      # publish = true
│   │
│   ├── velo-rift/          # [OPEN SOURCE] The Standalone Tool ("Velo Rift")
│   │   ├── src/main.rs     # CLI binary (rift open, rift exec)
│   │   └── Cargo.toml
│   │
│   └── velo-supervisor/    # [INTERNAL] The Orchestration Brain
│       ├── src/            # Depends on velo-vfs
│       └── Cargo.toml
│
├── docs/                   # Shared Documentation
├── LICENSE                 # Apache 2.0
└── CONTRIBUTING.md         # Community Guidelines
```

### 1.2 License Selection
*   **License**: **Apache 2.0**.
*   **Rationale**: Industry standard for infrastructure (Kubernetes, Terraform, Rust). Allows commercial adoption while protecting patent rights.

---

## 2. The "Rift" MVP (Minimum Viable Product)

We will release `velo-rift` v0.1.0 with the following capabilities:

1.  **CAS Storage**: Standard BLAKE3-based content addressable storage (On-Disk).
2.  **FUSE Projection**: Read-only mounting of CAS blobs.
3.  **CLI**: `rift open <s3_url> <dir>` and `rift mount <hash> <mountpoint>`.

*Note: Advanced features like DAX/Virtio-FS will follow in v0.2.0.*

---

## 3. Governance & Community

To be a "Good Citizen" of the OSS world, we need more than code.

### 3.1 Documentation First
*   **README.md**: Must be "Action-Oriented". 
    *   "Install in 1 command."
    *   "Rift through your `node_modules` in 30 seconds."
*   **Architecture Guide**: Promoting the "Memory Broker" philosophy.
