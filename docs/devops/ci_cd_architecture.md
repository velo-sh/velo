# Velo CI/CD Architecture: High-Performance Verification

> **Status**: Institutionalized | **Last Updated**: 2026-01-05
> **Optimization Metric**: 60-80% Reduction in Total Run Time

Velo implements a "Build Once, Run Everywhere" CI/CD architecture to maximize throughput and ensure environment parity between local development and CI runners.

## 1. Core Optimization Strategies

### 1.1 "Build Once, Run Everywhere" (Artifact Sharing)
To eliminate redundant compilation overhead (the most expensive part of Rust CI), Velo decouples compilation from verification.
- **Primary Build Node**: The `build` job runs on Ubuntu/Python 3.11. It compiles the `velo` binary in `--release` mode.
- **Artifact Propagation**: The resulting binary is uploaded as a GitHub Action artifact (`velo-binary-ubuntu`).
- **QA Consumption**: All downstream QA tiers (Zygote, Serve, Loader, Phase 6.1) download this pre-built binary.
- **Impact**: Avoids ~15 redundant `cargo build` cycles across the job matrix.

### 1.2 Differential CI (Path-Based Execution)
Velo uses `dorny/paths-filter` to dynamically calculate the required test scope.
- **Job Gating**: Jobs only execute if relevant files (e.g., `src/zygote/**`, `.github/workflows/ci.yml`) are modified.
- **Feedback Loop**: PRs affecting only documentation or specific sub-modules receive feedback in seconds rather than minutes.

### 1.3 Strategic Caching
Multi-layer caching is mandatory for all Velo workflows:
- **Rust Caching**: `swatinem/rust-cache@v2` is used for all jobs touching Rust code to cache registry indices and build increments.
- **Python Caching**: `astral-sh/setup-uv@v4` with `enable-cache: true` manages the persistent `uv` environment cache.

### 1.4 Lazy Matrix Decoupling
The primary build/test flow (Ubuntu 3.11) is decoupled from the full OS/Python matrix.
- **QA Priority**: QA suites depend only on the primary Ubuntu build, allowing them to start immediately.
- **Extended Matrix**: macOS and secondary Python versions (3.12) are run in parallel as a secondary `build-matrix` job, ensuring they don't block core verification.

## 2. Environment Governance (SSoT)

### 2.1 The `setup-velo` Composite Action
To prevent "Local Pass, Remote Fail" mismatches, all environment setup logic is encapsulated in a single source of truth: `.github/actions/setup-velo/action.yml`.

**Capabilities:**
- Installs `uv` (standardized version).
- Sets up Python with proper `uv venv` and `uv sync`.
- (Optional) Downloads the pre-built `velo` binary and sets execution permissions.
- Centralizes Python versions used across 15+ jobs.

## 3. Monitoring & Maintenance

### 3.1 Diagnostic Protocol
Velo's CI is monitored primarily through the GitHub CLI (`gh`) for low-latency feedback:
- **Status Overview**: `gh run list --branch <branch> --limit 5 --json databaseId,status,displayTitle`
- **Job Details**: `gh run view <run-id> --json status,conclusion,jobs`
- **Failed Logs**: `gh run view --job <job-id> --log-failed` to identify specific test failures.
- **Local Parity Check**: `gh run view <ID> --log` to find environmental mismatches.
- **Known Exception (Coverage)**: The `Code Coverage` job is currently permitted to fail (`continue-on-error: true`) due to a pre-existing Rust BLAKE3 hash verification issue. This is a known infrastructure constraint, not a regression.

### 3.2 Single Source of Truth (Linting & Rules)
To prevent "Push-and-Fail" cycles where Clippy fails in CI but passes locally:
- **Rule Alignment**: The `.githooks/pre-commit` MUST mirror the exact flags used in `ci.yml`: `cargo clippy --all-targets --all-features -- -D warnings`.
- **Compiler Version Drift**: If flags are aligned but discrepancies persist, verify versions via `rustc --version`. CI uses a fixed toolchain (`1.92.0`); local environments should match or exceed this to catch newer lints like `collapsed_if`.
- **Platform-Specific Lints**: Be aware that some lints (especially those in `cfg` blocks or dependent on OS APIs) may trigger on CI (Linux) but not on local development machines (macOS/Windows). Always run a "Clean Scan" if discrepancies persist.
- **Hook Verification**: If a CI-level Clippy failure occurs, the first step is to verify the local hook version via `cat .githooks/pre-commit`.
- **Rule Centralization (Implemented)**: All Clippy configurations are centralized in the workspace-level `Cargo.toml` under `[lints.clippy]` to ensure 100% character-level parity.

### 3.3 Queue Management & CI Hygiene
To prevent "Queue Congestion" during high-frequency development cycles, Velo enforces a "Latest is Greatest" policy:
- **Bulk Cancellation**: Older, redundant runs on the same branch should be cancelled to free up runner slots for the latest commit.
- **Global Queue Purge (Emergency)**: If the entire repo's CI queue is blocked by hundreds of stale jobs, a global purge can be executed:
  ```bash
  # Purge all queued jobs across all branches
  gh run list --status queued --limit 50 --json databaseId | jq -r '.[] | .databaseId' | xargs -n 1 gh run cancel
  
  # Purge stalled 'in_progress' jobs
  gh run list --status in_progress --limit 50 --json databaseId | jq -r '.[] | .databaseId' | xargs -n 1 gh run cancel
  ```
- **Targeted Branch Clearance**: To clear the path for a specific branch while leaving other branches' latest runs alone:
  ```bash
  gh run list --status queued --limit 50 --json databaseId,headBranch | \
    jq -r '.[] | select(.headBranch != "your-branch-name") | .databaseId' | \
    xargs -n 1 gh run cancel
  ```
- **Pruning Branch Noise (Latest is Greatest)**: To cancel ALL but the single most recent run on the current branch (recommended after a rebase or multiple rapid pushes):
  ```bash
  gh run list --limit 100 --json databaseId,status | \
    jq -r '.[] | select(.status == "queued" or .status == "in_progress" or .status == "waiting") | .databaseId' | \
    sort -rn | sed '1d' | xargs -n 1 gh run cancel
  ```
- **Pruning Inactive Branches**: Periodically cancel workflows on abandoned or feature-complete branches using `gh run list --status in_progress` to identify dangling jobs.

### 3.4 Advanced Troubleshooting: The In-Progress Log Trap
When CI fails but logs are inaccessible (e.g., job in-progress or storage limits), Velo engineers use the **"Reverse-Engineering via Git Log"** pattern.

- **The Constraint**: The GitHub CLI (`gh`) cannot stream logs for jobs that have not yet completed, or even for *failed* jobs if the overall Run is still `in_progress`. Logs are typically only rotated and made available via CLI once the entire Workflow Run finalizes.
- **The Pattern**: If a job (like Clippy) fails but provides no output via `gh run view --job <ID> --log-failed` (returning "run is still in progress"), search the local git history for recent "fix" or "align" commits targeting that specific job. 
  ```bash
  # Identify previous fixes to reverse-engineer current failure
  git log -n 50 --grep="clippy" --oneline --all
  ```
- **The Multi-Run Pivot**: If current logs are inaccessible due to `in_progress` status, list recent failed runs on the same branch and extract logs from a **completed** historical job with the same name.
  ```bash
  # Find latest completed failure for Clippy
  gh run list --status completed --limit 100 --json databaseId,conclusion | \
    jq -r '.[] | select(.conclusion == "failure") | .databaseId' | \
    xargs -I {} gh run view {} --json jobs --jq '.jobs[] | select(.name == "Clippy" and .conclusion == "failure") | .databaseId'
  ```
- **Historical Context Warning**: When using historical logs (The Multi-Run Pivot), be aware of **Line Number Drift**. If the codebase has changed since the historical run, line numbers in the logs (e.g., `src/serve/watcher.rs:130`) may no longer match the current `HEAD`. Verify the file state at the specific commit of the failed run using `git show <commit_hash>:<file_path>`.
- **Ghost Failures**: If versions, flags, and OS match but CI still fails while local passes, perform a `cargo clean` locally. Spurious cache artifacts can occasionally suppress lints that the CI's fresh environment correctly identifies.
- **Diagnostic Ritual**: If local `pre-commit` passes while CI fails, verify the flags in `.githooks/pre-commit` against `ci.yml`. The **Single Source of Truth** for rules is now the `[lints]` section in `Cargo.toml`.
- **The SSoT Pivot (Cargo.toml)**: Prefer using `[lints.rust]` and `[lints.clippy]` in `Cargo.toml` over CLI flags. 
    - *Insight*: Avoid global `all = "deny"` in large legacy projects as it can trigger hundreds of secondary warnings. Instead, use `all = "warn"` and explicitly `deny` the specific lints (like `collapsible_if`) that must block CI.

### 3.5 Regression Policy
Any new job added to `ci.yml` MUST:
1. Use the `setup-velo` composite action.
2. Respect the differential gating (`changes` job outputs).
3. Follow the "Build Once, Run Everywhere" artifact consumption pattern.
### 3.6 Environment Sensitivity (Timeouts)
CI runners (especially shared GitHub nodes) are often significantly more resource-constrained and exhibit higher I/O latency than local development machines. 
- **The Standard**: Asynchronous operations and E2E tests should use a minimum timeout of **30 seconds** (up from 10s baseline) to avoid flaky failures during period of runner congestion.
- **Evidence**: Legacy 10s timeouts in `test_phase3_5_serve.py` and `test_phase3_5_leader_brutal.py` were established failure points during high-concurrency CI runs and have been institutionalized at 30s.
