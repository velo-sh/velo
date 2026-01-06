# Accessibility Standard (TITANIUM Grade)

> **Authority**: A11y Expert / Product Manager
> **Status**: **IMMUTABLE**

## 1. Terminal Output

**Constraint**: "Inclusive UI."

*   **NO_COLOR**: Respect the `NO_COLOR` environment variable to strip ANSI codes.
*   **Contrast**: Ensure default colors work on both Light and Dark terminal themes.
*   **Screen Readers**: Output should be structured and parseable.

## 2. Error Messages

**Constraint**: "Human Readable."

*   **Structure**: [Error Code] + [Concise Summary] + [Actionable Fix].
*   **Clarity**: Avoid jargon. "Zygote Socket Failed" -> "Unable to connect to worker process."

---

**Last Updated**: 2026-01-06
