# Network Protocol Standard (TITANIUM Grade)

> **Authority**: Network SRE / Architect
> **Status**: **IMMUTABLE**

## 1. Velo IPC Protocol (Private)

**Constraint**: "Trust but Verify."

*   **Magic Header**: All connections MUST start with `VELO` (4 bytes).
*   **Version Check**: Followed by `u32` (BE) version number. Mismatch = Immediate Close.
*   **Framing**: Length-prefixed (`u32` BE) JSON payloads.

## 2. HTTP/L7 Proxy

**Constraint**: "Standards Compliance."

*   **Hop-by-Hop**: The Proxy MUST strip `Connection`, `Keep-Alive`, `Te`, `alters`, `Proxy-Authenticate`, `Upgrade`.
*   **Forwarded Headers**: Inject `X-Forwarded-For`, `X-Forwarded-Proto`.
*   **Server Name**: `Server: velo/x.y.z`.

## 3. Socket Lifecycle

**Constraint**: "Cleanup is Mandatory."

*   **Bind**: Atomic unlink-before-bind (for file-based sockets).
*   **Backlog**: Minimum 128 connections.
*   **Timeout**: Client connection timeout (5s) to prevent Holdup DoS.

---

**Last Updated**: 2026-01-06
