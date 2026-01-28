# Product Vision: Velo Rift

> **Slogan**: "Rift through the I/O Latency."
> **Architecture**: Built on the [Trinity Architecture](../architecture/trinity_architecture.md).

---

## 1. The Concept: Zero-Distance I/O

We are building a tool that lets you **tear a hole in the network**.

When you run `npm install` or load an AI dataset, you are normally doing "Heavy I/O":
1.  Download compressed tarball.
2.  Decompress to disk (CPU heavy).
3.  Write 100,000 files to NVMe (Metadata heavy).
4.  Read back from NVMe to RAM (Kernel heavy).

**Velo Rift** skips steps 2, 3, and 4.
It opens a "Rift" — a memory tunnel that maps the remote dataset directly into your process's address space.
It feels like downloading a 100GB dataset takes **seconds**—because you aren't actually downloading it. You are projecting it.

---

## 2. Technical Form Factor: `rift` (The CLI)

We expose this capability via a standalone binary tool (`rift`).

### 2.1 Mode A: Explicit Acceleration (`rift open`)

Tear open a rift to any remote dataset.

```bash
# Old Way: 
$ wget dataset.tar.gz && tar -xvf dataset.tar.gz # Waits 10 minutes

# Rift Way:
$ rift open s3://my-bucket/dataset ./local_mount
> Opening Spatial Rift... Done (0.5s).
> ./local_mount is now consistent. 
> Data is streamed on-demand via the Rift directly to CPU L3 Cache.
```

### 2.2 Mode B: Just-in-Time Projection (`rift exec`)

Intercept filesystem operations to project dependencies on demand.

```bash
# Traditional
$ npm install  # Writes 500MB to disk, high I/O wait time.

# Rift Powered
$ rift exec -- npm install
> Intercepting I/O...
> Materializing Rift Projection...
> Done. (Significant reduction in I/O wait).
```

### 2.3 Zero-Friction Integration (The "Magic Alias")

To eliminate muscle-memory friction, `rift` supports transparent shell hooks.
*   **The Hook**: `rift hook --shell zsh`. Use standard commands (`npm`, `cargo`) and they are transparently accelerated.
*   **The Experience**: Users don't learn a new tool. They just notice their existing tools became instant.
*   **The Psychology**: Zero friction means zero cognitive load. It leverages **Muscle Memory** to drive adoption.

---

## 3. Key Use Cases

### 3.1 CI/CD Shared Cache
*   **Scenario**: Multiple CI Runners in a cluster downloading similar dependencies.
*   **Optimization**: 
    1.  **Runner 1**: Downloads & Ingests to a Shared CAS.
    2.  **Runner 2-N**: Mounts the CAS Hash instantly via Rift.
*   **The Viral Loop (Share the Speed)**:
    *   At the end of every CI run, `rift` prints a high-contrast summary:
    ```text
    🚀 Rift Summary:
    ---------------------------------------------
    Original Est. Time:   5m 42s
    Rift Time:            11s
    You just Rifted 5m 31s of your life.
    ---------------------------------------------
    Share: https://velo.dev/rift #RiftChallenge
    ```

### 3.2 High-Performance Dataloaders
*   **Scenario**: Training models on datasets with millions of small files.
*   **Optimization**:
    *   Ingest dataset into a single VeloVFS CAS blob.
    *   Mount using `FUSE_PASSTHROUGH` or DAX.
    *   **Result**: Random access patterns achieve near-sequential read performance.

---

## 4. Visual Identity (The Glitch)

*   **Logo**: A teared circle or fracture, with **Purple/Blue Neon** glow.
*   **Aesthetic**: **Glitch Art / Sci-Fi**. 
*   **Metaphor**: "Tearing Space". It shouldn't look like a "File Manager". It should look like a "Portal Gun".
*   **Landing Page**: Hero section features a dynamic rift opening animation, projecting data as light onto the user's screen.
*   **Optimization**:
    *   Ingest dataset into a single VeloVFS CAS blob.
    *   Mount using `FUSE_PASSTHROUGH` or DAX.
    *   **Result**: Random access patterns achieve near-sequential read performance.

---

## 4. Operational Modes

| Mode | Backend | Use Case |
|:---|:---|:---|
| **Local Accelerate** | Local NVMe (`/var/cas`) | **Latency Focus**: Developer workstations, Gaming assets |
| **Cluster Shared** | Network CAS + Local Cache | **Throughput Focus**: CI Runners (P2P), K8s Pods. Seamlessly switches between Local hot-path and Cluster cold-storage. |
| **Ephemeral memory** | RAM (`/dev/shm`) | **Speed Focus**: Temporary builds, High-speed test fixtures |

> **Engineering Note (The Globbing Trap)**: 
> Tools like Webpack/ESLint often scan the entire directory tree (Globbing) at startup.
> Rift must implement **Metadata Prefetching** (faking the dentry structure in RAM) to prevent these scans from triggering a "JIT Storm" of network requests.

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
