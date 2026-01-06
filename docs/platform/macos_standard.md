# macOS Platform Standard (TITANIUM Grade)

> **Authority**: macOS Specialist / Architect
> **Status**: **IMMUTABLE**

## 1. Filesystem Events (FSEvents)

**Constraint**: "Latency is Physical."

*   **Latency Floor**: FSEvents has a minimum latency of ~10ms-100ms depending on load.
*   **Debounce**: Velo MUST enforce a hardware-aligned debounce (e.g., 300ms) to prevent "stuttering" reloads.
*   **Atomic Renames**: Watchers must handle `Rename` events as `Create`+`Delete` pairs if the OS squashes them.

## 2. App Sandbox & TCC

**Constraint**: "Permission is a Privilege."

*   **TmpDir**: Never assume `/tmp` is writable or readable. Use `confstr(_CS_DARWIN_USER_TEMP_DIR)`.
*   **SIP**: System Integrity Protection prevents attaching debuggers to system binaries. Velo binaries must be signed (ad-hoc ok) for local debugging.

## 3. Networking

**Constraint**: "Ports are Shared Resources."

*   **SO_REUSEADDR**: Mandatory for listening sockets to allow rapid restarts.
*   **Socket Path Limit**: UDS paths limited to 104 characters. Use hashing (SHA256 trunk) for socket names.

---

**Last Updated**: 2026-01-06
