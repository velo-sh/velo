# Documentation Standard (TITANIUM Grade)

> **Authority**: Technical Writer / Architect
> **Status**: **IMMUTABLE**

## 1. Voice & Tone

**Constraint**: "Industrial Precision."

*   **Tone**: Confident, Technical, Concise. No fluff.
*   **Perspective**: Velo is a tool (Supervisor), not a human.
*   **Language**: English Only (UK/US neutral).

## 2. Structure

**Constraint**: "Information Hierarchy."

*   **Headers**: Use ATX headers (`#`). No setext headers (`===`).
*   **Meta**: All major docs must have metadata block (Authority, Status).
*   **Linking**: Use relative links for portability.

## 3. Maintenance

**Constraint**: "Docs as Code."

*   **Sync**: `task.md` and `SOPs` must be updated atomically with code changes.
*   **Dead Links**: Prohibited. Run link checker in CI (future).

---

**Last Updated**: 2026-01-06
