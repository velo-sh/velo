# RFC-0036: LifeCode™ Model

> *"Software That Lives"*

**Status**: DRAFT (Vision)
**Author**: 0xMaster
**Date**: 2026-01-19
**Phase**: Future (v2.0)
**Scope**: Software Representation & Composition
**Depends**: RFC-0034 (v1.0 Bundle Foundation)

---

## 1. Executive Summary

**LifeCode™** is a revolutionary software model that treats applications as living organisms composed of fundamental units (cells), genetic identifiers (hashes), and their relationships.

> **Core Questions**:
> 1. How to describe a software organism? (Representation)
> 2. How to reassemble a software organism? (Composition)

| Aspect | Description |
|:---|:---|
| **Model Name** | LifeCode™ |
| **Metaphor** | Software = Living Organism |
| **Representation** | Hash Tree = Genetic Blueprint |
| **Composition** | Rebuild organism from gene fragments |
| **Deduplication** | Shared gene pool, store each gene once |

---

## 2. Core Concept

### 2.1 The Biological Metaphor

> **Software = Living Organism**: An organic whole composed of fundamental units, genetic fragments, and their relationships.

| Biology Concept | Software Equivalent | Description |
|:---|:---|:---|
| **Cell** | File (blob) | Fundamental unit, indivisible |
| **Gene (DNA)** | Hash | Unique identifier, defines characteristics |
| **Organ** | Module (tree) | Organic combination of cells |
| **Organism** | Application (root) | Complete system of all organs |
| **Species** | Root Hash | Unique identity of the organism |
| **Gene Pool** | Object Store | Shared storage for all gene fragments |
| **Reproduction** | Distribution | Transmit Root Hash = transmit blueprint |
| **Evolution** | Version Update | Mutation = content change = new Hash |

```
                  ┌─────────────────────────────────────────┐
                  │              Organism                   │
                  │            Root Hash: abc123            │
                  └─────────────────┬───────────────────────┘
                                    │
           ┌────────────────────────┼────────────────────────┐
           │                        │                        │
    ┌──────▼──────┐          ┌──────▼──────┐          ┌──────▼──────┐
    │ Organ: app/ │          │ Organ: deps/│          │Organ: assets│
    │ (def456)    │          │ (ghi789)    │          │ (jkl012)    │
    └──────┬──────┘          └──────┬──────┘          └──────┬──────┘
           │                        │                        │
    ┌──────▼──────┐          ┌──────▼──────┐          ┌──────▼──────┐
    │Cell: main.py│          │Cell: torch/ │          │Cell: model  │
    │ DNA: mno345 │          │ DNA: stu901 │          │ DNA: vwx234 │
    └─────────────┘          └─────────────┘          └─────────────┘
```

**Core Insights**:
- **Shared Genes**: Different organisms can share identical genes (deduplication)
- **Incremental Evolution**: Version updates only change mutated genes
- **Blueprint Transmission**: Distribution = transmit DNA blueprint, not entire organism

### 2.2 Hash Tree Structure

```
                    Root Hash (abc123)
                   /         |         \
                  /          |          \
            app/          deps/        assets/
           (def456)      (ghi789)     (jkl012)
           /     \          |            |
      main.py  utils.py  torch/      model.safetensors
     (mno345)  (pqr678)  (stu901)      (vwx234)
```

### 2.3 Representation

> **Question**: How to fully describe a software organism?

```json
{
  "type": "organism",
  "root": "abc123...",
  "name": "my-app",
  "version": "1.0.0",
  "organs": [
    { "name": "app", "hash": "def456...", "type": "tree" },
    { "name": "deps", "hash": "ghi789...", "type": "tree" },
    { "name": "assets", "hash": "jkl012...", "type": "tree" }
  ],
  "entrypoint": "app:main",
  "environment": {
    "python_version": ">=3.11"
  }
}
```

**Representation = Root Hash + Manifest**
- Root Hash is the organism's "Species ID"
- Manifest is the "Genetic Map", describing all organs and cells

### 2.4 Composition

> **Question**: How to reassemble a complete organism from gene fragments?

```
Composition Pipeline:

1. Read Root Hash
   └─→ Fetch Manifest (genetic map)

2. Parse Organs (organ list)
   └─→ Recursively parse each organ's subtree

3. Locate Cells
   └─→ Find each hash in Object Store

4. Materialize
   ├─→ Cached: hardlink directly
   └─→ Not cached: fetch from source + store in cache

5. Activate
   └─→ Run entrypoint
```

**Composition Strategies**:

| Strategy | Description | Use Case |
|:---|:---|:---|
| **Full Materialization** | Materialize entire tree | Offline execution |
| **Lazy Materialization** | Materialize on demand | Fast startup |
| **Virtual Materialization** | mmap + overlay | Large models |

---

## 3. Design Principles

### 3.1 Content-Addressable Storage

| Principle | Description |
|:---|:---|
| **Immutable** | Objects never change (hash = identity) |
| **Dedup** | Same content = same hash = stored once |
| **Verifiable** | Hash verifies integrity |

### 3.2 Object Store Layout

```
~/.velo/objects/
├── ab/
│   └── c123...  # Root manifest
├── de/
│   └── f456...  # app/ subtree
├── gh/
│   └── i789...  # deps/ subtree
└── ...
```

### 3.3 Manifest Format

```json
{
  "type": "tree",
  "hash": "abc123...",
  "entries": [
    { "name": "app", "type": "tree", "hash": "def456..." },
    { "name": "deps", "type": "tree", "hash": "ghi789..." },
    { "name": "assets", "type": "tree", "hash": "jkl012..." }
  ],
  "metadata": {
    "name": "my-app",
    "version": "1.0.0",
    "entrypoint": "app:main"
  }
}
```

---

## 4. Industry Comparison

| System | Similarity | Difference |
|:---|:---|:---|
| **Git** | Object store, SHA, trees | Git is for source, Velo for distribution |
| **IPFS** | Content-addressable, DAG | IPFS is p2p, Velo is client-server |
| **Nix** | `/nix/store/{hash}-{name}` | Nix is system-wide, Velo is app-focused |
| **OSTree** | Atomic updates, hardlinks | OSTree is for OS, Velo for apps |
| **Docker** | Layer dedup | Docker is containers, Velo is packages |

---

## 5. Key Features

### 5.1 Incremental Updates

```
v1.0.0 (root: abc123)           v1.0.1 (root: xyz789)
├── app/ (def456) ──────────────├── app/ (NEW: uvw111)  ← Only this changes
├── deps/ (ghi789) ─────────────├── deps/ (ghi789)      ← Reused
└── assets/ (jkl012) ───────────└── assets/ (jkl012)    ← Reused

Download: Only new root + changed subtree
```

### 5.2 Global Deduplication

```
App A uses PyTorch 2.1.0 (hash: torch-abc)
App B uses PyTorch 2.1.0 (hash: torch-abc)

Storage: torch-abc stored ONCE
Both apps reference same hash
```

### 5.3 Lazy Loading

```bash
velo run sha256:abc123

# Initial: Download root manifest
# On-demand: Download subtrees as accessed
# Cache: Never re-download same hash
```

### 5.4 Adaptive Dependency Resolution

> **One hash, any platform**: Automatically resolve and substitute dependencies based on runtime environment.

**Manifest Declaration**:
```json
{
  "name": "my-app",
  "dependencies": {
    "torch": {
      "preferred": "torch==2.1.0",
      "alternatives": [
        { "variant": "cuda", "hash": "abc123...", "requires": "nvidia-gpu" },
        { "variant": "rocm", "hash": "def456...", "requires": "amd-gpu" },
        { "variant": "mps", "hash": "ghi789...", "requires": "apple-silicon" },
        { "variant": "cpu", "hash": "jkl012...", "requires": null }
      ],
      "fallback": "cpu"
    }
  }
}
```

**Runtime Behavior**:
```
velo run sha256:abc123

[velo] Detecting environment...
[velo] ✓ Apple M3 detected (MPS capable)
[velo] Preferred torch-cuda not compatible
[velo] Selecting alternative: torch-mps (gene: ghi789)
[velo] Fetching from gene pool...
[velo] ✓ Organism materialized
[velo] ✓ App started
```

**Resolution Priority**:
| Priority | Check | Action |
|:---|:---|:---|
| 1 | Preferred available locally | Use cached |
| 2 | Preferred available remotely | Fetch & use |
| 3 | Compatible alternative locally | Use cached |
| 4 | Compatible alternative remotely | Fetch & use |
| 5 | Fallback | Use CPU variant |

### 5.5 Hash-based Deployment

> **Deploy = Send Hash**: A single hash message deploys an entire application.

**Deployment Flow**:
```
Developer                          Server
   │                                 │
   │  "sha256:abc123"                │
   │ ────────────────────────►       │
   │                                 │
   │                    1. Receive hash
   │                    2. Query registry
   │                    3. Fetch genes (dedup)
   │                    4. Materialize organism
   │                    5. Start service
   │                                 │
   │     ◄──── Service Running ──    │
```

**CLI Examples**:
```bash
# Local run
velo run sha256:abc123

# Remote deploy (SSH)
velo deploy sha256:abc123 --to server.example.com

# Kubernetes
velo deploy sha256:abc123 --to k8s://cluster/namespace

# CI/CD pipeline
echo "$RELEASE_HASH" | velo deploy --stdin --to production
```

**Benefits**:
| Traditional | LifeCode™ |
|:---|:---|
| Build different packages per platform | One hash, auto-adapt |
| Transfer large archives | Transfer hash, fetch delta |
| Manual dependency resolution | Auto-resolve alternatives |
| Complex deploy scripts | Single command |

---

## 6. CLI Interface (Draft)

```bash
# Pull by root hash
velo pull sha256:abc123

# Run by root hash
velo run sha256:abc123

# Publish (upload tree to registry)
velo publish --registry registry.example.com

# Inspect tree
velo tree sha256:abc123
# Output:
# abc123 (root)
# ├── def456 app/
# │   ├── mno345 main.py (1.2KB)
# │   └── pqr678 utils.py (0.8KB)
# ├── ghi789 deps/
# │   └── stu901 torch/ (500MB)
# └── jkl012 assets/
#     └── vwx234 model.safetensors (2.1GB)

# Garbage collection
velo gc --keep-days 30
```

---

## 7. Migration Path

| Version | Format | Compatibility |
|:---|:---|:---|
| **v1.0** | tar.zst (.lcpkg) | Current RFC-0034 |
| **v1.5** | tar.zst + manifest hash | Hybrid (hash in manifest) |
| **v2.0** | Full Hash Tree | Native content-addressable |

### 7.1 v1.0 → v2.0 Conversion

```bash
# Convert v1.0 bundle to v2.0 tree
velo bundle convert app.lcpkg --to-tree
# → Outputs root hash

# Run either format
velo run app.lcpkg           # v1.0
velo run sha256:abc123      # v2.0
```

---

## 8. Security Model & Threat Analysis

### 8.1 Threat Model

| Threat | Attack Vector | Mitigation |
|:---|:---|:---|
| **Hash Collision** | Craft malicious content with same hash | blake3 256-bit (2^128 collision resistance) |
| **Gene Injection** | Insert malicious blob into object store | Recursive hash verification from root |
| **Registry Compromise** | Attacker modifies registry | Signed root + transparency log |
| **Man-in-the-Middle** | Intercept and modify downloads | TLS + hash verification |
| **Replay Attack** | Serve old vulnerable version | Manifest versioning + revocation list |
| **Supply Chain** | Compromised dependency | Hash pinning + SBOM integration |

### 8.2 Hash Verification

```
Verification Pipeline:

1. Download object by hash
   download(hash) → content

2. Verify content
   computed = blake3(content)
   assert computed == hash

3. Recurse for trees
   for child in tree.entries:
       verify(child.hash)
```

### 8.3 Root Signing

```json
{
  "root": "abc123...",
  "algorithm": "ed25519",
  "signature": "base64:...",
  "signer": {
    "identity": "developer@example.com",
    "keyid": "fingerprint..."
  },
  "timestamp": "2026-01-19T12:00:00Z"
}
```

### 8.4 Transparency Log (Future)

```
Sigstore/Rekor Integration:
- Every publish recorded in immutable log
- Auditable history of all versions
- Revocation detection
```

---

## 9. Core Abstractions

### 9.1 Rust Traits

```rust
/// Hash digest (256-bit blake3)
pub struct Hash([u8; 32]);

/// Content-addressed object store
pub trait ObjectStore: Send + Sync {
    /// Retrieve object by hash
    fn get(&self, hash: &Hash) -> Result<Bytes>;
    
    /// Store object, returns computed hash
    fn put(&self, content: &[u8]) -> Result<Hash>;
    
    /// Check if object exists
    fn exists(&self, hash: &Hash) -> bool;
    
    /// List all objects (for GC)
    fn list(&self) -> Box<dyn Iterator<Item = Hash>>;
}

/// Object types in the tree
pub enum Object {
    Blob(Bytes),           // File content
    Tree(Vec<TreeEntry>),  // Directory
    Manifest(Manifest),    // Root with metadata
}

/// Tree entry (directory item)
pub struct TreeEntry {
    pub name: String,
    pub hash: Hash,
    pub obj_type: ObjectType,
    pub size: u64,
}

/// Organism composition strategy
pub trait Composer {
    /// Materialize tree to filesystem
    fn materialize(&self, root: &Hash, target: &Path) -> Result<()>;
    
    /// Lazy load with on-demand fetching
    fn lazy_load(&self, root: &Hash) -> Result<LazyTree>;
}
```

### 9.2 Python API

```python
from velo.organism import Organism, ObjectStore

# Load organism by root hash
org = Organism.from_hash("sha256:abc123")

# Inspect structure
print(org.name)        # "my-app"
print(org.version)     # "1.0.0"
print(org.tree())      # Display tree structure

# Composition strategies
org.materialize("./app")           # Full materialization
org.lazy_load()                    # On-demand loading
org.virtual_mount("/mnt/app")      # Virtual (FUSE-based)

# Build new organism
with ObjectStore() as store:
    org = Organism.build(
        name="my-app",
        version="1.0.0",
        source="./src",
        deps=["torch==2.1.0"]
    )
    print(org.root_hash)  # sha256:def456...
```

---

## 10. Chunking Strategy

### 10.1 Large File Handling

For files > 1MB, use content-defined chunking (FastCDC):

```
Large File (2GB model.safetensors):

┌──────────┬──────────┬──────────┬──────────┐
│ Chunk 1  │ Chunk 2  │ Chunk 3  │ Chunk 4  │ ...
│ hash:a1  │ hash:b2  │ hash:c3  │ hash:d4  │
└──────────┴──────────┴──────────┴──────────┘
     │           │           │           │
     └───────────┴─────┬─────┴───────────┘
                       │
              ┌────────▼────────┐
              │   Chunk List    │
              │   hash: xyz789  │
              └─────────────────┘
```

### 10.2 Chunking Parameters

| Parameter | Value | Rationale |
|:---|:---|:---|
| **Algorithm** | FastCDC | Content-aware boundaries |
| **Min chunk** | 64KB | Avoid tiny chunks |
| **Avg chunk** | 256KB | Balance dedup vs overhead |
| **Max chunk** | 1MB | Limit memory usage |

### 10.3 Deduplication Benefits

```
Scenario: Update model.safetensors (2GB → 2.1GB)

Without chunking:
  Download: 2.1GB (entire file)

With chunking:
  Changed chunks: 3 × 256KB = 768KB
  Download: 768KB (99.96% saved)
```

---

## 11. Filesystem Integration

### 11.1 Materialization Modes

| Mode | Mechanism | Performance | Copy-on-Write |
|:---|:---|:---|:---|
| **Hardlink** | `link()` | ✅ Instant | ❌ No |
| **Reflink** | `copy_file_range()` | ✅ Instant | ✅ Yes |
| **Copy** | `read()` + `write()` | ❌ Slow | ✅ Yes |

### 11.2 Filesystem Compatibility

| Filesystem | Hardlink | Reflink | Recommended |
|:---|:---|:---|:---|
| **btrfs** | ✅ | ✅ | Reflink |
| **xfs** | ✅ | ✅ | Reflink |
| **ext4** | ✅ | ❌ | Hardlink |
| **zfs** | ✅ | ✅ | Reflink |
| **APFS** (macOS) | ✅ | ✅ | Reflink |
| **NTFS** (Windows) | ✅ | ❌ | Hardlink |

### 11.3 Atomic Operations

```rust
// Concurrent-safe materialization
fn materialize_atomic(hash: &Hash, target: &Path) -> Result<()> {
    let tmp = target.with_extension(".velo-tmp");
    
    // Write to temp location
    write_content(&tmp, store.get(hash)?)?;
    
    // Atomic rename
    std::fs::rename(&tmp, target)?;
    
    Ok(())
}
```

---

## 12. Cloud Distribution

### 12.1 Registry Protocol

```
HTTP-based protocol (OCI-compatible):

GET  /v2/{name}/manifests/{reference}  → Manifest
GET  /v2/{name}/blobs/{hash}           → Blob content
HEAD /v2/{name}/blobs/{hash}           → Check existence
POST /v2/{name}/blobs/uploads/         → Initiate upload
PUT  /v2/{name}/blobs/uploads/{id}     → Complete upload
```

### 12.2 CDN Caching

| Object Type | Cache TTL | Cache-Control |
|:---|:---|:---|
| **Blob** | Immutable | `public, immutable, max-age=31536000` |
| **Manifest** | 1 hour | `public, max-age=3600` |
| **Named ref** | 5 min | `public, max-age=300` |

### 12.3 Container Integration

```yaml
# Kubernetes Volume (Future)
apiversion: v1
kind: Pod
spec:
  volumes:
    - name: app
      velo:
        hash: sha256:abc123
        materialize: lazy
```

---

## 13. Performance Targets

| Scenario | Target | Measurement |
|:---|:---|:---|
| **Cold manifest parse** | < 100ms | Time to parse root manifest |
| **Tree traversal (1M files)** | < 1s | O(n) with index |
| **Blob lookup** | < 1ms | O(1) hash table |
| **Concurrent downloads** | 10K QPS | Per registry node |
| **Local materialization** | 1GB/s | Limited by disk I/O |
| **Dedup ratio (ML apps)** | > 80% | Cross-version sharing |

---

## 14. Open Questions

| # | Question | Options | Recommendation |
|:---|:---|:---|:---|
| 1 | Hash algorithm | blake3 vs sha256 | blake3 (faster) |
| 2 | Object chunking | Fixed-size vs content-defined | FastCDC |
| 3 | Registry protocol | HTTP + JSON vs gRPC vs IPFS | HTTP (OCI-compat) |
| 4 | P2P distribution | BitTorrent-like sharing? | Future consideration |
| 5 | Garbage collection | Reference counting vs mark-sweep | Mark-sweep |

---

## 15. References

- [Git Internals](https://git-scm.com/book/en/v2/Git-Internals-Git-Objects)
- [IPFS Content Addressing](https://docs.ipfs.tech/concepts/content-addressing/)
- [Nix Store](https://nixos.org/manual/nix/stable/store/store-path.html)
- [OSTree](https://ostreedev.github.io/ostree/)
- [FastCDC](https://www.usenix.org/system/files/conference/atc16/atc16-paper-xia.pdf)
- [OCI Distribution Spec](https://github.com/opencontainers/distribution-spec)
- [RFC-0034: Velo Bundle v1.0](./0034-preload-bundle-distribution.md)

---

## 16. Appendix

### A. Glossary

| Term | Definition |
|:---|:---|
| **Organism** | A complete software application represented as a hash tree |
| **Cell** | A single file (blob) in the tree |
| **Organ** | A directory (subtree) containing cells |
| **Gene** | The hash identifier of any object |
| **Gene Pool** | The shared object store where all genes are cached |
| **Materialization** | The process of assembling an organism from genes |
| **Root Hash** | The unique identifier of an organism version |

### B. Object Types

| Type | Description | Example |
|:---|:---|:---|
| `blob` | File content | main.py |
| `tree` | Directory listing | app/, deps/ |
| `manifest` | Root with metadata | Application definition |
| `chunklist` | Large file chunks | model.safetensors |

### C. Hash Prefix Convention

```
sha256:abc123...    # Full hash (64 chars)
sha256:abc123       # Short hash (first 6 chars)
blake3:xyz789...    # Blake3 hash
@my-app:1.0.0       # Named reference (resolved to hash)
@my-app:latest      # Mutable tag
```

