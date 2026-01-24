# Project Gravity: Download RAM. Literally.

> **The Slogan**: "Why download files when you can download memory?"

---

## 1. The Concept: Zero-Gravity I/O

We are building a tool that lets you **download RAM**.

When you run `npm install` or load an AI dataset, you are normally doing "Heavy I/O":
1.  Download compressed tarball.
2.  Decompress to disk (CPU heavy).
3.  Write 100,000 files to NVMe (Metadata heavy).
4.  Read back from NVMe to RAM (Kernel heavy).

**Gravity** skips steps 2, 3, and 4.
It maps the remote dataset directly into your process's memory space.
It feels like downloading a 100GB dataset takes **seconds**—because you aren't actually downloading it. You are just "linking" it.

---

## 2. Technical Form Factor: `velocity` (The CLI)

We expose this capability via a standalone binary tool (`velocity`).

### 2.1 Mode A: Explicit Acceleration (`velocity map`)

Turn any remote dataset into a local memory map.

```bash
# Old Way: 
$ wget dataset.tar.gz && tar -xvf dataset.tar.gz # Waits 10 minutes

# Gravity Way:
$ velocity map s3://my-bucket/dataset ./local_mount
> Establishing Memory Link... Done (0.5s).
> ./local_mount is now accessible. 
> Data is streamed on-demand from the network directly to CPU L3 Cache.
```
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

### 2.3 Zero-Friction Integration (The "Magic Alias")

To eliminate muscle-memory friction, `velocity` supports transparent shell hooks.
*   **The Hook**: `velocity hook --shell zsh`. Use standard commands (`npm`, `cargo`) and they are transparently accelerated.
*   **The Experience**: Users don't learn a new tool. They just notice their existing tools became instant.

---

## 3. Key Use Cases

### 3.1 CI/CD Shared Cache
*   **Scenario**: Multiple CI Runners in a cluster downloading similar dependencies.
*   **Optimization**: 
    1.  **Runner 1**: Downloads & Ingests to a Shared CAS (S3/Redis/NFS).
    2.  **Runner 2-N**: Mounts the CAS Hash instantly.
*   **The Billboard Effect (Viral Loop)**:
    *   At the end of every CI run, `velocity` prints a high-contrast summary:
    ```text
    🚀 Velocity Summary:
    ---------------------------------------------
    Original Est. Time:   4m 30s
    Velocity Time:        12s
    You saved:            4m 18s (☕ time!)
    ---------------------------------------------
    Get Velocity: https://velo.dev/cli
    ```
    *   **Goal**: Convert every engineer debugging a build log into a user.

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
