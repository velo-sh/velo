# The Trinity Architecture

> **Philosophy**: Data, Compute, and Environment are distinct manifestations of a single substance: **Memory**.

The **Trinity Architecture** unifies the cloud stack by eliminating the boundaries between storage, execution, and context. It is the foundation of the Velo platform.

---

## I. The Father: Data (Velo Rift)
*   **The Substance**: Immutable Content-Addressable Storage (CAS).
*   **The Mechanism**: **Memory Projection**.
*   **Concept**: Data is not "downloaded" to disk; it is "projected" into the address space.
*   **RFC**: [RFC-0043 VeloVFS](./rfcs/0043-velovfs-cas-layer.md)

## II. The Son: Compute (Zygote Tree)
*   **The Act**: Execution as a Branching Tree.
*   **The Mechanism**: **Copy-on-Write (CoW)**.
*   **The Theory**: **Compute Phylogeny**.
    *   Compute is not a linear "process start"; it is a phylogenetic fork from a parent state.
*   **RFC**: [RFC-0044 Kinetic Zygote](./rfcs/0044-kinetic-zygote-phylogeny.md)

### 2.1 Modular Phylogeny (Composable Genes)
A Zygote is not a monolithic snapshot. It is composed of independent **Genetic Units** (e.g., specific Python Libs, Shared Objects).
*   **Composition**: A Zygote State = `Σ(Unit_A, Unit_B, Unit_C...)`.
*   **Evolution**: Upgrading a single unit (e.g., `LibA v1` -> `v2`) does not restart the process. It **forks** a new state leaf where only that unit's memory pages are rebased.
*   **Result**: Granular, non-destructive upgrades for running compute.

## III. The Spirit: Environment (Universal Intent)
*   **The Context**: Pervasive Logic & Configuration.
*   **The Mechanism**: **Dirty State Injection**.
*   **Concept**: The environment is not a static container Image; it is a dynamic overlay applied to the compute branch.
*   **RFC**: [RFC-0042 Execution Cell](./rfcs/0042-velo-virtual-environment.md)

---

## Consubstantiality (Memory Unification)

In traditional cloud:
`S3 (Disk) -> Network -> Docker (OverlayFS) -> RAM -> CPU`

In Trinity:
`CAS Blob (Memory) == Process Memory (Memory) == Environment (Memory)`

We do not move bytes. We manipulate pointers.
**Zero Copy. Zero Friction. Zero Distance.**
