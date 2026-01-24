# Product Vision: Universal VeloVFS (Project Gravity)

> **Goal**: Generalize the VeloVFS technology into a standalone I/O accelerator for read-heavy workloads (NPM, Cargo, AI Datasets), independent of the full Velo platform.

---

## 1. The Engineering Problem: "The File Fatigue"

Modern development is plagued by "Many-Small-Files" bottlenecks:
*   **NPM/Node**: `node_modules` often contains 100k+ small files, causing slow deletions and high I/O latency.
*   **AI Training**: ImageNet datasets consist of millions of JPEGs. Loading them puts immense pressure on Metadata Servers.
*   **CI/CD**: Pipelines repeatedly re-download and extract identical tarballs, wasting bandwidth and time.

**Solution**: VeloVFS transforms these file operations into efficient **Memory Mappings**, bypassing traditional I/O overhead.

---

## 2. Technical Form Factor: `velo-cli`

We expose VeloVFS via a standalone binary tool (`velo`), decoupling the filesystem technology from the orchestration layer.

### 2.1 Mode A: Explicit Acceleration (`velo accelerate`)

Accelerate an existing directory on a workstation or server.

```bash
# Before: High latency, significant disk usage
$ ls -R ./big_dataset

# Action: Ingest & Accelerate
$ velo accelerate ./big_dataset --in-place
> Ingesting 1,000,000 files... Done (3s)
> Deduplication Ratio: 4.2x
> Mounting VeloVFS at ./big_dataset... OK.

# After: ./big_dataset is now a VeloVFS Mountpoint
# Reads are served via Memory/DAX. 
# Metadata operations are O(1).
```

### 2.2 Mode B: Just-in-Time Projection (`velo run`)

Intercept filesystem operations to project dependencies on demand.

```bash
# Traditional
$ npm install  # Writes 500MB to disk, high I/O wait time.

# Velo-Powered
$ velo exec -- npm install
> Intercepting I/O writes...
> Redirecting to CAS Store...
> Materializing node_modules as VeloVFS Projection...
> Done. (Significant reduction in I/O wait).
```

---

## 3. Key Use Cases

### 3.1 CI/CD Shared Cache
*   **Scenario**: Multiple CI Runners in a cluster downloading similar dependencies.
*   **Optimization**: 
    1.  **Runner 1**: Downloads & Ingests to a Shared CAS (S3/Redis/NFS).
    2.  **Runner 2-N**: Mounts the CAS Hash instantly.
    3.  **Result**: 
        *   **Bandwidth**: Minimal redundant downloads.
        *   **Startup**: Instant environment provisioning.
        *   **Storage**: Physical deduplication across the cluster.

### 3.2 High-Performance Dataloaders
*   **Scenario**: Training models on datasets with millions of small files.
*   **Optimization**:
    *   Ingest dataset into a single VeloVFS CAS blob.
    *   Mount using `FUSE_PASSTHROUGH` or DAX.
    *   **Result**: Random access patterns achieve near-sequential read performance.

---

## 4. Operational Modes

| Mode | Backend | Use Case |
|:---|:---|:---|
| **Local Accelerate** | Local NVMe (`/var/cas`) | Developer workstations, Gaming assets |
| **Cluster Shared** | Network CAS (S3/MinIO) | CI Runners, K8s Pods, Distributed Training |
| **Ephemeral memory** | RAM (`/dev/shm`) | Temporary builds, High-speed test fixtures |

---

## 5. Ecosystem Integration

To ensure seamless adoption, we provide adapters for common tools:

*   **`velo-npm`**: Integrates with npm/pnpm to utilize CAS for package storage.
*   **`velo-uv`**: Collaborates with modern python tools to add **Runtime Memory Deduplication** to their fast resolution capabilities.
*   **`velo-pytorch`**: Implements a `torch.utils.data.Dataset` that reads directly from Velo CAS blobs, bypassing standard VFS overhead.

---

## 6. Adoption Strategy: Bottom-Up Utility

The strategy focuses on providing immediate, standalone value to engineers:
1.  **Solve a Specific Pain Point**: Fix the "slow `node_modules`" or "slow dataloading" problem first.
2.  **Zero-Friction Adoption**: The CLI tool requires no daemon or complex infrastructure setup.
3.  **Pathway to Platform**: Teams benefiting from the I/O acceleration can naturally graduate to the full Velo Compute architecture for wider orchestration needs.
