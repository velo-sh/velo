# VeloVFS: Architecture & Design Internals

> **Supplementary Document to RFC-0042**  
> **Topic**: The "Projection Layer" Implementation of CAS Isolation

---

## 1. Core Philosophy: The Projection Layer

VeloVFS is not a traditional general-purpose filesystem. It does not manage disk blocks, journals, or bitmaps. Instead, it is a **Read-Only Projection Layer**.

*   **Physical Reality**: A flat, content-addressable storage (CAS) on the host NVMe (`/var/cas/velo/objects/...`).
*   **Logical Illusion**: A standard, hierarchical POSIX filesystem presented to the Agent.
*   **Mechanism**: A Rust-based FUSE (Filesystem in Userspace) daemon that intercepts Kernel VFS calls and verifies/redirects them to CAS blobs.

---

## 2. Core Data Structures (In-Memory)

Since the filesystem is read-only and ephemeral (per-session), we do not need on-disk metadata structures. The entire filesystem skeleton is maintained in RAM.

### 2.1 The Inode Map
```rust
struct VeloInode {
    ino: u64,           // Unique 64-bit ID
    name: String,       // "numpy", "__init__.py"
    kind: FileType,     // Directory | RegularFile
    
    // IF File: Point to the Immutable Truth
    cas_hash: Option<Blake3Hash>, 
    
    // IF Directory: Point to Children
    children: Vec<u64>, 
}
```

### 2.2 The Filesystem State
```rust
struct VeloFS {
    // fast lookups: O(1) access to any node
    inodes: HashMap<u64, VeloInode>,
    
    // The "Lie" Dictionary: Mapping Virtual Paths to Physical CAS Paths
    // e.g. Virtual Inode 10086 -> Physical /var/cas/velo/objects/e3/b0/...
    cas_root: PathBuf,
}
```

---

## 3. The I/O Workflow: Interception & Redirection

When a Python Agent performs `import numpy`, the following kernel-user dance occurs:

### Phase 1: Lookup (The "Lie")
1.  **Agent**: Syscall `open("/site-packages/numpy/__init__.py")`.
2.  **Kernel (VFS)**: Asks VeloVFS daemon: "Does `numpy` contain `__init__.py`?"
3.  **VeloVFS**: 
    *   Checks in-memory `children` list of the `numpy` directory inode.
    *   Finds match. Returns attributes: `Inode: 10086`, `Size: 512`, `Perm: 0o444`.
    *   *Note*: VeloVFS confirms existence without checking disk.

### Phase 2: Read (The "Redirection")
1.  **Agent**: Syscall `read(fd, 512 bytes)`.
2.  **Kernel**: Forwards request to VeloVFS for Inode 10086.
3.  **VeloVFS**:
    *   **Resolution**: Looks up Inode 10086 -> Hash `e3b0c442...`
    *   **Redirection**: Opens host file `/var/cas/velo/objects/e3/b0/e3b0c442...`
    *   **Execution**: Performs `pread` on the physical file.
    *   **Return**: Sends secure bytes back to Kernel.

---

## 4. Performance Optimizations (The "Nuclear" Option)

User-space filesystems (FUSE) are notoriously slow due to Context Switches. VeloVFS eliminates this penalty using three "Nuclear" optimizations:

### 4.1 Infinite Kernel Cache (TTL = ∞)
Because CAS content is **Cryptographically Immutable**:
*   VeloVFS returns `entry_timeout` and `attr_timeout` as **100 Years**.
*   **Result**: The Linux Kernel will **NEVER** ask VeloVFS about the same file twice.
    *   First Access: FUSE Overhead.
    *   Second Access: **Zero Overhead** (Direct Hit in Kernel Page Cache).

### 4.2 Physical Deduplication (OS Page Cache Magic)
*   **Scenario**: 1000 Agents running `numpy`.
*   **Virtual View**: 1000 distinct `numpy.so` files.
*   **Physical View**: All 1000 VeloVFS daemons redirect `read()` to the **same physical path** on the host.
*   **Result**: Linux Kernel detects the same physical inode is being read. It keeps **ONE COPY** in RAM (Page Cache). 1000 Agents share a single physical memory footprint.

### 4.3 Lazy Loading
*   VeloVFS does not preload the entire CAS map.
*   Inodes are constructed lazily only when a directory is `opendir`'d by the Agent.
*   Startup cost is proportional to `O(1)`, not `O(Total Files)`.

---

## 5. Summary

VeloVFS is not "Storage". It is a **Secure Mapping Protocol**.
*   **Input**: A logical tree of Hashes.
*   **Output**: A high-performance POSIX filesystem.
*   **Guarantee**: Absolute Isolation (No symlinks) + Native Performance (Page Cache).
