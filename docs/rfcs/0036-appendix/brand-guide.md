# LifeCode™ Brand Guide

> **Author**: 0xMaster
> **Date**: 2026-01-20
> **Status**: Official

---

## Strategic Positioning (Keynotes & Headers)

Use these contrasts for high-impact visual headers (Posters, Website, Tweets).

> *"Containers ship software. LifeCode grows it."*
>
> *"Docker packages code. LifeCode gives it life."*
>
> *"The container era packaged software. The LifeCode era lets it live."*

---

## Brand Family

### Runtime Lifecycle (Deployment)

| Brand | Type | Tagline |
|:---|:---|:---|
| **Gene Spark™** | Ignition Event | *"One spark ignites the organism"* |
| **Instant Genesis™** | Bootstrap Process | *"Let there be app"* |
| **Gene as Deploy™ (GaD)** | Deployment Model | *"Drop a gene, deploy an app"* |

### Build Lifecycle (Creation)

| Brand | Type | Tagline |
|:---|:---|:---|
| **Gene Synthesis™** | File → Hash | *"From code to DNA"* |
| **Organ Assembly™** | Hash → Tree | *"Genes form organs"* |
| **Organism Birth™** | Tree → Root | *"The organism is born"* |
| **Gene Propagation™** | Root → GenePool™ | *"Spread the DNA"* |

### Infrastructure

| Brand | Type | Tagline |
|:---|:---|:---|
| **LifeCode™** | Core Model | *"Software That Lives"* |
| **GenePool™** | Distribution Registry | *"The universal gene pool"* |
| **.lcpkg** | File Format | LifeCode Package |

---

## The Biological Metaphor

| Biology Concept | LifeCode™ Equivalent | Description |
|:---|:---|:---|
| **Cell** | File (blob) | Fundamental unit, indivisible |
| **Gene (DNA)** | Hash | Unique identifier, defines characteristics |
| **Organ** | Module (tree) | Organic combination of cells |
| **Organism** | Application (root) | Complete system of all organs |
| **Species** | Root Hash | Unique identity of the organism |
| **Gene Pool** | Object Store | Shared storage for all gene fragments |
| **Reproduction** | Distribution | Transmit Root Hash = transmit blueprint |
| **Evolution** | Version Update | Mutation = content change = new Hash |

---

## Core Concepts

### LifeCode™ - The Philosophy

> **Software as a Living Organism**
>
> An organic whole composed of fundamental units (cells), genetic fragments (hashes), 
> and their relationships.

**Core Questions**:
1. How to describe a software organism? → **Representation**
2. How to reassemble a software organism? → **Composition**

---

### Gene Spark™ - The Ignition

> *"One spark ignites the organism."*
>
> A dormant server receives a single hash - the Gene Spark - 
> and in that instant, life begins. The organism awakens, 
> processes ignite, and the application springs into existence.
>
> No packages to install. No dependencies to resolve. No waiting.
>
> **Just a spark. And life.**

---

### Instant Genesis™ - The Creation

> *"Let there be app."*
>
> From a single hash, an organism springs to life in milliseconds.

| Metric | Traditional | Instant Genesis™ |
|:---|:---|:---|
| First byte to running | 30s+ | < 100ms |
| Network transfer | Entire package | Manifest only |
| Disk write before start | Full extraction | Zero |
| Cold start | Minutes | Milliseconds |

---

### Gene as Deploy™ (GaD) - The Deployment

> *"Drop a gene, deploy an app."*
>
> A single gene (hash) transmission deploys an entire application.

**Flow**:
```
Developer  ──── sha256:abc123 ────►  Server
                                        │
                                   Instant Genesis™
                                        │
                                        ▼
                                   App Running!
```

---

### GenePool™ - The Registry

> *"The universal gene pool"*
>
> The distributed registry where all genes are stored, shared, and replicated.

**Features**:
- Content-addressable storage
- Global deduplication
- Federation across organizations
- Pull-through caching for edge

---

## File Format

| Format | Extension | Purpose |
|:---|:---|:---|
| **Runtime** | `.lcpkg` | Uncompressed, mmap-friendly |
| **Distribution** | `.lcpkg.zst` | Compressed for transfer |

---

## Visual Identity

### ASCII Art - Gene Spark™
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
      ⚡ Gene Spark™ ⚡
       sha256:abc123
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### ASCII Art - Organism Structure
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
    └──────┬──────┘          └──────┬──────┘          └──────┬──────┘
           │                        │                        │
    ┌──────▼──────┐          ┌──────▼──────┐          ┌──────▼──────┐
    │Cell: main.py│          │Cell: torch/ │          │Cell: model  │
    └─────────────┘          └─────────────┘          └─────────────┘
```

---

## Trademark Notices

All brand names marked with ™ are trademarks of the LifeCode™ project:

**Runtime Lifecycle**:
- Gene Spark™
- Instant Genesis™
- Gene as Deploy™

**Build Lifecycle**:
- Gene Synthesis™
- Organ Assembly™
- Organism Birth™
- Gene Propagation™

**Infrastructure**:
- LifeCode™
- GenePool™

---

## References

- [RFC-0036: LifeCode™ Model](./0036-lifecode-model.md)
- [RFC-0034: Velo Bundle](./0034-preload-bundle-distribution.md)
