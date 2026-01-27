# RFC-0046: Git-Driven Metadata & Connection Governance

**Status**: DRAFT (Vision)  
**Author**: Velo Architect  
**Date**: 2026-01-27  
**Scope**: Zygote Topology, VeloVFS Metadata, Environment Versioning

---

## 1. Executive Summary

This RFC proposes a **Separation of Concerns (SoC)** for Velo's environment and process management:
- **Governance Layer (Git)**: Use the Git Object Model (DAG) to manage lineage, connection relationships, and versioning.
- **Storage Layer (TheSource)**: Use a simple, flat directory structure for actual content (blobs) to maximize I/O performance and bypass Git's internal overhead (packfiles/zlib).

---

## 2. The Philosophy: Metadata vs. Content

Traditional Git manages both. Velo decouples them to achieve **Industrial-Grade Scale** and **Mechanical Sympathy**.

### 2.1 TheSource (Data Layer)
`TheSource` is a high-performance content-addressable directory.
- **Path**: `${VELO_HOME}/the_source/[digest_prefix]/[digest]`
- **Storage**: Raw files (uncompressed or LZ4/Zstd) for direct `mmap` and `sendfile` support.
- **Speed**: Optimized for NVMe throughput and Kernel Page Cache.

### 2.2 Git (Metadata Layer)
Git is used as a **Topological Engine**.
- **Commits**: Represent an "Environment Snapshot" or "Zygote State".
- **Trees**: Represent the filesystem structure (pointing to hashes in `TheSource`).
- **Refs**: Represent "Living Lineages" (e.g., `prod/stable`, `dev/experimental`).
- **Parents**: Represent the **Genealogical Linkage** between Zygotes (Phylogeny).

---

## 3. Zygote Connection Governance

Instead of a flat process list, Zygotes are managed as a **Live Git Tree**.

```text
Commit A (Python 3.11 Genesis)
  │
  └── Commit B (Numpy Loaded) ─── [Zygote Process 1024]
        │
        └── Commit C (Torch Loaded) ─── [Zygote Process 2048]
```

### 3.1 Genealogical Discovery
When an agent requests an environment with `[Python 3.11, Numpy, Torch]`:
1. The Supervisor queries the Git ODB: `git rev-parse torch-linage`.
2. It finds the nearest **Live Commit** (a Zygote process that is currently running).
3. If `Commit C` is alive, `fork()` from it.
4. If only `Commit B` is alive, `fork()` from B, load Torch, and "commit" the new state.

---

## 4. VFS Projection Logic

VeloVFS uses the Git Tree to decide *what* to show, but reads from `TheSource` for *how* to show it.

```rust
fn lookup(path: &str) -> FileHandle {
    // 1. Query Git Metadata
    let blob_hash = git_odb.find_tree_entry(path).hash();
    
    // 2. Open from TheSource
    let physical_path = the_source.get_path(blob_hash);
    return File::open(physical_path); // Pure I/O, no Git overhead
}
```

---

## 5. Benefits

### 5.1 Performance (TheSource)
- **Zero-Copy**: Files are stored in a format ready for `mmap`/`sendfile`.
- **No Decoupling Latency**: Bypasses Git's delta-chain reconstruction.

### 5.2 Governance (Git)
- **Proven Lineage**: 15 years of industry-tested DAG logic for version conflicts and merging.
- **Traceability**: Every running worker has a `Commit ID` identifying exactly what is in its memory and disk.
- **Distributed Push/Pull**: Sync metadata via `git push`, sync content via `rsync` or `S3 sideband` from `TheSource`.

---

## 6. Environment Governance Pillars

By adopting this architecture, Velo achieves four strategic goals for enterprise-grade runtimes:

| Pillar | Implementation | Value |
|:---|:---|:---|
| **Auditing** | Zygote associated with unique Commit ID | Every line of code and every dependency in production is signed and traceable. |
| **Tracking** | Git parent/child lineage | Full visibility into how an environment evolved from a bare Genesis image to its current state. |
| **Reproduction** | CommitID + CAS Bit-Identity | Guaranteed bit-for-bit identical environments across different machines/clusters if Commit ID matches. |
| **Reuse** | Branch-based hot-partitioning | Heavy initializations (e.g., loading 70B LLM) happen once in a parent node; all children reuse that state instantly via COW. |

---

## 7. Implementation Strategy

1. **Velo-Git-Core**: Integration of `git-oxide` for ODB metadata lookups.
2. **TheSource Manager**: Logic for hashing and storing blobs into the flat directory.
3. **Phylogeny Bridge**: Supervisor logic to map OS PIDs to Git Commits.

---

**Custodian**: Velo Architect  
**Review Type**: Strategic Architectural Shift
