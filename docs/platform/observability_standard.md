# Observability Standard (TITANIUM Grade)

> **Authority**: O11y Expert / Architect
> **Status**: **IMMUTABLE**

## 1. Structured Logging

**Constraint**: "Logs are Data."

*   **Format**: JSON in production, Human-readable in dev.
*   **Fields**: Must include `timestamp`, `level`, `pid`, `component`.
*   **No Secrets**: Zero tolerance for logging env vars or keys.
*   **NO_COLOR**: Respect `NO_COLOR` env var.

## 2. Tracing & Profiling

**Constraint**: "Zero Overhead Default."

*   **Sampling**: Tracing must be sampling-based in production.
*   **Profile**: `--profile` triggers `py-spy` or `cProfile`.
*   **Spans**: All major ops (Fork, Init, Compile) must be spans.

## 3. Health Checks

**Constraint**: "Deep Verification."

*   **Liveness**: "Is the process up?" (PID check).
*   **Readiness**: "Can it serve requests?" (HTTP /health endpoint).
*   **Startup**: "Did it burn down?" (Exit code check).

---

**Last Updated**: 2026-01-06
