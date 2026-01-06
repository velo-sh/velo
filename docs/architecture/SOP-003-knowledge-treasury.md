# SOP-003: The Knowledge Treasury (Architecture Guild Charter)

> **Status**: **TITANIUM (Active)**
> **Authority**: The Grand Council
> **Version**: 1.0.0

## 1. The Mandate

**"Code is Ephemeral; Knowledge is Eternal."**

The **Architecture Guild** is the custodian of the **Velo Knowledge Treasury**. This SOP defines the structure, maintenance, and enforcement of the project's intellectual assets.

## 2. The Map of the Empire (Tiered Index)

All assets MUST be categorized into one of the following Tiers:

### 🏛️ Tier 1: Strategic (The "Why")
| Asset | Description | Guardian |
|:---|:---|:---|
| [`product_vision.md`](../strategy/product_vision.md) | The 5-Year Horizon & "Wooden Bucket" Theory | CTO |
| [`risk_register.md`](../governance/risk_register.md) | Existential & Technical Risk Dashboard | Risk Council |
| [`roadmap/2026-H1.md`](../roadmap/2026-H1.md) | Execution Plan | Senior PM |

### ⚙️ Tier 2: Domain Engineering (The "How")
| Asset | Description | Guardian |
|:---|:---|:---|
| [`rust_safety_standard.md`](../engineering/rust_safety_standard.md) | `unsafe` Policy & RAII Rules | Rust Core |
| [`python_integration_standard.md`](../engineering/python_integration_standard.md) | ABI, GIL, & Signal Protocols | Python Core |
| [`master_security_standard.md`](../../knowledge/velo_runtime/artifacts/security/master_security_standard.md) | Surgical Shielding & Invariants | Security Lead |

### 🏗️ Tier 3: Platform Architecture (The "Where")
| Asset | Description | Guardian |
|:---|:---|:---|
| [`macos_standard.md`](../platform/macos_standard.md) | FSEvents, Sandbox, TCC | macOS Spec. |
| [`linux_standard.md`](../platform/linux_standard.md) | Abstract Sockets, Cgroups | Linux Spec. |
| [`network_protocol_standard.md`](../platform/network_protocol_standard.md) | Magic Handshake & Framing | Network SRE |
| [`observability_standard.md`](../platform/observability_standard.md) | Structured Logging & Tracing | O11y Expert |

### 💎 Tier 4: Specialized & Operational (The "Depth")
| Asset | Description | Guardian |
|:---|:---|:---|
| [`cryptography_standard.md`](../specialized/cryptography_standard.md) | BLAKE3, CSPRNG, Nonces | Cryptographer |
| [`user_manual_master.md`](../manuals/user_manual_master.md) | Developer Usage Guide | Tech Writer |
| [`master_technical_forensics.md`](../governance/forensics/master_technical_forensics.md) | Incident Response Protocol | DevOps |

## 3. The Guardians (Agent Roles)

The Treasury is guarded by **The Trinity** and the **Specialists**:
*   [Agent A (Core)](../agents/trinity/agent_a_core.md): Verifies Tier 1 & Manuals.
*   [Agent B (Edge)](../agents/trinity/agent_b_edge.md): Verifies Tier 2 & 3 Constraints.
*   [Agent C (Security)](../agents/trinity/agent_c_security.md): Verifies Tier 2 & 4 Invariants.

## 4. Maintenance Protocol (The "Living Document" Rule)

1.  **Atomic Updates**: No code change is complete without a corresponding Doc update (if applicable).
    *   *Example*: Changing the hash algorithm in code -> Update `cryptography_standard.md`.
2.  **Drift Detection**:
    *   Agents MUST verify that code matches documentation during Audit Phases.
    *   Drift = **P0 Defect**.

---

**Last Updated**: 2026-01-06
