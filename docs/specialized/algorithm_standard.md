# Algorithm Standard (TITANIUM Grade)

> **Authority**: Data Structure Expert / Architect
> **Status**: **IMMUTABLE**

## 1. Complexity Budget

**Constraint**: "Scale Free."

*   **Hot Path**: O(1) or O(log n) strictly enforced for request path (Serve/Analyze).
*   **Cold Path**: O(n) permitted for one-time initialization (Loader).
*   **Forbidden**: O(n^2) or worse is globally prohibited.

## 2. Data Structures

**Constraint**: "Fit for Purpose."

*   **Hashing**: Use `AHasher` (HashBrown) for performance-critical maps.
*   **Zero-Copy**: Prefer `Cow<str>` or `&str` over `String` where possible.
*   **Allocations**: Minimize `Vec::push` in tight loops; use `Vec::with_capacity`.

## 3. Recursion

**Constraint**: "Stack Safety."

*   **Depth Limit**: All recursive parsers/walkers MUST have a hard-depth limit (e.g., 500).
*   **Bomb Defusal**: Detect malicious nested structures (Marshal Bomb).

---

**Last Updated**: 2026-01-06
