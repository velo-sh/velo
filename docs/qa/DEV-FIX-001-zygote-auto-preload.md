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

### REQ-5: Preload 合并策略

**问题**：多个来源可能提供 preload 配置

| 来源 | 优先级 | 说明 |
|------|--------|------|
| `pyproject.toml` | 1 (最高) | 用户意图 |
| CLI `--preload` 参数 | 2 | 临时覆盖 |
| Auto-detect (未来) | 3 | 自动补充 |

**策略**：
- 合并所有来源的模块列表
- 去重 (保持顺序，后来的不重复添加)
- 不存在冲突覆盖 (只做并集)

**示例**：
```
pyproject.toml: ["fastapi", "numpy"]
CLI --preload:  ["pydantic"]
→ 最终: ["fastapi", "numpy", "pydantic"]
```

## Priority

**P1** - Critical for Zygote performance claim (55% faster)

## References

- Benchmark: 470ms → 275ms with preload
- Related QA: QA-REQ-001-zygote-preload.md

