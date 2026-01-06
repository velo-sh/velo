# Cryptography Standard (TITANIUM Grade)

> **Authority**: Cryptographer / Security Engineer
> **Status**: **IMMUTABLE**

## 1. Hashing

**Constraint**: "Speed & Security."

*   **Algo**: BLAKE3 is the standard for file integrity and content addressing.
*   **Legacy**: SHA-256 is permitted ONLY for legacy verification.
*   **Usage**: Checksums must be verified before execution.

## 2. Randomness

**Constraint**: "No Prediction."

*   **CSPRNG**: Use `rand::rngs::OsRng` or `StdRng` seeded from OS.
*   **Nonces**: Must be unique per operation.
*   **Secrets**: Never log random seeds or keys.

## 3. Storage

**Constraint**: "At Rest Protection."

*   **Keys**: Material must never be committed to repo.
*   **Env**: Use `EnvironmentShield` to protect secrets in memory.

---

**Last Updated**: 2026-01-06
