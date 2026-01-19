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
| **Species** | Root Hash | **Global Consistency**: Root Hash = Species. The species identity is globally unique and immutable. |
| **Gene Pool** | Object Store | Shared storage for all gene fragments |
| **Reproduction** | Distribution | Transmit Root Hash = transmit blueprint |
| **Evolution** | Version Update | Mutation = content change = new Hash |

> **Global Consistency**:
> *"Root Hash = Species."*
> This setting naturally supports global consistency. Any divergence in environment or build results in a different Species.


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

### 2.5 Theoretical Foundation

> *"LifeCode™ turns software from a procedural artifact into a referentially transparent value."*

By treating software as a **Persistent Graph of Meaningful Atoms**, LifeCode™ achieves properties of a **Purely Functional Store**:

*   **Software = Value**: The entire organism is a single, immutable value (Root Hash), not a collection of files.
*   **Deployment = Pass-by-Value**: distribution is simply transmitting the value reference.
*   **Rollback = Pointer Swap**: Changing versions is an atomic pointer move, isomorphic to variable reassignment in functional programming.
*   **Execution = Evaluation**: Running an organism is evaluating the value in a runtime context.

This shifts system architecture from **Imperative State Mutation** (apt-get install, docker pull) to **OS-Level Lambda Calculus**.

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
    "entrypoint": "app:main",
    "build": {
      "toolchain": "velo@2.0",
      "source_hash": "sha256:git-commit-hash",
      "reproducible": true,
      "timestamp": "2026-01-20T12:00:00Z"
    },
    "sbom": {
      "format": "spdx-json",
      "hash": "sha256:sbom-hash..."
    }
  }
}
```

### 3.4 Deterministic Identity (Canonical Encoding)

> **Critical**: To ensure `Hash(A) == Hash(B)` across all platforms, we strictly define Canonical Encoding.

1.  **Sorted Keys**: All map keys (e.g., in Manifest) must be sorted lexicographically.
2.  **Deterministic Serialization**: Use a strict subset of JSON (or CBOR in v2.0) with no whitespace.
3.  **Normalized Paths**: All file paths inside trees are relative, forward-slash `/`, and normalized (no `./` or `../`).

---

## 4. Industry Comparison

| System | Similarity | Difference |
|:---|:---|:---|
| **Git** | Object store, SHA, trees | Git is for source, Velo for distribution |
| **IPFS** | Content-addressable, DAG | IPFS is p2p, Velo is client-server |
| **Nix** | `/nix/store/{hash}-{name}` | Nix is system-wide, Velo is app-focused |
| **Docker** | Layer dedup | Docker is containers, Velo is packages |

### 4.1 Paradigm Shift: OCI vs LifeCode™

| Feature | OCI / Container | LifeCode™ Organism |
|:---|:---|:---|
| **Form Factor** | Image (Static Tarball) | Organism (Living Tree) |
| **Startup** | Download Full Image → Start | Recieve Hash → Spark → Background Growth |
| **Composition** | OverlayFS Layers | Gene-level Sharing |
| **Cold Start** | Seconds (Pull + Extract) | Milliseconds (Manifest + Instant Genesis) |

---

## 5. Build Lifecycle (Creation)

> The process of assembling a living organism from source code.

### 5.1 Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    Build Lifecycle                          │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌───────────────────┐                                      │
│  │  Source Files     │                                      │
│  │  main.py, deps/   │                                      │
│  └─────────┬─────────┘                                      │
│            │                                                │
│            ▼                                                │
│  ┌───────────────────┐                                      │
│  │ Gene Synthesis™   │  Files → Genes (hash each file)     │
│  └─────────┬─────────┘                                      │
│            │                                                │
│            ▼                                                │
│  ┌───────────────────┐                                      │
│  │ Organ Assembly™   │  Genes → Trees (directory structure) │
│  └─────────┬─────────┘                                      │
│            │                                                │
│            ▼                                                │
│  ┌───────────────────┐                                      │
│  │ Organism Birth™   │  Trees → Root Hash (manifest)       │
│  └─────────┬─────────┘                                      │
│            │                                                │
│            ▼                                                │
│  ┌───────────────────┐                                      │
│  │ Gene Propagation™ │  Upload to GenePool™ (deduplicated) │
│  └─────────┬─────────┘                                      │
│            │                                                │
│            ▼                                                │
│       sha256:abc123  ─────────────────────►  GaD Deploy     │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 5.2 Gene Synthesis™

> *"From code to DNA"*

Transform source files into content-addressable genes.

```bash
# Input: Source files
main.py (1.2KB)
utils.py (0.8KB)
config.json (0.3KB)

# Process: Hash each file
blake3(main.py)   → abc123...
blake3(utils.py)  → def456...
blake3(config.json) → ghi789...

# Output: Genes (blobs)
~/.velo/objects/ab/c123...
~/.velo/objects/de/f456...
~/.velo/objects/gh/i789...
```

### 5.3 Organ Assembly™

> *"Genes form organs"*

Organize genes into tree structures (directories).

```bash
# Input: Genes + directory structure
app/
├── main.py (abc123)
└── utils.py (def456)
config.json (ghi789)

# Process: Create tree objects
tree(app/) = {
  entries: [
    { name: "main.py", hash: "abc123", type: "blob" },
    { name: "utils.py", hash: "def456", type: "blob" }
  ]
} → tree hash: jkl012...

# Output: Tree genes
~/.velo/objects/jk/l012...
```

### 5.4 Organism Birth™

> *"The organism is born"*

Generate the root manifest and final identity.

```bash
# Input: All trees + metadata
app/ (jkl012)
deps/ (mno345)
assets/ (pqr678)

# Process: Create manifest
manifest = {
  name: "my-app",
  version: "1.0.0",
  entrypoint: "app:main",
  organs: [
    { name: "app", hash: "jkl012" },
    { name: "deps", hash: "mno345" },
    { name: "assets", hash: "pqr678" }
  ]
}

# Output: Root Hash (organism identity)
blake3(manifest) → sha256:ROOT_HASH
```

### 5.5 Gene Propagation™

> *"Spread the DNA"*

Upload all genes to GenePool™, with global deduplication.

```bash
# Process: Upload to GenePool™
velo genepool push sha256:ROOT_HASH

# Deduplication check:
# ✓ abc123 - new, uploading
# ✓ def456 - new, uploading
# ⊘ mno345 - exists, skipping (torch already in pool)
# ✓ ROOT_HASH - new, uploading

# Result:
# Uploaded: 3 genes (2.1MB)
# Skipped: 1 gene (500MB) - deduplicated!
# Total time: 1.2s
```

---

## 6. Runtime Lifecycle (Deployment)

### 6.1 Key Features

#### 6.1.1 Incremental Updates

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

### 5.3 Gene Spark™ & Instant Genesis™

#### Gene Spark™ - The Ignition

> *"One spark ignites the organism."*

A dormant server receives a single hash - the **Gene Spark™** - and in that instant, life begins.

```
                        ┌─────────────────────────┐
                        │      Server (Dormant)   │
                        │   ░░░░░░░░░░░░░░░░░░░   │
                        │   ░░░  Waiting...  ░░░   │
                        └───────────┬─────────────┘
                                    │
                    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
                          ⚡ Gene Spark™ ⚡
                           sha256:abc123
                    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
                                    │
                                    ▼
                        ┌─────────────────────────┐
                        │      Server (ALIVE!)    │
                        │   🧬 Organism Active    │
                        │   ⚡ Instant Genesis™   │
                        └─────────────────────────┘
```

**Gene Spark™** = The moment of ignition (receiving the hash)
**Instant Genesis™** = The creation process that follows

#### Instant Genesis™ - The Creation

> *"Let there be app."*
>
> From a single hash, an organism springs to life in milliseconds.

**Tagline**: *"From hash to running in milliseconds"*

**The Process**:
```
┌─────────────────────────────────────────────────────────────┐
│                    Instant Genesis™                          │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Step 1: Receive Hash (64 bytes)                           │
│          sha256:abc123...                                   │
│                    ↓                                        │
│  Step 2: Fetch Manifest (2KB, ~10ms)                       │
│          { name, version, entrypoint, organs... }          │
│                    ↓                                        │
│  Step 3: Bootstrap Entrypoint (~50ms)                      │
│          Load only: main.py + critical deps                │
│                    ↓                                        │
│  Step 4: App Running! (< 100ms total)                      │
│                    ↓                                        │
│  Step 5: Lazy Load (on-demand, background)                 │
│          torch/, models/, assets/... as accessed           │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

**Comparison**:
| Metric | Traditional | Instant Genesis™ |
|:---|:---|:---|
| **First byte to running** | 30s+ (download all) | < 100ms |
| **Network transfer** | Entire package | Manifest only |
| **Disk write before start** | Full extraction | Zero |
| **Cold start** | Minutes | Milliseconds |

**Code Example**:
```python
from velo import Organism

# Instant Genesis™ - starts immediately
org = Organism.instant_genesis("sha256:abc123")
org.run()  # Running in < 100ms

# Background: lazy loading torch, models as needed
```

**CLI**:
```bash
# Instant Genesis™ mode (default)
velo run sha256:abc123

# Verbose: watch the genesis
velo run --verbose sha256:abc123
# [genesis] Fetching manifest... 12ms
# [genesis] Bootstrapping entrypoint... 45ms
# [genesis] App running! Total: 57ms
# [lazy] Loading torch... (background)
# [lazy] Loading model.safetensors... (background)
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

### 5.5 Gene as Deploy™ (GaD)

> *"Drop a gene, deploy an app"*
>
> A single gene (hash) transmission deploys an entire application.

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

# Kubernetes (via Velo Operator)
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

## 7. GenePool™ Distribution

> *"The universal gene pool"*
>
> GenePool™ is the distributed registry for LifeCode™ organisms - where all genes are stored, shared, and replicated.

### 6.1 Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      GenePool™ Registry                     │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
│  │   Genes     │  │   Genes     │  │   Genes     │         │
│  │  (blobs)    │  │  (trees)    │  │ (manifests) │         │
│  │             │  │             │  │             │         │
│  │ abc123...   │  │ def456...   │  │ ghi789...   │         │
│  │ jkl012...   │  │ mno345...   │  │ pqr678...   │         │
│  └─────────────┘  └─────────────┘  └─────────────┘         │
│                                                             │
│                   Content-Addressable Storage               │
└─────────────────────────────────────────────────────────────┘
          │                    │                    │
          ▼                    ▼                    ▼
    ┌──────────┐        ┌──────────┐        ┌──────────┐
    │ Dev      │        │ Server   │        │ Edge     │
    │ Machine  │        │ Cluster  │        │ Device   │
    └──────────┘        └──────────┘        └──────────┘
```

### 6.2 CLI Commands

```bash
# Login to GenePool™
velo genepool login

# Push organism to GenePool™
velo genepool push sha256:abc123

# Pull organism from GenePool™
velo genepool pull sha256:abc123

# Search for organisms
velo genepool search "torch"

# List published organisms
velo genepool list --mine
```

### 6.3 Federation

> Multiple GenePool™ instances can federate, sharing genes across organizations.

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  Company A  │◄───►│   Public    │◄───►│  Company B  │
│  GenePool™  │     │  GenePool™  │     │  GenePool™  │
└─────────────┘     └─────────────┘     └─────────────┘
       │                   │                   │
       │     Federated Gene Sharing            │
       └───────────────────┴───────────────────┘
```

### 6.4 Replication Strategy

| Mode | Description | Use Case |
|:---|:---|:---|
| **Pull-through** | Fetch on demand, cache locally | Edge deployment |
| **Mirror** | Full replication | Air-gapped environments |
| **Selective** | Replicate specific organisms | Regional deployment |

### 6.5 Privacy & Isolation (Council Advisory)

> **Warning**: Global deduplication in a public pool creates a "Privacy Oracle" side-channel (existence confirmation).

To mitigate this, GenePool™ implements **Tenant Isolation**:

*   **Public GenePool™**: Global deduplication. Public content only.
*   **Private GenePool™**: Scoped deduplication (per-org or per-tenant).
    *   *Convergent Encryption*: Optional. Encrypts genes before storage using a key derived from the content itself, allowing deduplication only among holders of the same content.

### 6.6 Process Model & Lifecycle Hooks

> **Process Model**:
> *   **Scaling**: Organisms fork from the Zygote.
> *   **Memory**: Multi-replica organisms share the same read-only memory pages (code/assets) via `mmap`, maximizing density.
> *   **Cache**: All replicas share the node-local GenePool cache.

**Lifecycle Hooks (`manifest.toml`)**:
```toml
[runtime.hooks]
pre_genesis = "check_gpu"      # Run before app start
post_genesis = "warm_model"    # Run background warmer
pre_shutdown = "flush_state"   # Graceful termination
```

---

## 8. CLI Interface (Draft)

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

## 17. Migration Path

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

## 10. Security Model & Threat Analysis

### 10.1 Threat Model

| Threat | Attack Vector | Mitigation |
|:---|:---|:---|
| **Hash Collision** | Craft malicious content with same hash | blake3 256-bit (2^128 collision resistance) |
| **Gene Injection** | Insert malicious blob into object store | Recursive hash verification from root |
| **Registry Compromise** | Attacker modifies registry | Signed root + transparency log |
| **Man-in-the-Middle** | Intercept and modify downloads | TLS + hash verification |
| **Replay Attack** | Serve old vulnerable version | Manifest versioning + revocation list |
| **Replay Attack** | Serve old vulnerable version | Manifest versioning + revocation list |
| **Supply Chain** | Compromised dependency | Hash pinning + SBOM integration |

> **Structural Security**: LifeCode™ naturally satisfies **SLSA Level 4** requirements.
> *   **Identity**: Hash = Identity.
> *   **Proof**: Tree = Proof. 
> *   **Authority**: Root = Authority.

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

### 10.4 Transparency Log (Immutable Audit)

> **Requirement**: GenePool™ must not be a black box.

1.  **Immutable Audit Log**: Every `push` event is legally recorded in a append-only log (e.g., Trillian/Rekor).
2.  **First-Seen Verification**: Clients can query "When was hash `abc123` first seen?".
    *   *Mitigation*: Prevents "Time-Travel Attacks" where an attacker tries to backdate a malicious package.
3.  **Organ-Level SBOM**: Every Organ carries its own SBOM, aggregated automatically at the Root Manifest.

### 8.5 Merkle Proofs & Partial Verification

> Allows "Partial Verification" instead of full root verification. Critical for Edge/IoT.

*   **Mechanism**: A client can request a specific file (Gene) plus a "Merkle Proof" (sibling hashes path to Root).
*   **Benefit**: Verify a single 1KB configuration file is part of the 10GB Organism without downloading the 10GB.

---

## 11. Core Abstractions

### 11.1 Rust Traits

```rust
/// Hash digest (256-bit blake3)
pub struct Hash([u8; 32]);

/// Content-addressed object store
pub trait ObjectStore: Send + Sync {
    /// Retrieve object by hash
    fn get(&self, hash: &Hash) -> Result<Bytes>;
    
    /// Store object, returns computed hash
    fn put(&self, content: &[u8]) -> Result<Hash>;
    
    /// Check if object exists (Async)
    async fn exists(&self, hash: &Hash) -> bool;
    
    /// List all objects (Async Stream for Scalability)
    fn list(&self) -> impl Stream<Item = Result<Hash>> + Send;
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

## 17. Chunking Strategy

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

## 17. Filesystem Integration

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

## 17. Cloud Distribution

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

## 17. Performance Targets

| Scenario | Target | Measurement |
|:---|:---|:---|
| **Cold manifest parse** | < 100ms | Time to parse root manifest |
| **Tree traversal (1M files)** | < 1s | O(n) with index |
| **Blob lookup** | < 1ms | O(1) hash table |
| **Concurrent downloads** | 10K QPS | Per registry node |
| **Local materialization** | 1GB/s | Limited by disk I/O |
| **Dedup ratio (ML apps)** | > 80% | Cross-version sharing |

---

## 17. Open Questions

| # | Question | Options | Recommendation |
|:---|:---|:---|:---|
| 1 | Hash algorithm | blake3 vs sha256 | blake3 (faster) |
| 2 | Object chunking | Fixed-size vs content-defined | FastCDC |
| 3 | Registry protocol | HTTP + JSON vs gRPC vs IPFS | HTTP (OCI-compat) |
| 4 | P2P distribution | BitTorrent-like sharing? | Future consideration |
| 5 | Garbage collection | Reference counting vs mark-sweep | Mark-sweep |

---

## 17. References

- [Git Internals](https://git-scm.com/book/en/v2/Git-Internals-Git-Objects)
- [IPFS Content Addressing](https://docs.ipfs.tech/concepts/content-addressing/)
- [Nix Store](https://nixos.org/manual/nix/stable/store/store-path.html)
- [OSTree](https://ostreedev.github.io/ostree/)
- [FastCDC](https://www.usenix.org/system/files/conference/atc16/atc16-paper-xia.pdf)
- [OCI Distribution Spec](https://github.com/opencontainers/distribution-spec)
- [RFC-0034: Velo Bundle v1.0](./0034-preload-bundle-distribution.md)

---

## 17. Appendix

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

### D. Rollback Strategy

> **P0: Critical for production safety**

```bash
# View deployment history
velo history my-app
# v1.0.0  sha256:abc123  2026-01-19 10:00
# v1.0.1  sha256:def456  2026-01-19 12:00  ← current
# v1.0.2  sha256:ghi789  2026-01-19 14:00  ← failed

# Instant rollback (gene already in pool)
velo rollback my-app --to v1.0.1
# [rollback] Switching to sha256:def456
# [genesis] Restarting organism...
# [success] Rolled back in 57ms
```

**Rollback Modes**:
| Mode | Description | Use Case |
|:---|:---|:---|
| **Instant** | Switch to cached gene | Normal rollback |
| **Canary** | Gradual traffic shift | Safe rollback |
| **Force** | Immediate, skip health | Emergency |

### E. Observability

> **P1: Essential for production operations**

**Metrics**:
```
# Prometheus format
lifecode_genesis_duration_ms{app="my-app"} 57
lifecode_gene_cache_hit_ratio{} 0.95
lifecode_lazy_load_count{module="torch"} 1
lifecode_organism_memory_bytes{app="my-app"} 1073741824
```

**Structured Logs**:
```json
{
  "level": "info",
  "event": "genesis_complete",
  "app": "my-app",
  "root_hash": "sha256:abc123",
  "duration_ms": 57,
  "genes_fetched": 3,
  "genes_cached": 47
}
```

**Tracing**:
```
velo run --trace sha256:abc123

Trace ID: abc-123-xyz
├── [10ms] fetch_manifest
├── [5ms] parse_organs
├── [30ms] bootstrap_entrypoint
│   ├── [15ms] load_main
│   └── [15ms] load_deps
└── [12ms] start_app
Total: 57ms
```

### F. Error Types

> **P1: Clear error handling**

```rust
#[derive(Debug, thiserror::Error)]
pub enum LifeCodeError {
    // Network errors
    #[error("Failed to fetch gene {hash}: {source}")]
    FetchError { hash: Hash, source: reqwest::Error },
    
    #[error("Registry unreachable: {url}")]
    RegistryUnavailable { url: String },
    
    // Integrity errors
    #[error("Hash mismatch: expected {expected}, got {actual}")]
    HashMismatch { expected: Hash, actual: Hash },
    
    #[error("Invalid signature for {hash}")]
    InvalidSignature { hash: Hash },
    
    // Runtime errors
    #[error("Entrypoint not found: {path}")]
    EntrypointNotFound { path: String },
    
    #[error("Dependency conflict: {a} requires {dep_a}, {b} requires {dep_b}")]
    DependencyConflict { a: String, dep_a: String, b: String, dep_b: String },
    
    // Resource errors
    #[error("Insufficient disk space: need {need}, have {have}")]
    InsufficientDisk { need: u64, have: u64 },
}
```

### G. Configuration (lifecode.toml)

> **P2: Project configuration**

```toml
[organism]
name = "my-app"
version = "1.0.0"
entrypoint = "app:main"

[organism.metadata]
author = "0xMaster"
license = "MIT"
description = "A living application"

[build]
hash_algorithm = "blake3"
chunk_threshold = "1MB"
include = ["src/", "assets/"]
exclude = ["*.pyc", "__pycache__/"]

[dependencies]
torch = { version = "2.1.0", alternatives = ["torch-cpu", "torch-mps"] }
numpy = "1.26.0"

[genepool]
registry = "genepool.io"
cache_dir = "~/.velo/objects"

[runtime]
lazy_load = true
prefetch = ["torch"]  # Prefetch in background
memory_limit = "8GB"
```

### H. Offline Mode

> **P2: Air-gapped deployments**

```bash
# Export organism with all genes
velo export sha256:abc123 --output organism.tar
# Exports: manifest + all genes (fully self-contained)

# Transfer to air-gapped environment
scp organism.tar airgap:/deploy/

# Import and run (no network required)
velo import organism.tar
velo run sha256:abc123  # Works offline
```

**Offline Bundle Structure**:
```
organism.tar
├── manifest.json      # Root manifest
├── objects/           # All genes
│   ├── ab/c123...
│   ├── de/f456...
│   └── ...
└── metadata.json      # Export info
```

### I. Environment Management

> **P2: Multi-environment support**

```bash
# Tag for different environments
velo tag sha256:abc123 @my-app:dev
velo tag sha256:def456 @my-app:staging
velo tag sha256:ghi789 @my-app:prod

# Promote between environments
velo promote @my-app:staging --to prod
# → @my-app:prod now points to sha256:def456

# Environment-specific config
velo run @my-app:prod --env production
```

**Environment Matrix**:
| Environment | Tag | Config | GenePool |
|:---|:---|:---|:---|
| Development | `@app:dev` | dev.toml | Local |
| Staging | `@app:staging` | staging.toml | Private |
| Production | `@app:prod` | prod.toml | Private + Mirror |

### J. Key Management

> **P1: Secure key handling**

```bash
# Generate signing key
velo key generate --output ~/.velo/keys/signing.key

# Sign organism
velo sign sha256:abc123 --key ~/.velo/keys/signing.key

# Verify signature
velo verify sha256:abc123 --keyring ~/.velo/keys/trusted/

# Key rotation
velo key rotate --old old.key --new new.key --resign
```

**Trust Model**:
```
Root of Trust (Organization Key)
        │
        ├── Team A Key (signs team A apps)
        │   ├── Dev 1 Key
        │   └── Dev 2 Key
        │
        └── Team B Key (signs team B apps)
            └── Dev 3 Key
```

### K. Benchmarking Strategy

> **P3: Performance validation**

```bash
# Run standard benchmark suite
velo benchmark sha256:abc123

# Results:
# ┌────────────────────────┬──────────┬──────────┐
# │ Metric                 │ Measured │ Target   │
# ├────────────────────────┼──────────┼──────────┤
# │ Genesis time           │ 57ms     │ < 100ms  │
# │ Manifest parse         │ 8ms      │ < 50ms   │
# │ Gene cache hit ratio   │ 95%      │ > 90%    │
# │ Lazy load (torch)      │ 1.2s     │ < 2s     │
# │ Memory footprint       │ 128MB    │ < 256MB  │
# └────────────────────────┴──────────┴──────────┘
# ✓ All targets met
```

### L. System Integration

> **P3: OS-level integration**

**Systemd Service**:
```ini
[Unit]
Description=LifeCode Organism: my-app
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/velo run @my-app:prod
ExecStop=/usr/bin/velo stop @my-app:prod
Restart=on-failure
RestartSec=5s

Environment=VELO_GENEPOOL=genepool.io
Environment=VELO_LOG_LEVEL=info

[Install]
WantedBy=multi-user.target
```

**Signal Handling**:
| Signal | Action |
|:---|:---|
| SIGTERM | Graceful shutdown (30s timeout) |
| SIGINT | Graceful shutdown (10s timeout) |
| SIGHUP | Reload configuration |
| SIGUSR1 | Dump diagnostics |

**Health Check**:
```bash
# Liveness probe
velo health @my-app:prod --liveness
# Exit 0 = alive, Exit 1 = dead

# Readiness probe
velo health @my-app:prod --readiness
# Exit 0 = ready, Exit 1 = not ready
```

---

## 12. Future Architecture (Orbit)

### 12.1 P2P Data Plane

> LifeCode™ becomes "The BitTorrent + git of Software".

*   **GenePool™ (Control Plane)**: Centralized registry for Root Hashes and Metadata (DNS-like).
*   **P2P (Data Plane)**: Nodes exchange Genes (Blobs) directly.
    *   *Scenario*: A cluster of 1000 nodes needs to upgrade. Instead of 1000 requests to GenePool, they peer-to-peer share the Genes.

### 12.2 Kubernetes Native (CRD)

> **Vision**: LifeCode™ as "Cloud Native v2".

```yaml
apiVersion: lifecode.io/v1
kind: Organism
metadata:
  name: my-ai-service
spec:
  species: "sha256:abc123..."
  mode: lazy            # Instant Genesis + Background Load
  replicas: 3           # 3 Organisms
  genePool:
    policy: AlwaysPull  # Vs IfNotPresent
```

---

## 13. Conclusion: The Three Leaps

> LifeCode™ is not just a package manager, a faster container, or a smarter registry.
> **It is a redefinition of software existence: from "File System Object" to "Composable Organism".**

We have achieved three fundamental paradigm leaps:

1.  **Storage**: From **Archive** (Zip/Tar) → **Merkle Graph** (Meaningful Atoms)
2.  **Distribution**: From **Transmission** (Copy) → **Reproduction** (Biological Propagation)
3.  **Runtime**: From **Cold Start** (Boot) → **Genesis** (Instant Life)

**LifeCode™ transforms software from a procedural artifact into a living, evolving value.**
