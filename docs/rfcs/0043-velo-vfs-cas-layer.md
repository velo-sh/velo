# RFC-0043: VeloVFS - The CAS Projection Layer

> **Status**: DRAFT  
> **Revision**: 0.1.0  
> **Author**: Velo Architect / Storage Team  
> **Date**: 2026-01-25  
> **Target Version**: v12.0.0 (Phase 2)  
> **Related Documents**: [RFC-0042](0042-velo-virtual-environment.md) (Execution Cell)

---

## 1. Executive Summary

RFC-0042 introduces the **Content-Addressable Storage (CAS)** isolation strategy for the Velo Virtual Environment (VVE). RFC-0043 formalizes the implementation of **VeloVFS**: the userspace filesystem daemon responsible for projecting the flat, immutable CAS store into a standard POSIX filesystem hierarchy for Agents.

VeloVFS acts as a **"Security Projection Layer"** that decouples the Agent's logical view (`/site-packages/numpy`) from the Host's physical reality (`/var/cas/objects/...`).

---

## 2. Core Philosophy (The "Lie")

VeloVFS is not a general-purpose filesystem. It does not manage disk blocks or journals.
*   **Physical Reality**: Flat BLAKE3-hashed blobs on host NVMe.
*   **Logical Illusion**: Standard POSIX directory tree.
*   **Mechanism**: A Rust-based FUSE daemon intercepting VFS calls.

---

## 3. Core Data Structures (In-Memory)

Since the filesystem is read-only and ephemeral (per-session), we do not need on-disk metadata structures. The entire filesystem skeleton is maintained in RAM.

### 3.1 The Inode Map
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

### 3.2 The Filesystem State
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

## 4. The I/O Workflow: Interception & Redirection

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

## 5. Optimization & Risk Management

While the design is architecturally sound, real-world implementation must address three critical bottlenecks:

### 5.1 Infinite Kernel Cache (The Speed of Light)
Because CAS content is **Cryptographically Immutable**:
*   VeloVFS returns `entry_timeout` and `attr_timeout` as **100 Years**.
*   **Result**: The Linux Kernel will **NEVER** ask VeloVFS about the same file twice.
    *   First Access: FUSE Overhead.
    *   Second Access: **Zero Overhead** (Direct Hit in Kernel Page Cache).

### 5.2 Physical Deduplication (OS Page Cache Magic)
*   **Virtual View**: 1000 distinct `numpy.so` files across 1000 Agents.
*   **Physical View**: All 1000 VeloVFS daemons redirect `read()` to the **same physical inode** on the host.
*   **Result**: Linux Kernel detects the physical inode overlap and keeps **ONE COPY** in global RAM. We utilize the OS to achieve zero-cost memory deduplication.

### 5.3 Cold Start Latency (FUSE Passthrough)
*   **Risk**: The "First Bite" latency. Even with infinite cache, the very first metadata lookup hits user-space.
*   **Mitigation**: Use `FUSE_PASSTHROUGH` (Linux 5.15+ / Android Common Kernel).
    *   VeloVFS can hand a physical file descriptor to the kernel during `open()`.
    *   Subsequent `read()` calls bypass the FUSE daemon entirely, routed directly by the kernel to the underlying NVMe file.

### 5.4 Resource Exhaustion (FD & Memory)
*   **FD Exhaustion**: 10k open files in Agent = 10k open FDs in VeloVFS.
    *   **Mitigation**: Implement an **FD LRU Cache**. VeloVFS virtually holds files open for the Agent but physically closes inactive host FDs, re-opening them silently on demand.
*   **Inode Bloat**: Storing millions of inodes in RAM.
    *   **Mitigation**: Use compact Rust structures (`SmallString` for filenames, `u32` for indices) to minimize heap fragmentation.

### 5.5 Invariant-Driven Memory Convergence (The Memory Singularity)
Aligning with the philosophy "Maximize Sharing, Minimize I/O", VeloVFS leverages the immutability of CAS blobs to implement **Global Memory Deduplication**:

*   **Tiered Hot-Mem CAS**:
    *   The Supervisor identifies "Hot Blobs" (e.g., `numpy`, `torch` core libraries).
    *   These blobs are actively preloaded into a **Shared Memory Region** (`/dev/shm/velo_hot_cas`) or pinned via `mlock`.
*   **Zero-Copy Projection**:
    *   Instead of `read()`, VeloVFS can utilize `mmap` to project these physical RAM pages directly into the Agent's address space.
    *   **Benefit**: 1000 Agents loading `torch` consume exactly **0 bytes** of additional physical RAM for the library code. It becomes a pure pointer mapping operation.
    *   **Result**: "Disk" becomes just a backup. Execution happens entirely in shared memory.

```rust
//! VeloVFS Reference Implementation (Proof of Concept)
//! 
//! Architecture:
//! - Content-Addressable Storage (CAS): Flat blob store keyed by BLAKE3 hash.
//! - Virtual Filesystem (VFS): In-memory directory tree mapping to CAS blobs.
//! - FUSE: Serves the VFS to the kernel via /dev/fuse.
//!
//! Dependencies:
//! [dependencies]
//! fuser = "0.12"
//! blake3 = "1.3"
//! serde = { version = "1.0", features = ["derive"] }
//! libc = "0.2"

use fuser::{
    FileAttr, FileType, Filesystem, MountOption, ReplyAttr, ReplyData, ReplyDirectory, ReplyEntry,
    Request,
};
use libc::ENOENT;
use std::collections::HashMap;
use std::ffi::OsStr;
use std::fs::File;
use std::io::{Read, Seek, SeekFrom};
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::{Duration, UNIX_EPOCH};

const TTL: Duration = Duration::from_secs(60 * 60 * 24 * 365); // 1 Year Cache (Immutable)
const BLOCK_SIZE: u64 = 512;

/// A node in the virtual filesystem tree
#[derive(Debug, Clone)]
enum VeloNode {
    Directory {
        children: HashMap<String, u64>, // Filename -> Inode
    },
    File {
        hash: String, // BLAKE3 Hash Key
        size: u64,
    },
}

struct VeloVFS {
    /// Flat CAS storage root (e.g., /var/cas/velo/objects)
    cas_root: PathBuf,
    /// Inode Table: Inode -> Node Data
    inodes: HashMap<u64, VeloNode>,
    /// Parent mapping for ".." lookups (Inode -> Parent Inode)
    parents: HashMap<u64, u64>,
}

impl VeloVFS {
    fn new(cas_root: PathBuf) -> Self {
        let mut fs = Self {
            cas_root,
            inodes: HashMap::new(),
            parents: HashMap::new(),
        };
        // Initialize Root Inode (1)
        fs.inodes.insert(
            1,
            VeloNode::Directory {
                children: HashMap::new(),
            },
        );
        fs.parents.insert(1, 1);
        fs
    }

    /// Helper: Construct a physical path to a CAS blob from its hash
    /// e.g., hash "e3b0c442..." -> /var/cas/velo/objects/e3/b0/e3b0c442...
    fn get_cas_path(&self, hash: &str) -> PathBuf {
        let mut path = self.cas_root.clone();
        path.push(&hash[0..2]);
        path.push(&hash[2..4]);
        path.push(hash);
        path
    }

    /// Helper: Generate file attributes
    fn get_attr(&self, inode: u64) -> Option<FileAttr> {
        match self.inodes.get(&inode) {
            Some(VeloNode::Directory { .. }) => Some(FileAttr {
                ino: inode,
                size: 0,
                blocks: 0,
                atime: UNIX_EPOCH,
                mtime: UNIX_EPOCH,
                ctime: UNIX_EPOCH,
                crtime: UNIX_EPOCH,
                kind: FileType::Directory,
                perm: 0o555, // Read-Execute only
                nlink: 2,
                uid: 0,
                gid: 0,
                rdev: 0,
                blksize: 512,
                flags: 0,
            }),
            Some(VeloNode::File { size, .. }) => Some(FileAttr {
                ino: inode,
                size: *size,
                blocks: (*size + BLOCK_SIZE - 1) / BLOCK_SIZE,
                atime: UNIX_EPOCH,
                mtime: UNIX_EPOCH, // Immutable: Epoch time implies "never changed"
                ctime: UNIX_EPOCH,
                crtime: UNIX_EPOCH,
                kind: FileType::RegularFile,
                perm: 0o444, // Read-only
                nlink: 1,
                uid: 0,
                gid: 0,
                rdev: 0,
                blksize: 512,
                flags: 0,
            }),
            None => None,
        }
    }
}

impl Filesystem for VeloVFS {
    /// Step 1: Lookup - Resolves a filename in a directory to an Inode and Attributes
    fn lookup(&mut self, _req: &Request, parent: u64, name: &OsStr, reply: ReplyEntry) {
        let name_str = name.to_str().unwrap();
        
        // 1. Check if parent exists and is a directory
        if let Some(VeloNode::Directory { children }) = self.inodes.get(&parent) {
            // 2. Look for the child filename
            if let Some(&inode) = children.get(name_str) {
                // 3. Retrieve attributes
                if let Some(attr) = self.get_attr(inode) {
                    // Success: Return Inode + TTL (Infinite)
                    reply.entry(&TTL, &attr, 0);
                    return;
                }
            }
        }
        reply.error(ENOENT);
    }

    /// Step 2: GetAttr - Responds to `stat()` calls
    fn getattr(&mut self, _req: &Request, inode: u64, reply: ReplyAttr) {
        match self.get_attr(inode) {
            Some(attr) => reply.attr(&TTL, &attr),
            None => reply.error(ENOENT),
        }
    }

    /// Step 3: Read - Responds to file content reads
    /// This is where the CAS Magic happens. We map the virtual read to the physical blob.
    fn read(
        &mut self,
        _req: &Request,
        inode: u64,
        _fh: u64,
        offset: i64,
        size: u32,
        _flags: i32,
        _lock_owner: Option<u64>,
        reply: ReplyData,
    ) {
        if let Some(VeloNode::File { hash, .. }) = self.inodes.get(&inode) {
            // 1. Resolve physical path
            let cas_path = self.get_cas_path(hash);
            
            // 2. Open the physical blob
            match File::open(cas_path) {
                Ok(mut file) => {
                    // 3. Seek to the requested offset
                    // Note: In a real implementation, we would keep file handles open (Handle Cache)
                    // to avoid `open()` syscall overhead on every chunk.
                    if let Ok(_) = file.seek(SeekFrom::Start(offset as u64)) {
                        let mut buffer = vec![0u8; size as usize];
                        
                        // 4. Read data
                        match file.read(&mut buffer) {
                            Ok(bytes_read) => {
                                // 5. Return data to kernel
                                reply.data(&buffer[..bytes_read]);
                            }
                            Err(_) => reply.error(libc::EIO),
                        }
                    } else {
                        reply.error(libc::EIO);
                    }
                }
                Err(_) => reply.error(ENOENT), // CAS Blob missing! Major Integrity Error.
            }
        } else {
            reply.error(libc::EISDIR);
        }
    }

    /// Step 4: Readdir - Lists directory contents
    fn readdir(
        &mut self,
        _req: &Request,
        inode: u64,
        _fh: u64,
        offset: i64,
        mut reply: ReplyDirectory,
    ) {
        if let Some(VeloNode::Directory { children }) = self.inodes.get(&inode) {
            let mut entries = vec![];
            
            // Standard entries: "." and ".."
            entries.push((inode, FileType::Directory, "."));
            let parent = *self.parents.get(&inode).unwrap_or(&inode); 
            entries.push((parent, FileType::Directory, ".."));

            // Child entries
            for (name, &child_ino) in children.iter() {
                let kind = match self.inodes.get(&child_ino) {
                    Some(VeloNode::Directory { .. }) => FileType::Directory,
                    _ => FileType::RegularFile,
                };
                entries.push((child_ino, kind, name.as_str()));
            }

            // Pagination logic (skip entries before offset)
            for (i, (ino, kind, name)) in entries.into_iter().enumerate().skip(offset as usize) {
                // i + 1 because offset 0 is "start", next entry is at offset 1
                if reply.add(ino, (i + 1) as i64, kind, name) {
                    break; // Buffer full
                }
            }
            reply.ok();
        } else {
            reply.error(ENOENT);
        }
    }
}
```

---

## 7. Critical Implementation Constraints

The Reference PoC above is simplified. Production implementation **MUST** address three known bottlenecks:

### 7.1 Concurrency Bottleneck (The `&mut self` Trap)
*   **Problem**: The PoC uses `&mut self` for FUSE callbacks, forcing exclusive locking.
*   **Mandate**: Production code **MUST** use `&self` with internal mutability containers (e.g., `DashMap` or `Arc<RwLock<InodeMap>>`).
*   **Goal**: Lock-free reads for high-concurrency Agents (`import` storms).

### 7.2 Syscall Trashing (The `open()` Trap)
*   **Problem**: Calling `File::open()` on every `read()` chunk generates 2x Syscall amplification.
*   **Mandate**: Implement a **File Handle Cache**.
    *   `opendir/open`: Open physical file once, store fd in a map, return a generic handle ID.
    *   `read`: Resolve handle ID -> pinned fd.
    *   `release`: Close physical fd.

### 7.3 Memory Spikes (Readdir Buffering)
*   **Problem**: Generates a full `Vec<Entry>` for `readdir`. A directory with 50k files triggers massive allocation.
*   **Mandate**: Use **Iterator-Based Streaming**. Populate the reply buffer incrementally until full, then yield. Do not materialize the full list.

---

## 8. Security & Stability Hardening

### 8.1 Path Traversal Defense
*   **Risk**: If a malicious Controller injects a hash like `../../etc/passwd`.
*   **Defense**: **Strict Hash Validation**. The CAS path builder MUST verify:
    *   Length == 64 chars (BLAKE3).
    *   Charset == `[a-f0-9]`.
    *   Otherwise: PANIC/Refuse to Serve.

### 8.2 Zero-Copy mmap Support
*   **Requirement**: Python relies heavily on loading `.pyc` and `.so` files via `mmap`.
*   **Implementation**: VeloVFS MUST support `FOPEN_KEEP_CACHE` (or `FUSE_PASSTHROUGH` where available) to allow the Kernel to manage page faults directly from the physical file, bypassing the FUSE daemon for memory-mapped regions.

---

## 9. Multi-Version Support (The ABI Matrix)

A critical requirement is supporting multiple Python versions (3.9, 3.10, 3.11) and System ABIs (glibc 2.31, 2.35) simultaneously on the same host. VeloVFS handles this via **Dimensional Isolation**:

### 9.1 ABI-Keyed Hash Separation
*   **Challenge**: `numpy v1.24` compiled for Python 3.10 is NOT binary compatible with Python 3.11.
*   **Solution**: The CAS key is NOT just `Hash(Content)`. It is `Hash(Content + ABI_Tag)`.
    *   Blob A: `numpy.so (cp310)` -> stored at `/var/cas/objects/a1/b2/...`
    *   Blob B: `numpy.so (cp311)` -> stored at `/var/cas/objects/c3/d4/...`
    *   **Result**: Different ABIs physically map to different blobs. No collision possible.

### 9.2 Unified System Projection (The "One File System" Theory)
*   **Concept**: We eliminate the "Split Brain" distinction between "Base OS" (SquashFS) and "Packages" (VeloVFS).
*   **Mechanism**:
    *   **Ingestion**: The Base OS (e.g., Ubuntu 22.04) is decomposed. Every file in `/usr/lib`, `/bin`, `/etc` is hashed and stored in the global CAS.
    *   **Projection**: VeloVFS mounts as the **Global Root (`/`)**.
    *   **Composition**: The "Root Inode" is now a merge of:
        *   `System Manifest` (Hash of Ubuntu 22.04 file tree)
        *   `Environment Manifest` (Hash of Python 3.11 + Numpy 1.24 file tree)
*   **Implication**:
    *   **Atomic OS Switching**: Switching from glibc 2.31 to 2.35 is just a VeloVFS pointer swap.
    *   **Total Deduplication**: Common files between different OS versions (e.g. `ca-certificates`, `locale`) are physically deduplicated.
    *   **Simplicity**: No OverlayFS Driver needed. VeloVFS handles the entire stack.
