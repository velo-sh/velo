# Environment Strategy: Local vs. CI Parity

Velo follows the **Single Source of Truth (SSoT)** principle for configuration. This strategy is governed by the definitive [SPEC-0005: Velo SSOT Master Standard](./SPEC-0005-SSOT-MASTER-STANDARD.md).

## 1. Configuration Hierarchy

Velo resolves settings using a three-tiered hierarchy, with a strong preference for **explicit configuration**:

1.  **Environment Variables (`VELO_*`)**: Use ONLY for runtime overrides (CI jitter handling) or sensitive secrets.
2.  **`pyproject.toml` ([tool.velo])**: **PRIMARY SOURCE OF TRUTH.** All shared team settings should be explicitly declared here to ensure transparency and consistency.
3.  **Built-in Defaults**: Hardcoded safe values.

> [!IMPORTANT]
> To ensure "What you see is what you get" across the team, prefer adding settings to `pyproject.toml` rather than relying on hidden `.env` files. Environment variables should be treated as exceptions, not the rule.

### Supported Environment Variables

| Variable | TOML Key | Description | Example |
| :--- | :--- | :--- | :--- |
| `VELO_PRELOAD` | `preload` | Comma-separated list of modules to preload | `fastapi,pydantic` |
| `VELO_MAX_BUNDLE_SIZE` | `max_bundle_size` | Max bundle size in MB | `1024` |
| `VELO_ZYGOTE_WORKER_TIMEOUT` | `zygote_worker_timeout` | Worker lifecycle timeout (s) | `60` |
| `VELO_ZYGOTE_SOCKET_TIMEOUT` | `zygote_socket_timeout` | Socket startup timeout (s) | `45` |

---

## 2. Standard Profiles

### 🏗️ DEV (Local Development)
- **Goal**: Iteration speed.
- **Config**: Relies on `pyproject.toml`.
- **Overrides**: Use a local `.env` file (not committed) for personal pathing or shorter timeouts.

### 🧪 TEST (Local Verification)
- **Goal**: Reproduce CI behavior locally.
- **Config**: Uses `pytest` markers (Tier 0-3).
- **Tooling**: `uv run pytest`.

### ⚖️ PROSECUTOR (CI / Remote Verification)
- **Goal**: Formal verification in a "Clean Room".
- **Config**: Injected via GitHub Actions environment variables in `ci.yml`.
- **Best Practice**: CI should strictly use the same `cargo` and `uv` commands as developers, but with higher timeout caps (e.g., `VELO_ZYGOTE_SOCKET_TIMEOUT=60` to handle runner jitter).

---

## 3. Best Practices for Developers

1.  **Avoid hardcoding** environment-specific paths in the Rust code.
2.  **Use `load_with_overrides()`** when accessing configuration in new modules.
3.  **Keep `pyproject.toml` lean**. Only put settings there that apply to *everyone* on the team.
4.  **Local `.env`**: Create your own `.env` from `.env.example` to customize your local workflow without affecting others.
