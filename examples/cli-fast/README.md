# HIO-005: CLI Accelerator

> **Scenario**: Simulate performance optimization for high-performance Python CLI tools (e.g., `pip`, `uv`, `aws-cli`) during short-lived command execution.

## 1. The Pain: Interpreter & Import Tax

Python CLI tools face an awkward problem: even if your business logic only runs for 5ms, users may wait 400ms or longer. This "fixed overhead" consists of:

1. **Interpreter Startup**: Python VM cold start.
2. **Path Scanning**: Searching for libraries across a large `sys.path`.
3. **Dependency Import**: Loading and parsing heavy libraries like `rich`, `click`, `pydantic`.

## 2. The Velo Solution

Velo uses **Zygote Pre-loading** technology to move all these costs to an "offline" phase:

- **Pre-warm**: A persistent parent process completes interpreter initialization, library imports, and path scanning ahead of time.
- **Instant Fork**: When the user runs a command, Velo instantly forks a child process. The child inherits all pre-loaded memory state.
- **TTFL Optimization**: Reduces Time To First Logic (TTFL) from hundreds of milliseconds to **sub-millisecond levels**.

---

## 3. ⚖️ Engineering Statement (TITANIUM Standard)

### 🍎 macOS Fork Safety
For the special handling of `os.fork()` on macOS, Velo implements `_atfork` hook cleanup mechanisms and strictly distributes Zygote in a single-threaded environment, ensuring child process system resources (like GCD, CoreFoundation handles) are in a clean state.

### 🛡️ Environment Purity
Since child processes in Zygote mode inherit the parent process environment, developers should not rely on unstable global environment variable modifications. Velo resets critical variables via `EnvironmentShield` at fork time, ensuring execution environment determinism.

---

## 4. Running the Benchmark

### Prerequisites

Install [uv](https://github.com/astral-sh/uv) package manager:

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Or via Homebrew (macOS)
brew install uv
```

### Run the Benchmark

```bash
# Quick start (uv handles dependencies automatically)
./examples/cli-fast/run_hio.sh --compare --runs=20

# Or run directly with uv
uv run --with pydantic --with rich --with click python examples/cli-fast/bench_race.py --runs=20
```
