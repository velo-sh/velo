# Velo Security: The Three Sins (Lessons from Phase 6.1)

To prevent future security regressions, all developers must be aware of the "Three Sins" that led to the total failure of the initial security implementation.

## 1. Environment Starvation (The Sin of Denial)
- **What happened**: Using `env_clear()` blindly stripped `PATH` and `VIRTUAL_ENV`.
- **The Result**: Total system collapse; workers couldn't find `python` or load modules.
- **The Lesson**: **Surgical Scrubbing over Brute Force**. Use whitelists and validate values (Provenance) instead of clearing everything.

## 2. Seatbelt Death Spiral (The Sin of Over-Restriction)
- **What happened**: Hard-blocking `/tmp` and `/var` without understanding IPC requirements.
- **The Result**: Zygote couldn't create sockets; workers couldn't communicate.
- **The Lesson**: **Capability-Based Access**. Use `cap-std` and randomized, atomic temporary directories instead of top-level blocking.

## 3. Workspace Collision (The Sin of Determinism)
- **What happened**: Using a single global socket path `/tmp/velo-zygote.sock`.
- **The Result**: Parallel projects hijacked or crashed each other's Zygote servers.
- **The Lesson**: **Identity-Keyed Isolation**. Use Project Hashes + Abstract Namespaces (Linux) or randomized directories (macOS) to ensure identity uniqueness.

---
*Reference: [RFC-0012](../rfcs/0012-full-armor-security-standard.md)*
