# pytest-velo Isolation Behavior

> **⚠️ Important**: pytest-velo provides stronger isolation than vanilla pytest.
> Tests that pass with `velo test` may fail with `pytest` due to shared-state bugs.

## Isolation Comparison

| Aspect | pytest | pytest-xdist | pytest-velo |
|:---|:---|:---|:---|
| **Process Model** | Single | Subprocess spawn | Fork (COW) |
| **TMPDIR** | Shared | Per-worker | Per-worker |
| **Memory** | Shared | Isolated | Isolated (COW) |
| **Global State** | Accumulates | Inherited | Fresh per test |
| **FD Cleanup** | On exit | On worker exit | Explicit `os._exit()` |

## What This Means

### Tests May Pass in velo but Fail in pytest

```python
# This test has a hidden dependency on test order
shared_list = []

def test_a():
    shared_list.append(1)
    assert len(shared_list) == 1

def test_b():
    shared_list.append(2)
    assert len(shared_list) == 2  # Fails if test_a didn't run first!
```

- **velo test**: ✅ Both pass (each fork starts fresh)
- **pytest**: ⚠️ Order-dependent (shared state)

### Recommendation: Periodic pytest Verification

```bash
# Development: fast iteration
velo test tests/

# Pre-release: verify in vanilla pytest
pytest tests/
```

### CI Configuration

```yaml
jobs:
  fast-check:
    runs-on: ubuntu-latest
    steps:
      - run: velo test --fast

  full-verify:
    runs-on: ubuntu-latest
    steps:
      - run: pytest -v  # Catches shared-state bugs
```

## Environment Variables Set by velo test

| Variable | Purpose |
|:---|:---|
| `TMPDIR` | Worker-isolated temp directory |
| `VELO_WORKER_ID` | Worker process ID |
| `VELO_WORKER_SOCKET_DIR` | Isolated socket directory |
| `VELO_WORKER_LOG_DIR` | Isolated log directory |

## When to Use Each

| Scenario | Recommended Tool |
|:---|:---|
| Local development | `velo test` (fast) |
| CI quick check | `velo test` |
| Pre-merge gate | `pytest` (canonical) |
| Debugging isolation issues | `pytest -v` |

---

## Future: `--strict-compat` Mode (Roadmap)

> **Status**: Planned for future implementation

A `--strict-compat` flag that mimics vanilla pytest behavior:

```bash
velo test --strict-compat tests/
```

| Behavior | Default | `--strict-compat` |
|:---|:---|:---|
| TMPDIR isolation | Yes | No |
| Socket isolation | Yes | No |
| Per-test fork | Yes | Yes |
| Global state reset | No | No (like pytest) |

This would help catch shared-state bugs without switching to vanilla pytest.

### Implementation Notes

```python
def worker_environment_isolation(strict_compat: bool = False) -> str:
    if strict_compat:
        return ""  # Skip isolation, mimic pytest
    # ... normal isolation
```

