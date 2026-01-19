# RFC-0036: LifeCode Object Model Specification

> **Status**: Standard Track
> **Category**: Engineering Specification
> **Phase**: Implementation (v2.0)

## 1. Abstract

This document specifies the **LifeCode Object Model**, a content-addressable data structure for representing software applications as Merkle Directed Acyclic Graphs (DAGs). It defines the canonical encoding, hashing algorithms, and storage interfaces required to implement a LifeCode-compliant Runtime or Registry.

### 1.1 Terminology Mapping (The Ontology Bridge)
This document uses biological metaphors to describe the system. For implementing engineering specifications, the following mapping applies:

| Metaphor | Technical Term | Definition |
| :--- | :--- | :--- |
| **Organism** | `RootManifestObject` | The root JSON metadata object defining the application graph. |
| **Gene** | `ContentAddressedChunk` | An immutable blob or tree node addressed by its BLAKE3 hash. |
| **Species** | `RootHash` | The unique cryptographic identity of a specific organism version. |
| **GenePool** | `ObjectStore` | A content-addressable storage layer (CAS) for deduplicated chunks. |
| **Death** | `GarbageCollection` | The reclamation of storage when chunks are no longer reachable. |
| **Genesis** | `RuntimeInstantiation` | The process of materializing a Root Hash into a running process. |

## 2. Core Primitives

### 2.1 Hashing Algorithm
*   **Algorithm**: `BLAKE3` (256-bit).
*   **Encoding**: Lowercase Hexadecimal (e.g., `sha256:abc...`).
*   **Constraint**: All object referneces MUST use this hash.

### 2.2 Object Types

The system consists of three fundamental object types.

#### 2.2.1 Blob (Cell)
A raw sequence of bytes.
*   **Identity**: `blake3(content)`

#### 2.2.2 Tree (Organ)
A directory listing mapping names to hashes.
*   **Format**: Canonical JSON.
*   **Identity**: `blake3(canonical_json(entries))`

```json
{
  "type": "tree",
  "entries": [
    { "name": "main.py", "mode": 0o644, "hash": "sha256:...", "size": 1024 },
    { "name": "lib/", "mode": 0o040000, "hash": "sha256:..." }
  ]
}
```

#### 2.2.3 Manifest (Organism)
The root metadata object defining an application.
*   **Format**: Canonical JSON.
*   **Identity**: `blake3(canonical_json(manifest))`

```json
{
  "type": "organism",
  "meta": {
    "name": "my-app",
    "version": "1.0.0",
    "entrypoint": ["python", "main.py"]
  },
  "rootfs": "sha256:tree_hash...",
  "hooks": {
    "pre_genesis": ["check_gpu"],
    "post_genesis": ["warm_cache"]
  }
}
```

## 3. Canonical Encoding

To ensure **Deterministic Identity** (`Hash(A) == Hash(B)` across all platforms), strict encoding rules MUST be followed:

1.  **Serialization**: Strict subset of JSON (RFC 8259).
    *   No whitespace (minified).
    *   UTF-8 encoding.
2.  **Key Sorting**: Object keys MUST be sorted lexicographically.
3.  **Path Normalization**:
    *   No relative paths (`./`, `../`).
    *   Forward slashes only (`/`).
    *   No trailing slashes for directories.

## 4. Storage Interface (Rust Trait)

Implementations MUST adhere to the following `Async` interface:

```rust
#[async_trait]
pub trait ObjectStore: Send + Sync {
    /// Retrieve object by hash
    async fn get(&self, hash: &Hash) -> Result<Bytes>;
    
    /// Store object, returns computed hash
    async fn put(&self, content: &[u8]) -> Result<Hash>;
    
    /// Check existence (Head request)
    async fn exists(&self, hash: &Hash) -> bool;
    
    /// Enumerate objects (Stream)
    fn list(&self) -> impl Stream<Item = Result<Hash>> + Send;
}
```

## 5. Security & Verification

### 5.1 Supply Chain
*   **Signature**: Root Manifests MUST be signed using `Ed25519`.
*   **SBOM**: Every `Tree` object SHOULD contain a `.sbom.spdx.json` entry.

### 5.2 Privacy (Tenant Isolation)
*   **Public GenePool**: Global deduplication allowed.
*   **Private GenePool**: MUST use **Scoped Deduplication** (per-tenant namespaces) or **Convergent Encryption** to prevent Privacy Oracle attacks via hash existence checks.

## 6. Runtime Contract
*   **Gene Spark**: The Runtime MUST accept a naked Root Hash to initiate genesis.
*   **Lifecycle**:
    1.  **Resolution**: Fetch Manifest.
    2.  **Genesis**: Materialize RootFS (Lazy/Mmap).
    3.  **Hooks**: Execute `pre_genesis`.
    4.  **Entrypoint**: Fork process.
    5.  **Shutdown**: Execute `pre_shutdown`.

### 6.5 Entropy: Object Lifecycle & Death
To convert "Death" from a metaphor to an engineering constraint, we define the technical criteria for **Extinction**.

An Object (Hash) is considered **Extinct** and eligible for Garbage Collection (GC) if and only if:
1.  **Unreachable**: It is not referenced by any known `RootManifest` in the active registry.
2.  **Unpinned**: It is not explicitly pinned by an archival policy (e.g., "Keep all versions of `my-app`").
3.  **Cold**: It has not been accessed (read) within the configured `half_life` window.

*Implementation Note*: A `GenePool` MUST implement a Mark-and-Sweep or Reference Counting mechanism to enforce Entropy. A storage system without GC is not a valid LifeCode system.

## 7. Kubernetes Integration
Kubernetes integration MUST be implemented via a Custom Resource Definition (CRD):
*   **Group**: `lifecode.io`
*   **Version**: `v1`
*   **Kind**: `Organism`
