# DEV Fix Requirement: Zygote Auto-Preload from pyproject.toml

**DEV-FIX-001**: Zygote should read `[tool.velo].preload` from pyproject.toml

## Background

When user runs `velo run --zygote`, Zygote auto-starts but does NOT read preload config from pyproject.toml.

**Current behavior**:
- `velo zygote start --preload fastapi` → ✅ Works (275ms)
- `velo run --zygote` with pyproject.toml config → ❌ Ignores preload (470ms)

## Requirements

### REQ-1: Read pyproject.toml on Zygote auto-start

When `velo run --zygote` triggers Zygote auto-start:
1. Read `pyproject.toml` from current directory
2. Parse `[tool.velo].preload` array
3. Pass modules to Zygote daemon via `--preload` arg

### REQ-2: Affected files

| File | Change |
|------|--------|
| `src/cmd/run.rs` | Read pyproject.toml before launching Zygote |
| (New) `src/config.rs` | Parse `[tool.velo]` section |

### REQ-3: Config format

```toml
[tool.velo]
preload = ["fastapi", "pydantic", "uvicorn"]
```

### REQ-4: Acceptance criteria

```bash
# Given pyproject.toml with preload config
# When running:
velo run --zygote app.py

# Then Zygote should preload configured modules
# Expected: ~275ms (not 470ms)
```

## Priority

**P1** - Critical for Zygote performance claim (55% faster)

## References

- Benchmark: 470ms → 275ms with preload
- Related QA: QA-REQ-001-zygote-preload.md
