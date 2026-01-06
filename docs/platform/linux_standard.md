# Linux Platform Standard (TITANIUM Grade)

> **Authority**: Linux Specialist / Architect
> **Status**: **IMMUTABLE**

## 1. Process Isolation

**Constraint**: "Namespaces are Cheap."

*   **Cgroups**: Velo workers SHOULD be identifiable via cgroups (future).
*   **Signals**: `PR_SET_PDEATHSIG` is mandatory for parent-death cleanup.
*   **Zombies**: The Supervisor MUST assume PID 1 responsibilities (reaping adopted orphans) if running in a container.

## 2. Networking (Abstract Namespaces)

**Constraint**: "Filesystem is Slow; Memory is Fast."

*   **Abstract Sockets**: Use Abstract Namespace sockets (leading NULL byte) for IPC to bypass filesystem permissions and cleanup issues.
*   **Naming**: `@velo-{project_hash}-{uid}`.
*   **PeerCred**: `SO_PEERCRED` verification is MANDATORY for all UDS connections.

## 3. File Descriptors

**Constraint**: "Everything is a File."

*   **Limit**: Check `RLIMIT_NOFILE` on startup. Warn if < 1024.
*   **Close Range**: Use `close_range(3, ~0)` syscall for efficient FD sanitation in Zygote forks.
*   **Epoll**: Use Edge-Triggered (`EPOLLET`) mode for high-concurrency loops.

---

**Last Updated**: 2026-01-06
